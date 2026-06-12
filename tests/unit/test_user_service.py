from __future__ import annotations

import pytest

from core.exceptions import ValidationError
from infrastructure.db.repositories import SqlAlchemyUserRepository
from services.users import UserService


async def test_create_user_hashes_password(session) -> None:
    service = UserService(SqlAlchemyUserRepository(session), session)

    user = await service.create_user("Beta@Example.com", "password123", "beta_user")

    assert user.email == "beta@example.com"
    assert user.password_hash != "password123"
    assert user.password_hash.startswith("$2")


async def test_authenticate_user_success(session) -> None:
    service = UserService(SqlAlchemyUserRepository(session), session)
    await service.create_user("beta@example.com", "password123", "beta_user")

    user = await service.authenticate_user("beta@example.com", "password123")

    assert user is not None
    assert user.last_login_at is not None


async def test_authenticate_user_wrong_password_fails(session) -> None:
    service = UserService(SqlAlchemyUserRepository(session), session)
    await service.create_user("beta@example.com", "password123", "beta_user")

    assert await service.authenticate_user("beta@example.com", "wrongpass") is None


async def test_inactive_user_cannot_authenticate(session) -> None:
    service = UserService(SqlAlchemyUserRepository(session), session)
    user = await service.create_user("beta@example.com", "password123", "beta_user")
    assert user.id is not None
    await service.deactivate_user(user.id)

    assert await service.authenticate_user("beta@example.com", "password123") is None


async def test_bootstrap_initial_admin_creates_once(session) -> None:
    service = UserService(SqlAlchemyUserRepository(session), session)

    first = await service.bootstrap_initial_admin("admin@example.com", "password123")
    second = await service.bootstrap_initial_admin("other@example.com", "password123")

    assert first is not None
    assert first.role == "admin"
    assert second is None


async def test_invalid_email_fails(session) -> None:
    service = UserService(SqlAlchemyUserRepository(session), session)

    with pytest.raises(ValidationError):
        await service.create_user("not-an-email", "password123", "beta_user")


async def test_short_password_fails(session) -> None:
    service = UserService(SqlAlchemyUserRepository(session), session)

    with pytest.raises(ValidationError):
        await service.create_user("beta@example.com", "short", "beta_user")
