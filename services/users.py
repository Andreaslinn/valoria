"""User management for private beta authentication."""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime

from dotenv import dotenv_values
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.security import hash_password, verify_password
from core.entities.user import Role, User
from core.exceptions import ValidationError
from infrastructure.db.repositories.user_repo import SqlAlchemyUserRepository

PUBLIC_AUTH_ERROR = "Credenciales inválidas"
MIN_PASSWORD_LENGTH = 8
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserService:
    def __init__(self, repo: SqlAlchemyUserRepository, session: AsyncSession) -> None:
        self._repo = repo
        self._session = session

    async def create_user(self, email: str, password: str, role: Role = "beta_user") -> User:
        email = validate_email(email)
        validate_password(password)
        validate_role(role)
        user = User(
            id=None,
            email=email,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        try:
            saved = await self._repo.save(user)
            await self._session.commit()
            return saved
        except IntegrityError as e:
            await self._session.rollback()
            raise ValidationError("El usuario ya existe") from e

    async def authenticate_user(self, email: str, password: str) -> User | None:
        try:
            email = validate_email(email)
        except ValidationError:
            return None
        user = await self._repo.find_by_email(email)
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None
        if user.id is not None:
            user.last_login_at = datetime.now(UTC)
            await self._repo.mark_last_login(user.id, user.last_login_at)
            await self._session.commit()
        return user

    async def find_by_email(self, email: str) -> User | None:
        return await self._repo.find_by_email(validate_email(email))

    async def list_users(self) -> list[User]:
        return await self._repo.list_users()

    async def deactivate_user(self, user_id: int) -> User:
        user = await self._get_user(user_id)
        user.is_active = False
        saved = await self._repo.save(user)
        await self._session.commit()
        return saved

    async def activate_user(self, user_id: int) -> User:
        user = await self._get_user(user_id)
        user.is_active = True
        saved = await self._repo.save(user)
        await self._session.commit()
        return saved

    async def change_password(self, user_id: int, new_password: str) -> User:
        validate_password(new_password)
        user = await self._get_user(user_id)
        user.password_hash = hash_password(new_password)
        saved = await self._repo.save(user)
        await self._session.commit()
        return saved

    async def bootstrap_initial_admin(
        self,
        admin_email: str | None = None,
        admin_password: str | None = None,
    ) -> User | None:
        if await self._repo.has_admin():
            return None
        admin_email = admin_email or _read_bootstrap_secret("ADMIN_EMAIL")
        admin_password = admin_password or _read_bootstrap_secret("ADMIN_PASSWORD")
        if not admin_email or not admin_password:
            raise ValidationError(
                "No existe admin inicial. Configura ADMIN_EMAIL y ADMIN_PASSWORD para bootstrap."
            )
        return await self.create_user(admin_email, admin_password, "admin")

    async def _get_user(self, user_id: int) -> User:
        user = await self._repo.find_by_id(user_id)
        if user is None:
            raise ValidationError("Usuario no encontrado")
        return user


def validate_email(email: str) -> str:
    cleaned = email.strip().lower()
    if not _EMAIL_RE.fullmatch(cleaned):
        raise ValidationError("Email invalido")
    return cleaned


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError("Password debe tener al menos 8 caracteres")


def validate_role(role: str) -> None:
    if role not in ("admin", "beta_user"):
        raise ValidationError("Rol invalido")


def _read_bootstrap_secret(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value.strip()
    env_value = dotenv_values(".env").get(name)
    if env_value:
        return str(env_value).strip()
    return None
