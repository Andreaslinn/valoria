from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api import deps
from api.v1 import market as market_api
from core.entities.user import User
from infrastructure.db.database import get_db
from infrastructure.db.models import ListingORM, PriceHistoryORM


@pytest.mark.asyncio
async def test_market_briefing_returns_empty_without_listings(engine: AsyncEngine) -> None:
    client, _session_factory = _client(engine)
    async with client:
        response = await client.get("/api/v1/market/briefing")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "empty"
    assert body["available"] is False
    assert body["valoria_index"]["value"] is None
    assert body["indicators"][0]["value"] == 0
    assert body["source"] == "listings_db_empty"


@pytest.mark.asyncio
async def test_market_briefing_uses_real_listing_signals(engine: AsyncEngine) -> None:
    client, session_factory = _client(engine)
    async with session_factory() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                _listing(
                    listing_id=1,
                    comuna="las_condes",
                    price_uf=Decimal("6200"),
                    usable_area_m2=62,
                    geocode_precision="address",
                    last_seen_at=now - timedelta(days=1),
                ),
                _listing(
                    listing_id=2,
                    comuna="providencia",
                    price_uf=Decimal("4800"),
                    usable_area_m2=48,
                    geocode_precision="street",
                    last_seen_at=now - timedelta(days=20),
                ),
            ]
        )
        await session.commit()

    async with client:
        response = await client.get("/api/v1/market/briefing")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["available"] is True
    assert body["source"] == "listings_db"
    assert body["indicators"][0]["key"] == "active_supply"
    assert body["indicators"][0]["value"] == 2
    assert body["indicators"][1]["key"] == "fresh_listings"
    assert body["indicators"][1]["value"] == 1
    assert body["indicators"][2]["key"] == "new_listings_7d"
    assert isinstance(body["indicators"][2]["value"], int)
    assert body["diagnostics"]["active_apartments"] == 2
    assert body["diagnostics"]["fresh_apartments"] == 1
    assert body["diagnostics"]["stale_listings"] == 1
    assert body["diagnostics"]["new_listings_7d"] >= 0
    assert body["diagnostics"]["price_changes_30d"] == 0
    assert 0 <= body["valoria_index"]["value"] <= 100
    assert body["valoria_index"]["description"] == (
        "Indice de salud de datos Valoria, no senal de precio."
    )


@pytest.mark.asyncio
async def test_liquidity_summary_uses_real_counts_and_price_history(engine: AsyncEngine) -> None:
    client, session_factory = _client(engine)
    async with session_factory() as session:
        now = datetime.now(UTC)
        listing = _listing(
            listing_id=1,
            comuna="las_condes",
            price_uf=Decimal("6200"),
            usable_area_m2=62,
            geocode_precision="address",
            last_seen_at=now - timedelta(days=1),
        )
        session.add(listing)
        session.add(
            PriceHistoryORM(
                listing_id=1,
                price_clp=Decimal("248000000"),
                price_uf=Decimal("6200"),
                price_clp_snapshot=Decimal("248000000"),
                price_currency="CLP",
                uf_rate_used=Decimal("40000"),
                change_basis="observed",
                is_artifact=False,
                observed_at=now - timedelta(days=2),
            )
        )
        await session.commit()

    async with client:
        response = await client.get("/api/v1/market/liquidity/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert 0 <= body["value"] <= 100
    assert body["diagnostics"]["active_listings"] == 1
    assert body["diagnostics"]["fresh_listings"] == 1
    assert body["diagnostics"]["new_listings_7d"] >= 0
    assert body["diagnostics"]["removed_7d"] == 0
    assert body["diagnostics"]["price_changes_30d"] == 1
    assert body["source"] == "listings_price_history_db"


@pytest.mark.asyncio
async def test_microzones_summary_falls_back_to_comuna_proxy(engine: AsyncEngine) -> None:
    client, session_factory = _client(engine)
    async with session_factory() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                _listing(
                    listing_id=idx,
                    comuna="vitacura",
                    price_uf=Decimal("8000") + Decimal(idx),
                    usable_area_m2=80,
                    geocode_precision="address",
                    last_seen_at=now - timedelta(days=1),
                )
                for idx in range(1, 4)
            ]
        )
        await session.commit()

    async with client:
        response = await client.get("/api/v1/market/microzones/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["available"] is True
    assert body["items"][0]["type"] == "comuna_proxy"
    assert body["items"][0]["name"] == "Vitacura"
    assert body["items"][0]["active_listings"] == 3
    assert body["items"][0]["median_price_m2_uf"] is not None


def _client(engine: AsyncEngine) -> tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[deps._resolve_current_user] = _authenticated_user
    app.include_router(market_api.router, prefix="/api/v1")
    return (
        httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test"),
        session_factory,
    )


def _listing(
    *,
    listing_id: int,
    comuna: str,
    price_uf: Decimal | None,
    usable_area_m2: float | None,
    geocode_precision: str | None,
    last_seen_at: datetime,
) -> ListingORM:
    price_clp = Decimal("40000000") if price_uf is None else price_uf * Decimal("40000")
    return ListingORM(
        id=listing_id,
        source="test",
        external_id=f"ext-{listing_id}",
        title=f"Depto {listing_id}",
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
        geocode_precision=geocode_precision,
        price_clp=price_clp,
        price_uf=price_uf,
        price_currency="CLP",
        price_uf_confidence="high" if price_uf is not None else None,
        price_uf_source="test" if price_uf is not None else None,
        price_recovery_method=None,
        status="active",
        fingerprint=f"fingerprint-{listing_id}",
        raw_metadata={},
        scraped_at=last_seen_at,
        last_seen_at=last_seen_at,
        last_refresh_attempted_at=None,
        last_refresh_status=None,
    )


async def _authenticated_user() -> User:
    return User(
        id=7,
        email="dashboard-user@example.com",
        password_hash="hash",
        role="beta_user",
        is_active=True,
    )
