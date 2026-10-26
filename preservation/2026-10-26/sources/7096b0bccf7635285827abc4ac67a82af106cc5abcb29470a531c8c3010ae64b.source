"""Inyeccion de dependencias para los endpoints FastAPI.

Usos tipicos:

    from fastapi import Depends
    from api.deps import CurrentUser, DbSession

    @router.get("/me")
    async def me(user: CurrentUser) -> UserOut:
        return UserOut.from_entity(user)

    @router.get("/items")
    async def list_items(db: DbSession) -> list[Item]:
        ...

`CurrentUser` exige que la request venga con un JWT valido; si no, 401.
"""
from __future__ import annotations

import logging
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.security import TokenError, decode_token
from config import Settings, get_settings
from core.entities.user import User
from core.ports.listing_repo import ListingRepository
from core.ports.uf_service import UFService
from core.ports.user_repo import UserRepository
from infrastructure.db.database import get_db, get_session_factory
from infrastructure.db.repositories import (
    SqlAlchemyListingRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.external.uf_client import UFClient
from services.listings import ListingService
from services.portfolio import PortfolioService
from services.portfolio_comparisons import PortfolioComparisonService
from services.portfolio_snapshots import PortfolioSnapshotService
from services.radar import RadarService
from services.users import UserService
from services.valuation import ValuationService

# El token viaja en `Authorization: Bearer <token>`. tokenUrl es la ruta del
# endpoint de login - FastAPI la usa para el boton "Authorize" en /docs.
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
_log = logging.getLogger(__name__)

_uf_http_client: httpx.AsyncClient | None = None
_uf_redis_client: Redis | None = None


# ------------------------------------------------------------
#  Dependencias primitivas
# ------------------------------------------------------------
DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_user_repo(session: DbSession) -> UserRepository:
    return SqlAlchemyUserRepository(session)


UserRepoDep = Annotated[UserRepository, Depends(get_user_repo)]


def get_user_service(session: DbSession) -> UserService:
    return UserService(SqlAlchemyUserRepository(session), session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


def get_listing_repo(session: DbSession) -> ListingRepository:
    return SqlAlchemyListingRepository(session)


ListingRepoDep = Annotated[ListingRepository, Depends(get_listing_repo)]


def _get_uf_http_client() -> httpx.AsyncClient:
    global _uf_http_client
    if _uf_http_client is None or _uf_http_client.is_closed:
        _uf_http_client = httpx.AsyncClient()
    return _uf_http_client


def _get_uf_redis_client(settings: Settings) -> Redis | None:
    global _uf_redis_client
    if not settings.redis_enabled or not settings.redis_url:
        return None
    if _uf_redis_client is None:
        _uf_redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _uf_redis_client


def get_uf_service(settings: AppSettings) -> UFService:
    return UFClient(
        api_url=settings.uf_api_url,
        http_client=_get_uf_http_client(),
        redis=_get_uf_redis_client(settings),
        cache_ttl=settings.uf_cache_ttl_hours * 60 * 60,
        max_staleness_days=settings.uf_max_staleness_days,
        allow_stale_on_failure=settings.uf_allow_stale_on_failure,
        session_factory=get_session_factory(),
    )


async def close_external_clients() -> None:
    global _uf_http_client, _uf_redis_client
    if _uf_http_client is not None and not _uf_http_client.is_closed:
        await _uf_http_client.aclose()
        _uf_http_client = None
    if _uf_redis_client is not None:
        try:
            await _uf_redis_client.aclose()
        except Exception as e:
            _log.warning("Redis UF close failed: %s", e)
        finally:
            _uf_redis_client = None


UFServiceDep = Annotated[UFService, Depends(get_uf_service)]


def get_listing_service(listing_repo: ListingRepoDep) -> ListingService:
    return ListingService(listing_repo)


ListingServiceDep = Annotated[ListingService, Depends(get_listing_service)]


def get_valuation_service(
    listing_repo: ListingRepoDep,
    uf_service: UFServiceDep,
) -> ValuationService:
    return ValuationService(listing_repo=listing_repo, uf_service=uf_service)


ValuationServiceDep = Annotated[ValuationService, Depends(get_valuation_service)]


def get_radar_service(
    listing_repo: ListingRepoDep,
    uf_service: UFServiceDep,
) -> RadarService:
    return RadarService(listing_repo=listing_repo, uf_service=uf_service)


RadarServiceDep = Annotated[RadarService, Depends(get_radar_service)]


def get_portfolio_service(session: DbSession) -> PortfolioService:
    return PortfolioService(session)


PortfolioServiceDep = Annotated[PortfolioService, Depends(get_portfolio_service)]


def get_portfolio_comparison_service(session: DbSession) -> PortfolioComparisonService:
    return PortfolioComparisonService(session)


PortfolioComparisonServiceDep = Annotated[
    PortfolioComparisonService,
    Depends(get_portfolio_comparison_service),
]


def get_portfolio_snapshot_service(
    session: DbSession,
    valuation_service: ValuationServiceDep,
) -> PortfolioSnapshotService:
    return PortfolioSnapshotService(session, valuation_service)


PortfolioSnapshotServiceDep = Annotated[
    PortfolioSnapshotService,
    Depends(get_portfolio_snapshot_service),
]


# ------------------------------------------------------------
#  Autenticacion - resuelve User desde el JWT
# ------------------------------------------------------------
async def _resolve_current_user(
    token: Annotated[str, Depends(_oauth2_scheme)],
    settings: AppSettings,
    user_repo: UserRepoDep,
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales invalidas o token expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token, settings)
    except TokenError as e:
        raise credentials_exc from e

    email = payload.get("sub")
    if not isinstance(email, str):
        raise credentials_exc

    user = await user_repo.find_by_username(email)
    if user is None or not user.is_active:
        raise credentials_exc
    return user


CurrentUser = Annotated[User, Depends(_resolve_current_user)]


async def _require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol admin",
        )
    return user


CurrentAdmin = Annotated[User, Depends(_require_admin)]

