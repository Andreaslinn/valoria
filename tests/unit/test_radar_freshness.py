from __future__ import annotations

from datetime import UTC, datetime, timedelta

from domain.radar.freshness import (
    RadarFreshnessConfig,
    is_fresh_for_radar,
)
from tests.unit.factories import make_listing

NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)
CONFIG = RadarFreshnessConfig(
    require_fresh_listings=True,
    max_listing_staleness_days=7,
    exclude_refresh_failed=True,
    exclude_removed_or_unavailable=True,
)


def test_active_with_recent_last_seen_is_allowed() -> None:
    listing = _listing(last_seen_at=NOW - timedelta(days=2))

    decision = is_fresh_for_radar(listing, now=NOW, config=CONFIG)

    assert decision.allowed is True
    assert decision.cause == "fresh_seen"


def test_active_with_recent_refresh_ok_is_allowed() -> None:
    listing = _listing(
        last_seen_at=NOW - timedelta(days=30),
        last_refresh_attempted_at=NOW - timedelta(days=1),
        last_refresh_status="ok",
    )

    decision = is_fresh_for_radar(listing, now=NOW, config=CONFIG)

    assert decision.allowed is True
    assert decision.cause == "fresh_refresh_ok"


def test_active_old_last_seen_without_refresh_is_stale() -> None:
    listing = _listing(last_seen_at=NOW - timedelta(days=21))

    decision = is_fresh_for_radar(listing, now=NOW, config=CONFIG)

    assert decision.allowed is False
    assert decision.cause == "stale"


def test_removed_404_is_excluded_as_removed_or_unavailable() -> None:
    listing = _listing(last_seen_at=NOW, last_refresh_status="removed_404")

    decision = is_fresh_for_radar(listing, now=NOW, config=CONFIG)

    assert decision.allowed is False
    assert decision.cause == "removed_or_unavailable"


def test_inactive_explicit_is_excluded_as_removed_or_unavailable() -> None:
    listing = _listing(last_seen_at=NOW, last_refresh_status="inactive_explicit")

    decision = is_fresh_for_radar(listing, now=NOW, config=CONFIG)

    assert decision.allowed is False
    assert decision.cause == "removed_or_unavailable"


def test_old_timeout_is_excluded_as_refresh_failed() -> None:
    listing = _listing(
        last_seen_at=NOW - timedelta(days=30),
        last_refresh_attempted_at=NOW - timedelta(days=20),
        last_refresh_status="timeout",
    )

    decision = is_fresh_for_radar(listing, now=NOW, config=CONFIG)

    assert decision.allowed is False
    assert decision.cause == "refresh_failed"


def test_recent_redirect_is_excluded_as_refresh_failed() -> None:
    listing = _listing(
        last_seen_at=NOW - timedelta(days=1),
        last_refresh_attempted_at=NOW - timedelta(hours=1),
        last_refresh_status="redirect",
    )

    decision = is_fresh_for_radar(listing, now=NOW, config=CONFIG)

    assert decision.allowed is False
    assert decision.cause == "refresh_failed"


def test_old_blocked_or_captcha_is_excluded_as_refresh_failed() -> None:
    listing = _listing(
        last_seen_at=NOW - timedelta(days=30),
        last_refresh_attempted_at=NOW - timedelta(days=20),
        last_refresh_status="blocked_or_captcha",
    )

    decision = is_fresh_for_radar(listing, now=NOW, config=CONFIG)

    assert decision.allowed is False
    assert decision.cause == "refresh_failed"


def test_missing_url_is_excluded() -> None:
    listing = _listing(last_seen_at=NOW)
    listing.url = None

    decision = is_fresh_for_radar(listing, now=NOW, config=CONFIG)

    assert decision.allowed is False
    assert decision.cause == "missing_url"


def test_removed_status_is_excluded() -> None:
    listing = _listing(status="removed", last_seen_at=NOW)

    decision = is_fresh_for_radar(listing, now=NOW, config=CONFIG)

    assert decision.allowed is False
    assert decision.cause == "removed_or_unavailable"


def test_freshness_disabled_preserves_legacy_active_listing_without_url() -> None:
    listing = _listing(last_seen_at=NOW - timedelta(days=90))
    listing.url = None
    config = RadarFreshnessConfig(require_fresh_listings=False)

    decision = is_fresh_for_radar(listing, now=NOW, config=config)

    assert decision.allowed is True
    assert decision.cause == "fresh_seen"


def test_freshness_disabled_still_excludes_removed_signal() -> None:
    listing = _listing(
        last_seen_at=NOW - timedelta(days=90),
        last_refresh_status="removed_redirect",
    )
    config = RadarFreshnessConfig(require_fresh_listings=False)

    decision = is_fresh_for_radar(listing, now=NOW, config=config)

    assert decision.allowed is False
    assert decision.cause == "removed_or_unavailable"


def _listing(**overrides):
    listing = make_listing()
    listing.url = overrides.pop("url", "https://example.test/listing")
    for name, value in overrides.items():
        setattr(listing, name, value)
    return listing
