"""APScheduler entrypoint for recurring background jobs.

Run with:
    python -m workers.scheduler

and keep the process alive with systemd, supervisor, or Docker restart policy.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from redis.asyncio import Redis

from config import get_settings
from config.constants import (
    SCRAPER_HTTP_TIMEOUT_SEC,
    SCRAPER_MIN_REQUEST_INTERVAL_SEC,
    SCRAPER_USER_AGENT,
)
from infrastructure.db.database import get_session_factory
from infrastructure.external.uf_client import UFClient
from infrastructure.scrapers.base import RateLimiter
from infrastructure.scrapers.portalinmobiliario import PortalInmobiliarioScraper
from infrastructure.scrapers.yapo import YapoScraper
from workers.alerts_job import run_alerts_job
from workers.refresh_scraper import (
    DEFAULT_REFRESH_COOLDOWN_HOURS,
    DEFAULT_REFRESH_LIMIT,
    DEFAULT_REFRESH_STALE_DAYS,
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
DEFAULT_ALERTS_THRESHOLD_PCT = 5.0
DEFAULT_ALERTS_LOOKBACK_DAYS = 30

DISCOVERY_JOB_ID = "discovery_scraper"
REFRESH_JOB_ID = "refresh_scraper"
ALERTS_JOB_ID = "alerts_job"

_DISCOVERY_REFRESH_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class SchedulerConfig:
    discovery_cron: str = DEFAULT_DISCOVERY_CRON
    refresh_cron: str = DEFAULT_REFRESH_CRON
    alerts_cron: str = DEFAULT_ALERTS_CRON
    refresh_limit: int = DEFAULT_REFRESH_LIMIT
    refresh_stale_days: int = DEFAULT_REFRESH_STALE_DAYS
    refresh_cooldown_hours: int = DEFAULT_REFRESH_COOLDOWN_HOURS
    alerts_threshold_pct: float = DEFAULT_ALERTS_THRESHOLD_PCT
    alerts_lookback_days: int = DEFAULT_ALERTS_LOOKBACK_DAYS


@dataclass(frozen=True)
class SchedulerJobs:
    discovery: Callable[[], Awaitable[None]]
    refresh: Callable[[], Awaitable[None]]
    alerts: Callable[[], Awaitable[None]]


def scheduler_config_from_env(env: Mapping[str, str] | None = None) -> SchedulerConfig:
    values = env or os.environ
    return SchedulerConfig(
        discovery_cron=values.get("SCHEDULER_DISCOVERY_CRON", DEFAULT_DISCOVERY_CRON),
        refresh_cron=values.get("SCHEDULER_REFRESH_CRON", DEFAULT_REFRESH_CRON),
        alerts_cron=values.get("SCHEDULER_ALERTS_CRON", DEFAULT_ALERTS_CRON),
        refresh_limit=_env_int(values, "SCHEDULER_REFRESH_LIMIT", DEFAULT_REFRESH_LIMIT),
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
    )
    effective_config = config or scheduler_config_from_env()

    scheduler = AsyncIOScheduler()
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


async def _run_discovery_scrape_job() -> None:
    _log.info("[discovery] start")
    settings = get_settings()
    session_factory = get_session_factory()

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
            rate = RateLimiter(min_interval=SCRAPER_MIN_REQUEST_INTERVAL_SEC)

            scrapers = [
                YapoScraper(
                    http_client=http,
                    rate_limiter=rate,
                    start_urls=_YAPO_URLS,
                    uf_service=uf_service,
                ),
                PortalInmobiliarioScraper(
                    http_client=http,
                    rate_limiter=rate,
                    start_urls=_PORTAL_URLS,
                    uf_service=uf_service,
                ),
            ]

            for scraper in scrapers:
                try:
                    stats = await run_scraper_job(scraper, session_factory)
                    _log.info(
                        "[discovery] source=%s scraped=%d processed=%d success_rate=%.1f%%",
                        scraper.source_name,
                        stats.scraped,
                        stats.processed,
                        stats.success_rate * 100,
                    )
                except Exception:
                    _log.exception(
                        "[discovery] source=%s failed; continuing",
                        scraper.source_name,
                    )
        finally:
            await redis.aclose()

    _log.info("[discovery] done")


async def _run_refresh_scraper_job() -> None:
    _log.info("[refresh] start")
    config = scheduler_config_from_env()
    async with httpx.AsyncClient(
        timeout=SCRAPER_HTTP_TIMEOUT_SEC,
        headers={"User-Agent": SCRAPER_USER_AGENT},
        follow_redirects=False,
    ) as http_client:
        stats = await run_refresh_scraper(
            get_session_factory(),
            http_client=http_client,
            limit=config.refresh_limit,
            stale_days=config.refresh_stale_days,
            cooldown_hours=config.refresh_cooldown_hours,
            rate_limiter=RateLimiter(SCRAPER_MIN_REQUEST_INTERVAL_SEC),
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

    scheduler = build_scheduler()
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


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
