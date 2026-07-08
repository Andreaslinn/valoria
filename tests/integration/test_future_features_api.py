from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.main import create_app
from api.security import hash_password
from core.entities.user import User
from infrastructure.db.database import get_db
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
                email="future-features@example.com",
                password_hash=hash_password("passwordsegura123"),
                role="beta_user",
                is_active=True,
            )
        )
        await session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "future-features@example.com", "password": "passwordsegura123"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_future_features_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/future-features")

    assert resp.status_code == 401


async def test_future_features_endpoint_lists_stub_contracts(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    resp = await client.get("/api/v1/future-features", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body
    keys = {item["feature_key"] for item in body}
    assert "negotiation_recommendation" in keys
    negotiation = next(item for item in body if item["feature_key"] == "negotiation_recommendation")
    assert negotiation["status"] == "requires_price_history"
    assert negotiation["safe_to_show_in_beta"] is False
    assert "suggested_offer_range" in negotiation["future_fields"]
    assert "suggested_offer_range" not in negotiation


async def test_future_feature_detail_and_not_found(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    detail = await client.get(
        "/api/v1/future-features/alert_rules",
        headers=auth_headers,
    )
    missing = await client.get(
        "/api/v1/future-features/does_not_exist",
        headers=auth_headers,
    )

    assert detail.status_code == 200
    assert detail.json()["status"] == "not_configured"
    assert missing.status_code == 404
