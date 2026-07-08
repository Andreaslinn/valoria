"""Engine asincrono + session factory.

El engine se crea de forma perezosa (lazy) la primera vez que se solicita.
Esto permite que los tests sustituyan su propia DB sin que el modulo falle
al importarse por un .env ausente o invalido.

Uso tipico en FastAPI:

    from fastapi import Depends
    from sqlalchemy.ext.asyncio import AsyncSession
    from infrastructure.db import get_db

    @router.get("/x")
    async def handler(db: AsyncSession = Depends(get_db)):
        ...
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Engine cacheado (singleton). Creado en el primer uso."""
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=(settings.log_level == "DEBUG"),
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        get_engine(),
        expire_on_commit=False,
        class_=AsyncSession,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia FastAPI: abre una sesion, rollback automatico en excepcion.

    El commit queda a cargo del caller (casos de uso / servicios), que saben
    cuando la unidad de trabajo esta completa.
    """
    async with get_session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


