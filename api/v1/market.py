"""Market reference endpoints."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.deps import AppSettings, CurrentUser, DbSession, UFServiceDep
from core.exceptions import UFServiceError
from services.market_dashboard import (
    liquidity_summary_placeholder,
    market_briefing_placeholder,
    microzones_summary_placeholder,
)
from services.price_trends import PriceTrendService
from services.uf_rate import require_real_uf_rate

router = APIRouter(prefix="/market", tags=["market"])


class UFRateOut(BaseModel):
    rate_clp: float
    source: str
    is_fallback: bool
    cache_hit: bool
    cache_ttl_seconds: int
    observed_at: datetime
    rate_date: str | None = None
    fetched_at: datetime | None = None
    is_stale: bool = False
    stale_reason: str | None = None


class PriceTrendPointOut(BaseModel):
    month: str
    median_price_m2_uf: float
    sample_count: int


class PriceTrendOut(BaseModel):
    status: str
    metric: str
    property_type: str
    comuna: str
    period_months: int
    points: list[PriceTrendPointOut] = Field(default_factory=list)
    latest_value: float | None = None
    previous_value: float | None = None
    change_pct: float | None = None
    direction: str
    coverage_count: int
    source: str
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MarketIndicatorOut(BaseModel):
    key: str
    label: str
    status: str
    value: float | int | str | None = None
    delta_pct: float | None = None
    unit: str | None = None
    description: str


class MarketInsightOut(BaseModel):
    status: str
    text: str


class ValoriaIndexOut(BaseModel):
    status: str
    available: bool
    value: float | None = None
    max: int
    label: str
    confidence_label: str
    description: str
    source: str


class MarketBriefingOut(BaseModel):
    status: str
    available: bool
    market: str
    headline: str
    summary: str
    indicators: list[MarketIndicatorOut] = Field(default_factory=list)
    insight: MarketInsightOut
    valoria_index: ValoriaIndexOut
    updated_at: datetime | None = None
    source: str


class MicrozoneSummaryItemOut(BaseModel):
    name: str
    score: float | None = None
    change_pct: float | None = None
    status: str | None = None


class MicrozonesSummaryOut(BaseModel):
    status: str
    available: bool
    items: list[MicrozoneSummaryItemOut] = Field(default_factory=list)
    message: str
    source: str


class LiquiditySummaryOut(BaseModel):
    status: str
    available: bool
    value: float | None = None
    max: int
    label: str
    message: str
    source: str


@router.get("/uf", response_model=UFRateOut)
async def get_current_uf(uf_service: UFServiceDep, settings: AppSettings) -> UFRateOut:
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
        cache_ttl_seconds=settings.uf_cache_ttl_hours * 60 * 60,
        observed_at=datetime.now(UTC),
        rate_date=info.rate_date.isoformat() if info.rate_date else None,
        fetched_at=info.fetched_at,
        is_stale=info.is_stale,
        stale_reason=info.stale_reason,
    )


@router.get("/briefing", response_model=MarketBriefingOut)
async def get_market_briefing(_user: CurrentUser) -> MarketBriefingOut:
    return MarketBriefingOut(**market_briefing_placeholder())


@router.get("/microzones/summary", response_model=MicrozonesSummaryOut)
async def get_microzones_summary(_user: CurrentUser) -> MicrozonesSummaryOut:
    return MicrozonesSummaryOut(**microzones_summary_placeholder())


@router.get("/liquidity/summary", response_model=LiquiditySummaryOut)
async def get_liquidity_summary(_user: CurrentUser) -> LiquiditySummaryOut:
    return LiquiditySummaryOut(**liquidity_summary_placeholder())


@router.get("/trends/price-m2", response_model=PriceTrendOut)
async def get_price_m2_trend(
    session: DbSession,
    _user: CurrentUser,
    comuna: str = Query(..., min_length=1),
    property_type: str = Query(..., min_length=1),
    period_months: int = Query(default=12, ge=3, le=36),
) -> PriceTrendOut:
    trend = await PriceTrendService(session).price_m2_trend(
        comuna=comuna,
        property_type=property_type,
        period_months=period_months,
    )
    data = trend.to_dict()
    return PriceTrendOut(**data)


def _decimal_to_float(value: Decimal) -> float:
    return float(value)
