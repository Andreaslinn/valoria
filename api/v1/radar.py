"""Radar endpoints."""
from __future__ import annotations

import logging
from time import perf_counter

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.deps import CurrentUser, RadarServiceDep

router = APIRouter(prefix="/radar", tags=["radar"])
_log = logging.getLogger(__name__)


class OpportunityOut(BaseModel):
    listing_id: int | None
    title: str
    comuna: str
    price_uf: float
    price_clp: int
    m2: float
    estimated_price_uf: float
    discount_pct: float
    score: float
    confidence: str
    confidence_score: float | None = None
    confidence_label: str
    confidence_reasons: list[str] = Field(default_factory=list)
    confidence_risk_flags: list[str] = Field(default_factory=list)
    comparables_used: int
    url: str | None
    warnings: list[str]
    radar_verdict: str
    radar_verdict_message: str
    risk_flags: list[str] = Field(default_factory=list)
    comparable_quality_level: str | None = None
    comparable_quality_flags: list[str] = Field(default_factory=list)
    beta_scope_status: str | None = None
    beta_scope_message: str | None = None
    beta_scope_flags: list[str] = Field(default_factory=list)
    estimated_value_uf: float | None = None
    estimated_value_clp: int | None = None
    price_currency: str | None = None
    price_clp_snapshot: int | None = None
    price_basis_used: str | None = None
    price_data_quality: str | None = None


@router.get("/opportunities", response_model=list[OpportunityOut])
async def opportunities(
    _current_user: CurrentUser,
    service: RadarServiceDep,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[OpportunityOut]:
    start = perf_counter()
    try:
        result = await service.opportunities(limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        _log.exception("Unexpected radar error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error inesperado al detectar oportunidades",
        ) from e
    _log.info(
        "radar_endpoint_completed limit=%s results=%s total_ms=%.1f",
        limit,
        len(result),
        _elapsed_ms(start),
    )
    return [OpportunityOut.model_validate(item, from_attributes=True) for item in result]


def _elapsed_ms(start: float) -> float:
    return (perf_counter() - start) * 1000
