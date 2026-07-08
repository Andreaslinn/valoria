from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api import deps
from api.v1 import tasar as tasar_api
from core.entities.user import User
from infrastructure.db.database import get_db
from infrastructure.db.models import UsageLogORM


@pytest.mark.asyncio
async def test_tasar_recent_activity_requires_auth(engine: AsyncEngine) -> None:
    client, _session_factory = _client(engine, authenticated=False)
    async with client:
        response = await client.get("/api/v1/tasar/activity/recent")

    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_tasar_recent_activity_returns_empty_for_authenticated_user(engine: AsyncEngine) -> None:
    client, _session_factory = _client(engine, authenticated=True)
    async with client:
        response = await client.get("/api/v1/tasar/activity/recent")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "empty"
    assert body["user_id"] == 7
    assert body["events"] == []


@pytest.mark.asyncio
async def test_tasar_recent_activity_does_not_return_other_user_events(engine: AsyncEngine) -> None:
    client, session_factory = _client(engine, authenticated=True)
    async with session_factory() as session:
        session.add(
            UsageLogORM(
                user_id=8,
                event_type="valuation_completed",
                payload={"metadata": {"comuna": "las_condes"}},
                created_at=datetime(2026, 6, 25, 10, 0, tzinfo=UTC),
            )
        )
        await session.commit()

    async with client:
        response = await client.get("/api/v1/tasar/activity/recent")

    assert response.status_code == 200
    assert response.json()["events"] == []


@pytest.mark.asyncio
async def test_tasar_recent_activity_returns_partial_available_events(engine: AsyncEngine) -> None:
    client, session_factory = _client(engine, authenticated=True)
    async with session_factory() as session:
        session.add(
            UsageLogORM(
                user_id=7,
                event_type="valuation_completed",
                payload={"metadata": {"comuna": "providencia", "estimated_value_uf": 6294}},
                created_at=datetime(2026, 6, 25, 10, 0, tzinfo=UTC),
            )
        )
        await session.commit()

    async with client:
        response = await client.get("/api/v1/tasar/activity/recent?limit=3")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["events_count"] == 1
    assert body["events"][0]["event_type"] == "valuation_created"


def _client(
    engine: AsyncEngine,
    *,
    authenticated: bool,
) -> tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.dependency_overrides[get_db] = _get_db_override
    if authenticated:
        app.dependency_overrides[deps._resolve_current_user] = _authenticated_user
    app.include_router(tasar_api.router, prefix="/api/v1")

    return (
        httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test"),
        session_factory,
    )


async def _authenticated_user() -> User:
    return User(
        id=7,
        email="activity-user@example.com",
        password_hash="hash",
        role="beta_user",
        is_active=True,
    )
