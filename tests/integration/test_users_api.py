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
            yield s

    app = create_app()
    app.dependency_overrides[get_db] = _get_db_override
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_admin_can_create_beta_user(client: httpx.AsyncClient, engine: AsyncEngine) -> None:
    await _seed_user(engine, "admin@example.com", "admin")
    token = await _login_token(client, "admin@example.com")

    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "beta@example.com", "password": "password123", "role": "beta_user"},
    )

    assert resp.status_code == 201
    assert resp.json()["email"] == "beta@example.com"


async def test_beta_user_cannot_create_users(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
) -> None:
    await _seed_user(engine, "beta@example.com", "beta_user")
    token = await _login_token(client, "beta@example.com")

    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "other@example.com", "password": "password123", "role": "beta_user"},
    )

    assert resp.status_code == 403


async def _seed_user(engine: AsyncEngine, email: str, role: str) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        await repo.save(
            User(
                id=None,
                email=email,
                password_hash=hash_password("password123"),
                role=role,  # type: ignore[arg-type]
                is_active=True,
            )
        )
        await session.commit()


async def _login_token(client: httpx.AsyncClient, email: str) -> str:
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "password123"},
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])
