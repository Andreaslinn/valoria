from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from infrastructure.db.models import ListingORM, PriceHistoryORM
from services.market_intelligence import (
    MarketIntelligenceConfig,
    build_communes_summary,
    build_dynamism_summary,
    build_market_pulse,
)


@pytest.mark.asyncio
async def test_market_pulse_empty_db_returns_honest_empty(engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        pulse = await build_market_pulse(session)

    assert pulse["status"] == "empty"
    assert pulse["recent_activity"]["new_7d"] == 0
    assert pulse["observed_publication_time"]["sample_size"] == 0
    assert pulse["market_balance"]["score"] == 50


@pytest.mark.asyncio
async def test_recent_activity_uses_created_at_and_removed_detection_timestamp(
    engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all(
            [
                _listing(1, created_at=now - timedelta(hours=3), scraped_at=now - timedelta(days=80)),
                _listing(2, created_at=now - timedelta(days=3), scraped_at=now - timedelta(days=80)),
                _listing(
                    3,
                    status="removed",
                    created_at=now - timedelta(days=90),
                    updated_at=now - timedelta(hours=2),
                    last_refresh_attempted_at=now - timedelta(hours=1),
                ),
                _listing(
                    4,
                    status="inactive",
                    created_at=now - timedelta(days=90),
                    updated_at=now - timedelta(days=3),
                ),
            ]
        )
        await session.commit()
        pulse = await build_market_pulse(session)

    activity = pulse["recent_activity"]
    assert activity["new_24h"] == 1
    assert activity["new_7d"] == 2
    assert activity["removed_24h"] == 1
    assert activity["removed_7d"] == 2
    assert activity["net_flow_7d"] == 0
    assert "vend" not in pulse["insight"]["text"].lower()


@pytest.mark.asyncio
async def test_price_drops_exclude_artifacts_and_count_unique_listings(engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all([_listing(1), _listing(2), _listing(3), _listing(4)])
        session.add_all(
            [
                _history(1, now - timedelta(days=9), Decimal("5000")),
                _history(1, now - timedelta(days=2), Decimal("4800")),
                _history(1, now - timedelta(days=1), Decimal("4700")),
                _history(2, now - timedelta(days=4), Decimal("5000")),
                _history(2, now - timedelta(days=1), Decimal("5100")),
                _history(3, now - timedelta(days=4), Decimal("5000"), is_artifact=True),
                _history(3, now - timedelta(days=1), Decimal("4500"), is_artifact=True),
                _history(4, now - timedelta(days=4), Decimal("5000"), change_basis="legacy_unrecoverable"),
                _history(4, now - timedelta(days=1), Decimal("4500"), change_basis="legacy_unrecoverable"),
            ]
        )
        await session.commit()
        pulse = await build_market_pulse(session)

    activity = pulse["recent_activity"]
    assert activity["price_drops_7d"] == 1
    assert activity["unique_listings_with_price_drop_30d"] == 1
    assert activity["total_price_drop_events_30d"] == 2


@pytest.mark.asyncio
async def test_observed_time_uses_median_excludes_future_and_falls_back_created_at(
    engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all(
            [
                _listing(1, created_at=now - timedelta(days=10), scraped_at=now - timedelta(days=60)),
                _listing(2, created_at=now - timedelta(days=20)),
                _listing(3, created_at=now - timedelta(days=30)),
                _listing(4, created_at=now + timedelta(days=2)),
            ]
        )
        await session.commit()
        pulse = await build_market_pulse(session)

    observed = pulse["observed_publication_time"]
    assert observed["median_days"] == 20
    assert observed["sample_size"] == 3
    assert observed["comparison"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_market_balance_scores_high_low_and_neutral(engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    now = datetime.now(UTC)
    async with session_factory() as session:
        for idx in range(1, 51):
            created = now - timedelta(days=90)
            if idx <= 10:
                created = now - timedelta(days=2)
            session.add(_listing(idx, created_at=created))
            if idx <= 10:
                session.add(_history(idx, now - timedelta(days=20), Decimal("5000")))
                session.add(_history(idx, now - timedelta(days=2), Decimal("4500")))
        await session.commit()
        pulse = await build_market_pulse(session)

    balance = pulse["market_balance"]
    assert 0 <= balance["score"] <= 100
    assert balance["score"] > 55
    assert balance["label"] in {
        "Leve ventaja comprador",
        "Favorece al comprador",
        "Mercado equilibrado",
    }
    assert sum(component["weight"] for component in balance["components"]) == pytest.approx(1.0)
    assert next(c for c in balance["components"] if c["key"] == "price_trend")["status"] == "unavailable"


@pytest.mark.asyncio
async def test_communes_respect_minimum_sample_and_featured_has_reason(engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    now = datetime.now(UTC)
    async with session_factory() as session:
        for idx in range(1, 36):
            session.add(
                _listing(
                    idx,
                    comuna="nunoa",
                    created_at=now - timedelta(days=idx % 10),
                    usable_area_m2=50,
                    price_uf=Decimal("5000"),
                )
            )
        for idx in range(100, 102):
            session.add(_listing(idx, comuna="vitacura", created_at=now - timedelta(days=1)))
        session.add(_history(1, now - timedelta(days=10), Decimal("5000")))
        session.add(_history(1, now - timedelta(days=1), Decimal("4800")))
        await session.commit()
        summary = await build_communes_summary(
            session,
            config=MarketIntelligenceConfig(
                commune_min_active_listings=30,
                commune_min_time_sample=5,
                commune_min_price_history_sample=1,
            ),
        )
        pulse = await build_market_pulse(
            session,
            config=MarketIntelligenceConfig(
                commune_min_active_listings=30,
                commune_min_time_sample=5,
                commune_min_price_history_sample=1,
            ),
        )

    comunas = {item["comuna"] for item in summary["items"]}
    assert "Nunoa" in comunas
    assert "Vitacura" not in comunas
    assert pulse["featured_commune"]["criterion"] == "highest_supply_pressure"
    assert pulse["featured_commune"]["reason_code"]
    assert summary["items"][0]["median_price_m2_uf"] == 100.0


@pytest.mark.asyncio
async def test_dynamism_is_activity_not_liquidity_and_insight_is_product_safe(
    engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    now = datetime.now(UTC)
    async with session_factory() as session:
        for idx in range(1, 41):
            session.add(_listing(idx, created_at=now - timedelta(days=idx % 7), comuna="santiago"))
        await session.commit()
        dynamism = await build_dynamism_summary(session)
        pulse = await build_market_pulse(session)

    assert 0 <= dynamism["score"] <= 100
    assert "liquidez" not in dynamism["label"].lower()
    assert "liquidez" not in dynamism["summary"].lower()
    insight = pulse["insight"]["text"].lower()
    forbidden = ("radar", "endpoint", "proxy", "scope", "vendida", "scraper")
    assert all(word not in insight for word in forbidden)


def _listing(
    listing_id: int,
    *,
    comuna: str = "las_condes",
    status: str = "active",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    scraped_at: datetime | None = None,
    last_seen_at: datetime | None = None,
    last_refresh_attempted_at: datetime | None = None,
    price_uf: Decimal | None = Decimal("5000"),
    usable_area_m2: float | None = 50,
) -> ListingORM:
    now = datetime.now(UTC)
    first_seen = created_at or now - timedelta(days=20)
    return ListingORM(
        id=listing_id,
        source="test",
        external_id=f"mi-{listing_id}",
        title=f"Listing {listing_id}",
        url=f"https://example.test/{listing_id}",
        comuna=comuna,
        property_type="apartment",
        m2=usable_area_m2,
        built_area_m2=usable_area_m2,
        usable_area_m2=usable_area_m2,
        land_area_m2=None,
        bedrooms=2,
        bathrooms=2,
        parking=1,
        lat=-33.4,
        lon=-70.6,
        geocode_precision="address",
        price_clp=(price_uf or Decimal("1000")) * Decimal("40000"),
        price_uf=price_uf,
        price_currency="CLP",
        price_uf_confidence="high" if price_uf is not None else None,
        price_uf_source="test" if price_uf is not None else None,
        price_recovery_method=None,
        status=status,
        fingerprint=f"mi-fingerprint-{listing_id}",
        raw_metadata={},
        scraped_at=scraped_at or first_seen,
        last_seen_at=last_seen_at or first_seen,
        last_refresh_attempted_at=last_refresh_attempted_at,
        last_refresh_status=None,
        created_at=first_seen,
        updated_at=updated_at or first_seen,
    )


def _history(
    listing_id: int,
    observed_at: datetime,
    price_uf: Decimal,
    *,
    is_artifact: bool = False,
    change_basis: str = "uf",
) -> PriceHistoryORM:
    return PriceHistoryORM(
        listing_id=listing_id,
        price_clp=price_uf * Decimal("40000"),
        price_uf=price_uf,
        price_clp_snapshot=price_uf * Decimal("40000"),
        price_currency="CLP",
        uf_rate_used=Decimal("40000"),
        change_basis=change_basis,
        is_artifact=is_artifact,
        artifact_reason="test" if is_artifact else None,
        observed_at=observed_at,
    )
