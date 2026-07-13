from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api import deps
from api.main import create_app
from api.rate_limit import RateLimiter
from api.security import hash_password
from api.v1 import listings as listings_api
from api.v1 import reports as reports_api
from config import get_settings
from core.entities.user import User
from infrastructure.db.database import get_db
from infrastructure.db.repositories import SqlAlchemyUserRepository


class FakeRedis:
    def __init__(self) -> None:
        self.now = 0
        self.values: dict[str, int] = {}
        self.expires_at: dict[str, int] = {}
        self.keys_seen: list[str] = []

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[int]:
        key = str(keys_and_args[0])
        window = int(keys_and_args[1])
        self.keys_seen.append(key)
        if key in self.expires_at and self.expires_at[key] <= self.now:
            self.values.pop(key, None)
            self.expires_at.pop(key, None)
        self.values[key] = self.values.get(key, 0) + 1
        if key not in self.expires_at:
            self.expires_at[key] = self.now + window
        return [self.values[key], self.expires_at[key] - self.now]


class BrokenRedis:
    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        raise RuntimeError("redis unavailable")


async def _db_override(session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session


async def _create_user(engine: AsyncEngine, email: str = "andy@example.com") -> User:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        user = User(
            id=None,
            email=email,
            password_hash=hash_password("passwordsegura123"),
            role="beta_user",
            is_active=True,
        )
        saved = await SqlAlchemyUserRepository(session).save(user)
        await session.commit()
        return saved


async def _auth_client(
    engine: AsyncEngine,
    redis: FakeRedis | BrokenRedis,
    *,
    settings_overrides: dict[str, Any] | None = None,
    client_ip: str = "203.0.113.10",
) -> AsyncGenerator[httpx.AsyncClient, None]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    settings = get_settings().model_copy(update=settings_overrides or {})

    async def get_db_override() -> AsyncGenerator[AsyncSession, None]:
        async for session in _db_override(session_factory):
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = get_db_override
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[deps.get_rate_limiter] = lambda: RateLimiter(redis=redis, settings=settings)
    transport = ASGITransport(app=app, client=(client_ip, 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_login_allowed_within_limit(engine: AsyncEngine) -> None:
    await _create_user(engine)
    async for client in _auth_client(engine, FakeRedis()):
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "andy@example.com", "password": "passwordsegura123"},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_login_ip_limit_returns_429_with_retry_after(engine: AsyncEngine) -> None:
    async for client in _auth_client(engine, FakeRedis()):
        responses = [
            await client.post(
                "/api/v1/auth/login",
                data={"username": f"unknown-{idx}@example.com", "password": "badpassword"},
            )
            for idx in range(11)
        ]

    assert [response.status_code for response in responses[:10]] == [401] * 10
    assert responses[-1].status_code == 429
    assert int(responses[-1].headers["Retry-After"]) > 0
    assert responses[-1].json() == {"detail": "Demasiadas solicitudes. Intenta nuevamente mas tarde."}


@pytest.mark.asyncio
async def test_login_account_limit_uses_normalized_account_and_returns_429(engine: AsyncEngine) -> None:
    async for client in _auth_client(engine, FakeRedis(), settings_overrides={"rate_limit_login_ip_max": 100}):
        responses = [
            await client.post(
                "/api/v1/auth/login",
                data={"username": "  PERSON@Example.com  ", "password": "badpassword"},
            )
            for _ in range(21)
        ]

    assert responses[-1].status_code == 429


@pytest.mark.asyncio
async def test_register_limit_and_signup_remains_disabled(engine: AsyncEngine) -> None:
    async for client in _auth_client(engine, FakeRedis()):
        responses = [
            await client.post(
                "/api/v1/auth/register",
                json={"email": f"beta-{idx}@example.com", "password": "passwordsegura123"},
            )
            for idx in range(7)
        ]

    assert [response.status_code for response in responses[:6]] == [403] * 6
    assert responses[-1].status_code == 429


@pytest.mark.asyncio
async def test_ip_distinct_buckets_for_login(engine: AsyncEngine) -> None:
    redis = FakeRedis()
    async for client_a in _auth_client(engine, redis, client_ip="203.0.113.1"):
        for idx in range(10):
            await client_a.post(
                "/api/v1/auth/login",
                data={"username": f"a-{idx}@example.com", "password": "badpassword"},
            )
    async for client_b in _auth_client(engine, redis, client_ip="203.0.113.2"):
        response = await client_b.post(
            "/api/v1/auth/login",
            data={"username": "other@example.com", "password": "badpassword"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_redis_unavailable_fail_open_does_not_return_500(engine: AsyncEngine) -> None:
    async for client in _auth_client(engine, BrokenRedis()):
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "missing@example.com", "password": "badpassword"},
        )

    assert response.status_code == 401


@dataclass(frozen=True)
class _LookupResult:
    status: str
    listing_data: dict[str, Any]
    warnings: list[str]
    source: str | None
    url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "listing_data": self.listing_data,
            "warnings": self.warnings,
            "source": self.source,
            "url": self.url,
        }


async def _authenticated_user() -> User:
    return User(id=1, email="lookup@example.com", password_hash="hash", role="beta_user", is_active=True)


def _listing_client(redis: FakeRedis, *, authenticated: bool = True) -> httpx.AsyncClient:
    settings = get_settings()

    async def db_override() -> AsyncGenerator[None, None]:
        yield None

    app = FastAPI()
    if authenticated:
        app.dependency_overrides[deps._resolve_current_user] = _authenticated_user
    app.dependency_overrides[deps.get_db] = db_override
    app.dependency_overrides[deps.get_uf_service] = lambda: object()
    app.dependency_overrides[deps.get_rate_limiter] = lambda: RateLimiter(redis=redis, settings=settings)
    app.include_router(listings_api.router, prefix="/api/v1")
    transport = ASGITransport(app=app, client=("203.0.113.55", 1234))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _fake_lookup(url: str) -> _LookupResult:
    return _LookupResult(
        status="parsed_new",
        listing_data={"title": "Depto", "comuna": "nunoa", "m2": 70},
        warnings=[],
        source="yapo",
        url=url,
    )


@pytest.mark.asyncio
async def test_analyze_url_allowed_and_limited_by_user(monkeypatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(listings_api, "lookup_listing_url", _fake_lookup)
    monkeypatch.setattr(listings_api, "_maybe_ensure_lookup_freshness", _no_freshness)

    async with _listing_client(redis) as client:
        responses = [
            await client.post("/api/v1/listings/lookup-url", json={"url": f"https://example.test/{idx}"})
            for idx in range(11)
        ]

    assert [response.status_code for response in responses[:10]] == [200] * 10
    assert responses[-1].status_code == 429
    assert int(responses[-1].headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_protected_endpoint_without_token_does_not_consume_bucket(monkeypatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(listings_api, "lookup_listing_url", _fake_lookup)
    monkeypatch.setattr(listings_api, "_maybe_ensure_lookup_freshness", _no_freshness)

    async with _listing_client(redis, authenticated=False) as client:
        response = await client.post("/api/v1/listings/lookup-url", json={"url": "https://example.test/1"})

    assert response.status_code in {401, 403}
    assert redis.keys_seen == []


async def _no_freshness(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_invalid_token_still_returns_401(engine: AsyncEngine) -> None:
    async for client in _auth_client(engine, FakeRedis()):
        response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid-token"})

    assert response.status_code == 401


def _report_client(redis: FakeRedis, *, user_id: int = 1) -> httpx.AsyncClient:
    settings = get_settings()

    async def auth_user() -> User:
        return User(id=user_id, email=f"reports-{user_id}@example.com", password_hash="hash", role="beta_user", is_active=True)

    app = FastAPI()
    app.dependency_overrides[deps._resolve_current_user] = auth_user
    app.dependency_overrides[deps.get_rate_limiter] = lambda: RateLimiter(redis=redis, settings=settings)
    app.include_router(reports_api.router, prefix="/api/v1")
    transport = ASGITransport(app=app, client=("203.0.113.77", 1234))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_reports_allowed_and_limited_by_user() -> None:
    redis = FakeRedis()
    async with _report_client(redis) as client:
        responses = [
            await client.post("/api/v1/reports/valuation", json=_valuation_report_payload())
            for _ in range(21)
        ]

    assert [response.status_code for response in responses[:20]] == [200] * 20
    assert responses[-1].status_code == 429
    assert int(responses[-1].headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_distinct_report_users_have_distinct_buckets() -> None:
    redis = FakeRedis()
    async with _report_client(redis, user_id=1) as client:
        for _ in range(20):
            await client.post("/api/v1/reports/valuation", json=_valuation_report_payload())
    async with _report_client(redis, user_id=2) as client:
        response = await client.post("/api/v1/reports/valuation", json=_valuation_report_payload())

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_is_not_rate_limited_even_when_limiter_would_block(engine: AsyncEngine) -> None:
    async for client in _auth_client(engine, FakeRedis(), settings_overrides={"rate_limit_login_ip_max": 0}):
        response = await client.get("/health")

    assert response.status_code == 200


def _valuation_report_payload() -> dict[str, Any]:
    return {
        "valuation_payload": {"comuna": "Nunoa", "property_type": "apartment", "m2": 75},
        "valuation_result": {
            "estimated_price_uf": 5200,
            "estimated_price_clp": 205000000,
            "confidence": "medium",
            "confidence_label": "medium",
            "comparable_count": 1,
            "price_m2_uf": 69.3,
            "warnings": [],
            "comparables": [
                {
                    "listing_id": 10,
                    "title": "Comparable",
                    "comuna": "Nunoa",
                    "price_uf": 5100,
                    "price_clp": 201000000,
                    "m2": 74,
                    "similarity": 0.82,
                    "url": "https://example.test/comparable",
                }
            ],
        },
    }
