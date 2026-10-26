"""Manual Portfolio AVM snapshot runner.

This service is deliberately controlled: callers must invoke it explicitly and
the default endpoint path can run as dry-run without persisting rows.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from core.exceptions import InsufficientDataError, UFServiceError, ValidationError
from infrastructure.db.models import (
    ListingORM,
    PortfolioAggregateSnapshotORM,
    PortfolioItemValuationSnapshotORM,
    SavedListingORM,
)
from services.valuation import ValuationInput, ValuationService

VALUATION_AVAILABLE = "available"
VALUATION_UNAVAILABLE = "unavailable"
DELTA_AVAILABLE = "available"
DELTA_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PortfolioSnapshotItemResult:
    listing_id: int
    watchlist_item_id: int | None
    valuation_status: str
    unavailable_reason: str | None
    delta_status: str
    delta_unavailable_reason: str | None
    estimated_value_uf: Decimal | None = None
    estimated_value_clp: Decimal | None = None
    published_price_uf: Decimal | None = None
    published_price_clp: Decimal | None = None
    delta_uf: Decimal | None = None
    delta_pct: float | None = None
    snapshot_id: int | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "watchlist_item_id": self.watchlist_item_id,
            "valuation_status": self.valuation_status,
            "unavailable_reason": self.unavailable_reason,
            "delta_status": self.delta_status,
            "delta_unavailable_reason": self.delta_unavailable_reason,
            "estimated_value_uf": _float_or_none(self.estimated_value_uf),
            "estimated_value_clp": _float_or_none(self.estimated_value_clp),
            "published_price_uf": _float_or_none(self.published_price_uf),
            "published_price_clp": _float_or_none(self.published_price_clp),
            "delta_uf": _float_or_none(self.delta_uf),
            "delta_pct": self.delta_pct,
            "snapshot_id": self.snapshot_id,
        }


@dataclass(frozen=True)
class PortfolioSnapshotRunResult:
    user_id: int
    dry_run: bool
    limit: int | None
    processed_count: int
    valued_count: int
    unavailable_count: int
    reasons: dict[str, int]
    aggregate_snapshot_id: int | None
    items: tuple[PortfolioSnapshotItemResult, ...]
    skipped_count: int = 0
    skipped_reason: str | None = None
    error_count: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "dry_run": self.dry_run,
            "limit": self.limit,
            "attempted_count": self.processed_count,
            "processed_count": self.processed_count,
            "valued_count": self.valued_count,
            "unavailable_count": self.unavailable_count,
            "skipped_count": self.skipped_count,
            "skipped_reason": self.skipped_reason,
            "error_count": self.error_count,
            "reasons": dict(self.reasons),
            "aggregate_snapshot_id": self.aggregate_snapshot_id,
            "items": [item.to_payload() for item in self.items],
        }


class PortfolioSnapshotService:
    def __init__(self, session: AsyncSession, valuation_service: ValuationService) -> None:
        self._session = session
        self._valuation_service = valuation_service

    async def create_snapshot(
        self,
        *,
        user_id: int,
        limit: int | None = 20,
        dry_run: bool = True,
        min_interval_hours: int | None = None,
        now: datetime | None = None,
    ) -> PortfolioSnapshotRunResult:
        snapshot_at = _ensure_aware(now or datetime.now(UTC))
        if min_interval_hours is not None and await self.has_recent_snapshot(
            user_id=user_id,
            min_interval_hours=min_interval_hours,
            now=snapshot_at,
        ):
            return PortfolioSnapshotRunResult(
                user_id=user_id,
                dry_run=dry_run,
                limit=limit,
                processed_count=0,
                valued_count=0,
                unavailable_count=0,
                reasons={},
                aggregate_snapshot_id=None,
                items=(),
                skipped_count=1,
                skipped_reason="recent_snapshot",
            )
        saved_items = await self._active_watchlist(user_id=user_id, limit=limit)
        results: list[PortfolioSnapshotItemResult] = []
        item_rows: list[PortfolioItemValuationSnapshotORM] = []

        for saved in saved_items:
            result, row = await self._evaluate_saved_item(
                user_id=user_id,
                saved=saved,
                snapshot_at=snapshot_at,
                persist=not dry_run,
            )
            results.append(result)
            if row is not None:
                item_rows.append(row)

        aggregate = self._aggregate_row(
            user_id=user_id,
            snapshot_at=snapshot_at,
            item_count=len(saved_items),
            results=results,
        )
        aggregate_id: int | None = None
        if not dry_run:
            self._session.add_all([*item_rows, aggregate])
            await self._session.flush()
            aggregate_id = aggregate.id
            results = [
                _with_snapshot_id(result, row.id)
                for result, row in zip(results, item_rows, strict=True)
            ]
            await self._session.commit()

        reasons = Counter(
            reason
            for result in results
            for reason in (result.unavailable_reason, result.delta_unavailable_reason)
            if reason
        )
        return PortfolioSnapshotRunResult(
            user_id=user_id,
            dry_run=dry_run,
            limit=limit,
            processed_count=len(results),
            valued_count=sum(1 for result in results if result.valuation_status == VALUATION_AVAILABLE),
            unavailable_count=sum(1 for result in results if result.valuation_status != VALUATION_AVAILABLE),
            reasons=dict(sorted(reasons.items())),
            aggregate_snapshot_id=aggregate_id,
            items=tuple(results),
        )

    async def has_recent_snapshot(
        self,
        *,
        user_id: int,
        min_interval_hours: int,
        now: datetime | None = None,
    ) -> bool:
        reference_time = _ensure_aware(now or datetime.now(UTC))
        cutoff = reference_time - timedelta(hours=max(0, int(min_interval_hours)))
        stmt = (
            select(PortfolioAggregateSnapshotORM.id)
            .where(PortfolioAggregateSnapshotORM.user_id == user_id)
            .where(PortfolioAggregateSnapshotORM.snapshot_at >= cutoff)
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def _active_watchlist(self, *, user_id: int, limit: int | None) -> list[SavedListingORM]:
        stmt = (
            select(SavedListingORM)
            .options(joinedload(SavedListingORM.listing))
            .where(SavedListingORM.user_id == user_id)
            .where(SavedListingORM.status == "active")
            .order_by(SavedListingORM.saved_at.desc())
        )
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def _evaluate_saved_item(
        self,
        *,
        user_id: int,
        saved: SavedListingORM,
        snapshot_at: datetime,
        persist: bool,
    ) -> tuple[PortfolioSnapshotItemResult, PortfolioItemValuationSnapshotORM | None]:
        listing = saved.listing
        valuation_input, reason = _valuation_input(listing)
        if reason is not None:
            return self._unavailable_result(
                user_id=user_id,
                saved=saved,
                snapshot_at=snapshot_at,
                reason=reason,
                persist=persist,
            )

        try:
            valuation = await self._valuation_service.valuate_property(valuation_input)
        except InsufficientDataError:
            return self._unavailable_result(
                user_id=user_id,
                saved=saved,
                snapshot_at=snapshot_at,
                reason="insufficient_comparables",
                persist=persist,
            )
        except ValidationError:
            return self._unavailable_result(
                user_id=user_id,
                saved=saved,
                snapshot_at=snapshot_at,
                reason="needs_valuation_input",
                persist=persist,
            )
        except UFServiceError:
            return self._unavailable_result(
                user_id=user_id,
                saved=saved,
                snapshot_at=snapshot_at,
                reason="needs_uf_rate",
                persist=persist,
            )
        except Exception:
            return self._unavailable_result(
                user_id=user_id,
                saved=saved,
                snapshot_at=snapshot_at,
                reason="valuation_failed",
                persist=persist,
            )

        estimated_value_uf = _decimal(valuation.estimated_price_uf)
        estimated_value_clp = _decimal(valuation.estimated_price_clp)
        if estimated_value_uf is None and estimated_value_clp is None:
            return self._unavailable_result(
                user_id=user_id,
                saved=saved,
                snapshot_at=snapshot_at,
                reason="valuation_failed",
                persist=persist,
            )

        published_price_uf = _canonical_price_uf(listing)
        published_price_clp = _decimal(listing.price_clp)
        delta_uf: Decimal | None = None
        delta_pct: float | None = None
        delta_status = DELTA_UNAVAILABLE
        delta_unavailable_reason = "needs_canonical_price"
        if estimated_value_uf is not None and published_price_uf is not None and published_price_uf > 0:
            delta_uf = estimated_value_uf - published_price_uf
            delta_pct = float((delta_uf / published_price_uf) * Decimal("100"))
            delta_status = DELTA_AVAILABLE
            delta_unavailable_reason = None

        result = PortfolioSnapshotItemResult(
            listing_id=saved.listing_id,
            watchlist_item_id=saved.id,
            valuation_status=VALUATION_AVAILABLE,
            unavailable_reason=None,
            delta_status=delta_status,
            delta_unavailable_reason=delta_unavailable_reason,
            estimated_value_uf=estimated_value_uf,
            estimated_value_clp=estimated_value_clp,
            published_price_uf=published_price_uf,
            published_price_clp=published_price_clp,
            delta_uf=delta_uf,
            delta_pct=delta_pct,
        )
        row = self._item_row(
            user_id=user_id,
            saved=saved,
            snapshot_at=snapshot_at,
            result=result,
            lower_bound_uf=_decimal(valuation.price_range_low_uf),
            upper_bound_uf=_decimal(valuation.price_range_high_uf),
            confidence=valuation.confidence,
            engine_name=_engine_name(valuation.selected_engine_names),
            engine_version=valuation.consensus_method,
            data_freshness_status=_data_freshness_status(valuation),
        )
        return result, row if persist else None

    def _unavailable_result(
        self,
        *,
        user_id: int,
        saved: SavedListingORM,
        snapshot_at: datetime,
        reason: str,
        persist: bool,
    ) -> tuple[PortfolioSnapshotItemResult, PortfolioItemValuationSnapshotORM | None]:
        result = PortfolioSnapshotItemResult(
            listing_id=saved.listing_id,
            watchlist_item_id=saved.id,
            valuation_status=VALUATION_UNAVAILABLE,
            unavailable_reason=reason,
            delta_status=DELTA_UNAVAILABLE,
            delta_unavailable_reason="needs_avm",
            published_price_uf=_canonical_price_uf(saved.listing),
            published_price_clp=_decimal(saved.listing.price_clp),
        )
        row = self._item_row(
            user_id=user_id,
            saved=saved,
            snapshot_at=snapshot_at,
            result=result,
            lower_bound_uf=None,
            upper_bound_uf=None,
            confidence=None,
            engine_name=None,
            engine_version=None,
            data_freshness_status="manual_snapshot",
        )
        return result, row if persist else None

    def _item_row(
        self,
        *,
        user_id: int,
        saved: SavedListingORM,
        snapshot_at: datetime,
        result: PortfolioSnapshotItemResult,
        lower_bound_uf: Decimal | None,
        upper_bound_uf: Decimal | None,
        confidence: str | None,
        engine_name: str | None,
        engine_version: str | None,
        data_freshness_status: str,
    ) -> PortfolioItemValuationSnapshotORM:
        return PortfolioItemValuationSnapshotORM(
            user_id=user_id,
            listing_id=saved.listing_id,
            watchlist_item_id=saved.id,
            valuation_id=None,
            estimated_value_uf=result.estimated_value_uf,
            estimated_value_clp=result.estimated_value_clp,
            lower_bound_uf=lower_bound_uf,
            upper_bound_uf=upper_bound_uf,
            confidence=confidence,
            engine_name=engine_name,
            engine_version=engine_version,
            valuation_source="portfolio_manual_snapshot",
            valuation_status=result.valuation_status,
            unavailable_reason=result.unavailable_reason,
            published_price_uf=result.published_price_uf,
            published_price_clp=result.published_price_clp,
            delta_uf=result.delta_uf,
            delta_pct=result.delta_pct,
            delta_status=result.delta_status,
            delta_unavailable_reason=result.delta_unavailable_reason,
            data_freshness_status=data_freshness_status,
            snapshot_at=snapshot_at,
        )

    def _aggregate_row(
        self,
        *,
        user_id: int,
        snapshot_at: datetime,
        item_count: int,
        results: list[PortfolioSnapshotItemResult],
    ) -> PortfolioAggregateSnapshotORM:
        valued = [result for result in results if result.valuation_status == VALUATION_AVAILABLE]
        estimated_values = [value for result in valued if (value := result.estimated_value_uf) is not None]
        published_prices = [value for result in valued if (value := result.published_price_uf) is not None]
        delta_results = [result for result in valued if result.delta_status == DELTA_AVAILABLE]
        deltas = [result.delta_uf for result in delta_results if result.delta_uf is not None]
        delta_pcts = [result.delta_pct for result in delta_results if result.delta_pct is not None]
        positive_deltas = [delta for delta in deltas if delta > 0]
        total_estimated = sum(estimated_values, Decimal("0")) if estimated_values else None
        return PortfolioAggregateSnapshotORM(
            user_id=user_id,
            snapshot_date=snapshot_at.date(),
            total_estimated_value_uf=total_estimated,
            average_estimated_value_uf=(
                total_estimated / Decimal(len(estimated_values))
                if total_estimated is not None and estimated_values
                else None
            ),
            total_published_price_uf=sum(published_prices, Decimal("0")) if published_prices else None,
            total_upside_uf=sum(positive_deltas, Decimal("0")) if delta_results else None,
            average_delta_pct=sum(delta_pcts) / len(delta_pcts) if delta_pcts else None,
            item_count=item_count,
            coverage_count=len(valued),
            unavailable_count=item_count - len(valued),
            snapshot_at=snapshot_at,
        )


def _valuation_input(listing: ListingORM) -> tuple[ValuationInput, str | None]:
    if not str(listing.comuna or "").strip():
        return _empty_input(), "insufficient_listing_data"
    area = listing.built_area_m2 or listing.usable_area_m2 or listing.m2
    if area is None or area <= 0:
        return _empty_input(), "needs_valuation_input"
    return (
        ValuationInput(
            comuna=listing.comuna,
            property_type=listing.property_type,
            m2=listing.m2,
            built_area_m2=listing.built_area_m2,
            land_area_m2=listing.land_area_m2,
            usable_area_m2=listing.usable_area_m2,
            dormitorios=listing.bedrooms,
            banos=listing.bathrooms,
            estacionamientos=listing.parking,
            precio_publicado_uf=_float_or_none(_canonical_price_uf(listing)),
            precio_publicado_clp=int(listing.price_clp) if listing.price_clp is not None else None,
        ),
        None,
    )


def _empty_input() -> ValuationInput:
    return ValuationInput(comuna="", property_type=None, m2=None)


def _canonical_price_uf(listing: ListingORM) -> Decimal | None:
    if str(listing.price_currency or "").strip().upper() != "UF":
        return None
    return _decimal(listing.price_uf)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _float_or_none(value: Decimal | float | int | None) -> float | None:
    return float(value) if value is not None else None


def _engine_name(selected_engine_names: list[str]) -> str | None:
    if not selected_engine_names:
        return None
    return ",".join(selected_engine_names[:3])


def _data_freshness_status(valuation: Any) -> str:
    source = str(getattr(valuation, "uf_rate_source", "") or "")
    if "latest_db_snapshot_within_max_staleness" in source:
        return "manual_snapshot:uf_latest_db"
    if "latest_cache_within_max_staleness" in source:
        return "manual_snapshot:uf_latest_cache"
    if "mindicador.cl" in source:
        return "manual_snapshot:uf_mindicador"
    return "manual_snapshot:uf_real"


def _with_snapshot_id(
    result: PortfolioSnapshotItemResult,
    snapshot_id: int | None,
) -> PortfolioSnapshotItemResult:
    return PortfolioSnapshotItemResult(
        listing_id=result.listing_id,
        watchlist_item_id=result.watchlist_item_id,
        valuation_status=result.valuation_status,
        unavailable_reason=result.unavailable_reason,
        delta_status=result.delta_status,
        delta_unavailable_reason=result.delta_unavailable_reason,
        estimated_value_uf=result.estimated_value_uf,
        estimated_value_clp=result.estimated_value_clp,
        published_price_uf=result.published_price_uf,
        published_price_clp=result.published_price_clp,
        delta_uf=result.delta_uf,
        delta_pct=result.delta_pct,
        snapshot_id=snapshot_id,
    )
