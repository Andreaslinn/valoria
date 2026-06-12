"""Independent alert evaluation job.

This job reads persisted listing + price_history data and writes alerts. It does
not run scraping, refresh listings, or modify listings.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infrastructure.db.repositories import SqlAlchemyAlertRepository
from services.alerts import detect_price_drops_with_stats

_log = logging.getLogger(__name__)
_DEFAULT_DEDUPE_SINCE = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass
class AlertJobStats:
    listings_evaluated: int = 0
    detected: int = 0
    created: int = 0
    skipped: int = 0


async def run_alerts_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    threshold_pct: float = 5.0,
    lookback_days: int = 30,
    dedupe_since: datetime | None = _DEFAULT_DEDUPE_SINCE,
) -> AlertJobStats:
    """Evaluate price-drop alerts from existing database state."""
    async with session_factory() as session:
        repo = SqlAlchemyAlertRepository(session)
        detection = await detect_price_drops_with_stats(
            session,
            threshold_pct=threshold_pct,
            lookback_days=lookback_days,
        )
        drops = detection.drops
        stats = AlertJobStats(
            listings_evaluated=detection.listings_evaluated,
            detected=len(drops),
        )
        for drop in drops:
            listing_id = int(drop["listing_id"])
            if await repo.price_drop_event_exists(
                listing_id=listing_id,
                previous_price_uf=drop.get("previous_price_uf"),
                new_price_uf=drop.get("new_price_uf"),
                previous_price_clp_snapshot=drop.get("previous_price_clp_snapshot"),
                new_price_clp_snapshot=drop.get("new_price_clp_snapshot"),
                change_basis=drop.get("change_basis"),
                since=dedupe_since,
            ):
                stats.skipped += 1
                continue
            await repo.create_alert(
                listing_id=listing_id,
                alert_type="price_drop",
                payload=_price_drop_payload(drop),
            )
            stats.created += 1
        await session.commit()
    _log.info(
        (
            "Alert job completed listings_evaluated=%d price_drops_detected=%d "
            "alerts_created=%d alerts_skipped_duplicate=%d"
        ),
        stats.listings_evaluated,
        stats.detected,
        stats.created,
        stats.skipped,
    )
    return stats


def _price_drop_payload(drop: dict[str, Any]) -> dict[str, Any]:
    detected_at = drop.get("detected_at")
    return {
        "previous_price_clp": int(drop["previous_price_clp"] or 0),
        "new_price_clp": int(drop["new_price_clp"] or 0),
        "previous_price_uf": drop.get("previous_price_uf"),
        "new_price_uf": drop.get("new_price_uf"),
        "previous_price_clp_snapshot": drop.get("previous_price_clp_snapshot"),
        "new_price_clp_snapshot": drop.get("new_price_clp_snapshot"),
        "price_currency": drop.get("price_currency"),
        "change_basis": drop.get("change_basis"),
        "canonical_previous_price": drop.get("canonical_previous_price"),
        "canonical_new_price": drop.get("canonical_new_price"),
        "canonical_price_unit": drop.get("canonical_price_unit"),
        "display_previous_price_clp": drop.get("display_previous_price_clp"),
        "display_new_price_clp": drop.get("display_new_price_clp"),
        "artifact_filtered": bool(drop.get("artifact_filtered", False)),
        "drop_pct": float(drop["drop_pct"]),
        "detected_at": detected_at.isoformat() if isinstance(detected_at, datetime) else str(detected_at),
        "source": drop.get("source"),
    }
