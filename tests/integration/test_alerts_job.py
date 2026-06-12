from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from infrastructure.db.models import AlertORM, ListingORM, PriceHistoryORM
from workers.alerts_job import run_alerts_job

NOW = datetime.now(UTC)


@pytest_asyncio.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def test_alerts_job_runs_without_scraper(session_factory) -> None:
    stats = await run_alerts_job(session_factory)

    assert stats.listings_evaluated == 0
    assert stats.detected == 0
    assert stats.created == 0
    assert stats.skipped == 0


async def test_alerts_job_creates_alert_for_valid_price_drop(session_factory) -> None:
    async with session_factory() as session:
        listing = _listing("drop", price_clp=90_000_000)
        session.add(listing)
        await session.flush()
        session.add(_price(listing.id, 100_000_000, NOW - timedelta(days=1)))
        await session.commit()
        original_status = listing.status
        original_price = listing.price_clp

    stats = await run_alerts_job(session_factory)

    async with session_factory() as session:
        alerts = (await session.execute(select(AlertORM))).scalars().all()
        stored = (await session.execute(select(ListingORM))).scalar_one()

    assert stats.listings_evaluated == 1
    assert stats.detected == 1
    assert stats.created == 1
    assert stats.skipped == 0
    assert len(alerts) == 1
    assert alerts[0].alert_type == "price_drop"
    assert alerts[0].payload["previous_price_clp"] == 100_000_000
    assert alerts[0].payload["new_price_clp"] == 90_000_000
    assert alerts[0].payload["previous_price_clp_snapshot"] == 100_000_000
    assert alerts[0].payload["new_price_clp_snapshot"] == 90_000_000
    assert alerts[0].payload["price_currency"] == "CLP"
    assert alerts[0].payload["canonical_previous_price"] == 100_000_000
    assert alerts[0].payload["canonical_new_price"] == 90_000_000
    assert alerts[0].payload["canonical_price_unit"] == "CLP"
    assert alerts[0].payload["artifact_filtered"] is False
    assert stored.status == original_status
    assert stored.price_clp == original_price


async def test_alerts_job_creates_alert_for_real_uf_drop(session_factory) -> None:
    async with session_factory() as session:
        listing = _listing("uf-drop", price_clp=118_400_000, price_currency="UF", price_uf=3200)
        session.add(listing)
        await session.flush()
        session.add(
            _price(
                listing.id,
                120_250_000,
                NOW - timedelta(days=1),
                price_currency="UF",
                price_uf=3250,
                change_basis="uf",
            )
        )
        await session.commit()

    stats = await run_alerts_job(session_factory, threshold_pct=1.0)

    async with session_factory() as session:
        alert = (await session.execute(select(AlertORM))).scalar_one()

    assert stats.detected == 1
    assert stats.created == 1
    assert alert.payload["previous_price_uf"] == 3250
    assert alert.payload["new_price_uf"] == 3200
    assert alert.payload["price_currency"] == "UF"
    assert alert.payload["change_basis"] == "uf"
    assert alert.payload["canonical_previous_price"] == 3250
    assert alert.payload["canonical_new_price"] == 3200
    assert alert.payload["canonical_price_unit"] == "UF"
    assert alert.payload["display_previous_price_clp"] == 120_250_000
    assert alert.payload["display_new_price_clp"] == 118_400_000


async def test_alerts_job_ignores_uf_rate_only_change(session_factory) -> None:
    async with session_factory() as session:
        listing = _listing("uf-rate-only", price_clp=120_250_000, price_currency="UF", price_uf=3250)
        session.add(listing)
        await session.flush()
        session.add(
            _price(
                listing.id,
                132_259_985,
                NOW - timedelta(days=1),
                price_currency="UF",
                price_uf=3250,
                change_basis="uf",
            )
        )
        await session.commit()

    stats = await run_alerts_job(session_factory, threshold_pct=1.0)

    async with session_factory() as session:
        alerts = (await session.execute(select(AlertORM))).scalars().all()

    assert stats.detected == 0
    assert stats.created == 0
    assert alerts == []


async def test_alerts_job_ignores_artifact_price_history(session_factory) -> None:
    async with session_factory() as session:
        listing = _listing("artifact", price_clp=120_250_000, price_currency="UF", price_uf=3250)
        session.add(listing)
        await session.flush()
        session.add(
            _price(
                listing.id,
                132_259_985,
                NOW - timedelta(days=1),
                price_currency="UF",
                price_uf=3250,
                change_basis="uf_rate_artifact",
                is_artifact=True,
            )
        )
        await session.commit()

    stats = await run_alerts_job(session_factory, threshold_pct=1.0)

    async with session_factory() as session:
        alerts = (await session.execute(select(AlertORM))).scalars().all()

    assert stats.detected == 0
    assert stats.created == 0
    assert alerts == []


async def test_alerts_job_ignores_legacy_unrecoverable_uf_without_price_uf(session_factory) -> None:
    async with session_factory() as session:
        listing = _listing(
            "legacy-unrecoverable",
            price_clp=120_250_000,
            price_currency="UF",
            price_uf_source="legacy_unrecoverable",
        )
        session.add(listing)
        await session.flush()
        session.add(
            _price(
                listing.id,
                132_259_985,
                NOW - timedelta(days=1),
                price_currency="UF",
                change_basis="legacy_uf_unknown",
            )
        )
        await session.commit()

    stats = await run_alerts_job(session_factory, threshold_pct=1.0)

    async with session_factory() as session:
        alerts = (await session.execute(select(AlertORM))).scalars().all()

    assert stats.detected == 0
    assert stats.created == 0
    assert alerts == []


async def test_alerts_job_ignores_estimated_uf_as_strong_signal(session_factory) -> None:
    async with session_factory() as session:
        listing = _listing(
            "estimated-uf",
            price_clp=118_400_000,
            price_currency="UF",
            price_uf=3200,
            price_uf_source="estimated",
        )
        session.add(listing)
        await session.flush()
        session.add(
            _price(
                listing.id,
                120_250_000,
                NOW - timedelta(days=1),
                price_currency="UF",
                price_uf=3250,
                change_basis="uf",
            )
        )
        await session.commit()

    stats = await run_alerts_job(session_factory, threshold_pct=1.0)

    async with session_factory() as session:
        alerts = (await session.execute(select(AlertORM))).scalars().all()

    assert stats.detected == 0
    assert stats.created == 0
    assert alerts == []


async def test_alerts_job_does_not_duplicate_existing_alert(session_factory) -> None:
    async with session_factory() as session:
        listing = _listing("dedupe", price_clp=90_000_000)
        session.add(listing)
        await session.flush()
        session.add_all(
            [
                _price(listing.id, 100_000_000, NOW - timedelta(days=1)),
                AlertORM(
                    listing_id=listing.id,
                    alert_type="price_drop",
                    payload=_price_drop_payload(100_000_000, 90_000_000),
                ),
            ]
        )
        await session.commit()

    stats = await run_alerts_job(session_factory)

    async with session_factory() as session:
        alerts = (await session.execute(select(AlertORM))).scalars().all()

    assert stats.listings_evaluated == 1
    assert stats.detected == 1
    assert stats.created == 0
    assert stats.skipped == 1
    assert len(alerts) == 1


async def test_alerts_job_does_not_duplicate_same_price_drop_event_on_rerun(
    session_factory,
) -> None:
    async with session_factory() as session:
        listing = _listing("rerun", price_clp=90_000_000)
        session.add(listing)
        await session.flush()
        session.add(_price(listing.id, 100_000_000, NOW - timedelta(days=1)))
        await session.commit()

    first_stats = await run_alerts_job(session_factory)
    second_stats = await run_alerts_job(session_factory)

    async with session_factory() as session:
        alerts = (await session.execute(select(AlertORM))).scalars().all()

    assert first_stats.created == 1
    assert first_stats.skipped == 0
    assert second_stats.detected == 1
    assert second_stats.created == 0
    assert second_stats.skipped == 1
    assert len(alerts) == 1


async def test_alerts_job_dedupes_uf_by_uf_values_not_clp_snapshots(session_factory) -> None:
    async with session_factory() as session:
        listing = _listing("uf-dedupe", price_clp=118_400_000, price_currency="UF", price_uf=3200)
        session.add(listing)
        await session.flush()
        session.add_all(
            [
                _price(
                    listing.id,
                    120_250_000,
                    NOW - timedelta(days=1),
                    price_currency="UF",
                    price_uf=3250,
                    change_basis="uf",
                ),
                AlertORM(
                    listing_id=listing.id,
                    alert_type="price_drop",
                    payload={
                        "previous_price_clp": 120_250_000,
                        "new_price_clp": 118_400_000,
                        "previous_price_clp_snapshot": 120_250_000,
                        "new_price_clp_snapshot": 118_400_000,
                        "previous_price_uf": 3300,
                        "new_price_uf": 3200,
                        "price_currency": "UF",
                        "change_basis": "uf",
                    },
                ),
            ]
        )
        await session.commit()

    stats = await run_alerts_job(session_factory, threshold_pct=1.0)

    async with session_factory() as session:
        alerts = (await session.execute(select(AlertORM))).scalars().all()

    assert stats.detected == 1
    assert stats.created == 1
    assert stats.skipped == 0
    assert len(alerts) == 2


async def test_alerts_job_dedupes_uf_when_uf_values_match_even_if_clp_snapshots_differ(session_factory) -> None:
    async with session_factory() as session:
        listing = _listing("uf-dedupe-match", price_clp=118_400_000, price_currency="UF", price_uf=3200)
        session.add(listing)
        await session.flush()
        session.add_all(
            [
                _price(
                    listing.id,
                    120_250_000,
                    NOW - timedelta(days=1),
                    price_currency="UF",
                    price_uf=3250,
                    change_basis="uf",
                ),
                AlertORM(
                    listing_id=listing.id,
                    alert_type="price_drop",
                    payload={
                        "previous_price_clp": 130_000_000,
                        "new_price_clp": 128_000_000,
                        "previous_price_clp_snapshot": 130_000_000,
                        "new_price_clp_snapshot": 128_000_000,
                        "previous_price_uf": 3250,
                        "new_price_uf": 3200,
                        "price_currency": "UF",
                        "change_basis": "uf",
                    },
                ),
            ]
        )
        await session.commit()

    stats = await run_alerts_job(session_factory, threshold_pct=1.0)

    async with session_factory() as session:
        alerts = (await session.execute(select(AlertORM))).scalars().all()

    assert stats.detected == 1
    assert stats.created == 0
    assert stats.skipped == 1
    assert len(alerts) == 1


async def test_alerts_job_creates_new_alert_for_distinct_price_drop_event(session_factory) -> None:
    async with session_factory() as session:
        listing = _listing("successive-drops", price_clp=90_000_000)
        session.add(listing)
        await session.flush()
        session.add(_price(listing.id, 100_000_000, NOW - timedelta(days=1)))
        await session.commit()
        listing_id = listing.id

    first_stats = await run_alerts_job(session_factory)

    async with session_factory() as session:
        listing = await session.get(ListingORM, listing_id)
        assert listing is not None
        listing.price_clp = Decimal("80000000")
        listing.scraped_at = NOW + timedelta(days=5)
        listing.last_seen_at = NOW + timedelta(days=5)
        session.add(_price(listing_id, 90_000_000, NOW + timedelta(days=1)))
        await session.commit()

    second_stats = await run_alerts_job(session_factory)

    async with session_factory() as session:
        alerts = (
            await session.execute(
                select(AlertORM).order_by(AlertORM.created_at.asc(), AlertORM.id.asc())
            )
        ).scalars().all()

    assert first_stats.created == 1
    assert second_stats.detected == 1
    assert second_stats.created == 1
    assert second_stats.skipped == 0
    assert len(alerts) == 2
    assert alerts[0].payload["previous_price_clp"] == 100_000_000
    assert alerts[0].payload["new_price_clp"] == 90_000_000
    assert alerts[1].payload["previous_price_clp"] == 90_000_000
    assert alerts[1].payload["new_price_clp"] == 80_000_000


async def test_read_price_drop_alert_does_not_block_distinct_later_drop(session_factory) -> None:
    async with session_factory() as session:
        listing = _listing("read-then-drop", price_clp=90_000_000)
        session.add(listing)
        await session.flush()
        session.add_all(
            [
                _price(listing.id, 100_000_000, NOW - timedelta(days=1)),
                AlertORM(
                    listing_id=listing.id,
                    alert_type="price_drop",
                    payload=_price_drop_payload(100_000_000, 90_000_000),
                    is_read=True,
                ),
            ]
        )
        await session.commit()
        listing_id = listing.id

    async with session_factory() as session:
        listing = await session.get(ListingORM, listing_id)
        assert listing is not None
        listing.price_clp = Decimal("80000000")
        listing.scraped_at = NOW + timedelta(days=5)
        listing.last_seen_at = NOW + timedelta(days=5)
        session.add(_price(listing_id, 90_000_000, NOW + timedelta(days=1)))
        await session.commit()

    stats = await run_alerts_job(session_factory)

    async with session_factory() as session:
        alerts = (
            await session.execute(
                select(AlertORM).order_by(AlertORM.created_at.asc(), AlertORM.id.asc())
            )
        ).scalars().all()

    assert stats.created == 1
    assert stats.skipped == 0
    assert len(alerts) == 2
    assert alerts[0].is_read is True
    assert alerts[1].is_read is False
    assert alerts[1].payload["previous_price_clp"] == 90_000_000
    assert alerts[1].payload["new_price_clp"] == 80_000_000


async def test_alerts_job_creates_no_alert_without_price_drop(session_factory) -> None:
    async with session_factory() as session:
        listing = _listing("stable", price_clp=100_000_000)
        session.add(listing)
        await session.flush()
        session.add(_price(listing.id, 90_000_000, NOW - timedelta(days=1)))
        await session.commit()

    stats = await run_alerts_job(session_factory)

    async with session_factory() as session:
        alerts = (await session.execute(select(AlertORM))).scalars().all()

    assert stats.listings_evaluated == 1
    assert stats.detected == 0
    assert stats.created == 0
    assert alerts == []


async def test_alerts_job_handles_missing_price_history(session_factory) -> None:
    async with session_factory() as session:
        session.add(_listing("thin", price_clp=100_000_000))
        await session.commit()

    stats = await run_alerts_job(session_factory)

    async with session_factory() as session:
        alerts = (await session.execute(select(AlertORM))).scalars().all()

    assert stats.listings_evaluated == 1
    assert stats.detected == 0
    assert stats.created == 0
    assert alerts == []


async def test_alerts_job_handles_many_listings_reasonable_scale(session_factory) -> None:
    async with session_factory() as session:
        listings = [_listing(f"scale-{index}", price_clp=90_000_000) for index in range(80)]
        session.add_all(listings)
        await session.flush()
        for index, listing in enumerate(listings):
            session.add(_price(listing.id, 100_000_000, NOW - timedelta(days=1)))
            if index % 4 == 0:
                session.add(
                    AlertORM(
                        listing_id=listing.id,
                        alert_type="price_drop",
                        payload=_price_drop_payload(100_000_000, 90_000_000),
                    )
                )
        await session.commit()

    stats = await run_alerts_job(session_factory)

    async with session_factory() as session:
        alerts = (await session.execute(select(AlertORM))).scalars().all()

    assert stats.listings_evaluated == 80
    assert stats.detected == 80
    assert stats.created == 60
    assert stats.skipped == 20
    assert len(alerts) == 80


def _listing(
    fingerprint: str,
    *,
    price_clp: int,
    price_currency: str | None = None,
    price_uf: int | None = None,
    price_uf_source: str | None = None,
    price_uf_confidence: str | None = None,
) -> ListingORM:
    return ListingORM(
        source="yapo",
        external_id=fingerprint,
        title=f"Listing {fingerprint}",
        comuna="nunoa",
        m2=70.0,
        bedrooms=2,
        bathrooms=2,
        parking=1,
        price_clp=Decimal(str(price_clp)),
        price_uf=Decimal(str(price_uf)) if price_uf is not None else None,
        price_currency=price_currency,
        price_uf_source=price_uf_source,
        price_uf_confidence=price_uf_confidence,
        status="active",
        fingerprint=fingerprint,
        scraped_at=NOW,
        last_seen_at=NOW,
        raw_metadata={},
    )


def _price(
    listing_id: int,
    price_clp: int,
    observed_at: datetime,
    *,
    price_currency: str | None = None,
    price_uf: int | None = None,
    change_basis: str | None = None,
    is_artifact: bool = False,
) -> PriceHistoryORM:
    return PriceHistoryORM(
        listing_id=listing_id,
        price_clp=Decimal(str(price_clp)),
        price_clp_snapshot=Decimal(str(price_clp)),
        price_uf=Decimal(str(price_uf)) if price_uf is not None else None,
        price_currency=price_currency,
        change_basis=change_basis,
        is_artifact=is_artifact,
        observed_at=observed_at,
    )


def _price_drop_payload(previous_price_clp: int, new_price_clp: int) -> dict[str, object]:
    return {
        "previous_price_clp": previous_price_clp,
        "new_price_clp": new_price_clp,
        "previous_price_clp_snapshot": previous_price_clp,
        "new_price_clp_snapshot": new_price_clp,
        "canonical_previous_price": previous_price_clp,
        "canonical_new_price": new_price_clp,
        "canonical_price_unit": "CLP",
        "change_basis": "clp_legacy",
        "drop_pct": 10.0,
    }
