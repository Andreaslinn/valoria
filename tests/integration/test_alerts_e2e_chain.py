from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.main import create_app
from api.security import hash_password
from core.entities.user import User
from domain.ingestion.pipeline import process_listing
from infrastructure.db.database import get_db
from infrastructure.db.models import AlertORM, ListingORM, PriceHistoryORM, SavedListingORM
from infrastructure.db.repositories import (
    SqlAlchemyListingRepository,
    SqlAlchemyPriceHistoryRepository,
    SqlAlchemyPropertyRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.scrapers.base import RateLimiter
from workers.alerts_job import run_alerts_job
from workers.refresh_scraper import run_refresh_scraper

BASELINE_AT = datetime(2026, 5, 30, 10, 0, tzinfo=UTC)
REFRESH_AT = BASELINE_AT + timedelta(days=1)
PASSWORD = "password123"


@pytest.fixture(autouse=True)
def alert_clock_matches_observations(monkeypatch):
    """Evaluate the fixed history inside its real 30-day eligibility window."""
    class ObservationClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return REFRESH_AT.astimezone(tz) if tz else REFRESH_AT.replace(tzinfo=None)
    monkeypatch.setattr("services.alerts.datetime", ObservationClock)


@pytest_asyncio.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncGenerator[httpx.AsyncClient, None]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _get_db_override
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client


async def test_refresh_to_alerts_api_chain_for_saved_listing(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    listing_url = "https://www.yapo.cl/departamento-nunoa/e2e-price-drop"
    user_email = "alerts-e2e-user@example.com"
    other_email = "alerts-e2e-other@example.com"

    listing_id, user_headers, other_headers = await _seed_saved_listing(
        session_factory,
        client,
        user_email=user_email,
        other_email=other_email,
        listing_url=listing_url,
    )

    async with session_factory() as session:
        initial_history = (
            await session.execute(
                select(PriceHistoryORM)
                .where(PriceHistoryORM.listing_id == listing_id)
                .order_by(PriceHistoryORM.observed_at.asc(), PriceHistoryORM.id.asc())
            )
        ).scalars().all()

    assert len(initial_history) == 1
    assert int(initial_history[0].price_clp) == 180_000_000

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="<html>ok</html>"))
    ) as refresh_http_client:
        refresh_stats = await run_refresh_scraper(
            session_factory,
            http_client=refresh_http_client,
            limit=1,
            rate_limiter=RateLimiter(0),
            parser=lambda listing, html: _raw_listing(
                price_clp=160_000_000,
                scraped_at=REFRESH_AT,
                url=listing.url or listing_url,
            ),
            now=REFRESH_AT,
        )

    assert refresh_stats.selected == 1
    assert refresh_stats.processed == 1

    async with session_factory() as session:
        refreshed_listing = await session.get(ListingORM, listing_id)
        price_history = (
            await session.execute(
                select(PriceHistoryORM)
                .where(PriceHistoryORM.listing_id == listing_id)
                .order_by(PriceHistoryORM.observed_at.asc(), PriceHistoryORM.id.asc())
            )
        ).scalars().all()

    assert refreshed_listing is not None
    assert int(refreshed_listing.price_clp) == 160_000_000
    assert refreshed_listing.last_refresh_status == "ok"
    assert len(price_history) >= 2
    assert any(int(point.price_clp) == 180_000_000 for point in price_history)

    alert_stats = await run_alerts_job(session_factory, threshold_pct=5.0, lookback_days=30)

    async with session_factory() as session:
        alerts = (
            await session.execute(
                select(AlertORM)
                .where(AlertORM.listing_id == listing_id)
                .order_by(AlertORM.created_at.asc())
            )
        ).scalars().all()

    assert alert_stats.listings_evaluated == 1
    assert alert_stats.detected == 1
    assert alert_stats.created == 1
    assert len(alerts) == 1
    assert alerts[0].alert_type == "price_drop"
    assert alerts[0].is_read is False
    assert alerts[0].payload["previous_price_clp"] == 180_000_000
    assert alerts[0].payload["new_price_clp"] == 160_000_000

    user_response = await client.get("/api/v1/alerts", headers=user_headers)
    other_response = await client.get("/api/v1/alerts", headers=other_headers)

    assert user_response.status_code == 200
    assert other_response.status_code == 200
    assert other_response.json() == []

    body = user_response.json()
    assert len(body) == 1
    assert body[0]["id"] == alerts[0].id
    assert body[0]["listing_id"] == listing_id
    assert body[0]["alert_type"] == "price_drop"
    assert body[0]["is_read"] is False
    assert body[0]["payload"]["previous_price_clp"] == 180_000_000
    assert body[0]["payload"]["new_price_clp"] == 160_000_000
    assert body[0]["price_clp"] == 160_000_000


async def test_refresh_uf_rate_artifact_does_not_create_false_price_drop_alert(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    listing_url = "https://www.yapo.cl/departamento-nunoa/e2e-uf-artifact"
    user_email = "alerts-uf-artifact@example.com"

    async with session_factory() as session:
        user_repo = SqlAlchemyUserRepository(session)
        user = await user_repo.save(
            User(
                id=None,
                email=user_email,
                password_hash=hash_password(PASSWORD),
                role="beta_user",
                is_active=True,
            )
        )
        listing = await process_listing(
            {
                **_raw_listing(
                    price_clp=132_259_985,
                    scraped_at=BASELINE_AT,
                    url=listing_url,
                ),
                "external_id": "e2e-uf-artifact",
                "raw_metadata": {"price_uf": 3250.0},
            },
            listing_repo=SqlAlchemyListingRepository(session),
            property_repo=SqlAlchemyPropertyRepository(session),
            price_history_repo=SqlAlchemyPriceHistoryRepository(session),
        )
        assert user.id is not None
        assert listing.id is not None
        session.add(
            SavedListingORM(
                user_id=user.id,
                listing_id=listing.id,
                saved_price_clp=Decimal("132259985"),
                status="active",
                saved_at=BASELINE_AT,
            )
        )
        await session.commit()
        listing_id = listing.id

    def parser(_listing, _html):
        return {
            **_raw_listing(price_clp=120_250_000, scraped_at=REFRESH_AT, url=listing_url),
            "external_id": "e2e-uf-artifact",
            "price_uf": 3250.0,
            "raw_metadata": {
                "price_uf": 3250.0,
                "price_conversion_source": "fallback",
                "uf_rate_used": "37000",
            },
        }

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="<html>ok</html>"))
    ) as refresh_http_client:
        refresh_stats = await run_refresh_scraper(
            session_factory,
            http_client=refresh_http_client,
            limit=1,
            rate_limiter=RateLimiter(0),
            parser=parser,
            now=REFRESH_AT,
        )

    alert_stats = await run_alerts_job(session_factory, threshold_pct=5.0, lookback_days=30)

    async with session_factory() as session:
        listing = await session.get(ListingORM, listing_id)
        price_history = (
            await session.execute(
                select(PriceHistoryORM).where(PriceHistoryORM.listing_id == listing_id)
            )
        ).scalars().all()
        alerts = (
            await session.execute(select(AlertORM).where(AlertORM.listing_id == listing_id))
        ).scalars().all()

    assert refresh_stats.price_changes_ignored_uf_rate_artifact == 1
    assert refresh_stats.price_changes_detected == 0
    assert listing is not None
    assert int(listing.price_clp) == 132_259_985
    assert len(price_history) == 1
    assert alert_stats.detected == 0
    assert alert_stats.listings_evaluated == 1
    assert alert_stats.created == 0
    assert alerts == []


async def _seed_saved_listing(
    session_factory: async_sessionmaker[AsyncSession],
    client: httpx.AsyncClient,
    *,
    user_email: str,
    other_email: str,
    listing_url: str,
) -> tuple[int, dict[str, str], dict[str, str]]:
    async with session_factory() as session:
        user_repo = SqlAlchemyUserRepository(session)
        user = await user_repo.save(
            User(
                id=None,
                email=user_email,
                password_hash=hash_password(PASSWORD),
                role="beta_user",
                is_active=True,
            )
        )
        other = await user_repo.save(
            User(
                id=None,
                email=other_email,
                password_hash=hash_password(PASSWORD),
                role="beta_user",
                is_active=True,
            )
        )
        listing = await process_listing(
            _raw_listing(price_clp=180_000_000, scraped_at=BASELINE_AT, url=listing_url),
            listing_repo=SqlAlchemyListingRepository(session),
            property_repo=SqlAlchemyPropertyRepository(session),
            price_history_repo=SqlAlchemyPriceHistoryRepository(session),
        )
        assert user.id is not None
        assert other.id is not None
        assert listing.id is not None
        session.add(
            SavedListingORM(
                user_id=user.id,
                listing_id=listing.id,
                saved_price_clp=Decimal("180000000"),
                status="active",
                saved_at=BASELINE_AT,
            )
        )
        await session.commit()
        listing_id = listing.id

    return (
        listing_id,
        await _login(client, user_email),
        await _login(client, other_email),
    )


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _raw_listing(*, price_clp: int, scraped_at: datetime, url: str) -> dict[str, Any]:
    return {
        "source": "yapo",
        "external_id": "e2e-price-drop",
        "title": "Departamento 3 dormitorios en Nunoa",
        "url": url,
        "comuna": "Nunoa",
        "property_type": "apartment",
        "m2": 75,
        "bedrooms": 3,
        "bathrooms": 2,
        "parking": 1,
        "price_clp": price_clp,
        "scraped_at": scraped_at,
        "raw_metadata": {},
    }
