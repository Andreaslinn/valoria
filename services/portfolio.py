"""Read-only Portfolio backend service with honest capability states."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from domain.portfolio.contracts import (
    PortfolioCapabilityState,
    PortfolioComparedState,
    PortfolioHistoryState,
    PortfolioItem,
    PortfolioItemAvmState,
    PortfolioItemDeltaState,
    PortfolioState,
    PortfolioSummary,
    PortfolioTrendState,
    PortfolioUpsideState,
    unavailable_avm_state,
    unavailable_delta_state,
    unavailable_favorite_state,
    unavailable_history_state,
    unavailable_recommendation_state,
    unavailable_trend_state,
    unavailable_upside_state,
)
from infrastructure.db.models import (
    AlertORM,
    AlertReadORM,
    ListingORM,
    PortfolioAggregateSnapshotORM,
    PortfolioItemValuationSnapshotORM,
    SavedListingORM,
)


class PortfolioService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build_summary(self, *, user_id: int) -> PortfolioSummary:
        saved_items = await self._active_watchlist(user_id)
        unread_alert_count = await self._unread_alert_count(user_id)
        item_snapshots = await self._latest_item_snapshots(user_id)
        item_histories = await self._item_snapshot_history(user_id)
        aggregate_snapshots = await self._aggregate_snapshot_history(user_id, limit=24)
        items = tuple(
            _portfolio_item(
                saved,
                snapshot=item_snapshots.get(saved.listing_id),
                history=item_histories.get(saved.listing_id, ()),
            )
            for saved in saved_items
        )
        return PortfolioSummary(
            user_id=user_id,
            tracked_properties=len(saved_items),
            unread_alert_count=unread_alert_count,
            items=items,
            average_avm_variation=_summary_trend_state(aggregate_snapshots),
            upside=_summary_upside_state(aggregate_snapshots),
            history=_summary_history_state(aggregate_snapshots),
            compared=PortfolioComparedState(status=PortfolioState.AVAILABLE, available=True),
            favorites=unavailable_favorite_state(),
            recommendations=unavailable_recommendation_state(),
        )

    async def build_items(self, *, user_id: int) -> tuple[PortfolioItem, ...]:
        saved_items = await self._active_watchlist(user_id)
        item_snapshots = await self._latest_item_snapshots(user_id)
        item_histories = await self._item_snapshot_history(user_id)
        return tuple(
            _portfolio_item(
                saved,
                snapshot=item_snapshots.get(saved.listing_id),
                history=item_histories.get(saved.listing_id, ()),
            )
            for saved in saved_items
        )

    async def build_capabilities(self, *, user_id: int) -> dict[str, object]:
        summary = await self.build_summary(user_id=user_id)
        item_avm = _capability_from_items(tuple(item.avm for item in summary.items), unavailable_avm_state())
        item_delta = _capability_from_items(tuple(item.delta for item in summary.items), unavailable_delta_state())
        item_trend = _capability_from_items(tuple(item.trend for item in summary.items), unavailable_trend_state())
        return {
            "user_id": user_id,
            "tracked_properties": summary.tracked_properties,
            "item_avm": item_avm.to_payload(),
            "item_delta": item_delta.to_payload(),
            "item_trend": item_trend.to_payload(),
            "average_avm_variation": summary.average_avm_variation.to_payload(),
            "upside": summary.upside.to_payload(),
            "history": summary.history.to_payload(),
            "compared": summary.compared.to_payload(),
            "favorites": summary.favorites.to_payload(),
            "recommendations": summary.recommendations.to_payload(),
        }

    async def _active_watchlist(self, user_id: int) -> list[SavedListingORM]:
        stmt = (
            select(SavedListingORM)
            .options(joinedload(SavedListingORM.listing))
            .where(SavedListingORM.user_id == user_id)
            .where(SavedListingORM.status == "active")
            .order_by(SavedListingORM.saved_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def _unread_alert_count(self, user_id: int) -> int:
        stmt = (
            select(func.count(AlertORM.id))
            .join(SavedListingORM, SavedListingORM.listing_id == AlertORM.listing_id)
            .where(SavedListingORM.user_id == user_id)
            .where(SavedListingORM.status == "active")
            .where(AlertORM.is_read.is_(False))
            .where(~select(AlertReadORM.alert_id).where(AlertReadORM.alert_id == AlertORM.id, AlertReadORM.user_id == user_id).exists())
        )
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def _latest_item_snapshots(
        self,
        user_id: int,
    ) -> dict[int, PortfolioItemValuationSnapshotORM]:
        stmt = (
            select(PortfolioItemValuationSnapshotORM)
            .where(PortfolioItemValuationSnapshotORM.user_id == user_id)
            .order_by(
                PortfolioItemValuationSnapshotORM.snapshot_at.desc(),
                PortfolioItemValuationSnapshotORM.id.desc(),
            )
        )
        snapshots: dict[int, PortfolioItemValuationSnapshotORM] = {}
        for snapshot in (await self._session.execute(stmt)).scalars().all():
            snapshots.setdefault(snapshot.listing_id, snapshot)
        return snapshots

    async def _item_snapshot_history(
        self,
        user_id: int,
    ) -> dict[int, tuple[PortfolioItemValuationSnapshotORM, ...]]:
        stmt = (
            select(PortfolioItemValuationSnapshotORM)
            .where(PortfolioItemValuationSnapshotORM.user_id == user_id)
            .where(PortfolioItemValuationSnapshotORM.valuation_status == "available")
            .where(PortfolioItemValuationSnapshotORM.estimated_value_uf.is_not(None))
            .order_by(
                PortfolioItemValuationSnapshotORM.listing_id,
                PortfolioItemValuationSnapshotORM.snapshot_at.desc(),
                PortfolioItemValuationSnapshotORM.id.desc(),
            )
        )
        grouped: dict[int, list[PortfolioItemValuationSnapshotORM]] = {}
        for snapshot in (await self._session.execute(stmt)).scalars().all():
            grouped.setdefault(snapshot.listing_id, []).append(snapshot)
        return {listing_id: tuple(items[:12]) for listing_id, items in grouped.items()}

    async def _aggregate_snapshot_history(
        self,
        user_id: int,
        *,
        limit: int,
    ) -> tuple[PortfolioAggregateSnapshotORM, ...]:
        stmt = (
            select(PortfolioAggregateSnapshotORM)
            .where(PortfolioAggregateSnapshotORM.user_id == user_id)
            .order_by(
                PortfolioAggregateSnapshotORM.snapshot_at.desc(),
                PortfolioAggregateSnapshotORM.id.desc(),
            )
            .limit(limit)
        )
        return tuple((await self._session.execute(stmt)).scalars().all())


def _portfolio_item(
    saved: SavedListingORM,
    *,
    snapshot: PortfolioItemValuationSnapshotORM | None,
    history: tuple[PortfolioItemValuationSnapshotORM, ...],
) -> PortfolioItem:
    listing = saved.listing
    return PortfolioItem(
        watchlist_item_id=saved.id,
        listing_id=saved.listing_id,
        title=listing.title,
        comuna=listing.comuna,
        property_type=listing.property_type,
        m2=listing.m2,
        bedrooms=listing.bedrooms,
        bathrooms=listing.bathrooms,
        parking=listing.parking,
        published_price_clp=listing.price_clp,
        published_price_uf=_canonical_price_uf(listing),
        price_basis=_price_basis(listing),
        price_data_quality=_price_data_quality(listing),
        url=listing.url,
        source=listing.source,
        listing_status=listing.status,
        saved_at=saved.saved_at,
        avm=_item_avm_state(snapshot),
        delta=_item_delta_state(snapshot),
        trend=_item_trend_state(history),
    )


def _canonical_price_uf(listing: ListingORM) -> Decimal | None:
    if str(listing.price_currency or "").strip().upper() != "UF":
        return None
    return listing.price_uf


def _price_basis(listing: ListingORM) -> str:
    currency = str(listing.price_currency or "").strip().upper()
    if currency == "UF" and listing.price_uf is not None:
        return "canonical_uf"
    if currency == "CLP":
        return "canonical_clp"
    if currency == "UF":
        return "legacy_uf_missing_price_uf"
    return "legacy_unknown"


def _price_data_quality(listing: ListingORM) -> str:
    currency = str(listing.price_currency or "").strip().upper()
    if currency == "UF":
        if listing.price_uf is None:
            return "legacy_unrecoverable"
        return str(listing.price_uf_source or listing.price_uf_confidence or "canonical_uf")
    if currency == "CLP":
        return "canonical_clp"
    return "legacy_unknown_currency"


def _item_avm_state(snapshot: PortfolioItemValuationSnapshotORM | None) -> PortfolioItemAvmState:
    if snapshot is None:
        return unavailable_avm_state()
    if snapshot.valuation_status != "available" or snapshot.estimated_value_uf is None:
        return PortfolioItemAvmState(
            status=PortfolioState.NEEDS_VALUATION,
            reason=snapshot.unavailable_reason or "needs_current_valuation",
        )
    return PortfolioItemAvmState(
        status=PortfolioState.AVAILABLE,
        available=True,
        estimated_value_uf=snapshot.estimated_value_uf,
        estimated_value_clp=snapshot.estimated_value_clp,
        lower_bound_uf=snapshot.lower_bound_uf,
        upper_bound_uf=snapshot.upper_bound_uf,
        confidence=snapshot.confidence,
        snapshot_id=snapshot.id,
        snapshot_created_at=snapshot.snapshot_at,
    )


def _item_delta_state(snapshot: PortfolioItemValuationSnapshotORM | None) -> PortfolioItemDeltaState:
    if snapshot is None:
        return unavailable_delta_state()
    if snapshot.delta_status != "available" or snapshot.delta_uf is None:
        return PortfolioItemDeltaState(
            status=PortfolioState.NEEDS_VALUATION,
            reason=snapshot.delta_unavailable_reason or "needs_current_valuation",
        )
    return PortfolioItemDeltaState(
        status=PortfolioState.AVAILABLE,
        available=True,
        delta_uf=snapshot.delta_uf,
        delta_pct=snapshot.delta_pct,
        snapshot_id=snapshot.id,
    )


def _item_trend_state(history: tuple[PortfolioItemValuationSnapshotORM, ...]) -> PortfolioTrendState:
    if len(history) < 2:
        return unavailable_trend_state()
    newest, oldest = history[0], history[-1]
    if newest.estimated_value_uf is None or oldest.estimated_value_uf in (None, Decimal("0")):
        return unavailable_trend_state()
    variation_pct = float(((newest.estimated_value_uf - oldest.estimated_value_uf) / oldest.estimated_value_uf) * 100)
    return PortfolioTrendState(
        status=PortfolioState.AVAILABLE,
        available=True,
        direction=_direction(variation_pct),
        points=tuple(reversed([snapshot.estimated_value_uf for snapshot in history if snapshot.estimated_value_uf is not None])),
        observation_window_days=_window_days(newest.snapshot_at, oldest.snapshot_at),
        variation_pct=variation_pct,
    )


def _summary_upside_state(
    snapshots: tuple[PortfolioAggregateSnapshotORM, ...],
) -> PortfolioUpsideState:
    if not snapshots:
        return unavailable_upside_state()
    latest = snapshots[0]
    if latest.total_upside_uf is None:
        return PortfolioUpsideState(status=PortfolioState.NEEDS_VALUATION, reason="needs_canonical_price")
    return PortfolioUpsideState(
        status=PortfolioState.AVAILABLE,
        available=True,
        total_upside_uf=latest.total_upside_uf,
        average_delta_pct=latest.average_delta_pct,
    )


def _summary_trend_state(
    snapshots: tuple[PortfolioAggregateSnapshotORM, ...],
) -> PortfolioTrendState:
    comparable = tuple(snapshot for snapshot in snapshots if snapshot.average_estimated_value_uf is not None)
    if len(comparable) < 2:
        return unavailable_trend_state()
    newest, oldest = comparable[0], comparable[-1]
    if oldest.average_estimated_value_uf in (None, Decimal("0")) or newest.average_estimated_value_uf is None:
        return unavailable_trend_state()
    variation_pct = float(
        ((newest.average_estimated_value_uf - oldest.average_estimated_value_uf) / oldest.average_estimated_value_uf)
        * 100
    )
    return PortfolioTrendState(
        status=PortfolioState.AVAILABLE,
        available=True,
        direction=_direction(variation_pct),
        points=tuple(reversed([snapshot.average_estimated_value_uf for snapshot in comparable])),
        observation_window_days=_window_days(newest.snapshot_at, oldest.snapshot_at),
        variation_pct=variation_pct,
    )


def _summary_history_state(
    snapshots: tuple[PortfolioAggregateSnapshotORM, ...],
) -> PortfolioHistoryState:
    comparable = tuple(snapshot for snapshot in snapshots if snapshot.average_estimated_value_uf is not None)
    if len(comparable) < 2:
        return unavailable_history_state()
    return PortfolioHistoryState(
        status=PortfolioState.AVAILABLE,
        available=True,
        points=tuple(
            {
                "snapshot_date": snapshot.snapshot_date.isoformat(),
                "snapshot_at": snapshot.snapshot_at.isoformat(),
                "average_estimated_value_uf": float(snapshot.average_estimated_value_uf),
                "coverage_count": snapshot.coverage_count,
                "unavailable_count": snapshot.unavailable_count,
            }
            for snapshot in reversed(comparable)
        ),
    )


def _capability_from_items(
    states: tuple[PortfolioCapabilityState, ...],
    fallback: PortfolioCapabilityState,
) -> PortfolioCapabilityState:
    if any(state.available for state in states):
        return PortfolioCapabilityState(status=PortfolioState.AVAILABLE, available=True)
    return fallback


def _direction(variation_pct: float) -> str:
    if variation_pct > 0:
        return "up"
    if variation_pct < 0:
        return "down"
    return "flat"


def _window_days(newest: datetime, oldest: datetime) -> int:
    return max((newest - oldest).days, 0)
