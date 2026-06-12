"""Listing endpoints."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from api.deps import CurrentUser, DbSession, ListingServiceDep, UFServiceDep
from core.ports.uf_service import UFRateInfo
from core.entities.listing import Listing
from core.exceptions import ListingNotFoundError, UFServiceError
from infrastructure.db.repositories import SqlAlchemyPriceHistoryRepository
from infrastructure.db.repositories.price_history_repo import PriceSeriesPoint
from services.formatting import price_clp_int
from services.listing_url_lookup import lookup_listing_url
from services.price_display import clp_to_uf_display, uf_to_clp_display
from services.uf_rate import require_real_uf_rate

router = APIRouter(prefix="/listings", tags=["listings"])
_log = logging.getLogger(__name__)


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None
    title: str
    comuna: str
    price_uf: float | None
    price_uf_display: float | None = None
    price_clp: int
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
    property_type: str | None = None
    built_area_m2: float | None = None
    land_area_m2: float | None = None
    usable_area_m2: float | None = None
    dormitorios: int
    banos: int
    estacionamientos: int
    url: str | None
    source: str
    status: str
    captured_at: datetime
    created_at: datetime | None = None


class ListingUrlLookupRequest(BaseModel):
    url: str


class ListingUrlLookupResponse(BaseModel):
    status: str
    listing_data: dict[str, Any]
    warnings: list[str]
    source: str | None
    url: str


class PriceHistoryPointOut(BaseModel):
    observed_at: datetime
    price_clp: int
    price_uf: float | None = None
    price_clp_snapshot: int | None = None
    price_currency: str | None = None
    change_basis: str | None = None
    is_artifact: bool = False
    artifact_reason: str | None = None
    source: str | None = None
    source_url: str | None = None
    point_type: str


class ListingPriceHistoryOut(BaseModel):
    listing_id: int
    points: list[PriceHistoryPointOut]


@router.get("", response_model=list[ListingOut])
async def list_listings(
    _current_user: CurrentUser,
    service: ListingServiceDep,
    uf_service: UFServiceDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    comuna: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[ListingOut]:
    try:
        listings = await service.list_listings(
            limit=limit,
            offset=offset,
            comuna=comuna,
            status=status_filter,
        )
    except Exception as e:
        _log.exception("Error listing properties")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error inesperado al listar publicaciones",
        ) from e
    uf_info = await _require_api_uf_info(uf_service)
    return [_listing_out(listing, uf_info=uf_info) for listing in listings]


@router.post("/lookup-url", response_model=ListingUrlLookupResponse)
async def lookup_url(
    payload: ListingUrlLookupRequest,
    _current_user: CurrentUser,
) -> ListingUrlLookupResponse:
    url = payload.url.strip()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL requerida",
        )

    try:
        result = await lookup_listing_url(url)
    except Exception as e:
        _log.exception("Unexpected listing URL lookup error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error inesperado al analizar la URL",
        ) from e

    if result.status == "invalid_url":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL invalida",
        )
    if result.status == "unsupported_source":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fuente aun no soportada",
        )
    if result.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo parsear la publicacion",
        )

    return ListingUrlLookupResponse.model_validate(result.to_dict())


@router.get("/{listing_id}/price-history", response_model=ListingPriceHistoryOut)
async def get_listing_price_history(
    listing_id: int,
    _current_user: CurrentUser,
    service: ListingServiceDep,
    session: DbSession,
    include_artifacts: bool = Query(default=False),
) -> ListingPriceHistoryOut:
    try:
        listing = await service.get_listing(listing_id)
    except ListingNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Listing no encontrado",
        ) from e
    except Exception as e:
        _log.exception("Error checking listing id=%s before price history", listing_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error inesperado al obtener historial de precios",
        ) from e

    assert listing.id is not None
    series = await SqlAlchemyPriceHistoryRepository(session).get_price_series_for_listing(listing.id)
    if not include_artifacts:
        series = [point for point in series if not point.is_artifact]
    return ListingPriceHistoryOut(
        listing_id=listing.id,
        points=[_price_history_point_out(point) for point in series],
    )


@router.get("/{listing_id}", response_model=ListingOut)
async def get_listing(
    listing_id: int,
    _current_user: CurrentUser,
    service: ListingServiceDep,
    uf_service: UFServiceDep,
) -> ListingOut:
    try:
        listing = await service.get_listing(listing_id)
    except ListingNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Listing no encontrado",
        ) from e
    except Exception as e:
        _log.exception("Error getting listing id=%s", listing_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error inesperado al obtener publicacion",
        ) from e
    uf_info = await _require_api_uf_info(uf_service)
    return _listing_out(listing, uf_info=uf_info)


async def _require_api_uf_info(uf_service) -> UFRateInfo:
    try:
        return await require_real_uf_rate(uf_service)
    except UFServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="UF real no disponible",
        ) from e


def _price_history_point_out(point: PriceSeriesPoint) -> PriceHistoryPointOut:
    return PriceHistoryPointOut(
        observed_at=_api_datetime(point.observed_at),
        price_clp=int(point.price_clp),
        price_uf=float(point.price_uf) if point.price_uf is not None else None,
        price_clp_snapshot=int(point.price_clp),
        price_currency=point.price_currency,
        change_basis=point.change_basis,
        is_artifact=point.is_artifact,
        artifact_reason=point.artifact_reason,
        source=point.source,
        source_url=point.source_url,
        point_type=point.point_type,
    )


def _api_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _listing_out(listing: Listing, *, uf_info: UFRateInfo) -> ListingOut:
    price_clp = price_clp_int(listing.price)
    canonical_price_uf = _canonical_price_uf(listing)
    return ListingOut(
        id=listing.id,
        title=listing.title,
        comuna=listing.comuna,
        price_uf=canonical_price_uf,
        price_uf_display=_price_uf_display(listing, uf_info=uf_info),
        price_clp=price_clp,
        price_currency=listing.price_currency,
        price_uf_source=listing.price_uf_source,
        price_uf_confidence=listing.price_uf_confidence,
        price_recovery_method=listing.price_recovery_method,
        price_clp_snapshot=price_clp,
        price_clp_display=_price_clp_display(listing, canonical_price_uf=canonical_price_uf, uf_info=uf_info),
        price_display_basis=_price_display_basis(listing, canonical_price_uf=canonical_price_uf),
        uf_rate_used_for_display=float(uf_info.rate),
        uf_rate_source=uf_info.source,
        uf_rate_is_fallback=uf_info.is_fallback,
        m2=listing.m2,
        property_type=listing.property_type,
        built_area_m2=listing.built_area_m2,
        land_area_m2=listing.land_area_m2,
        usable_area_m2=listing.usable_area_m2,
        dormitorios=listing.bedrooms,
        banos=listing.bathrooms,
        estacionamientos=listing.parking,
        url=listing.url,
        source=listing.source,
        status=listing.status,
        captured_at=listing.scraped_at,
        created_at=None,
    )


def _canonical_price_uf(listing: Listing) -> float | None:
    if listing.price_uf is None:
        return None
    currency = (listing.price_currency or "").strip().upper()
    if currency == "UF" or listing.price_uf_source in {
        "scraped",
        "recovered_exact",
        "recovered_high_confidence",
        "estimated",
    }:
        return float(listing.price_uf)
    return None


def _price_uf_display(listing: Listing, *, uf_info: UFRateInfo) -> float | None:
    canonical = _canonical_price_uf(listing)
    if canonical is not None:
        return canonical
    return clp_to_uf_display(listing.price.clp, uf_info.rate)


def _price_clp_display(
    listing: Listing,
    *,
    canonical_price_uf: float | None,
    uf_info: UFRateInfo,
) -> int | None:
    if canonical_price_uf is not None:
        return uf_to_clp_display(canonical_price_uf, uf_info.rate)
    return price_clp_int(listing.price)


def _price_display_basis(listing: Listing, *, canonical_price_uf: float | None) -> str:
    currency = (listing.price_currency or "").strip().upper()
    if currency == "UF" and canonical_price_uf is not None:
        return "canonical_uf"
    if currency == "CLP":
        return "canonical_clp"
    if currency == "UF" and canonical_price_uf is None:
        return "derived_display"
    return "legacy_unknown"
