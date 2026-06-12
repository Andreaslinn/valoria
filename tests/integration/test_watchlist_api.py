from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.deps import get_uf_service
from api.main import create_app
from api.security import hash_password
from core.entities.listing import Listing
from core.entities.user import User
from core.ports.uf_service import UFService
from core.value_objects.price import Price
from infrastructure.db.database import get_db
from infrastructure.db.models import SavedListingORM
from infrastructure.db.repositories import SqlAlchemyListingRepository, SqlAlchemyUserRepository


class FakeUFService(UFService):
    async def get_current_rate(self) -> Decimal:
        return Decimal("39000")


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
    app.dependency_overrides[get_uf_service] = lambda: FakeUFService()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(engine: AsyncEngine, client: httpx.AsyncClient) -> dict[str, str]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        await repo.save(
            User(
                id=None,
                email="watcher@example.com",
                password_hash=hash_password("passwordsegura123"),
                role="beta_user",
                is_active=True,
            )
        )
        await session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "watcher@example.com", "password": "passwordsegura123"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def listing(engine: AsyncEngine) -> Listing:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        repo = SqlAlchemyListingRepository(session)
        saved = await repo.save(
            Listing(
                id=None,
                source="yapo",
                external_id="watch-1",
                title="Depto watchlist",
                comuna="nunoa",
                m2=72.0,
                bedrooms=2,
                bathrooms=2,
                parking=1,
                price=Price(clp=Decimal("150000000")),
                status="active",
                fingerprint="watch-fp-1",
                scraped_at=datetime.now(UTC),
                url="https://example.test/watch",
            )
        )
        await session.commit()
        return saved


async def test_save_listing_to_watchlist(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    listing: Listing,
):
    resp = await client.post(f"/api/v1/watchlist/{listing.id}", headers=auth_headers)

    assert resp.status_code == 201
    body = resp.json()
    assert body["listing_id"] == listing.id
    assert body["saved_price_clp"] == 150000000
    assert body["saved_price_uf"] is None
    assert body["saved_price_basis"] == "legacy_unknown"
    assert body["price_uf_display"] == 3846.15
    assert body["price_clp_display"] == 150000000
    assert body["uf_rate_used_for_display"] == 39000.0
    assert body["status"] == "active"


async def test_watchlist_saves_canonical_price_uf_only(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
):
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        repo = SqlAlchemyListingRepository(session)
        saved = await repo.save(
            Listing(
                id=None,
                source="yapo",
                external_id="watch-uf",
                title="Depto UF",
                comuna="nunoa",
                m2=72.0,
                bedrooms=2,
                bathrooms=2,
                parking=1,
                price=Price(clp=Decimal("156000000")),
                price_uf=Decimal("4000"),
                price_currency="UF",
                price_uf_source="scraped",
                price_uf_confidence="high",
                price_recovery_method="raw_metadata.price_uf",
                status="active",
                fingerprint="watch-uf-fp",
                scraped_at=datetime.now(UTC),
                url="https://example.test/watch-uf",
            )
        )
        await session.commit()

    resp = await client.post(f"/api/v1/watchlist/{saved.id}", headers=auth_headers)

    assert resp.status_code == 201
    body = resp.json()
    assert body["saved_price_uf"] == 4000.0
    assert body["saved_price_basis"] == "canonical_uf"
    assert body["price_display_basis"] == "canonical_uf"
    assert body["price_uf_display"] == 4000.0
    assert body["price_clp_display"] == 156000000
    assert body["price_data_quality"] == "scraped"


async def test_watchlist_does_not_persist_fallback_uf_for_legacy_uf(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
):
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        repo = SqlAlchemyListingRepository(session)
        saved = await repo.save(
            Listing(
                id=None,
                source="yapo",
                external_id="watch-legacy-uf",
                title="Depto UF legacy",
                comuna="nunoa",
                m2=72.0,
                bedrooms=2,
                bathrooms=2,
                parking=1,
                price=Price(clp=Decimal("156000000")),
                price_currency="UF",
                price_uf_source="legacy_unrecoverable",
                price_recovery_method="legacy_unrecoverable",
                status="active",
                fingerprint="watch-legacy-uf-fp",
                scraped_at=datetime.now(UTC),
                url="https://example.test/watch-legacy-uf",
            )
        )
        await session.commit()

    resp = await client.post(f"/api/v1/watchlist/{saved.id}", headers=auth_headers)

    assert resp.status_code == 201
    body = resp.json()
    assert body["saved_price_uf"] is None
    assert body["saved_price_basis"] == "legacy_uf_missing_price_uf"
    assert body["price_display_basis"] == "legacy_uf_missing_price_uf"
    assert body["price_uf_display"] == 4000.0
    assert body["price_data_quality"] == "legacy_unrecoverable"


async def test_watchlist_hides_existing_saved_price_uf_when_listing_is_legacy_uf(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    engine: AsyncEngine,
):
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        repo = SqlAlchemyListingRepository(session)
        saved_listing = await repo.save(
            Listing(
                id=None,
                source="yapo",
                external_id="watch-old-fallback",
                title="Depto old fallback",
                comuna="nunoa",
                m2=72.0,
                bedrooms=2,
                bathrooms=2,
                parking=1,
                price=Price(clp=Decimal("156000000")),
                price_currency="UF",
                price_uf_source="legacy_unrecoverable",
                price_recovery_method="legacy_unrecoverable",
                status="active",
                fingerprint="watch-old-fallback-fp",
                scraped_at=datetime.now(UTC),
                url="https://example.test/watch-old-fallback",
            )
        )
        user = await SqlAlchemyUserRepository(session).find_by_email("watcher@example.com")
        assert user is not None and user.id is not None
        session.add(
            SavedListingORM(
                user_id=user.id,
                listing_id=saved_listing.id,
                saved_price_clp=Decimal("156000000"),
                saved_price_uf=Decimal("4216.22"),
                status="active",
            )
        )
        await session.commit()

    resp = await client.get("/api/v1/watchlist", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    item = next(row for row in body if row["listing_id"] == saved_listing.id)
    assert item["saved_price_uf"] is None
    assert item["saved_price_basis"] == "legacy_uf_missing_price_uf"


async def test_save_listing_does_not_duplicate(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    listing: Listing,
):
    first = await client.post(f"/api/v1/watchlist/{listing.id}", headers=auth_headers)
    second = await client.post(f"/api/v1/watchlist/{listing.id}", headers=auth_headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


async def test_list_watchlist(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    listing: Listing,
):
    await client.post(f"/api/v1/watchlist/{listing.id}", headers=auth_headers)

    resp = await client.get("/api/v1/watchlist", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Depto watchlist"


async def test_remove_watchlist_item_marks_removed(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    listing: Listing,
    engine: AsyncEngine,
):
    await client.post(f"/api/v1/watchlist/{listing.id}", headers=auth_headers)

    resp = await client.delete(f"/api/v1/watchlist/{listing.id}", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == {"listing_id": listing.id, "saved": False, "status": "removed"}

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        saved = (await session.execute(select(SavedListingORM))).scalar_one()
        assert saved.status == "removed"

    listed = await client.get("/api/v1/watchlist", headers=auth_headers)
    assert listed.json() == []


async def test_watchlist_requires_auth(client: httpx.AsyncClient, listing: Listing):
    resp = await client.post(f"/api/v1/watchlist/{listing.id}")

    assert resp.status_code == 401
