"""Tasar-specific endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.deps import CurrentUser, DbSession
from config.valuation_flags import sii_closing_layer_enabled
from services.recent_user_activity import RecentUserActivityService

router = APIRouter(prefix="/tasar", tags=["tasar"])


@router.get("/capabilities")
def capabilities() -> dict[str, bool]:
    """Public UI capability only; no SII data or application settings exposed."""
    return {"sii_closing_layer": sii_closing_layer_enabled()}


class AddressDetailsRequest(BaseModel):
    address: str = Field(min_length=1, max_length=512)
    comuna: str = Field(min_length=1, max_length=64)


class AddressFieldsOut(BaseModel):
    closed_area_m2: float | None = None
    land_area_m2: float | None = None
    construction_year: int | None = None
    property_type: str | None = None


class AddressCandidateOut(BaseModel):
    id: str
    label: str


class AddressDetailsOut(BaseModel):
    status: str
    fields: AddressFieldsOut = Field(default_factory=AddressFieldsOut)
    source: str | None = None
    source_period: str | None = None
    message: str
    missing_fields: list[str] = Field(default_factory=list)
    candidates: list[AddressCandidateOut] = Field(default_factory=list)
    candidate_count: int = 0


@router.post("/address-details", response_model=AddressDetailsOut)
async def lookup_address_details(payload: AddressDetailsRequest, current_user: CurrentUser):
    if not sii_closing_layer_enabled():
        raise HTTPException(status_code=404, detail="Autocompletado por dirección no habilitado")
    from services.sii.address_details import address_details

    try:
        return await run_in_threadpool(address_details, address=payload.address, comuna=payload.comuna)
    except Exception:
        return {"status": "unavailable", "message": "No pudimos consultar el catastro. Puedes completar los datos manualmente."}


class RecentUserActivityEventOut(BaseModel):
    id: str
    event_type: str
    title: str
    description: str
    occurred_at: datetime
    source: str
    valuation_id: int | None = None
    listing_id: int | None = None
    report_id: int | None = None
    comuna: str | None = None
    property_type: str | None = None
    estimated_value_uf: float | None = None
    range_low_uf: float | None = None
    range_high_uf: float | None = None
    trend_points_uf: list[float] = Field(default_factory=list)
    confidence: str | None = None
    status: str | None = None
    reason: str | None = None


class RecentUserActivityOut(BaseModel):
    status: str
    user_id: int
    events_count: int
    events: list[RecentUserActivityEventOut] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@router.get("/activity/recent", response_model=RecentUserActivityOut)
async def recent_activity(
    current_user: CurrentUser,
    session: DbSession,
    limit: int = Query(default=3, ge=1, le=5),
) -> RecentUserActivityOut:
    assert current_user.id is not None
    activity = await RecentUserActivityService(session).get_recent_activity(
        user_id=current_user.id,
        limit=limit,
    )
    return RecentUserActivityOut.model_validate(activity, from_attributes=True)
