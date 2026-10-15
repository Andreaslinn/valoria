"""Tests de integración de los endpoints de autenticación.

Estrategia:
    · App FastAPI real + httpx AsyncClient.
    · La dependencia `get_db` se sobrescribe para apuntar al session factory
      del fixture (SQLite in-memory), de modo que los tests corren aislados.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from api.main import create_app
from api.security import hash_password, verify_password
from api.v1 import health as health_router
from config import get_settings
from core.entities.user import User
from infrastructure.db.database import get_db
from infrastructure.db.repositories import SqlAlchemyUserRepository


@pytest_asyncio.fixture
async def client(
    engine: AsyncEngine,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

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


@asynccontextmanager
async def _client_with_signup(
    engine: AsyncEngine,
    *,
    enabled: bool,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as s:
            try:
                yield s
            except Exception:
                await s.rollback()
                raise

    app = create_app()
    app.dependency_overrides[get_db] = _get_db_override
    settings = get_settings().model_copy(update={"beta_signup_enabled": enabled})
    app.dependency_overrides[get_settings] = lambda: settings

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def admin_user(engine: AsyncEngine) -> User:
    """Crea un admin persistido en la DB de test."""
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with session_factory() as s:
        repo = SqlAlchemyUserRepository(s)
        user = User(
            id=None,
            email="andy@example.com",
            password_hash=hash_password("passwordsegura123"),
            role="admin",
            is_active=True,
        )
        saved = await repo.save(user)
        await s.commit()
        return saved


# ─────────────────────────────────────────────────────────
#  Health
# ─────────────────────────────────────────────────────────
class TestHealth:
    async def test_health_no_auth_required(self, client: httpx.AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["liveness"] == "ok"
        assert resp.json()["status"] in {"ok", "degraded"}

        versioned_resp = await client.get("/api/v1/health")
        assert versioned_resp.status_code == 200
        assert versioned_resp.json() == {"status": "ok"}

    async def test_full_health_requires_auth(self, client: httpx.AsyncClient):
        resp = await client.get("/api/v1/health/full")

        assert resp.status_code in {401, 403}

    async def test_full_health_with_admin_auth_returns_200(
        self,
        client: httpx.AsyncClient,
        admin_user: User,
        monkeypatch,
    ):
        async def fake_run_all_checks() -> list[dict]:
            return [{"name": "db", "status": "OK", "message": "ok", "details": {}}]

        monkeypatch.setattr(health_router, "run_all_checks", fake_run_all_checks)

        login = await client.post(
            "/api/v1/auth/login",
            data={"username": admin_user.email, "password": "passwordsegura123"},
        )
        assert login.status_code == 200

        resp = await client.get(
            "/api/v1/health/full",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "OK"


# ─────────────────────────────────────────────────────────
#  POST /api/v1/auth/login
# ─────────────────────────────────────────────────────────
class TestLogin:
    async def test_valid_credentials_return_token(
        self, client: httpx.AsyncClient, admin_user: User
    ):
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "andy@example.com", "password": "passwordsegura123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0
        assert len(body["access_token"]) > 20

    async def test_wrong_password_returns_401(
        self, client: httpx.AsyncClient, admin_user: User
    ):
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "andy@example.com", "password": "mala"},
        )
        assert resp.status_code == 401

    async def test_unknown_user_returns_401(self, client: httpx.AsyncClient):
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "fantasma@example.com", "password": "cualquiera"},
        )
        assert resp.status_code == 401

    async def test_inactive_user_returns_403(
        self, client: httpx.AsyncClient, engine: AsyncEngine
    ):
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as s:
            repo = SqlAlchemyUserRepository(s)
            user = User(
                id=None,
                email="inactivo@example.com",
                password_hash=hash_password("passwordsegura123"),
                role="beta_user",
                is_active=False,
            )
            await repo.save(user)
            await s.commit()

        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "inactivo@example.com", "password": "passwordsegura123"},
        )
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────
#  GET /api/v1/auth/me
# ─────────────────────────────────────────────────────────
class TestRegister:
    async def test_signup_disabled_returns_403(self, engine: AsyncEngine):
        async with _client_with_signup(engine, enabled=False) as client:
            resp = await client.post(
                "/api/v1/auth/register",
                json={"email": "beta@example.com", "password": "passwordsegura123"},
            )

        assert resp.status_code == 403

    async def test_signup_enabled_creates_normal_user_that_can_login(
        self,
        engine: AsyncEngine,
    ):
        async with _client_with_signup(engine, enabled=True) as client:
            resp = await client.post(
                "/api/v1/auth/register",
                json={"email": "  Beta.User@Example.com  ", "password": "passwordsegura123"},
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["email"] == "beta.user@example.com"
            assert body["role"] == "beta_user"
            assert body["is_active"] is True
            assert "password" not in body
            assert "password_hash" not in body

            duplicate = await client.post(
                "/api/v1/auth/register",
                json={"email": "beta.user@example.com", "password": "passwordsegura123"},
            )
            assert duplicate.status_code == 409

            login = await client.post(
                "/api/v1/auth/login",
                data={"username": "beta.user@example.com", "password": "passwordsegura123"},
            )
            assert login.status_code == 200

            me = await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            )
            assert me.status_code == 200
            assert me.json()["role"] == "beta_user"

        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as s:
            user = await SqlAlchemyUserRepository(s).find_by_email("beta.user@example.com")

        assert user is not None
        assert user.is_admin is False
        assert user.password_hash != "passwordsegura123"
        assert user.password_hash.startswith("$2")
        assert verify_password("passwordsegura123", user.password_hash)

    async def test_signup_rejects_short_password(self, engine: AsyncEngine):
        async with _client_with_signup(engine, enabled=True) as client:
            resp = await client.post(
                "/api/v1/auth/register",
                json={"email": "beta@example.com", "password": "short"},
            )

        assert resp.status_code == 400


class TestMe:
    async def test_without_token_returns_401(self, client: httpx.AsyncClient):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_with_valid_token_returns_user(
        self, client: httpx.AsyncClient, admin_user: User
    ):
        login = await client.post(
            "/api/v1/auth/login",
            data={"username": "andy@example.com", "password": "passwordsegura123"},
        )
        token = login.json()["access_token"]

        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "andy@example.com"
        assert body["role"] == "admin"
        assert body["is_active"] is True

    async def test_garbage_token_returns_401(self, client: httpx.AsyncClient):
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer definitely-not-a-jwt"},
        )
        assert resp.status_code == 401

    async def test_token_for_deleted_user_returns_401(
        self, client: httpx.AsyncClient, admin_user: User, engine: AsyncEngine
    ):
        """Si un usuario válido se desactiva después de emitir el token,
        la request subsiguiente debe fallar — no basta con firma válida."""
        login = await client.post(
            "/api/v1/auth/login",
            data={"username": "andy@example.com", "password": "passwordsegura123"},
        )
        token = login.json()["access_token"]

        # Desactivar al usuario
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as s:
            repo = SqlAlchemyUserRepository(s)
            u = await repo.find_by_email("andy@example.com")
            assert u is not None
            u.is_active = False
            await repo.save(u)
            await s.commit()

        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────
#  Password hashing — no re-hashea el mismo plaintext al mismo hash
# ─────────────────────────────────────────────────────────
class TestBcryptBehavior:
    def test_same_password_different_hashes(self):
        """bcrypt usa salt aleatorio; dos hashes del mismo password difieren."""
        from api.security import hash_password, verify_password

        h1 = hash_password("mismostring")
        h2 = hash_password("mismostring")
        assert h1 != h2
        assert verify_password("mismostring", h1)
        assert verify_password("mismostring", h2)

    def test_verify_rejects_wrong_password(self):
        from api.security import hash_password, verify_password

        h = hash_password("correcto")
        assert verify_password("correcto", h)
        assert not verify_password("incorrecto", h)

    def test_verify_corrupt_hash_returns_false(self):
        from api.security import verify_password

        # No explota — falla seguro.
        assert verify_password("algo", "definitely-not-a-bcrypt-hash") is False
