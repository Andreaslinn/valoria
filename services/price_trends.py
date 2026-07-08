"""Read-only price trend service for market UF/m2 series."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.market_trends.contracts import PriceTrend, PriceTrendConfig, PriceTrendPoint
from infrastructure.db.models import ListingORM, PriceHistoryORM


class PriceTrendService:
    def __init__(self, session: AsyncSession, *, config: PriceTrendConfig | None = None) -> None:
        self._session = session
        self._config = config or PriceTrendConfig()

    async def price_m2_trend(
        self,
        *,
        comuna: str,
        property_type: str,
        period_months: int = 12,
    ) -> PriceTrend:
        comuna_slug = str(comuna or "").strip().lower()
        property_type_slug = str(property_type or "").strip().lower()
        period = _bounded_period(period_months)
        if not comuna_slug:
            return _empty_trend(comuna_slug, property_type_slug, period, ("unsupported_comuna",))
        if property_type_slug in self._config.unsupported_property_types or not property_type_slug:
            return _empty_trend(comuna_slug, property_type_slug, period, ("unsupported_property_type",))

        cutoff = datetime.now(UTC) - timedelta(days=period * 31)
        history_samples = await self._history_samples(
            comuna=comuna_slug,
            property_type=property_type_slug,
            cutoff=cutoff,
        )
        history_trend = _build_trend(
            history_samples,
            comuna=comuna_slug,
            property_type=property_type_slug,
            period_months=period,
            source="price_history",
            config=self._config,
        )
        if history_trend.status in {"available", "partial"}:
            return history_trend

        listing_samples = await self._listing_observed_samples(
            comuna=comuna_slug,
            property_type=property_type_slug,
            cutoff=cutoff,
        )
        fallback = _build_trend(
            listing_samples,
            comuna=comuna_slug,
            property_type=property_type_slug,
            period_months=period,
            source="listing_observed",
            config=self._config,
        )
        if fallback.status != "not_available":
            return PriceTrend(
                **{
                    **fallback.to_dict(),
                    "points": tuple(fallback.points),
                    "reasons": tuple(dict.fromkeys(("insufficient_price_history", *fallback.reasons))),
                    "warnings": tuple(dict.fromkeys(("source_listing_observed", *fallback.warnings))),
                }
            )
        return PriceTrend(
            status="not_available",
            metric="price_m2_uf",
            property_type=property_type_slug,
            comuna=comuna_slug,
            period_months=period,
            source="not_available",
            reasons=tuple(
                dict.fromkeys(
                    (
                        "insufficient_price_history",
                        "insufficient_monthly_points",
                        *history_trend.reasons,
                        *fallback.reasons,
                    )
                )
            ),
        )

    async def _history_samples(
        self,
        *,
        comuna: str,
        property_type: str,
        cutoff: datetime,
    ) -> list[tuple[datetime, float]]:
        stmt = (
            select(PriceHistoryORM.observed_at, PriceHistoryORM.price_uf, ListingORM.m2, ListingORM.built_area_m2, ListingORM.usable_area_m2)
            .join(ListingORM, ListingORM.id == PriceHistoryORM.listing_id)
            .where(ListingORM.comuna == comuna)
            .where(ListingORM.property_type == property_type)
            .where(PriceHistoryORM.observed_at >= cutoff)
            .where(PriceHistoryORM.is_artifact.is_(False))
            .where(PriceHistoryORM.price_uf.is_not(None))
            .where(ListingORM.price_uf_source.is_distinct_from("legacy_unrecoverable"))
        )
        result = await self._session.execute(stmt)
        samples: list[tuple[datetime, float]] = []
        for observed_at, price_uf, m2, built_area_m2, usable_area_m2 in result.all():
            surface = _surface_m2(usable_area_m2, built_area_m2, m2)
            value = _price_m2_uf(price_uf, surface)
            if value is None:
                continue
            samples.append((_aware_datetime(observed_at), value))
        return samples

    async def _listing_observed_samples(
        self,
        *,
        comuna: str,
        property_type: str,
        cutoff: datetime,
    ) -> list[tuple[datetime, float]]:
        stmt = (
            select(ListingORM.last_seen_at, ListingORM.scraped_at, ListingORM.price_uf, ListingORM.m2, ListingORM.built_area_m2, ListingORM.usable_area_m2)
            .where(ListingORM.comuna == comuna)
            .where(ListingORM.property_type == property_type)
            .where(ListingORM.price_uf.is_not(None))
            .where(ListingORM.price_uf_source.is_distinct_from("legacy_unrecoverable"))
            .where(ListingORM.last_seen_at >= cutoff)
        )
        result = await self._session.execute(stmt)
        samples: list[tuple[datetime, float]] = []
        for last_seen_at, scraped_at, price_uf, m2, built_area_m2, usable_area_m2 in result.all():
            surface = _surface_m2(usable_area_m2, built_area_m2, m2)
            value = _price_m2_uf(price_uf, surface)
            if value is None:
                continue
            samples.append((_aware_datetime(last_seen_at or scraped_at), value))
        return samples


def _build_trend(
    samples: list[tuple[datetime, float]],
    *,
    comuna: str,
    property_type: str,
    period_months: int,
    source: str,
    config: PriceTrendConfig,
) -> PriceTrend:
    grouped: dict[str, list[float]] = defaultdict(list)
    for observed_at, value in samples:
        grouped[f"{observed_at.year:04d}-{observed_at.month:02d}"].append(value)
    points = tuple(
        PriceTrendPoint(
            month=month,
            median_price_m2_uf=round(float(median(values)), 2),
            sample_count=len(values),
        )
        for month, values in sorted(grouped.items())
    )
    reasons = _coverage_reasons(points, samples)
    status = _status(points, config)
    latest = points[-1].median_price_m2_uf if points else None
    previous = points[-2].median_price_m2_uf if len(points) >= 2 else None
    change_pct = _change_pct(previous, latest)
    return PriceTrend(
        status=status,
        metric="price_m2_uf",
        property_type=property_type,
        comuna=comuna,
        period_months=period_months,
        points=points,
        latest_value=latest,
        previous_value=previous,
        change_pct=change_pct,
        direction=_direction(change_pct),
        coverage_count=len(samples),
        source=source if status != "not_available" else "not_available",
        reasons=reasons,
        warnings=_warnings(points, config),
    )


def _status(points: tuple[PriceTrendPoint, ...], config: PriceTrendConfig) -> str:
    if len(points) >= config.min_available_points and all(
        point.sample_count >= config.min_samples_per_available_point for point in points
    ):
        return "available"
    if len(points) >= config.min_partial_points:
        return "partial"
    return "not_available"


def _coverage_reasons(points: tuple[PriceTrendPoint, ...], samples: list[tuple[datetime, float]]) -> tuple[str, ...]:
    reasons: list[str] = []
    if not samples:
        reasons.append("missing_canonical_price")
        reasons.append("missing_surface")
    if len(points) < 3:
        reasons.append("insufficient_monthly_points")
    if points and any(point.sample_count < 3 for point in points):
        reasons.append("insufficient_sample_count")
    return tuple(dict.fromkeys(reasons))


def _warnings(points: tuple[PriceTrendPoint, ...], config: PriceTrendConfig) -> tuple[str, ...]:
    warnings: list[str] = []
    if points and any(point.sample_count < config.min_samples_per_available_point for point in points):
        warnings.append("low_monthly_sample_count")
    return tuple(warnings)


def _change_pct(previous: float | None, latest: float | None) -> float | None:
    if previous is None or latest is None or previous <= 0:
        return None
    return round(((latest - previous) / previous) * 100, 2)


def _direction(change_pct: float | None) -> str:
    if change_pct is None:
        return "unknown"
    if change_pct > 1:
        return "up"
    if change_pct < -1:
        return "down"
    return "flat"


def _surface_m2(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        surface = float(value)
        if surface > 0:
            return surface
    return None


def _price_m2_uf(price_uf: Decimal | float | int | None, surface: float | None) -> float | None:
    if price_uf is None or surface is None or surface <= 0:
        return None
    value = float(price_uf) / surface
    return value if value > 0 else None


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _bounded_period(value: int) -> int:
    try:
        period = int(value)
    except (TypeError, ValueError):
        return 12
    return max(3, min(36, period))


def _empty_trend(comuna: str, property_type: str, period_months: int, reasons: tuple[str, ...]) -> PriceTrend:
    return PriceTrend(
        status="not_available",
        metric="price_m2_uf",
        property_type=property_type,
        comuna=comuna,
        period_months=period_months,
        source="not_available",
        reasons=reasons,
    )
