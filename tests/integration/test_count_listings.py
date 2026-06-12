from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from infrastructure.db.models import ListingORM
from scripts.count_listings import collect_counts, print_counts


@pytest_asyncio.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def test_collect_counts_reports_totals_sources_and_last_capture(session_factory):
    scraped_at = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        session.add_all(
            [
                ListingORM(
                    source="yapo",
                    external_id="a",
                    title="Depto A",
                    comuna="nunoa",
                    m2=70,
                    bedrooms=2,
                    bathrooms=2,
                    parking=1,
                    price_clp=Decimal("180000000"),
                    status="active",
                    fingerprint="fp-a",
                    raw_metadata={},
                    scraped_at=scraped_at,
                    last_seen_at=scraped_at,
                ),
                ListingORM(
                    source="portalinmobiliario",
                    external_id="b",
                    title="Depto B",
                    comuna="las-condes",
                    m2=90,
                    bedrooms=3,
                    bathrooms=2,
                    parking=1,
                    price_clp=Decimal("240000000"),
                    status="removed",
                    fingerprint="fp-b",
                    raw_metadata={},
                    scraped_at=scraped_at,
                    last_seen_at=scraped_at,
                ),
            ]
        )
        await session.commit()

    counts = await collect_counts(session_factory)

    assert counts.total == 2
    assert counts.active == 1
    assert counts.by_source == {"portalinmobiliario": 1, "yapo": 1}
    assert counts.last_scraped_at == scraped_at.replace(tzinfo=None)


def test_print_counts_is_explicit_on_empty_db(capsys):
    from scripts.count_listings import ListingCounts

    print_counts(ListingCounts(total=0, active=0, by_source={}, last_scraped_at=None))
    out = capsys.readouterr().out

    assert "total listings: 0" in out
    assert "sin listings" in out
    assert "ultima fecha de captura: sin capturas" in out
