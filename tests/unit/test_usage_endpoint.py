from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api import deps
from api.v1 import usage as usage_api
from core.entities.user import User
from infrastructure.db.database import get_db
from infrastructure.db.models import UsageLogORM


@pytest.mark.asyncio
async def test_usage_event_authenticated_happy_path_persists_usage_log(engine: AsyncEngine) -> None:
    client, session_factory = _client(engine, authenticated=True)
    async with client:
        response = await client.post(
            "/api/v1/usage/events",
            json={
                "event_type": "page_view",
                "feature": "Radar",
                "metadata": {
                    "page": "Radar",
                    "session_id": "session-123",
                    "session_duration_seconds": 1.25,
                    "unsafe_key": "drop-me",
                },
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["event_type"] == "page_view"
    assert body["user_id"] == 7
    assert body["payload"] == {
        "feature": "radar",
        "metadata": {
            "page": "radar",
            "session_id": "session-123",
            "session_duration_seconds": 1.25,
        },
    }

    async with session_factory() as session:
        logs = (await session.execute(select(UsageLogORM))).scalars().all()

    assert len(logs) == 1
    assert logs[0].user_id == 7
    assert logs[0].event_type == "page_view"
    assert logs[0].payload["metadata"]["page"] == "radar"


@pytest.mark.asyncio
async def test_usage_event_without_authenticated_user_returns_401(engine: AsyncEngine) -> None:
    client, _session_factory = _client(engine, authenticated=False)
    async with client:
        response = await client.post(
            "/api/v1/usage/events",
            json={"event_type": "page_view", "metadata": {"page": "Radar"}},
        )

    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_usage_event_invalid_payload_returns_400_or_422(engine: AsyncEngine) -> None:
    client, _session_factory = _client(engine, authenticated=True)
    async with client:
        response = await client.post(
            "/api/v1/usage/events",
            json={"event_type": "not_allowed", "metadata": {}},
        )

    assert response.status_code in {400, 422}


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
    app.include_router(usage_api.router, prefix="/api/v1")

    return (
        httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test"),
        session_factory,
    )


async def _authenticated_user() -> User:
    return User(
        id=7,
        email="usage-user@example.com",
        password_hash="hash",
        role="beta_user",
        is_active=True,
    )
