"""APScheduler entrypoint for recurring background jobs.

Run with:
    python -m workers.scheduler

and keep the process alive with systemd, supervisor, or Docker restart policy.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from redis.asyncio import Redis
from sqlalchemy import func, select

from config import get_settings
from config.constants import (
    SCRAPER_HTTP_TIMEOUT_SEC,
    SCRAPER_MIN_REQUEST_INTERVAL_SEC,
    SCRAPER_USER_AGENT,
    YAPO_MAX_PAGES_HARD_LIMIT,
    YAPO_TARGETS,
)
from infrastructure.db.database import get_session_factory
from infrastructure.db.models import AlertORM, ListingORM
from infrastructure.external.uf_client import UFClient
from infrastructure.scrapers.base import RateLimiter
from infrastructure.scrapers.portalinmobiliario import PortalInmobiliarioScraper
from infrastructure.scrapers.yapo import YapoScraper
from workers.alerts_job import AlertJobStats, run_alerts_job
from workers.portfolio_snapshots_job import (
    PortfolioSnapshotsJobConfig,
    run_portfolio_snapshots_job,
)
from workers.refresh_scraper import (
    DEFAULT_REFRESH_COOLDOWN_HOURS,
    DEFAULT_REFRESH_STALE_DAYS,
    RefreshStats,
    count_refresh_candidates,
    run_refresh_scraper,
)
from workers.scraper_job import run_scraper_job

_log = logging.getLogger(__name__)


# URLs de arranque. Actualizar segun el estado de los sitios.
_YAPO_URLS = (
    "https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-apartamentos"
    "?q=keyword.departamentos%20venta",
)
_PORTAL_URLS = (
    "https://www.portalinmobiliario.com/venta/departamento/propiedades-usadas/",
)

DEFAULT_DISCOVERY_CRON = "0 10 * * *"
DEFAULT_REFRESH_CRON = "0 12 * * mon,wed,fri"
DEFAULT_ALERTS_CRON = "0 13 * * *"
DEFAULT_DISCOVERY_MAX_PAGES = 0
DEFAULT_DISCOVERY_SLEEP_SECONDS = SCRAPER_MIN_REQUEST_INTERVAL_SEC
DEFAULT_SCHEDULER_REFRESH_LIMIT = 5
DEFAULT_ALERTS_THRESHOLD_PCT = 5.0
DEFAULT_ALERTS_LOOKBACK_DAYS = 30
DEFAULT_ENABLE_DISCOVERY = False
DEFAULT_ENABLE_PORTAL = False
DEFAULT_STARTUP_CATCHUP_ENABLED = False
DEFAULT_STARTUP_REFRESH_ENABLED = True
DEFAULT_STARTUP_ALERTS_ENABLED = True
DEFAULT_STARTUP_MIN_STALE_HOURS = 24
DEFAULT_ENABLE_UF_DAILY_SNAPSHOT = True
DEFAULT_UF_REFRESH_ON_STARTUP = True
DEFAULT_UF_REFRESH_HOUR = 8
DEFAULT_ENABLE_PORTFOLIO_SNAPSHOTS = False
DEFAULT_PORTFOLIO_SNAPSHOTS_CRON = "0 14 * * *"
DEFAULT_PORTFOLIO_SNAPSHOTS_LIMIT_USERS = 10
DEFAULT_PORTFOLIO_SNAPSHOTS_LIMIT_ITEMS_PER_USER = 20
DEFAULT_PORTFOLIO_SNAPSHOTS_MIN_INTERVAL_HOURS = 20
DEFAULT_PORTFOLIO_SNAPSHOTS_DRY_RUN = False
DEFAULT_PORTFOLIO_SNAPSHOTS_STARTUP_CATCHUP_ENABLED = False

DISCOVERY_JOB_ID = "discovery_scraper"
REFRESH_JOB_ID = "refresh_scraper"
ALERTS_JOB_ID = "alerts_job"
UF_DAILY_SNAPSHOT_JOB_ID = "uf_daily_snapshot_job"
PORTFOLIO_SNAPSHOTS_JOB_ID = "portfolio_snapshots_job"

_DISCOVERY_REFRESH_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class SchedulerConfig:
    enable_discovery: bool = DEFAULT_ENABLE_DISCOVERY
    enable_portal: bool = DEFAULT_ENABLE_PORTAL
    startup_catchup_enabled: bool = DEFAULT_STARTUP_CATCHUP_ENABLED
    startup_refresh_enabled: bool = DEFAULT_STARTUP_REFRESH_ENABLED
    startup_alerts_enabled: bool = DEFAULT_STARTUP_ALERTS_ENABLED
    startup_min_stale_hours: int = DEFAULT_STARTUP_MIN_STALE_HOURS
    discovery_cron: str = DEFAULT_DISCOVERY_CRON
    refresh_cron: str = DEFAULT_REFRESH_CRON
    alerts_cron: str = DEFAULT_ALERTS_CRON
    discovery_max_pages: int = DEFAULT_DISCOVERY_MAX_PAGES
    discovery_sleep_seconds: float = DEFAULT_DISCOVERY_SLEEP_SECONDS
    refresh_limit: int = DEFAULT_SCHEDULER_REFRESH_LIMIT
    refresh_stale_days: int = DEFAULT_REFRESH_STALE_DAYS
    refresh_cooldown_hours: int = DEFAULT_REFRESH_COOLDOWN_HOURS
    alerts_threshold_pct: float = DEFAULT_ALERTS_THRESHOLD_PCT
    alerts_lookback_days: int = DEFAULT_ALERTS_LOOKBACK_DAYS
    enable_uf_daily_snapshot: bool = DEFAULT_ENABLE_UF_DAILY_SNAPSHOT
    uf_refresh_on_startup: bool = DEFAULT_UF_REFRESH_ON_STARTUP
    uf_refresh_hour: int = DEFAULT_UF_REFRESH_HOUR
    enable_portfolio_snapshots: bool = DEFAULT_ENABLE_PORTFOLIO_SNAPSHOTS
    portfolio_snapshots_cron: str = DEFAULT_PORTFOLIO_SNAPSHOTS_CRON
    portfolio_snapshots_limit_users: int = DEFAULT_PORTFOLIO_SNAPSHOTS_LIMIT_USERS
    portfolio_snapshots_limit_items_per_user: int = DEFAULT_PORTFOLIO_SNAPSHOTS_LIMIT_ITEMS_PER_USER
    portfolio_snapshots_min_interval_hours: int = DEFAULT_PORTFOLIO_SNAPSHOTS_MIN_INTERVAL_HOURS
    portfolio_snapshots_dry_run: bool = DEFAULT_PORTFOLIO_SNAPSHOTS_DRY_RUN
    portfolio_snapshots_user_id: int | None = None
    portfolio_snapshots_startup_catchup_enabled: bool = (
        DEFAULT_PORTFOLIO_SNAPSHOTS_STARTUP_CATCHUP_ENABLED
    )


@dataclass(frozen=True)
class SchedulerJobs:
    discovery: Callable[[], Awaitable[None]]
    refresh: Callable[[], Awaitable[None]]
    alerts: Callable[[], Awaitable[None]]
    uf_daily_snapshot: Callable[[], Awaitable[None]] | None = None
    portfolio_snapshots: Callable[[], Awaitable[None]] | None = None


@dataclass(frozen=True)
class StartupFreshness:
    generated_at: datetime
    refresh_candidates: int = 0
    latest_refresh_attempted_at: datetime | None = None
    latest_alert_created_at: datetime | None = None


@dataclass(frozen=True)
class StartupCatchupDecision:
    job: str
    run: bool
    reason: str
    candidates: int = 0
    limit: int = 0
    cooldown_hours: int = 0
    last_run_at: datetime | None = None


@dataclass(frozen=True)
class StartupCatchupResult:
    refresh_decision: StartupCatchupDecision
    alerts_decision: StartupCatchupDecision
    refresh_stats: RefreshStats | None = None
    alerts_stats: AlertJobStats | None = None


def scheduler_config_from_env(env: Mapping[str, str] | None = None) -> SchedulerConfig:
    values = env or os.environ
    return SchedulerConfig(
        enable_discovery=_env_bool(
            values,
            "SCHEDULER_ENABLE_DISCOVERY",
            DEFAULT_ENABLE_DISCOVERY,
        ),
        enable_portal=_env_bool(values, "SCHEDULER_ENABLE_PORTAL", DEFAULT_ENABLE_PORTAL),
        startup_catchup_enabled=_env_bool(
            values,
            "SCHEDULER_STARTUP_CATCHUP_ENABLED",
            DEFAULT_STARTUP_CATCHUP_ENABLED,
        ),
        startup_refresh_enabled=_env_bool(
            values,
            "SCHEDULER_STARTUP_REFRESH_ENABLED",
            DEFAULT_STARTUP_REFRESH_ENABLED,
        ),
        startup_alerts_enabled=_env_bool(
            values,
            "SCHEDULER_STARTUP_ALERTS_ENABLED",
            DEFAULT_STARTUP_ALERTS_ENABLED,
        ),
        startup_min_stale_hours=_env_int(
            values,
            "SCHEDULER_STARTUP_MIN_STALE_HOURS",
            DEFAULT_STARTUP_MIN_STALE_HOURS,
        ),
        discovery_cron=values.get("SCHEDULER_DISCOVERY_CRON", DEFAULT_DISCOVERY_CRON),
        refresh_cron=values.get("SCHEDULER_REFRESH_CRON", DEFAULT_REFRESH_CRON),
        alerts_cron=values.get("SCHEDULER_ALERTS_CRON", DEFAULT_ALERTS_CRON),
        discovery_max_pages=_env_int(
            values,
            "SCHEDULER_DISCOVERY_MAX_PAGES",
            DEFAULT_DISCOVERY_MAX_PAGES,
        ),
        discovery_sleep_seconds=_env_float(
            values,
            "SCHEDULER_DISCOVERY_SLEEP_SECONDS",
            DEFAULT_DISCOVERY_SLEEP_SECONDS,
        ),
        refresh_limit=_env_int(
            values,
            "SCHEDULER_REFRESH_LIMIT",
            DEFAULT_SCHEDULER_REFRESH_LIMIT,
        ),
        refresh_stale_days=_env_int(
            values,
            "SCHEDULER_REFRESH_STALE_DAYS",
            DEFAULT_REFRESH_STALE_DAYS,
        ),
        refresh_cooldown_hours=_env_int(
            values,
            "SCHEDULER_REFRESH_COOLDOWN_HOURS",
            DEFAULT_REFRESH_COOLDOWN_HOURS,
        ),
        alerts_threshold_pct=_env_float(
            values,
            "SCHEDULER_ALERTS_THRESHOLD_PCT",
            DEFAULT_ALERTS_THRESHOLD_PCT,
        ),
        alerts_lookback_days=_env_int(
            values,
            "SCHEDULER_ALERTS_LOOKBACK_DAYS",
            DEFAULT_ALERTS_LOOKBACK_DAYS,
        ),
        enable_uf_daily_snapshot=_env_bool(
            values,
            "SCHEDULER_ENABLE_UF_DAILY_SNAPSHOT",
            DEFAULT_ENABLE_UF_DAILY_SNAPSHOT,
        ),
        uf_refresh_on_startup=_env_bool(
            values,
            "UF_REFRESH_ON_STARTUP",
            DEFAULT_UF_REFRESH_ON_STARTUP,
        ),
        uf_refresh_hour=_env_int(values, "UF_REFRESH_HOUR", DEFAULT_UF_REFRESH_HOUR),
        enable_portfolio_snapshots=_env_bool(
            values,
            "PORTFOLIO_SNAPSHOTS_ENABLED",
            DEFAULT_ENABLE_PORTFOLIO_SNAPSHOTS,
        ),
        portfolio_snapshots_cron=values.get(
            "PORTFOLIO_SNAPSHOTS_CRON",
            DEFAULT_PORTFOLIO_SNAPSHOTS_CRON,
        ),
        portfolio_snapshots_limit_users=_env_int(
            values,
            "PORTFOLIO_SNAPSHOTS_LIMIT_USERS",
            DEFAULT_PORTFOLIO_SNAPSHOTS_LIMIT_USERS,
        ),
        portfolio_snapshots_limit_items_per_user=_env_int(
            values,
            "PORTFOLIO_SNAPSHOTS_LIMIT_ITEMS_PER_USER",
            DEFAULT_PORTFOLIO_SNAPSHOTS_LIMIT_ITEMS_PER_USER,
        ),
        portfolio_snapshots_min_interval_hours=_env_int(
            values,
            "PORTFOLIO_SNAPSHOTS_MIN_INTERVAL_HOURS",
            DEFAULT_PORTFOLIO_SNAPSHOTS_MIN_INTERVAL_HOURS,
        ),
        portfolio_snapshots_dry_run=_env_bool(
            values,
            "PORTFOLIO_SNAPSHOTS_DRY_RUN",
            DEFAULT_PORTFOLIO_SNAPSHOTS_DRY_RUN,
        ),
        portfolio_snapshots_user_id=_env_optional_int(values, "PORTFOLIO_SNAPSHOTS_USER_ID"),
        portfolio_snapshots_startup_catchup_enabled=_env_bool(
            values,
            "PORTFOLIO_SNAPSHOTS_STARTUP_CATCHUP_ENABLED",
            DEFAULT_PORTFOLIO_SNAPSHOTS_STARTUP_CATCHUP_ENABLED,
        ),
    )


async def collect_startup_freshness(
    session_factory,
    config: SchedulerConfig,
    *,
    now: datetime | None = None,
) -> StartupFreshness:
    reference_time = _ensure_aware(now or datetime.now(UTC))
    refresh_source = _refresh_source_for_config(config)
    refresh_candidates = await count_refresh_candidates(
        session_factory,
        stale_days=config.refresh_stale_days,
        cooldown_hours=config.refresh_cooldown_hours,
        now=reference_time,
        source=refresh_source,
    )

    async with session_factory() as session:
        latest_refresh_stmt = select(func.max(ListingORM.last_refresh_attempted_at))
        if refresh_source:
            latest_refresh_stmt = latest_refresh_stmt.where(ListingORM.source == refresh_source)
        latest_refresh_attempted_at = await session.scalar(latest_refresh_stmt)
        latest_alert_created_at = await session.scalar(select(func.max(AlertORM.created_at)))

    return StartupFreshness(
        generated_at=reference_time,
        refresh_candidates=refresh_candidates,
        latest_refresh_attempted_at=_ensure_aware_or_none(latest_refresh_attempted_at),
        latest_alert_created_at=_ensure_aware_or_none(latest_alert_created_at),
    )


def should_run_startup_refresh(
    config: SchedulerConfig,
    freshness: StartupFreshness,
    *,
    now: datetime | None = None,
) -> StartupCatchupDecision:
    latest_refresh = _ensure_aware_or_none(freshness.latest_refresh_attempted_at)
    decision = StartupCatchupDecision(
        job=REFRESH_JOB_ID,
        run=False,
        reason="startup_catchup_disabled",
        candidates=freshness.refresh_candidates,
        limit=max(0, int(config.refresh_limit)),
        cooldown_hours=max(0, int(config.refresh_cooldown_hours)),
        last_run_at=latest_refresh,
    )
    if not config.startup_catchup_enabled:
        return decision
    if not config.startup_refresh_enabled:
        return replace(decision, reason="startup_refresh_disabled")
    if config.refresh_limit <= 0:
        return replace(decision, reason="refresh_limit_not_positive")
    if freshness.refresh_candidates <= 0:
        return replace(decision, reason="no_refresh_candidates")
    if _is_recent(latest_refresh, config.startup_min_stale_hours, now or freshness.generated_at):
        return replace(decision, reason="refresh_recent")
    if latest_refresh is None:
        return replace(decision, run=True, reason="never_refreshed_candidates")
    if not _has_missed_cron_window(config.refresh_cron, latest_refresh, now or freshness.generated_at):
        return replace(decision, reason="no_missed_refresh_window")
    return replace(decision, run=True, reason="refresh_stale")


def should_run_startup_alerts(
    config: SchedulerConfig,
    freshness: StartupFreshness,
    *,
    now: datetime | None = None,
) -> StartupCatchupDecision:
    latest_alert = _ensure_aware_or_none(freshness.latest_alert_created_at)
    decision = StartupCatchupDecision(
        job=ALERTS_JOB_ID,
        run=False,
        reason="startup_catchup_disabled",
        last_run_at=latest_alert,
    )
    if not config.startup_catchup_enabled:
        return decision
    if not config.startup_alerts_enabled:
        return replace(decision, reason="startup_alerts_disabled")
    if _is_recent(latest_alert, config.startup_min_stale_hours, now or freshness.generated_at):
        return replace(decision, reason="alerts_recent")
    if latest_alert is None:
        return replace(decision, run=True, reason="no_previous_alert_created")
    if not _has_missed_cron_window(config.alerts_cron, latest_alert, now or freshness.generated_at):
        return replace(decision, reason="no_missed_alerts_window")
    return replace(decision, run=True, reason="alerts_stale")


async def run_startup_catchup(
    config: SchedulerConfig | None = None,
    *,
    session_factory=None,
    now: datetime | None = None,
) -> StartupCatchupResult:
    effective_config = config or scheduler_config_from_env()
    reference_time = _ensure_aware(now or datetime.now(UTC))
    _log_startup_config(effective_config)

    empty_freshness = StartupFreshness(generated_at=reference_time)
    if not effective_config.startup_catchup_enabled:
        if effective_config.enable_uf_daily_snapshot and effective_config.uf_refresh_on_startup:
            await _run_startup_uf_snapshot()
        refresh_decision = should_run_startup_refresh(
            effective_config,
            empty_freshness,
            now=reference_time,
        )
        alerts_decision = should_run_startup_alerts(
            effective_config,
            empty_freshness,
            now=reference_time,
        )
        _log_startup_decision(refresh_decision)
        _log_startup_decision(alerts_decision)
        return StartupCatchupResult(
            refresh_decision=refresh_decision,
            alerts_decision=alerts_decision,
        )

    resolved_session_factory = session_factory or get_session_factory()
    try:
        freshness = await collect_startup_freshness(
            resolved_session_factory,
            effective_config,
            now=reference_time,
        )
    except Exception:
        _log.exception("[startup] freshness check failed; continuing with normal scheduler")
        refresh_decision = StartupCatchupDecision(
            job=REFRESH_JOB_ID,
            run=False,
            reason="freshness_check_failed",
            limit=max(0, int(effective_config.refresh_limit)),
            cooldown_hours=max(0, int(effective_config.refresh_cooldown_hours)),
        )
        alerts_decision = StartupCatchupDecision(
            job=ALERTS_JOB_ID,
            run=False,
            reason="freshness_check_failed",
        )
        return StartupCatchupResult(
            refresh_decision=refresh_decision,
            alerts_decision=alerts_decision,
        )

    refresh_decision = should_run_startup_refresh(
        effective_config,
        freshness,
        now=reference_time,
    )
    alerts_decision = should_run_startup_alerts(
        effective_config,
        freshness,
        now=reference_time,
    )
    _log_startup_decision(refresh_decision)
    _log_startup_decision(alerts_decision)

    if effective_config.enable_uf_daily_snapshot and effective_config.uf_refresh_on_startup:
        await _run_startup_uf_snapshot()

    refresh_stats = None
    alerts_stats = None
    if refresh_decision.run:
        try:
            async with _DISCOVERY_REFRESH_LOCK:
                refresh_stats = await _run_startup_refresh(
                    effective_config,
                    resolved_session_factory,
                    now=reference_time,
                )
            _log_startup_refresh_result(refresh_stats)
        except Exception:
            _log.exception("[startup] refresh catch-up failed; continuing")
            refresh_decision = replace(
                refresh_decision,
                run=False,
                reason="startup_refresh_failed",
            )

    if alerts_decision.run:
        try:
            async with _DISCOVERY_REFRESH_LOCK:
                alerts_stats = await _run_startup_alerts(
                    effective_config,
                    resolved_session_factory,
                )
            _log_startup_alerts_result(alerts_stats)
        except Exception:
            _log.exception("[startup] alerts catch-up failed; continuing")
            alerts_decision = replace(
                alerts_decision,
                run=False,
                reason="startup_alerts_failed",
            )

    return StartupCatchupResult(
        refresh_decision=refresh_decision,
        alerts_decision=alerts_decision,
        refresh_stats=refresh_stats,
        alerts_stats=alerts_stats,
    )


def build_scheduler(
    job: Callable[[], Awaitable[None]] | None = None,
    *,
    jobs: SchedulerJobs | None = None,
    config: SchedulerConfig | None = None,
) -> AsyncIOScheduler:
    effective_jobs = jobs or SchedulerJobs(
        discovery=job or daily_scrape_job,
        refresh=refresh_scraper_job,
        alerts=alerts_job,
        uf_daily_snapshot=uf_daily_snapshot_job,
        portfolio_snapshots=portfolio_snapshots_job,
    )
    effective_config = config or scheduler_config_from_env()

    scheduler = AsyncIOScheduler()
    if effective_config.enable_discovery:
        _add_job(
            scheduler,
            job_id=DISCOVERY_JOB_ID,
            func=effective_jobs.discovery,
            cron=effective_config.discovery_cron,
        )
    _add_job(
        scheduler,
        job_id=REFRESH_JOB_ID,
        func=effective_jobs.refresh,
        cron=effective_config.refresh_cron,
    )
    _add_job(
        scheduler,
        job_id=ALERTS_JOB_ID,
        func=effective_jobs.alerts,
        cron=effective_config.alerts_cron,
    )
    if effective_config.enable_uf_daily_snapshot:
        _add_job(
            scheduler,
            job_id=UF_DAILY_SNAPSHOT_JOB_ID,
            func=effective_jobs.uf_daily_snapshot or uf_daily_snapshot_job,
            cron=f"0 {max(0, min(23, int(effective_config.uf_refresh_hour)))} * * *",
        )
    if effective_config.enable_portfolio_snapshots:
        _add_job(
            scheduler,
            job_id=PORTFOLIO_SNAPSHOTS_JOB_ID,
            func=effective_jobs.portfolio_snapshots or portfolio_snapshots_job,
            cron=effective_config.portfolio_snapshots_cron,
        )
    return scheduler


async def daily_scrape_job() -> None:
    """Run discovery scrapers in sequence and persist their results."""
    async with _DISCOVERY_REFRESH_LOCK:
        await _run_discovery_scrape_job()


async def refresh_scraper_job() -> None:
    """Refresh already known listing URLs without running discovery."""
    async with _DISCOVERY_REFRESH_LOCK:
        await _run_refresh_scraper_job()


async def alerts_job() -> None:
    """Evaluate alerts from existing database state without scraping."""
    async with _DISCOVERY_REFRESH_LOCK:
        _log.info("[alerts] start")
        config = scheduler_config_from_env()
        stats = await run_alerts_job(
            get_session_factory(),
            threshold_pct=config.alerts_threshold_pct,
            lookback_days=config.alerts_lookback_days,
        )
        _log.info(
            "[alerts] done detected=%d created=%d skipped=%d",
            stats.detected,
            stats.created,
            stats.skipped,
        )


async def portfolio_snapshots_job() -> None:
    """Create bounded Portfolio snapshots from live DB state."""
    async with _DISCOVERY_REFRESH_LOCK:
        config = scheduler_config_from_env()
        stats = await run_portfolio_snapshots_job(
            PortfolioSnapshotsJobConfig(
                enabled=config.enable_portfolio_snapshots,
                limit_users=config.portfolio_snapshots_limit_users,
                limit_items_per_user=config.portfolio_snapshots_limit_items_per_user,
                min_interval_hours=config.portfolio_snapshots_min_interval_hours,
                dry_run=config.portfolio_snapshots_dry_run,
                user_id=config.portfolio_snapshots_user_id,
            )
        )
        _log.info("[portfolio_snapshots] scheduler stats=%s", stats.to_payload())


async def uf_daily_snapshot_job() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    async with httpx.AsyncClient() as http_client:
        client = UFClient(
            api_url=settings.uf_api_url,
            http_client=http_client,
            redis=redis,
            cache_ttl=settings.uf_cache_ttl_hours * 60 * 60,
            max_staleness_days=settings.uf_max_staleness_days,
            allow_stale_on_failure=settings.uf_allow_stale_on_failure,
            session_factory=get_session_factory(),
        )
        try:
            info = await client.ensure_daily_snapshot()
            _log.info(
                "[uf_daily_snapshot] ready date=%s value=%s source=%s cache_hit=%s",
                info.rate_date,
                info.rate,
                info.source,
                info.cache_hit,
            )
        finally:
            await redis.aclose()


async def _run_startup_uf_snapshot() -> None:
    try:
        await uf_daily_snapshot_job()
    except Exception:
        _log.exception("[startup] uf daily snapshot failed; continuing")


async def _run_discovery_scrape_job() -> None:
    started_at = datetime.now(UTC)
    _log.info("[discovery] start")
    config = scheduler_config_from_env()
    targets = _discovery_yapo_targets(config)
    target_pages = _target_pages_summary(targets)
    _log.info(
        (
            "[discovery] enabled=%s source=yapo portal_enabled=%s targets=%d "
            "pages_per_target=%s sleep_seconds=%.2f"
        ),
        config.enable_discovery,
        config.enable_portal,
        len(targets),
        target_pages,
        max(0.0, float(config.discovery_sleep_seconds)),
    )
    settings = get_settings()
    session_factory = get_session_factory()
    stats_by_source: dict[str, Any] = {}

    async with httpx.AsyncClient(
        timeout=SCRAPER_HTTP_TIMEOUT_SEC,
        headers={"User-Agent": SCRAPER_USER_AGENT},
        follow_redirects=True,
    ) as http:
        redis = Redis.from_url(settings.redis_url)
        try:
            uf_service = UFClient(
                api_url=settings.uf_api_url,
                http_client=http,
                redis=redis,
            )
            rate = RateLimiter(min_interval=max(0.0, float(config.discovery_sleep_seconds)))

            scrapers = [
                YapoScraper(
                    http_client=http,
                    rate_limiter=rate,
                    targets=targets,
                    uf_service=uf_service,
                ),
            ]
            if config.enable_portal:
                scrapers.append(
                    PortalInmobiliarioScraper(
                        http_client=http,
                        rate_limiter=rate,
                        start_urls=_PORTAL_URLS,
                        uf_service=uf_service,
                    )
                )
            else:
                _log.info("[discovery] portalinmobiliario disabled by scheduler config")

            for scraper in scrapers:
                try:
                    stats = await run_scraper_job(scraper, session_factory)
                    blocked_or_captcha = int(getattr(scraper, "last_blocked_or_captcha_count", 0))
                    forbidden = int(getattr(scraper, "last_forbidden_count", 0))
                    rate_limited = int(getattr(scraper, "last_rate_limited_count", 0))
                    fetch_errors = int(getattr(scraper, "last_fetch_error_count", 0))
                    stats.discovery_blocked_or_captcha = blocked_or_captcha
                    stats.discovery_forbidden = forbidden
                    stats.discovery_rate_limited = rate_limited
                    stats.discovery_fetch_errors = fetch_errors
                    stats_by_source[scraper.source_name] = stats
                    _log.info(
                        (
                            "[discovery] source=%s scraped_count=%d unique_count=%d "
                            "new_count=%d updated_count=%d skipped_count=%d errors=%d "
                            "captcha=%d http_403=%d http_429=%d success_rate=%.1f%%"
                        ),
                        scraper.source_name,
                        stats.raw_scraped,
                        stats.scraped,
                        stats.inserted,
                        stats.updated,
                        stats.skipped,
                        stats.validation_errors + stats.unexpected_errors + fetch_errors,
                        blocked_or_captcha,
                        forbidden,
                        rate_limited,
                        stats.success_rate * 100,
                    )
                    if blocked_or_captcha or forbidden or rate_limited:
                        _log.warning(
                            (
                                "[discovery] block_guardrail_triggered source=%s "
                                "captcha=%d http_403=%d http_429=%d; stopping discovery"
                            ),
                            scraper.source_name,
                            blocked_or_captcha,
                            forbidden,
                            rate_limited,
                        )
                        break
                except Exception:
                    _log.exception(
                        "[discovery] source=%s failed; continuing",
                        scraper.source_name,
                    )
        finally:
            await redis.aclose()

    _write_discovery_activation_report(
        stats_by_source=stats_by_source,
        config=config,
        targets=targets,
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )
    _log.info("[discovery] done")


async def _run_refresh_scraper_job() -> None:
    _log.info("[refresh] start")
    config = scheduler_config_from_env()
    refresh_source = _refresh_source_for_config(config)
    async with httpx.AsyncClient(
        timeout=SCRAPER_HTTP_TIMEOUT_SEC,
        headers={"User-Agent": SCRAPER_USER_AGENT},
        follow_redirects=False,
    ) as http_client:
        stats = await run_refresh_scraper(
            get_session_factory(),
            http_client=http_client,
            limit=max(0, int(config.refresh_limit)),
            stale_days=config.refresh_stale_days,
            cooldown_hours=config.refresh_cooldown_hours,
            rate_limiter=RateLimiter(SCRAPER_MIN_REQUEST_INTERVAL_SEC),
            source=refresh_source,
        )

    _log.info(
        (
            "[refresh] done selected=%d fetched=%d processed=%d removed=%d "
            "inactive=%d timeouts=%d rate_limited=%d server_errors=%d"
        ),
        stats.selected,
        stats.fetched,
        stats.processed,
        stats.removed,
        stats.inactive,
        stats.timeouts,
        stats.rate_limited,
        stats.server_errors,
    )


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    if settings.is_cloud_beta or not settings.scheduler_enabled:
        _log.info(
            "Scheduler disabled for runtime profile=%s environment=%s",
            settings.valoria_runtime_profile,
            settings.environment,
        )
        return

    config = scheduler_config_from_env()
    await run_startup_catchup(config=config)
    scheduler = build_scheduler(config=config)
    scheduler.start()
    _log.info("Scheduler started. Next runs: %s", _next_runs(scheduler))

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


def _add_job(
    scheduler: AsyncIOScheduler,
    *,
    job_id: str,
    func: Callable[[], Awaitable[None]],
    cron: str,
) -> None:
    scheduler.add_job(
        func,
        trigger=CronTrigger.from_crontab(cron),
        id=job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


def _next_runs(scheduler: AsyncIOScheduler) -> str:
    return ", ".join(
        f"{job.id}={job.next_run_time}" for job in scheduler.get_jobs()
    ) or "n/a"


async def _run_startup_refresh(
    config: SchedulerConfig,
    session_factory,
    *,
    now: datetime | None = None,
) -> RefreshStats:
    refresh_source = _refresh_source_for_config(config)
    async with httpx.AsyncClient(
        timeout=SCRAPER_HTTP_TIMEOUT_SEC,
        headers={"User-Agent": SCRAPER_USER_AGENT},
        follow_redirects=False,
    ) as http_client:
        return await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            limit=max(0, int(config.refresh_limit)),
            stale_days=config.refresh_stale_days,
            cooldown_hours=config.refresh_cooldown_hours,
            rate_limiter=RateLimiter(SCRAPER_MIN_REQUEST_INTERVAL_SEC),
            source=refresh_source,
            max_errors=max(1, int(config.refresh_limit)),
            stop_on_block=True,
            now=now,
        )


async def _run_startup_alerts(
    config: SchedulerConfig,
    session_factory,
) -> AlertJobStats:
    return await run_alerts_job(
        session_factory,
        threshold_pct=config.alerts_threshold_pct,
        lookback_days=config.alerts_lookback_days,
    )


def _refresh_source_for_config(config: SchedulerConfig) -> str | None:
    if config.enable_portal:
        return None
    return "yapo"


def _discovery_yapo_targets(config: SchedulerConfig) -> list[dict[str, Any]]:
    max_pages = max(0, min(int(config.discovery_max_pages), YAPO_MAX_PAGES_HARD_LIMIT))
    if max_pages <= 0:
        return [dict(target) for target in YAPO_TARGETS]
    return [{**target, "max_pages": max_pages} for target in YAPO_TARGETS]


def _target_pages_summary(targets: list[dict[str, Any]]) -> dict[str, int]:
    pages: dict[str, int] = {}
    for target in targets:
        value = int(target.get("max_pages", 0))
        pages[str(value)] = pages.get(str(value), 0) + 1
    return {key: pages[key] for key in sorted(pages, key=int)}


def _write_discovery_activation_report(
    *,
    stats_by_source: dict[str, Any],
    config: SchedulerConfig,
    targets: list[dict[str, Any]],
    started_at: datetime,
    finished_at: datetime,
) -> None:
    report_dir = Path("reports") / "discovery"
    report_dir.mkdir(parents=True, exist_ok=True)
    duration_sec = round((finished_at - started_at).total_seconds(), 3)
    yapo_stats = stats_by_source.get("yapo")
    payload = {
        "generated_at": finished_at.isoformat(),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_sec": duration_sec,
        "portal_enabled": config.enable_portal,
        "discovery_enabled": config.enable_discovery,
        "target_count": len(targets),
        "pages_per_target": _target_pages_summary(targets),
        "targets": [
            {
                "label": str(target.get("label", "")),
                "scope": str(target.get("scope", "")),
                "property_type": str(target.get("property_type", "")),
                "max_pages": int(target.get("max_pages", 0)),
                "query": str(target.get("query", "")),
            }
            for target in targets
        ],
        "summary": _stats_report_payload(yapo_stats),
        "recommendation": _discovery_recommendation(yapo_stats, config),
        "confirmations": {
            "no_portal": not config.enable_portal,
            "no_valuation": True,
            "no_radar": True,
            "no_comparables": True,
            "no_ui": True,
            "no_deploy": True,
        },
    }
    json_path = report_dir / "discovery_activation_latest.json"
    md_path = report_dir / "discovery_activation_latest.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    md_path.write_text(_discovery_report_markdown(payload), encoding="utf-8")


def _stats_report_payload(stats: Any) -> dict[str, Any]:
    if stats is None:
        return {
            "source": "yapo",
            "scraped_count": 0,
            "unique_count": 0,
            "new_count": 0,
            "updated_count": 0,
            "skipped_count": 0,
            "errors": 0,
            "captcha": 0,
            "http_403": 0,
            "http_429": 0,
            "by_target": {},
            "health_warnings": ["discovery_not_run_or_failed_before_stats"],
        }
    return {
        "source": stats.source,
        "scraped_count": stats.raw_scraped,
        "unique_count": stats.scraped,
        "new_count": stats.inserted,
        "updated_count": stats.updated,
        "skipped_count": stats.skipped,
        "fetch_errors": int(getattr(stats, "discovery_fetch_errors", 0)),
        "errors": (
            stats.validation_errors
            + stats.unexpected_errors
            + int(getattr(stats, "discovery_fetch_errors", 0))
        ),
        "captcha": int(getattr(stats, "discovery_blocked_or_captcha", 0)),
        "http_403": int(getattr(stats, "discovery_forbidden", 0)),
        "http_429": int(getattr(stats, "discovery_rate_limited", 0)),
        "by_target": stats.by_target,
        "health_warnings": stats.health_warnings,
    }


def _discovery_recommendation(stats: Any, config: SchedulerConfig) -> str:
    if config.enable_portal:
        return "Apagar PortalInmobiliario para mantener el alcance beta/local solicitado."
    if stats is None:
        return "Revisar logs de discovery; no se obtuvo estadistica Yapo."
    if stats.raw_scraped == 0:
        return "No subir frecuencia; revisar bloqueo, HTML o conectividad antes de otra corrida."
    if stats.inserted == 0 and stats.updated == 0:
        return "Discovery encuentra candidatos pero no cambia base; revisar duplicados/skips antes de aumentar cadencia."
    return "Mantener discovery Yapo con baja frecuencia y revisar la distribucion por target antes de ampliar volumen."


def _discovery_report_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Discovery Yapo activation latest",
        "",
        f"Generated at: {payload['generated_at']}",
        f"Duration seconds: {payload['duration_sec']}",
        "",
        "## Scope confirmations",
        "",
        f"- No Portal: {payload['confirmations']['no_portal']}",
        f"- No valuation: {payload['confirmations']['no_valuation']}",
        f"- No Radar: {payload['confirmations']['no_radar']}",
        f"- No comparables: {payload['confirmations']['no_comparables']}",
        f"- No UI: {payload['confirmations']['no_ui']}",
        f"- No deploy: {payload['confirmations']['no_deploy']}",
        "",
        "## Run summary",
        "",
        f"- Discovery enabled: {payload['discovery_enabled']}",
        f"- Portal enabled: {payload['portal_enabled']}",
        f"- Targets executed: {payload['target_count']}",
        f"- Pages per target: {payload['pages_per_target']}",
        f"- Listings scraped: {summary['scraped_count']}",
        f"- Unique listings: {summary['unique_count']}",
        f"- New inserted: {summary['new_count']}",
        f"- Existing updated: {summary['updated_count']}",
        f"- Existing skipped: {summary['skipped_count']}",
        f"- Errors: {summary['errors']}",
        f"- Captcha/block: {summary['captcha']}",
        f"- HTTP 403: {summary['http_403']}",
        f"- HTTP 429: {summary['http_429']}",
        "",
        "## Recommendation",
        "",
        str(payload["recommendation"]),
        "",
        "## Targets",
        "",
    ]
    for target in payload["targets"]:
        lines.append(
            "- {label} | {property_type} | pages={max_pages} | scope={scope} | query={query}".format(
                **target
            )
        )
    lines.append("")
    lines.append("## By target")
    lines.append("")
    if summary["by_target"]:
        for label, values in sorted(summary["by_target"].items()):
            lines.append(f"- {label}: {values}")
    else:
        lines.append("- No target stats captured.")
    lines.append("")
    return "\n".join(lines)


def _is_recent(value: datetime | None, min_stale_hours: int, now: datetime) -> bool:
    if value is None:
        return False
    reference_time = _ensure_aware(now)
    latest = _ensure_aware(value)
    cutoff = reference_time - timedelta(hours=max(0, int(min_stale_hours)))
    return latest >= cutoff


def _has_missed_cron_window(cron: str, last_run_at: datetime | None, now: datetime) -> bool:
    if last_run_at is None:
        return True
    reference_time = _ensure_aware(now)
    probe_time = _ensure_aware(last_run_at) + timedelta(seconds=1)
    next_fire = CronTrigger.from_crontab(cron).get_next_fire_time(None, probe_time)
    return next_fire is not None and _ensure_aware(next_fire) <= reference_time


def _ensure_aware_or_none(value: datetime | None) -> datetime | None:
    return None if value is None else _ensure_aware(value)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _log_startup_config(config: SchedulerConfig) -> None:
    _log.info(
        (
            "[startup] effective config catchup=%s startup_refresh=%s startup_alerts=%s "
            "min_stale_hours=%d discovery=%s portal=%s refresh_limit=%d "
            "refresh_stale_days=%d refresh_cooldown_hours=%d refresh_source=%s "
            "refresh_cron=%s alerts_cron=%s"
        ),
        config.startup_catchup_enabled,
        config.startup_refresh_enabled,
        config.startup_alerts_enabled,
        config.startup_min_stale_hours,
        config.enable_discovery,
        config.enable_portal,
        config.refresh_limit,
        config.refresh_stale_days,
        config.refresh_cooldown_hours,
        _refresh_source_for_config(config) or "all_enabled_sources",
        config.refresh_cron,
        config.alerts_cron,
    )
    _log.info(
        (
            "[startup] portfolio_snapshots enabled=%s cron=%s limit_users=%d "
            "limit_items=%d min_interval_hours=%d dry_run=%s user_id=%s catchup=%s"
        ),
        config.enable_portfolio_snapshots,
        config.portfolio_snapshots_cron,
        config.portfolio_snapshots_limit_users,
        config.portfolio_snapshots_limit_items_per_user,
        config.portfolio_snapshots_min_interval_hours,
        config.portfolio_snapshots_dry_run,
        config.portfolio_snapshots_user_id,
        config.portfolio_snapshots_startup_catchup_enabled,
    )
    if config.enable_discovery:
        _log.warning("[startup] discovery enabled by explicit scheduler config")
    else:
        _log.info("[startup] discovery disabled")
    if config.enable_portal:
        _log.warning("[startup] PortalInmobiliario enabled by explicit scheduler config")
    else:
        _log.info("[startup] PortalInmobiliario disabled")


def _log_startup_decision(decision: StartupCatchupDecision) -> None:
    _log.info(
        (
            "[startup] %s decision=%s reason=%s candidates=%d limit=%d "
            "cooldown_hours=%d last_run_at=%s"
        ),
        decision.job,
        "run" if decision.run else "skip",
        decision.reason,
        decision.candidates,
        decision.limit,
        decision.cooldown_hours,
        _format_datetime(decision.last_run_at),
    )


def _log_startup_refresh_result(stats: RefreshStats) -> None:
    _log.info(
        (
            "[startup] refresh result attempted=%d fetched=%d ok=%d updated=%d "
            "unchanged=%d captcha=%d http_403=%d http_429=%d http_5xx=%d errors=%d"
        ),
        stats.attempted,
        stats.fetched,
        stats.refreshed_ok,
        stats.updated,
        stats.unchanged,
        stats.blocked_or_captcha,
        stats.forbidden,
        stats.rate_limited,
        stats.server_errors,
        _refresh_error_count(stats),
    )


def _log_startup_alerts_result(stats: AlertJobStats) -> None:
    _log.info(
        (
            "[startup] alerts result listings_evaluated=%d detected=%d "
            "created=%d skipped=%d"
        ),
        stats.listings_evaluated,
        stats.detected,
        stats.created,
        stats.skipped,
    )


def _refresh_error_count(stats: RefreshStats) -> int:
    return (
        stats.forbidden
        + stats.rate_limited
        + stats.server_errors
        + stats.timeouts
        + stats.parse_errors
        + stats.validation_errors
        + stats.unexpected_http
        + stats.unexpected_errors
        + stats.blocked_or_captcha
    )


def _format_datetime(value: datetime | None) -> str:
    return "none" if value is None else value.isoformat()


def _env_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name)
    if raw is None:
        return default
    return int(raw)


def _env_float(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name)
    if raw is None:
        return default
    return float(raw)


def _env_bool(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_optional_int(values: Mapping[str, str], name: str) -> int | None:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return None
    return int(raw)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())

