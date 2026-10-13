"""Scheduled Portfolio AVM snapshot job.

The job derives Portfolio snapshots from live DB state. It is bounded by config,
idempotent through a recent aggregate snapshot check, and safe to dry-run.
"""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from infrastructure.db.database import get_session_factory
from infrastructure.db.models import PortfolioAggregateSnapshotORM, SavedListingORM
from infrastructure.db.repositories import SqlAlchemyListingRepository
from infrastructure.external.uf_client import UFClient
from services.portfolio_snapshots import PortfolioSnapshotService
from services.valuation import ValuationService

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PortfolioSnapshotsJobConfig:
    enabled: bool = False
    limit_users: int = 10
    limit_items_per_user: int = 20
    min_interval_hours: int = 20
    dry_run: bool = False
    user_id: int | None = None


@dataclass(frozen=True)
class PortfolioSnapshotsJobStats:
    users_seen: int = 0
    users_selected: int = 0
    users_skipped_no_watchlist: int = 0
    users_skipped_recent_snapshot: int = 0
    users_processed: int = 0
    items_attempted: int = 0
    items_valued: int = 0
    items_unavailable: int = 0
    snapshots_created: int = 0
    dry_run: bool = False
    errors_count: int = 0
    unavailable_reasons_count: dict[str, int] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "users_seen": self.users_seen,
            "users_selected": self.users_selected,
            "users_skipped_no_watchlist": self.users_skipped_no_watchlist,
            "users_skipped_recent_snapshot": self.users_skipped_recent_snapshot,
            "users_processed": self.users_processed,
            "items_attempted": self.items_attempted,
            "items_valued": self.items_valued,
            "items_unavailable": self.items_unavailable,
            "snapshots_created": self.snapshots_created,
            "dry_run": self.dry_run,
            "errors_count": self.errors_count,
            "unavailable_reasons_count": dict(self.unavailable_reasons_count),
        }


ValuationServiceFactory = Callable[[AsyncSession], ValuationService]


async def run_portfolio_snapshots_job(
    config: PortfolioSnapshotsJobConfig | None = None,
    *,
    session_factory=None,
    valuation_service_factory: ValuationServiceFactory | None = None,
    now: datetime | None = None,
) -> PortfolioSnapshotsJobStats:
    effective_config = config or PortfolioSnapshotsJobConfig()
    reference_time = _ensure_aware(now or datetime.now(UTC))
    if not effective_config.enabled:
        stats = PortfolioSnapshotsJobStats(dry_run=effective_config.dry_run)
        _log.info("[portfolio_snapshots] skipped disabled stats=%s", stats.to_payload())
        return stats

    resolved_session_factory = session_factory or get_session_factory()
    if valuation_service_factory is not None:
        return await _run_with_factory(
            effective_config,
            resolved_session_factory,
            valuation_service_factory,
            reference_time,
        )

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    async with httpx.AsyncClient() as http_client:

        def default_factory(session: AsyncSession) -> ValuationService:
            uf_service = UFClient(
                api_url=settings.uf_api_url,
                http_client=http_client,
                redis=redis,
                cache_ttl=settings.uf_cache_ttl_hours * 60 * 60,
                max_staleness_days=settings.uf_max_staleness_days,
                allow_stale_on_failure=settings.uf_allow_stale_on_failure,
                session_factory=resolved_session_factory,
            )
            return ValuationService(
                listing_repo=SqlAlchemyListingRepository(session),
                uf_service=uf_service,
                final_price_policy="canonical_only",
            )

        try:
            return await _run_with_factory(
                effective_config,
                resolved_session_factory,
                default_factory,
                reference_time,
            )
        finally:
            await redis.aclose()


async def _run_with_factory(
    config: PortfolioSnapshotsJobConfig,
    session_factory,
    valuation_service_factory: ValuationServiceFactory,
    now: datetime,
) -> PortfolioSnapshotsJobStats:
    users_seen, user_ids, skipped_no_watchlist = await _select_user_ids(
        session_factory,
        config,
    )
    reasons = Counter()
    users_skipped_recent = 0
    users_processed = 0
    items_attempted = 0
    items_valued = 0
    items_unavailable = 0
    snapshots_created = 0
    errors_count = 0

    for user_id in user_ids:
        try:
            async with session_factory() as session:
                if await _has_recent_snapshot(
                    session,
                    user_id=user_id,
                    min_interval_hours=config.min_interval_hours,
                    now=now,
                ):
                    users_skipped_recent += 1
                    continue

                service = PortfolioSnapshotService(
                    session,
                    valuation_service_factory(session),
                )
                result = await service.create_snapshot(
                    user_id=user_id,
                    limit=config.limit_items_per_user,
                    dry_run=config.dry_run,
                    now=now,
                )
                users_processed += 1
                items_attempted += result.processed_count
                items_valued += result.valued_count
                items_unavailable += result.unavailable_count
                snapshots_created += 1 if result.aggregate_snapshot_id is not None else 0
                reasons.update(result.reasons)
        except Exception:
            errors_count += 1
            _log.exception("[portfolio_snapshots] user_id=%s failed; continuing", user_id)

    stats = PortfolioSnapshotsJobStats(
        users_seen=users_seen,
        users_selected=len(user_ids),
        users_skipped_no_watchlist=skipped_no_watchlist,
        users_skipped_recent_snapshot=users_skipped_recent,
        users_processed=users_processed,
        items_attempted=items_attempted,
        items_valued=items_valued,
        items_unavailable=items_unavailable,
        snapshots_created=snapshots_created,
        dry_run=config.dry_run,
        errors_count=errors_count,
        unavailable_reasons_count=dict(sorted(reasons.items())),
    )
    _log.info("[portfolio_snapshots] done stats=%s", stats.to_payload())
    return stats


async def _select_user_ids(
    session_factory,
    config: PortfolioSnapshotsJobConfig,
) -> tuple[int, list[int], int]:
    limit_users = max(0, int(config.limit_users))
    if config.user_id is not None:
        async with session_factory() as session:
            has_watchlist = await session.scalar(
                select(SavedListingORM.id)
                .where(SavedListingORM.user_id == config.user_id)
                .where(SavedListingORM.status == "active")
                .limit(1)
            )
        return 1, ([config.user_id] if has_watchlist is not None and limit_users > 0 else []), (
            0 if has_watchlist is not None else 1
        )

    async with session_factory() as session:
        users_seen = int(
            await session.scalar(
                select(func.count(func.distinct(SavedListingORM.user_id))).where(
                    SavedListingORM.status == "active"
                )
            )
            or 0
        )
        if limit_users <= 0:
            return users_seen, [], 0
        rows = await session.execute(
            select(SavedListingORM.user_id)
            .where(SavedListingORM.status == "active")
            .group_by(SavedListingORM.user_id)
            .order_by(SavedListingORM.user_id)
            .limit(limit_users)
        )
        return users_seen, [int(user_id) for user_id in rows.scalars().all()], 0


async def _has_recent_snapshot(
    session: AsyncSession,
    *,
    user_id: int,
    min_interval_hours: int,
    now: datetime,
) -> bool:
    cutoff = now - timedelta(hours=max(0, int(min_interval_hours)))
    stmt = (
        select(PortfolioAggregateSnapshotORM.id)
        .where(PortfolioAggregateSnapshotORM.user_id == user_id)
        .where(PortfolioAggregateSnapshotORM.snapshot_at >= cutoff)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
