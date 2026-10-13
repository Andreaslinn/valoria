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
from api.v1 import radar as radar_api
from core.entities.user import User
from infrastructure.db.database import get_db
from infrastructure.db.models import ListingORM


@pytest.mark.asyncio
async def test_radar_summary_returns_real_scope_and_freshness_counts(engine: AsyncEngine) -> None:
    client, session_factory = _client(engine)
    async with session_factory() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                _listing(
                    listing_id=1,
                    property_type="apartment",
                    status="active",
                    last_seen_at=now - timedelta(days=1),
                ),
                _listing(
                    listing_id=2,
                    property_type="apartment",
                    status="active",
                    last_seen_at=now - timedelta(days=20),
                ),
                _listing(
                    listing_id=3,
                    property_type="apartment",
                    status="inactive",
                    last_seen_at=now - timedelta(days=1),
                ),
                _listing(
                    listing_id=4,
                    property_type="house",
                    status="active",
                    last_seen_at=now - timedelta(days=1),
                ),
            ]
        )
        await session.commit()

    async with client:
        response = await client.get("/api/v1/radar/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["mode"] == "manual"
    assert body["auto_run"] is False
    assert body["requires_manual_run"] is True
    assert body["opportunities_count"] is None
    assert body["allowed_property_types"] == ["apartment"]
    assert body["active_scope_count"] == 2
    assert body["fresh_candidates_count"] == 1
    assert body["ready_for_radar_count"] == 1
    assert body["excluded_stale_count"] == 1
    assert body["excluded_removed_count"] == 1
    assert body["excluded_missing_price_count"] == 0
    assert body["excluded_missing_area_count"] == 0
    assert body["last_refresh_at"] is not None
    assert body["source"] == "radar_shared_initial_eligibility_v1"


@pytest.mark.asyncio
async def test_radar_summary_counts_clp_candidates_without_price_uf(engine: AsyncEngine) -> None:
    client, session_factory = _client(engine)
    async with session_factory() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                _listing(
                    listing_id=10,
                    property_type="apartment",
                    status="active",
                    last_seen_at=now - timedelta(days=1),
                    price_uf=None,
                    price_currency="CLP",
                ),
                _listing(
                    listing_id=11,
                    property_type="apartment",
                    status="active",
                    last_seen_at=now - timedelta(days=1),
                    price_uf=None,
                    price_currency="UF",
                ),
                _listing(
                    listing_id=12,
                    property_type="house",
                    status="active",
                    last_seen_at=now - timedelta(days=1),
                    price_uf=None,
                    price_currency="CLP",
                ),
            ]
        )
        await session.commit()

    async with client:
        response = await client.get("/api/v1/radar/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["active_scope_count"] == 2
    assert body["fresh_candidates_count"] == 2
    assert body["ready_for_radar_count"] == 1
    assert body["excluded_missing_price_count"] == 1
    assert body["source"] == "radar_shared_initial_eligibility_v1"


@pytest.mark.asyncio
async def test_radar_summary_empty_db_does_not_return_fake_counts(engine: AsyncEngine) -> None:
    client, _session_factory = _client(engine)
    async with client:
        response = await client.get("/api/v1/radar/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "empty"
    assert body["fresh_candidates_count"] == 0
    assert body["ready_for_radar_count"] == 0
    assert body["active_scope_count"] == 0
    assert body["excluded_stale_count"] == 0
    assert body["excluded_removed_count"] == 0


@pytest.mark.asyncio
async def test_radar_summary_does_not_require_radar_service_dependency(engine: AsyncEngine) -> None:
    client, _session_factory = _client(engine, fail_radar_service=True)
    async with client:
        response = await client.get("/api/v1/radar/summary")

    assert response.status_code == 200


def _client(
    engine: AsyncEngine,
    *,
    fail_radar_service: bool = False,
) -> tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    def _fail_radar_service() -> None:
        raise AssertionError("RadarService should not be resolved by /radar/summary")

    app = FastAPI()
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[deps._resolve_current_user] = _authenticated_user
    if fail_radar_service:
        app.dependency_overrides[deps.get_radar_service] = _fail_radar_service
    app.include_router(radar_api.router, prefix="/api/v1")
    return (
        httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test"),
        session_factory,
    )


def _listing(
    *,
    listing_id: int,
    property_type: str,
    status: str,
    last_seen_at: datetime,
    price_uf: Decimal | None = Decimal("6000"),
    price_currency: str | None = "CLP",
) -> ListingORM:
    return ListingORM(
        id=listing_id,
        source="test",
        external_id=f"radar-{listing_id}",
        title=f"Listing {listing_id}",
        url=f"https://example.test/radar/{listing_id}",
        comuna="las_condes",
        property_type=property_type,
        m2=60,
        built_area_m2=60,
        usable_area_m2=60,
        land_area_m2=None,
        bedrooms=2,
        bathrooms=2,
        parking=1,
        lat=-33.4,
        lon=-70.6,
        geocode_precision="address",
        price_clp=Decimal("240000000"),
        price_uf=price_uf,
        price_currency=price_currency,
        price_uf_confidence="high",
        price_uf_source="test",
        price_recovery_method=None,
        status=status,
        fingerprint=f"radar-fingerprint-{listing_id}",
        raw_metadata={},
        scraped_at=last_seen_at,
        last_seen_at=last_seen_at,
        last_refresh_attempted_at=None,
        last_refresh_status=None,
    )


async def _authenticated_user() -> User:
    return User(
        id=7,
        email="radar-user@example.com",
        password_hash="hash",
        role="beta_user",
        is_active=True,
    )
