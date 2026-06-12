"""Market reference endpoints."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from api.deps import UFServiceDep
from core.exceptions import UFServiceError
from services.uf_rate import require_real_uf_rate

router = APIRouter(prefix="/market", tags=["market"])


class UFRateOut(BaseModel):
    rate_clp: float
    source: str
    is_fallback: bool
    cache_hit: bool
    cache_ttl_seconds: int
    observed_at: datetime


@router.get("/uf", response_model=UFRateOut)
async def get_current_uf(uf_service: UFServiceDep) -> UFRateOut:
    try:
        info = await require_real_uf_rate(uf_service)
    except UFServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="UF real no disponible",
        ) from e
    return UFRateOut(
        rate_clp=_decimal_to_float(info.rate),
        source=info.source,
        is_fallback=info.is_fallback,
        cache_hit=info.cache_hit,
        cache_ttl_seconds=86_400,
        observed_at=datetime.now(UTC),
    )


def _decimal_to_float(value: Decimal) -> float:
    return float(value)
