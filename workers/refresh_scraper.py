"""Minimal direct-URL refresh for already persisted listings.

This job intentionally does not discover new listings, mark stale rows, or
create alerts. It only revisits old active listing URLs and sends successfully
parsed pages through the existing ingestion pipeline.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.constants import MAX_BATHROOMS, MAX_BEDROOMS, SCRAPER_MIN_REQUEST_INTERVAL_SEC
from core.entities.listing import Listing
from core.exceptions import UnknownComunaError, ValidationError
from core.normalization.geocode_precision import geocode_precision_rank
from domain.ingestion.data_cleaning import match_comuna_candidate
from domain.ingestion.pipeline import process_listing
from infrastructure.db.mappers import listing_from_orm
from infrastructure.db.models import ListingORM, PriceHistoryORM, SavedListingORM
from infrastructure.db.repositories import (
    SqlAlchemyListingRepository,
    SqlAlchemyPriceHistoryRepository,
    SqlAlchemyPropertyRepository,
)
from infrastructure.scrapers.base import RateLimiter, ScraperResult
from infrastructure.scrapers.portalinmobiliario import PortalInmobiliarioScraper
from infrastructure.scrapers.yapo import parse_listing_detail

_log = logging.getLogger(__name__)

DEFAULT_REFRESH_LIMIT = 100
DEFAULT_REFRESH_STALE_DAYS = 30
DEFAULT_REFRESH_COOLDOWN_HOURS = 24
REFRESH_RECENT_DAYS = 30
REFRESH_LAST_REVIEW_DAYS = 45

RefreshParser = Callable[[Listing, str], ScraperResult | None]
ProcessListingFn = Callable[..., Awaitable[Listing]]


@dataclass
class RefreshStats:
    source: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_sec: float = 0.0
    stage_durations_sec: dict[str, float] = field(default_factory=dict)
    candidates_total: int = 0
    selected: int = 0
    attempted: int = 0
    fetched: int = 0
    processed: int = 0
    refreshed_ok: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    not_found: int = 0
    redirects: int = 0
    removed: int = 0
    inactive: int = 0
    forbidden: int = 0
    timeouts: int = 0
    rate_limited: int = 0
    server_errors: int = 0
    parse_errors: int = 0
    validation_errors: int = 0
    unexpected_http: int = 0
    unexpected_errors: int = 0
    blocked_or_captcha: int = 0
    reactivated: int = 0
    price_changes_detected: int = 0
    price_changes_ignored_uf_rate_artifact: int = 0
    price_drops_detected: int = 0
    price_increases_detected: int = 0
    m2_changes_detected: int = 0
    bedrooms_changes_detected: int = 0
    bathrooms_changes_detected: int = 0
    address_changes_detected: int = 0
    geocode_precision_upgrades: int = 0
    geocode_precision_downgrades: int = 0
    geocode_precision_downgrades_blocked: int = 0
    price_history_points_created: int = 0
    uf_rate_used: str | None = None
    uf_rate_source: str | None = None
    listings_with_price_uf: int = 0
    listings_using_uf_fallback: int = 0
    alerts_created: int = 0
    alerts_skipped: int = 0
    by_comuna: dict[str, dict[str, int]] = field(default_factory=dict)
    by_property_type: dict[str, int] = field(default_factory=dict)
    by_geocode_precision: dict[str, int] = field(default_factory=dict)
    geocode_precision_before: dict[str, int] = field(default_factory=dict)
    geocode_precision_after: dict[str, int] = field(default_factory=dict)
    geocode_precision_transitions: dict[str, int] = field(default_factory=dict)
    reason_counts: dict[str, int] = field(default_factory=dict)
    examples: list[dict[str, Any]] = field(default_factory=list)

    @property
    def valid(self) -> int:
        return self.updated + self.unchanged

    @property
    def critical_invalid(self) -> int:
        return self.validation_errors


async def run_refresh_scraper(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    http_client: httpx.AsyncClient,
    limit: int = DEFAULT_REFRESH_LIMIT,
    stale_days: int = DEFAULT_REFRESH_STALE_DAYS,
    cooldown_hours: int = DEFAULT_REFRESH_COOLDOWN_HOURS,
    rate_limiter: RateLimiter | None = None,
    parser: RefreshParser | None = None,
    process_listing_fn: ProcessListingFn = process_listing,
    now: datetime | None = None,
    source: str | None = None,
    only_active: bool = False,
    include_inactive: bool = True,
    only_missing_coordinates: bool = False,
    comuna: str | None = None,
    property_type: str | None = None,
    order: str = "watchlist_first",
    max_errors: int | None = None,
    stop_on_block: bool = False,
    examples: int = 0,
    uf_to_clp: Decimal | None = None,
    uf_rate_source: str | None = None,
) -> RefreshStats:
    """Refresh old active listings by visiting their saved URLs directly."""
    started_at = now or datetime.now(UTC)
    stats = RefreshStats(source=source or "", started_at=started_at)
    if uf_to_clp is not None:
        stats.uf_rate_used = str(uf_to_clp)
    stats.uf_rate_source = uf_rate_source
    total_start = time.perf_counter()
    select_start = time.perf_counter()
    stats.candidates_total = await count_refresh_candidates(
        session_factory,
        stale_days=stale_days,
        cooldown_hours=cooldown_hours,
        now=now,
        source=source,
        only_active=only_active,
        include_inactive=include_inactive,
        only_missing_coordinates=only_missing_coordinates,
        comuna=comuna,
        property_type=property_type,
    )
    candidates = await select_refresh_candidates(
        session_factory,
        limit=limit,
        stale_days=stale_days,
        cooldown_hours=cooldown_hours,
        now=now,
        source=source,
        only_active=only_active,
        include_inactive=include_inactive,
        only_missing_coordinates=only_missing_coordinates,
        comuna=comuna,
        property_type=property_type,
        order=order,
    )
    stats.stage_durations_sec["select_candidates"] = round(time.perf_counter() - select_start, 3)
    stats.selected = len(candidates)
    _record_selected_dimensions(stats, candidates)
    limiter = rate_limiter or RateLimiter(SCRAPER_MIN_REQUEST_INTERVAL_SEC)
    refresh_parser = parser or (
        lambda listing, html: parse_refresh_listing_html(
            listing,
            html,
            uf_to_clp=uf_to_clp,
            uf_rate_source=uf_rate_source,
        )
    )

    refresh_start = time.perf_counter()
    for listing in candidates:
        await _refresh_one(
            listing,
            session_factory=session_factory,
            http_client=http_client,
            rate_limiter=limiter,
            parser=refresh_parser,
            process_listing_fn=process_listing_fn,
            stats=stats,
            now=now,
            example_limit=examples,
        )
        if _should_stop(stats, max_errors=max_errors, stop_on_block=stop_on_block):
            _log.warning("Refresh stopped early by guardrail stats=%s", stats)
            break
    stats.stage_durations_sec["refresh_urls"] = round(time.perf_counter() - refresh_start, 3)
    stats.finished_at = datetime.now(UTC)
    stats.duration_sec = round(time.perf_counter() - total_start, 3)
    return stats


async def count_refresh_candidates(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    stale_days: int = DEFAULT_REFRESH_STALE_DAYS,
    cooldown_hours: int = DEFAULT_REFRESH_COOLDOWN_HOURS,
    now: datetime | None = None,
    source: str | None = None,
    only_active: bool = False,
    include_inactive: bool = True,
    only_missing_coordinates: bool = False,
    comuna: str | None = None,
    property_type: str | None = None,
) -> int:
    reference_time = now or datetime.now(UTC)
    conditions = _refresh_candidate_conditions(
        reference_time=reference_time,
        stale_days=stale_days,
        cooldown_hours=cooldown_hours,
        source=source,
        only_active=only_active,
        include_inactive=include_inactive,
        only_missing_coordinates=only_missing_coordinates,
        comuna=comuna,
        property_type=property_type,
    )
    async with session_factory() as session:
        total = await session.scalar(select(func.count(ListingORM.id)).where(*conditions))
    return int(total or 0)


async def select_refresh_candidates(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = DEFAULT_REFRESH_LIMIT,
    stale_days: int = DEFAULT_REFRESH_STALE_DAYS,
    cooldown_hours: int = DEFAULT_REFRESH_COOLDOWN_HOURS,
    now: datetime | None = None,
    source: str | None = None,
    only_active: bool = False,
    include_inactive: bool = True,
    only_missing_coordinates: bool = False,
    comuna: str | None = None,
    property_type: str | None = None,
    order: str = "watchlist_first",
) -> list[Listing]:
    safe_limit = max(0, int(limit))
    if safe_limit == 0:
        return []

    reference_time = now or datetime.now(UTC)
    conditions = _refresh_candidate_conditions(
        reference_time=reference_time,
        stale_days=stale_days,
        cooldown_hours=cooldown_hours,
        source=source,
        only_active=only_active,
        include_inactive=include_inactive,
        only_missing_coordinates=only_missing_coordinates,
        comuna=comuna,
        property_type=property_type,
    )
    ordering = _refresh_ordering(order, reference_time=reference_time)

    async with session_factory() as session:
        stmt = (
            select(ListingORM)
            .where(*conditions)
            .order_by(*ordering)
            .limit(safe_limit)
        )
        result = await session.execute(stmt)
        return [listing_from_orm(row) for row in result.scalars().all()]


async def _refresh_one(
    listing: Listing,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    rate_limiter: RateLimiter,
    parser: RefreshParser,
    process_listing_fn: ProcessListingFn,
    stats: RefreshStats,
    now: datetime | None,
    example_limit: int = 0,
) -> None:
    if not listing.url:
        stats.skipped += 1
        _increment_reason(stats, "missing_url")
        return

    attempted_at = now or datetime.now(UTC)
    stats.attempted += 1
    await rate_limiter.wait()
    try:
        response = await http_client.get(listing.url, follow_redirects=False)
    except httpx.TimeoutException:
        stats.timeouts += 1
        await _record_refresh_state(
            session_factory,
            listing_id=listing.id,
            attempted_at=attempted_at,
            refresh_status="timeout",
        )
        _increment_reason(stats, "timeout")
        _log.warning("Refresh timeout listing_id=%s url=%s", listing.id, listing.url)
        return
    except httpx.HTTPError as exc:
        stats.unexpected_errors += 1
        await _record_refresh_state(
            session_factory,
            listing_id=listing.id,
            attempted_at=attempted_at,
            refresh_status="http_error",
        )
        _increment_reason(stats, "http_error")
        _log.warning("Refresh HTTP error listing_id=%s url=%s error=%s", listing.id, listing.url, exc)
        return

    if response.status_code == 404:
        stats.not_found += 1
        stats.removed += 1
        await _record_refresh_state(
            session_factory,
            listing_id=listing.id,
            attempted_at=attempted_at,
            refresh_status="removed_404",
            status="removed",
        )
        _increment_reason(stats, "removed_404")
        _log.info("Refresh 404 listing_id=%s url=%s", listing.id, listing.url)
        return
    if 300 <= response.status_code < 400:
        stats.redirects += 1
        location = response.headers.get("location")
        blocked_redirect = _is_blocked_redirect(location)
        removed_redirect = _is_removed_redirect(listing.url, location)
        if blocked_redirect:
            stats.blocked_or_captcha += 1
            await _record_refresh_state(
                session_factory,
                listing_id=listing.id,
                attempted_at=attempted_at,
                refresh_status="blocked_or_captcha",
            )
        elif removed_redirect:
            stats.removed += 1
            await _record_refresh_state(
                session_factory,
                listing_id=listing.id,
                attempted_at=attempted_at,
                refresh_status="removed_redirect",
                status="removed",
            )
        else:
            await _record_refresh_state(
                session_factory,
                listing_id=listing.id,
                attempted_at=attempted_at,
                refresh_status="redirect",
            )
        _log.info(
            "Refresh redirect listing_id=%s url=%s status=%s location=%s",
            listing.id,
            listing.url,
            response.status_code,
            location,
        )
        if blocked_redirect:
            _increment_reason(stats, "blocked_or_captcha")
        else:
            _increment_reason(stats, "removed_redirect" if removed_redirect else "redirect")
        return
    if response.status_code == 403:
        stats.forbidden += 1
        stats.blocked_or_captcha += 1
        await _record_refresh_state(
            session_factory,
            listing_id=listing.id,
            attempted_at=attempted_at,
            refresh_status="blocked_403",
        )
        _increment_reason(stats, "blocked_403")
        _log.warning("Refresh forbidden/blocked listing_id=%s url=%s", listing.id, listing.url)
        return
    if response.status_code == 429:
        stats.rate_limited += 1
        stats.blocked_or_captcha += 1
        await _record_refresh_state(
            session_factory,
            listing_id=listing.id,
            attempted_at=attempted_at,
            refresh_status="transient_429",
        )
        _increment_reason(stats, "transient_429")
        _log.warning("Refresh rate limited listing_id=%s url=%s", listing.id, listing.url)
        return
    if 500 <= response.status_code < 600:
        stats.server_errors += 1
        await _record_refresh_state(
            session_factory,
            listing_id=listing.id,
            attempted_at=attempted_at,
            refresh_status="transient_5xx",
        )
        _increment_reason(stats, "transient_5xx")
        _log.warning(
            "Refresh server error listing_id=%s url=%s status=%s",
            listing.id,
            listing.url,
            response.status_code,
        )
        return
    if response.status_code != 200:
        stats.unexpected_http += 1
        await _record_refresh_state(
            session_factory,
            listing_id=listing.id,
            attempted_at=attempted_at,
            refresh_status=f"http_{response.status_code}",
        )
        _increment_reason(stats, f"http_{response.status_code}")
        _log.warning(
            "Refresh unexpected status listing_id=%s url=%s status=%s",
            listing.id,
            listing.url,
            response.status_code,
        )
        return

    stats.fetched += 1
    if _looks_blocked_or_captcha(response.text):
        stats.blocked_or_captcha += 1
        await _record_refresh_state(
            session_factory,
            listing_id=listing.id,
            attempted_at=attempted_at,
            refresh_status="blocked_or_captcha",
        )
        _increment_reason(stats, "blocked_or_captcha")
        _log.warning("Refresh blocked/captcha HTML listing_id=%s url=%s", listing.id, listing.url)
        return
    if _looks_explicit_inactive(response.text):
        stats.inactive += 1
        await _record_refresh_state(
            session_factory,
            listing_id=listing.id,
            attempted_at=attempted_at,
            refresh_status="inactive_explicit",
            status="inactive",
        )
        _increment_reason(stats, "inactive_explicit")
        _log.warning("Refresh explicit inactive listing_id=%s url=%s", listing.id, listing.url)
        return
    raw = parser(listing, response.text)
    if raw is None:
        stats.parse_errors += 1
        if _looks_blocked_or_captcha(response.text):
            stats.blocked_or_captcha += 1
            refresh_status = "blocked_or_captcha"
            _increment_reason(stats, refresh_status)
        elif _looks_explicit_inactive(response.text):
            stats.inactive += 1
            refresh_status = "inactive_explicit"
            await _record_refresh_state(
                session_factory,
                listing_id=listing.id,
                attempted_at=attempted_at,
                refresh_status=refresh_status,
                status="inactive",
            )
            _increment_reason(stats, refresh_status)
            _log.warning("Refresh explicit inactive listing_id=%s url=%s", listing.id, listing.url)
            return
        else:
            refresh_status = "unexpected_html"
            _increment_reason(stats, refresh_status)
        await _record_refresh_state(
            session_factory,
            listing_id=listing.id,
            attempted_at=attempted_at,
            refresh_status=refresh_status,
        )
        _log.warning("Refresh unexpected HTML listing_id=%s url=%s", listing.id, listing.url)
        return
    raw = _merge_listing_identity(listing, raw)
    raw = _merge_refresh_raw_with_existing_listing(raw, listing)
    _record_uf_price_metrics(stats, raw)
    raw = _suppress_uf_rate_artifact(listing, raw, stats)

    async with session_factory() as session:
        repos = _build_repos(session)
        try:
            before = await _listing_snapshot(session, listing.id)
            history_before = await _price_history_count(session, listing.id)
            saved_listing = await process_listing_fn(raw, **repos)
            await session.flush()
            saved_listing_id = getattr(saved_listing, "id", listing.id)
            after = await _listing_snapshot(session, saved_listing_id)
            after = await _block_geocode_precision_downgrade(
                session,
                listing_id=saved_listing_id,
                before=before,
                after=after,
                stats=stats,
            )
            history_after = await _price_history_count(session, saved_listing_id)
            _record_success_diff(
                stats,
                before=before,
                after=after,
                history_before=history_before,
                history_after=history_after,
            )
            await _set_refresh_state(
                session,
                listing_id=listing.id,
                attempted_at=attempted_at,
                refresh_status="ok",
                status="active",
            )
            await session.commit()
        except (ValidationError, UnknownComunaError, ValueError) as exc:
            await session.rollback()
            stats.validation_errors += 1
            await _record_refresh_state(
                session_factory,
                listing_id=listing.id,
                attempted_at=attempted_at,
                refresh_status="pipeline_error",
            )
            _increment_reason(stats, "pipeline_error")
            _log.warning(
                "Refresh pipeline rejected listing_id=%s url=%s error=%s",
                listing.id,
                listing.url,
                exc,
            )
            return
        except Exception as exc:
            await session.rollback()
            stats.unexpected_errors += 1
            await _record_refresh_state(
                session_factory,
                listing_id=listing.id,
                attempted_at=attempted_at,
                refresh_status="unexpected_error",
            )
            _increment_reason(stats, "unexpected_error")
            _log.warning(
                "Refresh unexpected error listing_id=%s url=%s error=%s",
                listing.id,
                listing.url,
                exc,
            )
            return
    stats.processed += 1
    stats.refreshed_ok += 1
    _record_example(stats, listing, raw, example_limit=example_limit)


def parse_refresh_listing_html(
    listing: Listing,
    html: str,
    *,
    uf_to_clp: Decimal | None = None,
    uf_rate_source: str | None = None,
) -> ScraperResult | None:
    """Parse direct listing HTML using existing source parsers where possible."""
    if listing.source == "yapo":
        raw = parse_listing_detail(html, url=listing.url or "", uf_to_clp=uf_to_clp)
        if raw is not None and raw.get("price_uf") is not None:
            metadata = dict(raw.get("raw_metadata") or {})
            metadata["price_conversion_source"] = uf_rate_source or ("real" if uf_to_clp is not None else "missing")
            if uf_to_clp is not None:
                metadata["uf_rate_used"] = str(uf_to_clp)
            raw["raw_metadata"] = metadata
        return raw
    if listing.source == "portalinmobiliario":
        items = PortalInmobiliarioScraper.parse_listings(html)
        return items[0] if items else None
    _log.info("Refresh source unsupported listing_id=%s source=%s", listing.id, listing.source)
    return None


def _merge_listing_identity(listing: Listing, raw: ScraperResult) -> ScraperResult:
    merged: ScraperResult = dict(raw)
    merged["source"] = listing.source
    merged["external_id"] = listing.external_id or merged.get("external_id")
    merged["url"] = listing.url or merged.get("url")
    metadata = merged.get("raw_metadata")
    raw_metadata = dict(metadata) if isinstance(metadata, dict) else {}
    raw_metadata["refresh_listing_id"] = listing.id
    raw_metadata["refresh_source"] = "direct_url"
    merged["raw_metadata"] = raw_metadata
    return merged


def _merge_refresh_raw_with_existing_listing(raw: ScraperResult, listing: Listing) -> ScraperResult:
    merged: ScraperResult = dict(raw)
    metadata = dict(merged.get("raw_metadata") or {})
    fallbacks: list[str] = []

    raw_comuna = merged.get("comuna")
    if not _is_valid_refresh_comuna(raw_comuna):
        if _is_valid_refresh_comuna(listing.comuna):
            merged["comuna"] = listing.comuna
            fallbacks.append("comuna")
        else:
            merged.pop("comuna", None)
            fallbacks.append("comuna_removed")

    for field_name, max_value in (
        ("bedrooms", MAX_BEDROOMS),
        ("bathrooms", MAX_BATHROOMS),
        ("parking", 10),
    ):
        value = merged.get(field_name)
        if _int_in_range(value, min_value=0, max_value=max_value):
            continue
        existing_value = getattr(listing, field_name, None)
        if _int_in_range(existing_value, min_value=0, max_value=max_value):
            merged[field_name] = existing_value
            fallbacks.append(field_name)
        else:
            merged.pop(field_name, None)
            fallbacks.append(f"{field_name}_removed")

    if fallbacks:
        metadata["refresh_existing_field_fallbacks"] = fallbacks
        merged["raw_metadata"] = metadata
    return merged


def _is_valid_refresh_comuna(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    lowered = text.lower()
    if len(text) > 80 or len(text.split()) > 5 or "|" in text:
        return False
    title_markers = (
        "departamento",
        "casa",
        "venta",
        "dormitorio",
        "dormitorios",
        "subsidio",
        "proyecto",
    )
    if any(marker in lowered for marker in title_markers):
        return False
    return match_comuna_candidate(text) is not None


def _int_in_range(value: Any, *, min_value: int, max_value: int) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return False
    return min_value <= parsed <= max_value


def _record_uf_price_metrics(stats: RefreshStats, raw: ScraperResult) -> None:
    if raw.get("price_uf") is None:
        return
    stats.listings_with_price_uf += 1
    metadata = raw.get("raw_metadata")
    raw_metadata = metadata if isinstance(metadata, dict) else {}
    if raw_metadata.get("price_conversion_source") == "fallback":
        stats.listings_using_uf_fallback += 1


def _suppress_uf_rate_artifact(
    listing: Listing,
    raw: ScraperResult,
    stats: RefreshStats,
) -> ScraperResult:
    new_price_uf = _decimal_or_none(raw.get("price_uf"))
    old_price_uf = _decimal_or_none(getattr(listing, "price_uf", None))
    if old_price_uf is None:
        old_price_uf = _decimal_or_none((listing.raw_metadata or {}).get("price_uf"))
    if new_price_uf is None or old_price_uf is None:
        return raw
    if abs(new_price_uf - old_price_uf) > Decimal("0.01"):
        return raw

    old_price_clp = Decimal(listing.price.clp)
    new_price_clp = _decimal_or_none(raw.get("price_clp"))
    if new_price_clp is None or new_price_clp == old_price_clp:
        return raw

    suppressed: ScraperResult = dict(raw)
    metadata = dict(suppressed.get("raw_metadata") or {})
    metadata["price_change_ignored_reason"] = "uf_rate_artifact"
    metadata["price_uf_previous"] = float(old_price_uf)
    metadata["price_uf_current"] = float(new_price_uf)
    metadata["price_clp_candidate"] = int(new_price_clp)
    metadata["price_clp_preserved"] = int(old_price_clp)
    suppressed["raw_metadata"] = metadata
    suppressed["price_clp"] = int(old_price_clp)
    stats.price_changes_ignored_uf_rate_artifact += 1
    _increment_reason(stats, "uf_rate_artifact")
    return suppressed


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


async def _record_refresh_state(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    listing_id: int | None,
    attempted_at: datetime,
    refresh_status: str,
    status: str | None = None,
) -> None:
    async with session_factory() as session:
        await _set_refresh_state(
            session,
            listing_id=listing_id,
            attempted_at=attempted_at,
            refresh_status=refresh_status,
            status=status,
        )
        await session.commit()


async def _set_refresh_state(
    session: AsyncSession,
    *,
    listing_id: int | None,
    attempted_at: datetime,
    refresh_status: str,
    status: str | None = None,
) -> None:
    if listing_id is None:
        return
    row = await session.get(ListingORM, listing_id)
    if row is None:
        return
    row.last_refresh_attempted_at = attempted_at
    row.last_refresh_status = refresh_status
    if status is not None:
        row.status = status
    await session.flush()


def _is_removed_redirect(original_url: str | None, location: str | None) -> bool:
    if not location:
        return False
    absolute = urljoin(original_url or "", location)
    parsed = urlsplit(absolute)
    path = parsed.path.strip("/").lower()
    if path in {"", "home"}:
        return True
    listing_category_paths = (
        "bienes-raices-venta-de-propiedades",
        "bienes-raices-arriendo",
    )
    if any(path.startswith(category) for category in listing_category_paths):
        return True
    return any(token in path for token in ("searchresult", "search", "listado"))


def _is_blocked_redirect(location: str | None) -> bool:
    if not location:
        return False
    parsed = urlsplit(location)
    text = f"{parsed.netloc} {parsed.path} {parsed.query}".lower()
    markers = (
        "captcha",
        "recaptcha",
        "hcaptcha",
        "login",
        "signin",
        "sign-in",
        "account",
        "auth",
        "verify",
        "verifica",
        "blocked",
    )
    return any(marker in text for marker in markers)


def _refresh_candidate_conditions(
    *,
    reference_time: datetime,
    stale_days: int,
    cooldown_hours: int,
    source: str | None,
    only_active: bool,
    include_inactive: bool,
    only_missing_coordinates: bool,
    comuna: str | None,
    property_type: str | None,
) -> list[Any]:
    stale_cutoff = reference_time - timedelta(days=stale_days)
    cooldown_cutoff = reference_time - timedelta(hours=max(0, int(cooldown_hours)))
    conditions: list[Any] = [
        ListingORM.url.is_not(None),
        or_(
            ListingORM.last_refresh_attempted_at.is_(None),
            ListingORM.last_refresh_attempted_at < cooldown_cutoff,
        ),
    ]
    if source:
        conditions.append(ListingORM.source == source)
    if only_active:
        conditions.append(ListingORM.status == "active")
    elif include_inactive:
        conditions.append(
            or_(
                ListingORM.status == "active",
                and_(
                    ListingORM.status == "inactive",
                    or_(
                        ListingORM.last_seen_at.is_(None),
                        ListingORM.last_seen_at < stale_cutoff,
                    ),
                ),
            )
        )
    else:
        conditions.append(ListingORM.status == "active")
    if only_missing_coordinates:
        conditions.append(or_(ListingORM.lat.is_(None), ListingORM.lon.is_(None)))
    if comuna:
        conditions.append(func.lower(ListingORM.comuna) == comuna.strip().lower())
    if property_type:
        conditions.append(ListingORM.property_type == property_type)
    return conditions


def _refresh_ordering(order: str, *, reference_time: datetime) -> list[Any]:
    never_refreshed_rank = case((ListingORM.last_refresh_attempted_at.is_(None), 0), else_=1)
    if order == "oldest_seen":
        return [ListingORM.last_seen_at.asc().nullsfirst(), ListingORM.id.asc()]
    if order == "oldest_refresh":
        return [never_refreshed_rank.asc(), ListingORM.last_refresh_attempted_at.asc(), ListingORM.id.asc()]
    if order == "random":
        return [func.random()]

    recent_cutoff = reference_time - timedelta(days=REFRESH_RECENT_DAYS)
    last_review_cutoff = reference_time - timedelta(days=REFRESH_LAST_REVIEW_DAYS)
    active_watchlist_exists = exists().where(
        SavedListingORM.listing_id == ListingORM.id,
        SavedListingORM.status == "active",
    )
    priority_rank = case(
        (active_watchlist_exists, 0),
        (and_(ListingORM.status == "active", ListingORM.last_seen_at >= recent_cutoff), 1),
        (
            and_(
                ListingORM.status == "active",
                ListingORM.last_seen_at >= last_review_cutoff,
                ListingORM.last_seen_at < recent_cutoff,
            ),
            2,
        ),
        else_=3,
    )
    return [
        priority_rank.asc(),
        never_refreshed_rank.asc(),
        ListingORM.last_refresh_attempted_at.asc(),
        ListingORM.last_seen_at.desc(),
        ListingORM.id.asc(),
    ]


async def _listing_snapshot(session: AsyncSession, listing_id: int | None) -> dict[str, Any] | None:
    if listing_id is None:
        return None
    row = await session.get(ListingORM, listing_id)
    if row is None:
        return None
    raw_metadata = dict(row.raw_metadata or {})
    price_uf = row.price_uf or _decimal_or_none(raw_metadata.get("price_uf"))
    price_currency = row.price_currency or ("UF" if price_uf is not None else None)
    return {
        "id": row.id,
        "status": row.status,
        "price_clp": row.price_clp,
        "price_uf": price_uf,
        "price_currency": price_currency,
        "m2": row.m2,
        "bedrooms": row.bedrooms,
        "bathrooms": row.bathrooms,
        "address": _address_value(raw_metadata),
        "geocode_precision": row.geocode_precision or "unknown",
    }


async def _price_history_count(session: AsyncSession, listing_id: int | None) -> int:
    if listing_id is None:
        return 0
    total = await session.scalar(
        select(func.count(PriceHistoryORM.id)).where(PriceHistoryORM.listing_id == listing_id)
    )
    return int(total or 0)


async def _block_geocode_precision_downgrade(
    session: AsyncSession,
    *,
    listing_id: int | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    stats: RefreshStats,
) -> dict[str, Any] | None:
    if listing_id is None or before is None or after is None:
        return after
    before_precision = str(before["geocode_precision"] or "unknown")
    after_precision = str(after["geocode_precision"] or "unknown")
    if _refresh_geocode_precision_rank(after_precision) >= _refresh_geocode_precision_rank(before_precision):
        return after

    row = await session.get(ListingORM, listing_id)
    if row is None:
        return after
    metadata = dict(row.raw_metadata or {})
    metadata["refresh_geocode_precision_downgrade_blocked"] = True
    metadata["refresh_geocode_precision_before"] = before_precision
    metadata["refresh_geocode_precision_candidate"] = after_precision
    row.geocode_precision = before_precision
    row.raw_metadata = metadata
    await session.flush()
    stats.geocode_precision_downgrades_blocked += 1
    _increment_reason(stats, "geocode_precision_downgrade_blocked")
    return await _listing_snapshot(session, listing_id)


def _record_success_diff(
    stats: RefreshStats,
    *,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    history_before: int,
    history_after: int,
) -> None:
    if before is None or after is None:
        stats.updated += 1
        return

    changed = False
    price_change = _canonical_price_change(before, after)
    if price_change is not None:
        changed = True
        stats.price_changes_detected += 1
        if price_change < 0:
            stats.price_drops_detected += 1
        elif price_change > 0:
            stats.price_increases_detected += 1

    for field_name, counter_name in (
        ("m2", "m2_changes_detected"),
        ("bedrooms", "bedrooms_changes_detected"),
        ("bathrooms", "bathrooms_changes_detected"),
        ("address", "address_changes_detected"),
    ):
        if before[field_name] != after[field_name]:
            changed = True
            setattr(stats, counter_name, getattr(stats, counter_name) + 1)

    before_precision = str(before["geocode_precision"] or "unknown")
    after_precision = str(after["geocode_precision"] or "unknown")
    _increment(stats.geocode_precision_before, before_precision)
    _increment(stats.geocode_precision_after, after_precision)
    if before_precision != after_precision:
        changed = True
        _increment(stats.geocode_precision_transitions, f"{before_precision}->{after_precision}")
        if geocode_precision_rank(after_precision) > geocode_precision_rank(before_precision):
            stats.geocode_precision_upgrades += 1
        elif geocode_precision_rank(after_precision) < geocode_precision_rank(before_precision):
            stats.geocode_precision_downgrades += 1

    if before["status"] != "active" and after["status"] == "active":
        stats.reactivated += 1
    stats.price_history_points_created += max(0, history_after - history_before)
    if changed:
        stats.updated += 1
    else:
        stats.unchanged += 1


def _canonical_price_change(before: dict[str, Any], after: dict[str, Any]) -> Decimal | None:
    before_currency = _canonical_price_currency(before.get("price_currency"))
    after_currency = _canonical_price_currency(after.get("price_currency"))
    if before_currency == "UF" or after_currency == "UF":
        before_uf = _decimal_or_none(before.get("price_uf"))
        after_uf = _decimal_or_none(after.get("price_uf"))
        if before_uf is None or after_uf is None:
            return None
        delta = after_uf - before_uf
        return delta if abs(delta) > Decimal("0.01") else None

    before_clp = _decimal_or_none(before.get("price_clp"))
    after_clp = _decimal_or_none(after.get("price_clp"))
    if before_clp is None or after_clp is None:
        return None
    delta = after_clp - before_clp
    return delta if delta != 0 else None


def _canonical_price_currency(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if text in {"UF", "CLF"}:
        return "UF"
    if text in {"CLP", "$", "PESO", "PESOS"}:
        return "CLP"
    return text or None


def _record_selected_dimensions(stats: RefreshStats, candidates: list[Listing]) -> None:
    for listing in candidates:
        comuna = str(listing.comuna or "unknown")
        values = stats.by_comuna.setdefault(comuna, {"selected": 0})
        values["selected"] = values.get("selected", 0) + 1
        _increment(stats.by_property_type, str(listing.property_type or "unknown"))
        _increment(stats.by_geocode_precision, str(listing.geocode_precision or "unknown"))


def _record_example(
    stats: RefreshStats,
    listing: Listing,
    raw: ScraperResult,
    *,
    example_limit: int,
) -> None:
    if example_limit <= 0 or len(stats.examples) >= example_limit:
        return
    stats.examples.append(
        {
            "listing_id": listing.id,
            "external_id": listing.external_id,
            "url": listing.url,
            "title": raw.get("title"),
            "price_clp": raw.get("price_clp"),
            "comuna": raw.get("comuna"),
            "property_type": raw.get("property_type"),
        }
    )


def _should_stop(stats: RefreshStats, *, max_errors: int | None, stop_on_block: bool) -> bool:
    if stop_on_block and (stats.forbidden or stats.rate_limited or stats.blocked_or_captcha):
        return True
    if max_errors is None:
        return False
    errors = (
        stats.forbidden
        + stats.rate_limited
        + stats.server_errors
        + stats.timeouts
        + stats.validation_errors
        + stats.unexpected_http
        + stats.unexpected_errors
        + stats.blocked_or_captcha
    )
    return errors >= max(0, int(max_errors))


def _looks_blocked_or_captcha(html: str) -> bool:
    text = html.lower()
    markers = (
        "captcha",
        "cloudflare",
        "access denied",
        "acceso denegado",
        "verify you are human",
        "verifica que eres humano",
        "unusual traffic",
        "robot",
        "bot detection",
    )
    return any(marker in text for marker in markers)


def _looks_explicit_inactive(html: str) -> bool:
    text = " ".join(html.lower().split())
    markers = (
        "publicacion no disponible",
        "publicación no disponible",
        "publicacion eliminada",
        "publicacion fue eliminada",
        "esta publicacion fue eliminada",
        "publicación eliminada",
        "publicacion finalizada",
        "publicación finalizada",
        "aviso finalizado",
        "aviso eliminado",
        "ya no esta disponible",
        "ya no está disponible",
        "vendida",
        "vendido",
    )
    return any(marker in text for marker in markers)


def _address_value(raw_metadata: dict[str, Any]) -> str:
    for key in ("address", "address_label", "street_hint", "location_text"):
        value = str(raw_metadata.get(key) or "").strip()
        if value:
            return value
    return ""


def _refresh_geocode_precision_rank(value: Any) -> int:
    # Refresh safety order requested for manual revisits:
    # address > street > comuna > comuna_centroid > unknown.
    ranks = {
        "unknown": 0,
        "comuna_centroid": 1,
        "comuna": 2,
        "street": 3,
        "address": 4,
        "exact": 4,
        "street_address": 4,
        "street_name": 3,
        "landmark_or_sector": 3,
        "intersection": 3,
    }
    return ranks.get(str(value or "unknown").strip().lower(), 0)


def _increment(target: dict[str, int], key: str) -> None:
    target[key] = target.get(key, 0) + 1


def _increment_reason(stats: RefreshStats, reason: str) -> None:
    _increment(stats.reason_counts, reason)


def _build_repos(session: AsyncSession) -> dict[str, Any]:
    return {
        "listing_repo": SqlAlchemyListingRepository(session),
        "property_repo": SqlAlchemyPropertyRepository(session),
        "price_history_repo": SqlAlchemyPriceHistoryRepository(session),
    }
