"""FastAPI app factory.

Arrancar en desarrollo:
    uvicorn api.main:app --reload

En producción:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import close_external_clients
from api.v1 import alerts as alerts_router
from api.v1 import auth as auth_router
from api.v1 import future_features as future_features_router
from api.v1 import health as health_router
from api.v1 import listings as listings_router
from api.v1 import market as market_router
from api.v1 import patrimony as patrimony_router
from api.v1 import portfolio as portfolio_router
from api.v1 import radar as radar_router
from api.v1 import reports as reports_router
from api.v1 import tasar as tasar_router
from api.v1 import thumbnails as thumbnails_router
from api.v1 import usage as usage_router
from api.v1 import users as users_router
from api.v1 import valuations as valuations_router
from api.v1 import watchlist as watchlist_router
from config import get_settings
from core.exceptions import ValidationError
from infrastructure.db.database import get_session_factory
from infrastructure.db.repositories import SqlAlchemyUserRepository
from services.thumbnails import close_store
from services.users import UserService

_log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    if os.getenv("VALORIA_ENFORCE_RELEASE_MANIFEST") == "1":
        from services.release_guard import verify_release_tree
        verify_release_tree(Path(__file__).resolve().parents[1])
    settings = get_settings()
    _log.info("AVM API iniciada en entorno=%s", settings.environment)
    await _bootstrap_initial_admin()
    try:
        yield
    finally:
        await close_store()
        await close_external_clients()
        _log.info("AVM API apagada")


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging(settings.log_level)
    app = FastAPI(
        title="AVM — Automated Valuation Model",
        description="API para tasación y detección de oportunidades en el mercado inmobiliario chileno.",
        version="0.1.0",
        lifespan=_lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )
    _configure_cors(app, settings.backend_cors_origin_list)

    # Routers v1
    app.include_router(auth_router.router, prefix="/api/v1")
    app.include_router(health_router.router, prefix="/api/v1")
    app.include_router(listings_router.router, prefix="/api/v1")
    app.include_router(market_router.router, prefix="/api/v1")
    app.include_router(valuations_router.router, prefix="/api/v1")
    app.include_router(radar_router.router, prefix="/api/v1")
    app.include_router(reports_router.router, prefix="/api/v1")
    app.include_router(tasar_router.router, prefix="/api/v1")
    app.include_router(patrimony_router.router, prefix="/api/v1")
    app.include_router(portfolio_router.router, prefix="/api/v1")
    app.include_router(watchlist_router.router, prefix="/api/v1")
    app.include_router(alerts_router.router, prefix="/api/v1")
    app.include_router(usage_router.router, prefix="/api/v1")
    app.include_router(users_router.router, prefix="/api/v1")
    app.include_router(future_features_router.router, prefix="/api/v1")
    app.include_router(thumbnails_router.router, prefix="/api/v1")

    # Healthcheck simple — no autenticado
    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        state = await health_router.source_health()
        result = {"status": state["status"], "liveness": "ok", "ingestion": state,
                  "sources": state.get("sources", {})}
        from services.sii.settings import enabled
        if enabled():
            import asyncio
            from services.sii.reporting import health as sii_health
            try:
                result["sii"] = await asyncio.to_thread(sii_health)
            except Exception as exc:
                result["sii"] = {"enabled": True, "status": "degraded", "error": type(exc).__name__}
        return result

    return app


def _configure_cors(app: FastAPI, allowed_origins: tuple[str, ...]) -> None:
    if not allowed_origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


def _configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def _bootstrap_initial_admin() -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = UserService(SqlAlchemyUserRepository(session), session)
        try:
            created = await service.bootstrap_initial_admin()
        except ValidationError as e:
            await session.rollback()
            _log.warning("%s", e)
            return
        if created is not None:
            _log.info("Admin inicial creado: %s", created.email)


# Instancia para `uvicorn api.main:app`
app = create_app()
