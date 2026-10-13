"""Read-only aggregated market contract for the dashboard."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.db.models import ListingORM, PriceHistoryORM
from services.market_intelligence import (
    MARKET,
    PROPERTY_TYPE,
    MarketDataset,
    MarketIntelligenceConfig,
    PricePoint,
    _aware,
    _commune_confidence,
    _first_seen_at,
    _is_removed,
    _listing_row,
    _market_balance,
    _market_dynamism,
    _new_count,
    _observed_publication_time,
    _price_drop_stats,
    _price_m2_uf,
    _recent_activity,
    _removed_count,
    _removed_detected_at,
    _valid_price_point_value,
    price_drop_events,
)

ALLOWED_PERIODS = frozenset({7, 30, 90})
CHILE = ZoneInfo("America/Santiago")


def period_bounds(now: datetime, days: int) -> tuple[datetime, datetime]:
    """Completed Chilean calendar dates, [start, end), represented in UTC."""
    end = now.astimezone(CHILE).replace(hour=0, minute=0, second=0, microsecond=0)
    return (end - timedelta(days=days)).astimezone(UTC), end.astimezone(UTC)


async def build_market_dashboard_overview(
    session: AsyncSession,
    *,
    period_days: int = 30,
    commune: str | None = None,
    property_type: str | None = None,
    selected_commune: str | None = None,
    config: MarketIntelligenceConfig | None = None,
) -> dict[str, Any]:
    if period_days not in ALLOWED_PERIODS:
        raise ValueError("period_days debe ser uno de: 7, 30, 90")
    if property_type is not None and property_type.strip().lower() != PROPERTY_TYPE:
        raise ValueError("property_type no es compatible; el dashboard de mercado soporta solo apartment")

    cfg = config or MarketIntelligenceConfig()
    normalized_commune = _normalize_commune(commune)
    dataset, bedrooms_by_listing = await _load_dataset(session, commune=normalized_commune)
    cutoff, period_end = period_bounds(dataset.now, period_days)
    events = price_drop_events(dataset.price_points)
    observed = _observed_publication_time(dataset)
    standard_activity = _recent_activity(dataset)
    standard_drops = _price_drop_stats(dataset.price_points, now=dataset.now)
    balance = _market_balance(
        activity=standard_activity,
        price_drops=standard_drops,
        observed_time=observed,
        active_count=len(dataset.active),
    )
    activity = _activity_for_period(dataset, events=events, days=period_days)
    communes = _commune_summaries(dataset, events=events, period_days=period_days, config=cfg)
    selected = _selected_commune(communes, selected_commune)

    return {
        "status": "available" if dataset.scoped else "empty",
        "scope": {
            "market": MARKET,
            "property_type": PROPERTY_TYPE,
            "commune": normalized_commune,
            "period_days": period_days,
            "period_start_at": cutoff,
            "period_end_at": period_end,
            "time_zone": "America/Santiago",
            "window": "completed_calendar_days",
        },
        "cutoff_at": dataset.now,
        "overview": {
            "market_balance": balance,
            "confidence": balance["confidence"],
            "new_listings": activity["new_listings"],
            "removed_or_inactive": activity["removed_or_inactive"],
            "listings_with_price_drop": activity["listings_with_price_drop"],
            "price_drop_events": activity["price_drop_events"],
            "median_observed_days": observed.median_days,
        },
        "daily_pulse": _daily_pulse(dataset, events=events, cutoff=cutoff),
        "communes": communes,
        "selected_commune": selected,
        "bedrooms_supply": _bedrooms_supply(dataset, bedrooms_by_listing),
        "coverage": {
            "scoped_listings": len(dataset.scoped),
            "active_listings": len(dataset.active),
            "eligible_for_observed_time": observed.sample_size,
            "eligible_for_price_changes": standard_drops.eligible_listings,
            "communes_with_data": len(communes),
        },
        "methodology": "market_intelligence_v1; timestamps reflect Valoria observations, not original portal publication dates.",
    }


async def _load_dataset(
    session: AsyncSession,
    *,
    commune: str | None,
) -> tuple[MarketDataset, dict[int, int | None]]:
    now = datetime.now(UTC)
    statement = select(ListingORM).where(ListingORM.property_type == PROPERTY_TYPE)
    if commune:
        statement = statement.where(ListingORM.comuna == commune)
    listings = (await session.scalars(statement)).all()
    scoped = [_listing_row(row) for row in listings]
    listing_ids = [row.id for row in listings]
    points: list[PricePoint] = []
    if listing_ids:
        rows = await session.execute(
            select(
                PriceHistoryORM.listing_id,
                PriceHistoryORM.observed_at,
                PriceHistoryORM.price_uf,
                PriceHistoryORM.price_clp,
                PriceHistoryORM.price_clp_snapshot,
                PriceHistoryORM.change_basis,
                PriceHistoryORM.is_artifact,
                ListingORM.price_uf_source,
                ListingORM.price_recovery_method,
            )
            .join(ListingORM, ListingORM.id == PriceHistoryORM.listing_id)
            .where(PriceHistoryORM.listing_id.in_(listing_ids))
        )
        points = [
            PricePoint(
                listing_id=row.listing_id,
                observed_at=_aware(row.observed_at),
                price_uf=row.price_uf,
                price_clp=row.price_clp,
                price_clp_snapshot=row.price_clp_snapshot,
                change_basis=row.change_basis,
                is_artifact=bool(row.is_artifact),
                listing_price_uf_source=row.price_uf_source,
                listing_price_recovery_method=row.price_recovery_method,
            )
            for row in rows.all()
        ]
    return (
        MarketDataset(
            now=now,
            scoped=scoped,
            active=[row for row in scoped if row.status.strip().lower() == "active"],
            removed=[row for row in scoped if _is_removed(row)],
            price_points=points,
        ),
        {row.id: row.bedrooms for row in listings},
    )


def _activity_for_period(dataset: MarketDataset, *, events: list[tuple[int, datetime]], days: int) -> dict[str, int]:
    cutoff, end = period_bounds(dataset.now, days)
    filtered_events = [(listing_id, occurred_at) for listing_id, occurred_at in events if cutoff <= occurred_at < end]
    return {
        "new_listings": sum(1 for row in dataset.scoped if (dt := _first_seen_at(row)) is not None and cutoff <= dt < end),
        "removed_or_inactive": sum(1 for row in dataset.removed if (dt := _removed_detected_at(row)) is not None and cutoff <= dt < end),
        "listings_with_price_drop": len({listing_id for listing_id, _occurred_at in filtered_events}),
        "price_drop_events": len(filtered_events),
        "status": "available" if dataset.scoped else "empty",
    }


def _daily_pulse(dataset: MarketDataset, *, events: list[tuple[int, datetime]], cutoff: datetime) -> list[dict[str, Any]]:
    _, end = period_bounds(dataset.now, 1)
    first_date, end_date = cutoff.astimezone(CHILE).date(), end.astimezone(CHILE).date()
    days = [first_date + timedelta(days=offset) for offset in range((end_date - first_date).days)]
    new_by_day: dict[object, int] = defaultdict(int)
    removed_by_day: dict[object, int] = defaultdict(int)
    drop_events_by_day: dict[object, int] = defaultdict(int)
    drop_listings_by_day: dict[object, set[int]] = defaultdict(set)
    for row in dataset.scoped:
        if (first_seen := _first_seen_at(row)) is not None and cutoff <= first_seen < end:
            new_by_day[first_seen.astimezone(CHILE).date()] += 1
    for row in dataset.removed:
        if (removed_at := _removed_detected_at(row)) is not None and cutoff <= removed_at < end:
            removed_by_day[removed_at.astimezone(CHILE).date()] += 1
    for listing_id, occurred_at in events:
        if cutoff <= occurred_at < end:
            drop_events_by_day[occurred_at.astimezone(CHILE).date()] += 1
            drop_listings_by_day[occurred_at.astimezone(CHILE).date()].add(listing_id)
    return [
        {
            "date": day,
            "new_listings": new_by_day[day],
            "removed_or_inactive": removed_by_day[day],
            "listings_with_price_drop": len(drop_listings_by_day[day]),
            "price_drop_events": drop_events_by_day[day],
        }
        for day in days
    ]


def _commune_summaries(
    dataset: MarketDataset,
    *,
    events: list[tuple[int, datetime]],
    period_days: int,
    config: MarketIntelligenceConfig,
) -> list[dict[str, Any]]:
    rows_by_commune: dict[str, list[Any]] = defaultdict(list)
    for row in dataset.scoped:
        rows_by_commune[row.comuna].append(row)
    summaries = [
        _commune_summary(dataset, comuna=comuna, rows=rows, events=events, period_days=period_days, config=config)
        for comuna, rows in rows_by_commune.items()
    ]
    return sorted(summaries, key=lambda item: (item["active_listings"], item["new_listings"]), reverse=True)


def _commune_summary(dataset: MarketDataset, *, comuna: str, rows: list[Any], events: list[tuple[int, datetime]], period_days: int, config: MarketIntelligenceConfig) -> dict[str, Any]:
    row_ids = {row.id for row in rows}
    subset = MarketDataset(
        now=dataset.now,
        scoped=rows,
        active=[row for row in rows if row.status.strip().lower() == "active"],
        removed=[row for row in rows if _is_removed(row)],
        price_points=[point for point in dataset.price_points if point.listing_id in row_ids],
    )
    observed = _observed_publication_time(subset)
    drops = _price_drop_stats(subset.price_points, now=subset.now)
    standard_activity = _recent_activity(subset)
    balance = _market_balance(activity=standard_activity, price_drops=drops, observed_time=observed, active_count=len(subset.active))
    dynamism = _market_dynamism(activity=standard_activity, active_count=len(subset.active), communes_with_activity=1 if standard_activity["new_7d"] or standard_activity["removed_7d"] or standard_activity["price_drops_30d"] else 0, total_communes=1)
    activity = _activity_for_period(subset, events=[event for event in events if event[0] in row_ids], days=period_days)
    price_m2 = [value for row in subset.active if (value := _price_m2_uf(row)) is not None]
    valid_points = sum(1 for point in subset.price_points if _valid_price_point_value(point) is not None)
    return {
        "comuna": comuna,
        "active_listings": len(subset.active),
        "new_listings": activity["new_listings"],
        "listings_with_price_drop": activity["listings_with_price_drop"],
        "price_drop_events": activity["price_drop_events"],
        "median_price_m2_uf": round(float(median(price_m2)), 1) if price_m2 else None,
        "median_observed_days": observed.median_days,
        "market_balance": balance,
        "dynamism": dynamism,
        "confidence": _commune_confidence(len(subset.active), observed.sample_size, valid_points, config),
    }


def _selected_commune(communes: list[dict[str, Any]], selected_commune: str | None) -> dict[str, Any] | None:
    if selected_commune is None:
        return None
    normalized = _normalize_commune(selected_commune)
    for item in communes:
        if _normalize_commune(item["comuna"]) == normalized:
            return {"status": "available", **item}
    return {"status": "empty", "comuna": selected_commune}


def _bedrooms_supply(dataset: MarketDataset, bedrooms_by_listing: dict[int, int | None]) -> list[dict[str, Any]]:
    buckets = (("1", lambda value: value == 1), ("2", lambda value: value == 2), ("3", lambda value: value == 3), ("4_plus", lambda value: value is not None and value >= 4))
    return [{"bucket": label, "active_listings": sum(1 for row in dataset.active if predicate(bedrooms_by_listing.get(row.id)))} for label, predicate in buckets]


def _normalize_commune(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "_".join(value.strip().lower().replace("-", " ").split())
    return normalized or None
