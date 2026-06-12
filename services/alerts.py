"""Alert service helpers backed by database state."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.alerts.price_drop_detector import detect_price_drop_from_history
from infrastructure.db.models import ListingORM, PriceHistoryORM

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PriceDropDetectionResult:
    drops: list[dict[str, Any]]
    listings_evaluated: int


async def detect_price_drops(
    session: AsyncSession,
    threshold_pct: float = 5.0,
    lookback_days: int = 30,
) -> list[dict[str, Any]]:
    result = await detect_price_drops_with_stats(
        session,
        threshold_pct=threshold_pct,
        lookback_days=lookback_days,
    )
    return result.drops


async def detect_price_drops_with_stats(
    session: AsyncSession,
    threshold_pct: float = 5.0,
    lookback_days: int = 30,
) -> PriceDropDetectionResult:
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    listing_rows = await _active_listing_rows(session, cutoff)
    history_by_listing_id = await _latest_price_points_for_listings(
        session,
        [listing_id for listing_id, *_ in listing_rows],
    )
    drops: list[dict[str, Any]] = []
    for (
        listing_id,
        source,
        current_price_clp,
        current_price_uf,
        price_currency,
        price_uf_source,
        price_uf_confidence,
        price_recovery_method,
        scraped_at,
    ) in listing_rows:
        if _is_weak_current_uf_price(
            price_currency=price_currency,
            price_uf_source=price_uf_source,
            price_uf_confidence=price_uf_confidence,
        ):
            continue
        history = [
            {
                "price_clp": current_price_clp,
                "price_clp_snapshot": current_price_clp,
                "price_uf": current_price_uf,
                "price_currency": price_currency,
                "price_uf_source": price_uf_source,
                "price_uf_confidence": price_uf_confidence,
                "price_recovery_method": price_recovery_method,
                "change_basis": _current_change_basis(price_currency),
                "observed_at": scraped_at,
            },
            *history_by_listing_id.get(listing_id, []),
        ]
        detected = detect_price_drop_from_history(history, threshold_pct=threshold_pct)
        if detected is None:
            continue
        drops.append({"listing_id": listing_id, "source": source, **detected})
    _log.info(
        "Price drop detection completed listings_evaluated=%d price_drops_detected=%d",
        len(listing_rows),
        len(drops),
    )
    return PriceDropDetectionResult(drops=drops, listings_evaluated=len(listing_rows))


async def _active_listing_rows(session: AsyncSession, cutoff: datetime) -> list[tuple[int, str, Any, Any, Any, Any, Any, Any, Any]]:
    stmt = (
        select(
            ListingORM.id,
            ListingORM.source,
            ListingORM.price_clp,
            ListingORM.price_uf,
            ListingORM.price_currency,
            ListingORM.price_uf_source,
            ListingORM.price_uf_confidence,
            ListingORM.price_recovery_method,
            ListingORM.scraped_at,
        )
        .where(ListingORM.status == "active")
        .where(ListingORM.scraped_at >= cutoff)
        .order_by(ListingORM.scraped_at.desc())
    )
    return [
        (int(row[0]), str(row[1]), row[2], row[3], row[4], row[5], row[6], row[7], row[8])
        for row in (await session.execute(stmt)).all()
    ]


async def _latest_price_points_for_listings(
    session: AsyncSession,
    listing_ids: list[int],
) -> dict[int, list[dict[str, Any]]]:
    if not listing_ids:
        return {}

    ranked_history = (
        select(
            PriceHistoryORM.listing_id.label("listing_id"),
            PriceHistoryORM.price_clp.label("price_clp"),
            PriceHistoryORM.price_clp_snapshot.label("price_clp_snapshot"),
            PriceHistoryORM.price_uf.label("price_uf"),
            PriceHistoryORM.price_currency.label("price_currency"),
            PriceHistoryORM.change_basis.label("change_basis"),
            PriceHistoryORM.is_artifact.label("is_artifact"),
            PriceHistoryORM.observed_at.label("observed_at"),
            func.row_number()
            .over(
                partition_by=PriceHistoryORM.listing_id,
                order_by=PriceHistoryORM.observed_at.desc(),
            )
            .label("row_num"),
        )
        .where(PriceHistoryORM.listing_id.in_(listing_ids))
        .where(PriceHistoryORM.is_artifact.is_(False))
        .subquery()
    )
    stmt = (
        select(
            ranked_history.c.listing_id,
            ranked_history.c.price_clp,
            ranked_history.c.price_clp_snapshot,
            ranked_history.c.price_uf,
            ranked_history.c.price_currency,
            ranked_history.c.change_basis,
            ranked_history.c.is_artifact,
            ranked_history.c.observed_at,
        )
        .where(ranked_history.c.row_num <= 2)
        .order_by(ranked_history.c.listing_id.asc(), ranked_history.c.observed_at.desc())
    )
    rows_by_listing_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in (await session.execute(stmt)).all():
        rows_by_listing_id[int(row.listing_id)].append(
            {
                "price_clp": row.price_clp,
                "price_clp_snapshot": row.price_clp_snapshot or row.price_clp,
                "price_uf": row.price_uf,
                "price_currency": row.price_currency,
                "change_basis": row.change_basis,
                "is_artifact": bool(row.is_artifact),
                "observed_at": row.observed_at,
            }
        )
    return dict(rows_by_listing_id)


def _current_change_basis(price_currency: str | None) -> str:
    if price_currency == "UF":
        return "uf_current"
    if price_currency == "CLP":
        return "clp_current"
    return "legacy_current"


def _is_weak_current_uf_price(
    *,
    price_currency: str | None,
    price_uf_source: str | None,
    price_uf_confidence: str | None,
) -> bool:
    if str(price_currency or "").strip().upper() != "UF":
        return False
    source = str(price_uf_source or "").strip().lower()
    confidence = str(price_uf_confidence or "").strip().lower()
    return source == "estimated" or confidence == "low"
