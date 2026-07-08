"""On-demand freshness checks for strong-intent listing flows."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings, get_settings
from core.ports.uf_service import UFRateInfo
from infrastructure.db.models import ListingORM
from services.uf_rate import require_real_uf_rate
from workers.refresh_scraper import RefreshStats, refresh_listing_once

FreshnessResultStatus = Literal[
    "already_fresh",
    "fresh_confirmed",
    "removed",
    "inactive",
    "blocked_or_captcha",
    "refresh_failed",
    "skipped_recent_attempt",
    "skipped_recent_block",
    "skipped_removed",
    "url_missing_or_invalid",
    "unknown",
]

REMOVED_REFRESH_STATUSES = {"removed_404", "removed_redirect", "removed", "not_found", "unavailable"}
INACTIVE_REFRESH_STATUSES = {"inactive_explicit", "inactive"}
BLOCKED_REFRESH_STATUSES = {"blocked_403", "blocked_or_captcha", "transient_429"}
FAILED_REFRESH_STATUSES = {
    "timeout",
    "http_error",
    "transient_5xx",
    "unexpected_html",
    "pipeline_error",
    "unexpected_error",
    "redirect",
}

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ListingFreshnessResult:
    status: FreshnessResultStatus
    listing_id: int | None
    reason: str
    refresh_attempted: bool = False
    last_seen_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    last_refresh_attempted_at: datetime | None = None
    last_refresh_status: str | None = None
    listing_status: str | None = None
    freshness_note: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


async def ensure_listing_fresh(
    listing_id: int,
    *,
    reason: str,
    session_factory: async_sessionmaker[AsyncSession],
    uf_service=None,
    settings: Settings | None = None,
    force: bool = False,
    now: datetime | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> ListingFreshnessResult:
    """Verify one listing URL when a user takes a strong-intent action."""
    settings = settings or get_settings()
    current_time = now or datetime.now(UTC)
    if (settings.is_cloud_beta or not settings.listing_on_demand_refresh_enabled) and not force:
        listing = await _load_listing(session_factory, listing_id)
        return _result_from_listing(
            listing,
            status="unknown",
            reason=reason,
            note="on_demand_refresh_disabled",
        )

    listing = await _load_listing(session_factory, listing_id)
    if listing is None:
        return ListingFreshnessResult(status="unknown", listing_id=listing_id, reason=reason)

    preflight = _preflight_result(
        listing,
        reason=reason,
        force=force,
        now=current_time,
        cooldown_hours=settings.listing_on_demand_refresh_cooldown_hours,
        skip_blocked_hours=settings.listing_on_demand_refresh_skip_blocked_hours,
    )
    if preflight is not None:
        return preflight

    uf_info = await _optional_uf_info(uf_service)
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        timeout=httpx.Timeout(settings.listing_on_demand_refresh_timeout_sec),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
        },
    )
    try:
        stats = await refresh_listing_once(
            session_factory,
            listing_id=listing_id,
            http_client=client,
            now=current_time,
            uf_to_clp=uf_info.rate if uf_info is not None else None,
            uf_rate_source=uf_info.source if uf_info is not None else None,
        )
    except Exception as exc:
        _log.warning("on-demand listing refresh failed listing_id=%s reason=%s error=%s", listing_id, reason, exc)
        latest = await _load_listing(session_factory, listing_id)
        return _result_from_listing(
            latest,
            status="refresh_failed",
            reason=reason,
            attempted=True,
            note="refresh_exception",
        )
    finally:
        if owns_client:
            await client.aclose()

    latest = await _load_listing(session_factory, listing_id)
    return _result_from_listing(
        latest,
        status=_status_from_stats(stats, latest),
        reason=reason,
        attempted=True,
        note=_note_from_stats(stats),
    )


def _preflight_result(
    listing: ListingORM,
    *,
    reason: str,
    force: bool,
    now: datetime,
    cooldown_hours: int,
    skip_blocked_hours: int,
) -> ListingFreshnessResult | None:
    if not listing.url or not str(listing.url).startswith(("http://", "https://")):
        return _result_from_listing(listing, status="url_missing_or_invalid", reason=reason)
    if not _is_supported_refresh_url(listing):
        return _result_from_listing(
            listing,
            status="url_missing_or_invalid",
            reason=reason,
            note="unsupported_refresh_url",
        )
    refresh_status = _normalized(listing.last_refresh_status)
    if listing.status in {"removed", "inactive"} and not force:
        return _result_from_listing(listing, status="skipped_removed", reason=reason)
    if refresh_status in REMOVED_REFRESH_STATUSES and not force:
        return _result_from_listing(listing, status="skipped_removed", reason=reason)
    if refresh_status in INACTIVE_REFRESH_STATUSES and not force:
        return _result_from_listing(listing, status="skipped_removed", reason=reason)
    last_attempt = _as_utc(listing.last_refresh_attempted_at)
    if (
        refresh_status in BLOCKED_REFRESH_STATUSES
        and last_attempt is not None
        and now - last_attempt < timedelta(hours=max(0, skip_blocked_hours))
        and not force
    ):
        return _result_from_listing(listing, status="skipped_recent_block", reason=reason)
    if (
        refresh_status == "ok"
        and last_attempt is not None
        and now - last_attempt < timedelta(hours=max(0, cooldown_hours))
        and not force
    ):
        return _result_from_listing(listing, status="already_fresh", reason=reason)
    if (
        last_attempt is not None
        and now - last_attempt < timedelta(hours=max(0, cooldown_hours))
        and not force
    ):
        return _result_from_listing(listing, status="skipped_recent_attempt", reason=reason)
    return None


async def _load_listing(
    session_factory: async_sessionmaker[AsyncSession],
    listing_id: int,
) -> ListingORM | None:
    async with session_factory() as session:
        return await session.get(ListingORM, listing_id)


async def _optional_uf_info(uf_service) -> UFRateInfo | None:
    if uf_service is None:
        return None
    try:
        return await require_real_uf_rate(uf_service)
    except Exception as exc:
        _log.warning("on-demand refresh continuing without UF rate: %s", exc)
        return None


def _status_from_stats(stats: RefreshStats, listing: ListingORM | None) -> FreshnessResultStatus:
    refresh_status = _normalized(getattr(listing, "last_refresh_status", None))
    listing_status = _normalized(getattr(listing, "status", None))
    if stats.refreshed_ok > 0 or refresh_status == "ok":
        return "fresh_confirmed"
    if stats.removed > 0 or refresh_status in REMOVED_REFRESH_STATUSES or listing_status == "removed":
        return "removed"
    if stats.inactive > 0 or refresh_status in INACTIVE_REFRESH_STATUSES or listing_status == "inactive":
        return "inactive"
    if stats.blocked_or_captcha > 0 or refresh_status in BLOCKED_REFRESH_STATUSES:
        return "blocked_or_captcha"
    if stats.unexpected_errors or stats.unexpected_http or stats.timeouts or stats.parse_errors or stats.validation_errors:
        return "refresh_failed"
    if refresh_status in FAILED_REFRESH_STATUSES:
        return "refresh_failed"
    return "unknown"


def _note_from_stats(stats: RefreshStats) -> str | None:
    if stats.reason_counts:
        return ",".join(f"{key}:{value}" for key, value in sorted(stats.reason_counts.items()))
    return None


def _result_from_listing(
    listing: ListingORM | None,
    *,
    status: FreshnessResultStatus,
    reason: str,
    attempted: bool = False,
    note: str | None = None,
) -> ListingFreshnessResult:
    return ListingFreshnessResult(
        status=status,
        listing_id=getattr(listing, "id", None),
        reason=reason,
        refresh_attempted=attempted,
        last_seen_at=getattr(listing, "last_seen_at", None),
        last_refreshed_at=getattr(listing, "last_refresh_attempted_at", None),
        last_refresh_attempted_at=getattr(listing, "last_refresh_attempted_at", None),
        last_refresh_status=getattr(listing, "last_refresh_status", None),
        listing_status=getattr(listing, "status", None),
        freshness_note=note,
    )


def _normalized(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _is_supported_refresh_url(listing: ListingORM) -> bool:
    source = _normalized(getattr(listing, "source", None))
    hostname = (urlparse(str(listing.url)).hostname or "").lower()
    if source == "yapo":
        return hostname == "yapo.cl" or hostname.endswith(".yapo.cl")
    if source == "portalinmobiliario":
        return "portalinmobiliario" in hostname
    return False


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

