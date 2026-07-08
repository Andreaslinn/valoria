from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from infrastructure.db.models import ListingORM
from services.listing_freshness import ensure_listing_fresh
from workers.refresh_scraper import RefreshStats

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.mark.asyncio
async def test_ensure_listing_fresh_skips_recent_ok(session_factory, monkeypatch):
    listing = await _insert_listing(
        session_factory,
        last_refresh_status="ok",
        last_refresh_attempted_at=NOW - timedelta(hours=2),
    )

    async def fail_refresh(*args, **kwargs):
        raise AssertionError("refresh should not run inside cooldown")

    monkeypatch.setattr("services.listing_freshness.refresh_listing_once", fail_refresh)

    result = await ensure_listing_fresh(
        listing.id,
        reason="test",
        session_factory=session_factory,
        settings=_settings(cooldown_hours=24),
        now=NOW,
    )

    assert result.status == "already_fresh"
    assert result.refresh_attempted is False


@pytest.mark.asyncio
async def test_ensure_listing_fresh_runs_single_refresh_for_stale_listing(session_factory, monkeypatch):
    listing = await _insert_listing(session_factory, last_refresh_attempted_at=NOW - timedelta(days=3))

    async def fake_refresh(session_factory_arg, *, listing_id, **kwargs):
        async with session_factory_arg() as session:
            stored = await session.get(ListingORM, listing_id)
            stored.last_refresh_status = "ok"
            stored.last_refresh_attempted_at = NOW
            stored.last_seen_at = NOW
            await session.commit()
        stats = RefreshStats(started_at=NOW)
        stats.refreshed_ok = 1
        return stats

    monkeypatch.setattr("services.listing_freshness.refresh_listing_once", fake_refresh)

    result = await ensure_listing_fresh(
        listing.id,
        reason="test",
        session_factory=session_factory,
        settings=_settings(cooldown_hours=24),
        now=NOW,
    )

    assert result.status == "fresh_confirmed"
    assert result.refresh_attempted is True
    assert result.last_refresh_status == "ok"


@pytest.mark.asyncio
async def test_ensure_listing_fresh_skips_removed_listing(session_factory, monkeypatch):
    listing = await _insert_listing(session_factory, status="removed", last_refresh_status="removed_redirect")

    async def fail_refresh(*args, **kwargs):
        raise AssertionError("removed listings should not refresh")

    monkeypatch.setattr("services.listing_freshness.refresh_listing_once", fail_refresh)

    result = await ensure_listing_fresh(
        listing.id,
        reason="test",
        session_factory=session_factory,
        settings=_settings(),
        now=NOW,
    )

    assert result.status == "skipped_removed"
    assert result.refresh_attempted is False


@pytest.mark.asyncio
async def test_ensure_listing_fresh_skips_recent_block(session_factory, monkeypatch):
    listing = await _insert_listing(
        session_factory,
        last_refresh_status="blocked_403",
        last_refresh_attempted_at=NOW - timedelta(hours=1),
    )

    async def fail_refresh(*args, **kwargs):
        raise AssertionError("blocked listings should respect skip window")

    monkeypatch.setattr("services.listing_freshness.refresh_listing_once", fail_refresh)

    result = await ensure_listing_fresh(
        listing.id,
        reason="test",
        session_factory=session_factory,
        settings=_settings(skip_blocked_hours=24),
        now=NOW,
    )

    assert result.status == "skipped_recent_block"
    assert result.refresh_attempted is False


@pytest.mark.asyncio
async def test_ensure_listing_fresh_rejects_unsupported_url(session_factory, monkeypatch):
    listing = await _insert_listing(session_factory, url="https://example.test/listing/1")

    async def fail_refresh(*args, **kwargs):
        raise AssertionError("unsupported URLs should not refresh")

    monkeypatch.setattr("services.listing_freshness.refresh_listing_once", fail_refresh)

    result = await ensure_listing_fresh(
        listing.id,
        reason="test",
        session_factory=session_factory,
        settings=_settings(),
        now=NOW,
    )

    assert result.status == "url_missing_or_invalid"
    assert result.freshness_note == "unsupported_refresh_url"


async def _insert_listing(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    url: str = "https://www.yapo.cl/region-metropolitana/departamentos/departamento-test",
    source: str = "yapo",
    status: str = "active",
    last_refresh_status: str | None = None,
    last_refresh_attempted_at: datetime | None = None,
) -> ListingORM:
    listing = ListingORM(
        source=source,
        external_id=f"fresh-{last_refresh_status or 'new'}-{last_refresh_attempted_at or 'none'}",
        title="Departamento test",
        url=url,
        comuna="nunoa",
        property_type="apartment",
        m2=75,
        bedrooms=2,
        bathrooms=2,
        parking=1,
        price_clp=Decimal("180000000"),
        status=status,
        fingerprint=f"fresh-{url}-{status}-{last_refresh_status}-{last_refresh_attempted_at}",
        raw_metadata={},
        scraped_at=NOW - timedelta(days=10),
        last_seen_at=NOW - timedelta(days=10),
        last_refresh_status=last_refresh_status,
        last_refresh_attempted_at=last_refresh_attempted_at,
    )
    async with session_factory() as session:
        session.add(listing)
        await session.commit()
        await session.refresh(listing)
    return listing


def _settings(*, cooldown_hours: int = 24, skip_blocked_hours: int = 24):
    return SimpleNamespace(
        listing_on_demand_refresh_enabled=True,
        listing_on_demand_refresh_cooldown_hours=cooldown_hours,
        listing_on_demand_refresh_skip_blocked_hours=skip_blocked_hours,
        listing_on_demand_refresh_timeout_sec=1.0,
    )
