"""Freshness gate for Radar beta candidates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from core.entities.listing import Listing

FreshnessCause = Literal[
    "fresh_seen",
    "fresh_refresh_ok",
    "stale",
    "missing_url",
    "removed_or_unavailable",
    "refresh_failed",
    "missing_freshness",
]

REMOVED_OR_UNAVAILABLE_REFRESH_STATUSES = frozenset(
    {
        "removed_404",
        "removed_redirect",
        "inactive_explicit",
        "not_found",
        "unavailable",
        "removed",
        "inactive",
    }
)

FAILED_REFRESH_STATUSES = frozenset(
    {
        "blocked_403",
        "blocked_or_captcha",
        "transient_429",
        "timeout",
        "http_error",
        "transient_5xx",
        "unexpected_html",
        "pipeline_error",
        "unexpected_error",
        "redirect",
    }
)


@dataclass(frozen=True)
class RadarFreshnessConfig:
    require_fresh_listings: bool = True
    max_listing_staleness_days: int = 7
    exclude_refresh_failed: bool = True
    exclude_removed_or_unavailable: bool = True


@dataclass(frozen=True)
class FreshnessDecision:
    allowed: bool
    cause: FreshnessCause
    note: str | None = None


def is_fresh_for_radar(
    listing: Listing,
    *,
    now: datetime,
    config: RadarFreshnessConfig,
) -> FreshnessDecision:
    """Return whether a listing is safe enough for Radar beta scoring."""
    refresh_status = _normalized_refresh_status(listing.last_refresh_status)

    if listing.status != "active":
        return FreshnessDecision(False, "removed_or_unavailable", f"status={listing.status}")
    if (
        config.exclude_removed_or_unavailable
        and refresh_status in REMOVED_OR_UNAVAILABLE_REFRESH_STATUSES
    ):
        return FreshnessDecision(False, "removed_or_unavailable", f"refresh_status={refresh_status}")
    if not listing.url:
        if not config.require_fresh_listings:
            return FreshnessDecision(True, "fresh_seen", "legacy_freshness_disabled")
        return FreshnessDecision(False, "missing_url")
    if not config.require_fresh_listings:
        return FreshnessDecision(True, "fresh_seen", "legacy_freshness_disabled")
    if config.exclude_refresh_failed and refresh_status in FAILED_REFRESH_STATUSES:
        return FreshnessDecision(False, "refresh_failed", f"refresh_status={refresh_status}")

    cutoff = _as_aware_utc(now) - timedelta(days=max(config.max_listing_staleness_days, 0))
    if listing.last_seen_at is not None and _as_aware_utc(listing.last_seen_at) >= cutoff:
        return FreshnessDecision(True, "fresh_seen")
    if (
        listing.last_refresh_attempted_at is not None
        and _as_aware_utc(listing.last_refresh_attempted_at) >= cutoff
        and refresh_status == "ok"
    ):
        return FreshnessDecision(True, "fresh_refresh_ok")
    if listing.last_seen_at is None and listing.last_refresh_attempted_at is None:
        return FreshnessDecision(False, "missing_freshness")
    return FreshnessDecision(False, "stale")


def _normalized_refresh_status(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
