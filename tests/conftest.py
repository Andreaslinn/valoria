"""Fixtures globales para la suite de tests.

Estrategia: aiosqlite en memoria por test.
    · Veloz (sin I/O de disco, sin red).
    · Schema recreado fresh en cada test → aislamiento total.
    · Compatible con los modelos porque no usamos tipos Postgres-específicos.

Si en el futuro necesitamos testear features Postgres-only (JSONB queries,
triggers, funciones), agregamos tests/integration_pg/ con un docker-compose
dedicado o testcontainers.
"""
from __future__ import annotations

import os

# Las env vars requeridas por config.settings deben estar presentes antes
# de importar cualquier cosa que las use. Las tests no dependen del valor
# real porque usamos fixtures que crean su propio engine.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SYNC_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "0" * 32)

from collections.abc import AsyncGenerator  # noqa: E402

import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from infrastructure.db.base import Base  # noqa: E402

# Importar modelos para que queden registrados en Base.metadata.
import infrastructure.db.models  # noqa: E402, F401


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Engine SQLite in-memory con schema recién creado."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Sesión async aislada por test."""
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
