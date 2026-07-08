from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.deps import get_portfolio_snapshot_service
from api.main import create_app
from api.security import hash_password
from core.entities.user import User
from infrastructure.db.database import get_db
from infrastructure.db.models import (
    AlertORM,
    ListingORM,
    PortfolioItemValuationSnapshotORM,
    SavedListingORM,
)
from infrastructure.db.repositories import SqlAlchemyUserRepository


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncGenerator[httpx.AsyncClient, None]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as s:
            try:
                yield s
            except Exception:
                await s.rollback()
                raise

    app = create_app()
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_portfolio_snapshot_service] = _get_snapshot_service_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class FakePortfolioSnapshotService:
    async def create_snapshot(self, *, user_id: int, limit: int | None, dry_run: bool):
        return _Payload(
            {
                "user_id": user_id,
                "dry_run": dry_run,
                "limit": limit,
                "processed_count": 0,
                "valued_count": 0,
                "unavailable_count": 0,
                "reasons": {},
                "aggregate_snapshot_id": None,
                "items": [],
            }
        )


class _Payload:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_payload(self) -> dict:
        return dict(self._payload)


def _get_snapshot_service_override() -> FakePortfolioSnapshotService:
    return FakePortfolioSnapshotService()


@pytest_asyncio.fixture
async def auth_headers(engine: AsyncEngine, client: httpx.AsyncClient) -> dict[str, str]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        await repo.save(
            User(
                id=None,
                email="portfolio-api@example.com",
                password_hash=hash_password("passwordsegura123"),
                role="beta_user",
                is_active=True,
            )
        )
        await session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "portfolio-api@example.com", "password": "passwordsegura123"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_portfolio_summary_endpoint_returns_real_watchlist_and_unavailable_states(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
) -> None:
    await _seed_portfolio_api_data(engine)

    resp = await client.get("/api/v1/portfolio/summary", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tracked_properties"] == 1
    assert body["unread_alert_count"] == 1
    assert body["items"][0]["title"] == "Casa portfolio API"
    assert body["items"][0]["published_price_clp"] == 250000000.0
    assert body["items"][0]["avm"]["estimated_value_uf"] is None
    assert body["items"][0]["avm"]["reason"] == "needs_portfolio_avm_snapshot"
    assert body["items"][0]["delta"]["delta_pct"] is None
    assert body["items"][0]["trend"]["points"] == []
    assert body["upside"]["total_upside_uf"] is None
    assert body["compared"]["available"] is True
    assert body["favorites"]["reason"] == "needs_favorites_model"
    assert body["recommendations"]["recommendations"] == []


async def test_portfolio_items_endpoint_does_not_require_future_metrics(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
) -> None:
    await _seed_portfolio_api_data(engine)

    resp = await client.get("/api/v1/portfolio/items", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["avm"]["status"] == "needs_snapshot"
    assert body["items"][0]["delta"]["status"] == "needs_valuation"


async def test_portfolio_capabilities_endpoint_is_honest(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
) -> None:
    await _seed_portfolio_api_data(engine)

    resp = await client.get("/api/v1/portfolio/capabilities", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["tracked_properties"] == 1
    assert body["item_avm"]["available"] is False
    assert body["item_trend"]["reason"] == "needs_repeated_avm_snapshots"
    assert body["compared"]["available"] is True
    assert body["recommendations"]["reason"] == "portfolio_recommendation_engine_not_implemented"


async def test_portfolio_snapshot_endpoint_empty_watchlist_is_controlled(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    resp = await client.post(
        "/api/v1/portfolio/snapshots",
        headers=auth_headers,
        json={"dry_run": False, "limit": 5},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dry_run"] is False
    assert body["processed_count"] == 0
    assert body["valued_count"] == 0
    assert body["unavailable_count"] == 0


async def test_portfolio_items_endpoint_uses_snapshot_without_fake_values(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
) -> None:
    listing_id = await _seed_portfolio_api_data(engine)
    await _seed_portfolio_item_snapshot(engine, listing_id=listing_id)

    resp = await client.get("/api/v1/portfolio/items", headers=auth_headers)

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["avm"]["status"] == "available"
    assert item["avm"]["estimated_value_uf"] == 7200.0
    assert item["delta"]["status"] == "available"
    assert item["delta"]["delta_uf"] == 800.0
    assert item["trend"]["status"] == "needs_history"


async def test_portfolio_comparison_endpoints_create_add_detail_and_html(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
) -> None:
    listing_id = await _seed_portfolio_api_data(engine)
    second_listing_id = await _seed_second_portfolio_listing(engine)
    await _seed_portfolio_item_snapshot(engine, listing_id=listing_id)

    created = await client.post(
        "/api/v1/portfolio/comparisons",
        headers=auth_headers,
        json={"title": "Comparacion API"},
    )
    assert created.status_code == 200, created.text
    comparison_id = created.json()["comparison"]["id"]

    first = await client.post(
        f"/api/v1/portfolio/comparisons/{comparison_id}/items",
        headers=auth_headers,
        json={"listing_id": listing_id},
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        f"/api/v1/portfolio/comparisons/{comparison_id}/items",
        headers=auth_headers,
        json={"listing_id": second_listing_id},
    )
    assert second.status_code == 200, second.text

    detail = await client.get(f"/api/v1/portfolio/comparisons/{comparison_id}", headers=auth_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["comparison"]["is_ready"] is True
    assert len(body["items"]) == 2
    assert body["items"][0]["avm"]["available"] is True
    assert body["items"][1]["avm"]["reason"] == "needs_portfolio_avm_snapshot"

    report = await client.get(f"/api/v1/portfolio/comparisons/{comparison_id}/report.html", headers=auth_headers)
    assert report.status_code == 200
    assert "text/html" in report.headers["content-type"]
    assert "Comparacion API" in report.text
    assert "No disponible" in report.text
    assert "Score Radar" not in report.text


async def test_portfolio_endpoints_require_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/portfolio/summary")

    assert resp.status_code == 401


async def _seed_portfolio_api_data(engine: AsyncEngine) -> int:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        user = await SqlAlchemyUserRepository(session).find_by_email("portfolio-api@example.com")
        assert user is not None and user.id is not None
        listing = ListingORM(
            source="yapo",
            external_id="portfolio-api-listing",
            title="Casa portfolio API",
            comuna="providencia",
            property_type="house",
            m2=120,
            bedrooms=3,
            bathrooms=2,
            parking=1,
            price_clp=Decimal("250000000"),
            price_uf=Decimal("6400"),
            price_uf_source="scraped",
            price_currency="CLP",
            status="active",
            fingerprint="portfolio-api-listing-fp",
            scraped_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
            url="https://example.test/portfolio-api",
        )
        session.add(listing)
        await session.flush()
        session.add(
            SavedListingORM(
                user_id=user.id,
                listing_id=listing.id,
                saved_price_clp=listing.price_clp,
                status="active",
            )
        )
        session.add(AlertORM(listing_id=listing.id, alert_type="price_drop", payload={}, is_read=False))
        await session.commit()
        return listing.id


async def _seed_second_portfolio_listing(engine: AsyncEngine) -> int:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        user = await SqlAlchemyUserRepository(session).find_by_email("portfolio-api@example.com")
        assert user is not None and user.id is not None
        listing = ListingORM(
            source="yapo",
            external_id="portfolio-api-listing-second",
            title="Depto portfolio API",
            comuna="nunoa",
            property_type="apartment",
            m2=70,
            bedrooms=2,
            bathrooms=2,
            parking=1,
            price_clp=Decimal("180000000"),
            price_uf=Decimal("4600"),
            price_uf_source="scraped",
            price_currency="UF",
            status="active",
            fingerprint="portfolio-api-listing-second-fp",
            scraped_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
            url="https://example.test/portfolio-api-second",
        )
        session.add(listing)
        await session.flush()
        session.add(
            SavedListingORM(
                user_id=user.id,
                listing_id=listing.id,
                saved_price_clp=listing.price_clp,
                saved_price_uf=listing.price_uf,
                status="active",
            )
        )
        await session.commit()
        return listing.id


async def _seed_portfolio_item_snapshot(engine: AsyncEngine, *, listing_id: int) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        user = await SqlAlchemyUserRepository(session).find_by_email("portfolio-api@example.com")
        assert user is not None and user.id is not None
        session.add(
            PortfolioItemValuationSnapshotORM(
                user_id=user.id,
                listing_id=listing_id,
                watchlist_item_id=None,
                valuation_id=None,
                estimated_value_uf=Decimal("7200"),
                estimated_value_clp=Decimal("288000000"),
                lower_bound_uf=Decimal("6900"),
                upper_bound_uf=Decimal("7500"),
                confidence="medium",
                engine_name="test",
                engine_version="test",
                valuation_source="test",
                valuation_status="available",
                unavailable_reason=None,
                published_price_uf=Decimal("6400"),
                published_price_clp=Decimal("250000000"),
                delta_uf=Decimal("800"),
                delta_pct=12.5,
                delta_status="available",
                delta_unavailable_reason=None,
                data_freshness_status="manual_snapshot",
                snapshot_at=datetime.now(UTC),
            )
        )
        await session.commit()
