"""Watchlist endpoints."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from api.deps import CurrentUser, DbSession, UFServiceDep
from core.exceptions import UFServiceError
from core.ports.uf_service import UFRateInfo
from infrastructure.db.models import ListingORM, SavedListingORM
from services.listing_freshness import ListingFreshnessResult, ensure_listing_fresh
from services.price_display import clp_to_uf_display, uf_to_clp_display
from services.uf_rate import require_real_uf_rate

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
_log = logging.getLogger(__name__)


class WatchlistItemOut(BaseModel):
    id: int
    listing_id: int
    saved_at: datetime
    saved_price_clp: int
    saved_price_uf: float | None
    saved_price_clp_snapshot: int | None = None
    saved_price_basis: str = "legacy_unknown"
    price_data_quality: str = "legacy_unknown"
    status: str
    note: str | None
    title: str
    comuna: str
    property_type: str | None = None
    price_clp: int
    price_uf: float | None
    price_uf_display: float | None = None
    price_currency: str | None = None
    price_uf_source: str | None = None
    price_uf_confidence: str | None = None
    price_recovery_method: str | None = None
    price_clp_snapshot: int | None = None
    price_clp_display: int | None = None
    price_display_basis: str = "legacy_unknown"
    uf_rate_used_for_display: float | None = None
    uf_rate_source: str | None = None
    uf_rate_is_fallback: bool = False
    m2: float | None
    dormitorios: int
    banos: int
    estacionamientos: int
    url: str | None
    source: str
    listing_status: str
    captured_at: datetime
    freshness_status: str | None = None
    last_seen_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    last_refresh_status: str | None = None
    freshness_note: str | None = None
    refresh_attempted: bool = False
    refresh_result: dict | None = None


class WatchlistStatusOut(BaseModel):
    listing_id: int
    saved: bool
    status: str | None = None


@router.get("", response_model=list[WatchlistItemOut])
async def list_watchlist(
    current_user: CurrentUser,
    session: DbSession,
    uf_service: UFServiceDep,
) -> list[WatchlistItemOut]:
    assert current_user.id is not None
    stmt = (
        select(SavedListingORM)
        .options(joinedload(SavedListingORM.listing))
        .where(
            SavedListingORM.user_id == current_user.id,
            SavedListingORM.status == "active",
        )
        .order_by(SavedListingORM.saved_at.desc())
    )
    items = (await session.execute(stmt)).scalars().all()
    uf_info = await _require_api_uf_info(uf_service)
    return [_watchlist_out(item, uf_info=uf_info) for item in items]


@router.post("/{listing_id}", response_model=WatchlistItemOut, status_code=status.HTTP_201_CREATED)
async def save_to_watchlist(
    listing_id: int,
    current_user: CurrentUser,
    session: DbSession,
    uf_service: UFServiceDep,
) -> WatchlistItemOut:
    assert current_user.id is not None
    listing = await session.get(ListingORM, listing_id)
    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Listing no encontrado",
        )

    freshness = await _maybe_ensure_watchlist_freshness(
        listing_id,
        session=session,
        uf_service=uf_service,
    )
    await session.refresh(listing)

    existing = await _find_saved(session, current_user.id, listing_id)
    saved_price_uf = _canonical_price_uf(listing)
    if existing is not None:
        if existing.status != "active":
            existing.status = "active"
            existing.saved_at = datetime.now(UTC)
            existing.saved_price_clp = listing.price_clp
            existing.saved_price_uf = saved_price_uf
        await session.commit()
        loaded = await _load_saved(session, existing.id)
        assert loaded is not None
        uf_info = await _require_api_uf_info(uf_service)
        return _watchlist_out(loaded, uf_info=uf_info, freshness=freshness)

    saved = SavedListingORM(
        user_id=current_user.id,
        listing_id=listing.id,
        saved_price_clp=listing.price_clp,
        saved_price_uf=saved_price_uf,
        status="active",
    )
    session.add(saved)
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        _log.exception("Error saving listing id=%s to watchlist", listing_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo guardar en watchlist",
        ) from e
    loaded = await _load_saved(session, saved.id)
    assert loaded is not None
    uf_info = await _require_api_uf_info(uf_service)
    return _watchlist_out(loaded, uf_info=uf_info, freshness=freshness)


@router.delete("/{listing_id}", response_model=WatchlistStatusOut)
async def remove_from_watchlist(
    listing_id: int,
    current_user: CurrentUser,
    session: DbSession,
) -> WatchlistStatusOut:
    assert current_user.id is not None
    saved = await _find_saved(session, current_user.id, listing_id)
    if saved is None or saved.status != "active":
        return WatchlistStatusOut(listing_id=listing_id, saved=False, status=None)
    saved.status = "removed"
    await session.commit()
    return WatchlistStatusOut(listing_id=listing_id, saved=False, status="removed")


@router.get("/{listing_id}/status", response_model=WatchlistStatusOut)
async def watchlist_status(
    listing_id: int,
    current_user: CurrentUser,
    session: DbSession,
) -> WatchlistStatusOut:
    assert current_user.id is not None
    saved = await _find_saved(session, current_user.id, listing_id)
    is_saved = saved is not None and saved.status == "active"
    return WatchlistStatusOut(
        listing_id=listing_id,
        saved=is_saved,
        status=saved.status if saved else None,
    )


async def _find_saved(
    session: DbSession,
    user_id: int,
    listing_id: int,
) -> SavedListingORM | None:
    stmt = select(SavedListingORM).where(
        SavedListingORM.user_id == user_id,
        SavedListingORM.listing_id == listing_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _load_saved(session: DbSession, saved_id: int) -> SavedListingORM | None:
    stmt = (
        select(SavedListingORM)
        .options(joinedload(SavedListingORM.listing))
        .where(SavedListingORM.id == saved_id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _require_api_uf_info(uf_service) -> UFRateInfo:
    try:
        return await require_real_uf_rate(uf_service)
    except UFServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="UF real no disponible",
        ) from e


async def _maybe_ensure_watchlist_freshness(
    listing_id: int,
    *,
    session: DbSession,
    uf_service,
) -> ListingFreshnessResult:
    try:
        return await ensure_listing_fresh(
            listing_id,
            reason="watchlist_save",
            session_factory=_request_session_factory(session),
            uf_service=uf_service,
        )
    except Exception as exc:
        _log.warning("watchlist freshness check failed listing_id=%s error=%s", listing_id, exc)
        return ListingFreshnessResult(
            status="refresh_failed",
            listing_id=listing_id,
            reason="watchlist_save",
            refresh_attempted=True,
            freshness_note="freshness_helper_failed",
        )


def _request_session_factory(session: DbSession) -> async_sessionmaker[AsyncSession]:
    bind = session.bind or session.get_bind()
    return async_sessionmaker(bind=bind, expire_on_commit=False, class_=AsyncSession)


def _watchlist_out(
    saved: SavedListingORM,
    *,
    uf_info: UFRateInfo,
    freshness: ListingFreshnessResult | None = None,
) -> WatchlistItemOut:
    listing = saved.listing
    saved_price_basis = _saved_price_basis(saved, listing)
    saved_price_uf = saved.saved_price_uf if saved_price_basis == "canonical_uf" else None
    canonical_price_uf = _canonical_price_uf(listing)
    return WatchlistItemOut(
        id=saved.id,
        listing_id=saved.listing_id,
        saved_at=saved.saved_at,
        saved_price_clp=int(saved.saved_price_clp),
        saved_price_uf=float(saved_price_uf) if saved_price_uf is not None else None,
        saved_price_clp_snapshot=int(saved.saved_price_clp),
        saved_price_basis=saved_price_basis,
        price_data_quality=_price_data_quality(listing),
        status=saved.status,
        note=saved.note,
        title=listing.title,
        comuna=listing.comuna,
        property_type=listing.property_type,
        price_clp=int(listing.price_clp),
        price_uf=float(canonical_price_uf) if canonical_price_uf is not None else None,
        price_uf_display=_price_uf_display(listing, canonical_price_uf=canonical_price_uf, uf_info=uf_info),
        price_currency=listing.price_currency,
        price_uf_source=listing.price_uf_source,
        price_uf_confidence=listing.price_uf_confidence,
        price_recovery_method=listing.price_recovery_method,
        price_clp_snapshot=int(listing.price_clp),
        price_clp_display=_price_clp_display(listing, canonical_price_uf=canonical_price_uf, uf_info=uf_info),
        price_display_basis=_price_display_basis(listing),
        uf_rate_used_for_display=float(uf_info.rate),
        uf_rate_source=uf_info.source,
        uf_rate_is_fallback=uf_info.is_fallback,
        m2=listing.m2,
        dormitorios=listing.bedrooms,
        banos=listing.bathrooms,
        estacionamientos=listing.parking,
        url=listing.url,
        source=listing.source,
        listing_status=listing.status,
        captured_at=listing.scraped_at,
        freshness_status=freshness.status if freshness is not None else None,
        last_seen_at=freshness.last_seen_at if freshness is not None else None,
        last_refreshed_at=freshness.last_refreshed_at if freshness is not None else None,
        last_refresh_status=freshness.last_refresh_status if freshness is not None else None,
        freshness_note=freshness.freshness_note if freshness is not None else None,
        refresh_attempted=freshness.refresh_attempted if freshness is not None else False,
        refresh_result=freshness.to_dict() if freshness is not None else None,
    )


def _canonical_price_uf(listing: ListingORM) -> Decimal | None:
    currency = str(listing.price_currency or "").strip().upper()
    if currency != "UF":
        return None
    return listing.price_uf


def _saved_price_basis(saved: SavedListingORM, listing: ListingORM) -> str:
    if saved.saved_price_uf is not None and _canonical_price_uf(listing) is not None:
        return "canonical_uf"
    currency = str(listing.price_currency or "").strip().upper()
    if currency == "CLP":
        return "canonical_clp"
    if currency == "UF":
        return "legacy_uf_missing_price_uf"
    return "legacy_unknown"


def _price_display_basis(listing: ListingORM) -> str:
    currency = str(listing.price_currency or "").strip().upper()
    if currency == "UF" and listing.price_uf is not None:
        return "canonical_uf"
    if currency == "CLP":
        return "canonical_clp"
    if currency == "UF":
        return "legacy_uf_missing_price_uf"
    return "legacy_unknown"


def _price_uf_display(
    listing: ListingORM,
    *,
    canonical_price_uf: Decimal | None,
    uf_info: UFRateInfo,
) -> float | None:
    if canonical_price_uf is not None:
        return float(canonical_price_uf)
    return clp_to_uf_display(listing.price_clp, uf_info.rate)


def _price_clp_display(
    listing: ListingORM,
    *,
    canonical_price_uf: Decimal | None,
    uf_info: UFRateInfo,
) -> int | None:
    if canonical_price_uf is not None:
        return uf_to_clp_display(canonical_price_uf, uf_info.rate)
    return int(listing.price_clp)


def _price_data_quality(listing: ListingORM) -> str:
    currency = str(listing.price_currency or "").strip().upper()
    if currency == "UF":
        if listing.price_uf is None:
            return "legacy_unrecoverable"
        return str(listing.price_uf_source or listing.price_uf_confidence or "canonical_uf")
    if currency == "CLP":
        return "canonical_clp"
    return "legacy_unknown_currency"
