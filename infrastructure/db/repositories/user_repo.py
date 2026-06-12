"""Repositorio SQLAlchemy para usuarios."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.entities.user import Role, User
from core.exceptions import AVMError
from core.ports.user_repo import UserRepository
from infrastructure.db.models import UserORM


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_username(self, username: str) -> User | None:
        return await self.find_by_email(username)

    async def find_by_email(self, email: str) -> User | None:
        stmt = select(UserORM).where(UserORM.email == _normalize_email(email))
        orm = (await self._session.execute(stmt)).scalar_one_or_none()
        return _from_orm(orm) if orm else None

    async def find_by_id(self, user_id: int) -> User | None:
        orm = await self._session.get(UserORM, user_id)
        return _from_orm(orm) if orm else None

    async def list_users(self) -> list[User]:
        stmt = select(UserORM).order_by(UserORM.created_at.desc(), UserORM.id.desc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_from_orm(orm) for orm in rows]

    async def has_admin(self) -> bool:
        stmt = select(UserORM.id).where(UserORM.role == "admin").limit(1)
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def save(self, user: User) -> User:
        if user.id is None:
            orm = UserORM(
                email=_normalize_email(user.email),
                password_hash=user.password_hash,
                role=user.role,
                is_active=user.is_active,
                last_login_at=user.last_login_at,
            )
            self._session.add(orm)
            await self._session.flush()
            await self._session.refresh(orm)
            return _from_orm(orm)

        orm = await self._session.get(UserORM, user.id)
        if orm is None:
            raise AVMError(f"User id={user.id} no existe")
        orm.email = _normalize_email(user.email)
        orm.password_hash = user.password_hash
        orm.role = user.role
        orm.is_active = user.is_active
        orm.last_login_at = user.last_login_at
        await self._session.flush()
        return _from_orm(orm)

    async def mark_last_login(self, user_id: int, when: datetime) -> None:
        orm = await self._session.get(UserORM, user_id)
        if orm is None:
            raise AVMError(f"User id={user_id} no existe")
        orm.last_login_at = when
        await self._session.flush()


def _from_orm(orm: UserORM) -> User:
    return User(
        id=orm.id,
        email=orm.email,
        password_hash=orm.password_hash,
        role=_coerce_role(orm.role),
        is_active=orm.is_active,
        created_at=orm.created_at,
        last_login_at=orm.last_login_at,
    )


def _coerce_role(raw: str) -> Role:
    if raw in ("admin", "beta_user"):
        return raw  # type: ignore[return-value]
    return "beta_user"


def _normalize_email(email: str) -> str:
    return email.strip().lower()
