"""Valuation endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_serializer
from starlette.concurrency import run_in_threadpool

from api.deps import AppSettings, CurrentUser, DbSession, ValuationServiceDep
from api.sii_closing_contract import SiiClosingOpinionOut
from config.valuation_flags import sii_closing_layer_enabled
from core.exceptions import InsufficientDataError, UFServiceError, ValidationError
from infrastructure.db.models import UsageLogORM
from services.product_usage import sanitize_properties
from services.valuation import ValuationInput
from services.valuation_feedback import submit_valuation_feedback

router = APIRouter(prefix="/valuations", tags=["valuations"])
_log = logging.getLogger(__name__)


class ValuationRequest(BaseModel):
    # Legacy release ignored this field. Preserve that behavior for every input
    # while off; validate the optional address only inside the enabled layer.
    address: Any = None
    target_listing_id: int | None = Field(default=None, gt=0)
    comuna: str
    property_type: str | None = None
    m2: float = Field(gt=0)
    built_area_m2: float | None = Field(default=None, gt=0)
    land_area_m2: float | None = Field(default=None, gt=0)
    usable_area_m2: float | None = Field(default=None, gt=0)
    dormitorios: int | None = Field(default=None, ge=0)
    banos: int | None = Field(default=None, ge=0)
    estacionamientos: int | None = Field(default=None, ge=0)
    precio_publicado_uf: float | None = Field(default=None, ge=0)
    precio_publicado_clp: int | None = Field(default=None, ge=0)


class ComparableOut(BaseModel):
    listing_id: int | None
    title: str
    comuna: str
    price_uf: float
    price_clp: int
    m2: float | None
    built_area_m2: float | None = None
    land_area_m2: float | None = None
    usable_area_m2: float | None = None
    similarity: float
    url: str | None
    source: str | None = None
    external_id: str | None = None


class ComparableQualityMetricsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    n_comparables: int | None = None
    avg_similarity_score: float | None = None
    median_similarity_score: float | None = None
    price_per_m2_dispersion: float | None = None
    same_comuna_ratio: float | None = None
    same_microzone_ratio: float | None = None
    address_level_geo_ratio: float | None = None
    m2_bucket_coverage: float | None = None
    target_m2_bucket: str | None = None
    property_type_consistency: float | None = None
    outlier_pressure: float | None = None


class BetaScopeMetricsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    segment_sample_count: int | None = None
    m2_bucket_sample_count: int | None = None
    target_m2_bucket: str | None = None
    property_type: str | None = None
    comparable_quality_level: str | None = None
    n_comparables: int | None = None
    price_per_m2_dispersion: float | None = None
    address_level_geo_ratio: float | None = None
    property_type_consistency: float | None = None


class ValuationEngineResultOut(BaseModel):
    engine_name: str
    engine_version: str
    engine_family: str | None = None
    role: str
    status: str
    estimate_uf: float | None = None
    estimate_clp: int | None = None
    range_low_uf: float | None = None
    range_high_uf: float | None = None
    confidence: float | None = None
    comparables_count: int | None = None
    selected_for_final: bool = False
    warnings: list[str] = Field(default_factory=list)
    safe_error_message: str | None = None


class ValuationConsensusOut(BaseModel):
    status: str
    method: str
    estimate_uf: float | None = None
    estimate_clp: int | None = None
    range_low_uf: float | None = None
    range_high_uf: float | None = None
    confidence: float | None = None
    selected_engine_names: list[str] = Field(default_factory=list)
    engine_weights: dict[str, float] = Field(default_factory=dict)
    consensus_used: bool = False
    valid_engine_count: int = 0
    engine_family_count: int = 0
    engine_families: list[str] = Field(default_factory=list)
    fallback_reason: str | None = None
    fallback_engine_used: str | None = None


class ValuationVerdictOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    estimate_uf: float | None = None
    low_uf: float | None = None
    high_uf: float | None = None
    confidence: float | None = None
    explanation: str | list[str] | None = None
    source: str | None = None
    status: str | None = None


class ValuationEngineBreakdownOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    engine_name: str
    label: str | None = None
    role: str | None = None
    estimate_uf: float | None = None
    low_uf: float | None = None
    high_uf: float | None = None
    confidence: float | None = None
    weight: float | None = None
    status: str
    explanation: str | None = None
    warning_flags: list[str] = Field(default_factory=list)


class ValuationConsensusAuditOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    engines_used: list[str] = Field(default_factory=list)
    engines_abstained: dict[str, str] = Field(default_factory=dict)
    engines_failed: dict[str, str] = Field(default_factory=dict)
    disagreement_level: str | float | None = None
    weight_audit: list[dict] = Field(default_factory=list)


class ValuationResponse(BaseModel):
    sii_closing_opinion: SiiClosingOpinionOut | None = None

    @model_serializer(mode="wrap")
    def omit_inactive_sii(self, handler):
        result = handler(self)
        if self.sii_closing_opinion is None:
            result.pop("sii_closing_opinion", None)
        return result

    valuation_debug: dict = Field(default_factory=dict)
    base_estimated_price_uf: float | None = None
    base_estimated_price_clp: int | None = None
    estimated_price_uf: float | None
    estimated_price_clp: int | None
    price_range_low_uf: float | None = None
    price_range_high_uf: float | None = None
    price_range_low_clp: int | None = None
    price_range_high_clp: int | None = None
    confidence: str
    confidence_score: float | None = None
    confidence_label: str
    confidence_reasons: list[str] = Field(default_factory=list)
    confidence_risk_flags: list[str] = Field(default_factory=list)
    comparable_count: int
    price_m2_uf: float | None
    status: str
    warnings: list[str]
    comparable_quality_level: str | None = None
    comparable_quality_flags: list[str] = Field(default_factory=list)
    comparable_quality_metrics: ComparableQualityMetricsOut = Field(default_factory=ComparableQualityMetricsOut)
    beta_scope_status: str | None = None
    beta_scope_flags: list[str] = Field(default_factory=list)
    beta_scope_metrics: BetaScopeMetricsOut = Field(default_factory=BetaScopeMetricsOut)
    beta_scope_message: str | None = None
    surface_adjustment_applied: bool = False
    surface_adjustment_weight: float = 0.0
    surface_adjustment_reason: str | None = None
    comparables: list[ComparableOut]
    consensus: ValuationConsensusOut | None = None
    engine_results: list[ValuationEngineResultOut] = Field(default_factory=list)
    selected_engine_names: list[str] = Field(default_factory=list)
    consensus_method: str | None = None
    uf_rate_source: str | None = None
    uf_rate_date: str | None = None
    uf_rate_is_stale: bool = False
    valuation_verdict: ValuationVerdictOut | None = None
    engine_breakdown: list[ValuationEngineBreakdownOut] = Field(default_factory=list)
    consensus_audit: ValuationConsensusAuditOut | None = None
    weight_audit: list[dict] = Field(default_factory=list)
    valuation_strategy: str = "current"
    consensus_used: bool = False
    consensus_unavailable_reason: str | None = None
    fallback_engine_used: str | None = None


class ValuationFeedbackRequest(BaseModel):
    valuation_result: dict
    valuation_payload: dict
    feedback: str
    comment: str | None = Field(default=None, max_length=1000)


class ValuationFeedbackResponse(BaseModel):
    status: str = "ok"
    record: dict
    path: str


@router.post("", response_model=ValuationResponse)
async def valuate(
    current_user: CurrentUser,
    payload: ValuationRequest,
    service: ValuationServiceDep,
    session: DbSession,
) -> ValuationResponse:
    try:
        result = await service.valuate_property(
            ValuationInput(
                target_listing_id=payload.target_listing_id,
                comuna=payload.comuna,
                property_type=payload.property_type,
                m2=payload.m2,
                built_area_m2=payload.built_area_m2,
                land_area_m2=payload.land_area_m2,
                usable_area_m2=payload.usable_area_m2,
                dormitorios=payload.dormitorios,
                banos=payload.banos,
                estacionamientos=payload.estacionamientos,
                precio_publicado_uf=payload.precio_publicado_uf,
                precio_publicado_clp=payload.precio_publicado_clp,
            ),
            valuation_strategy="canonical_only",
        )
    except UFServiceError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="UF real no disponible") from e
    except (ValidationError, InsufficientDataError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        _log.exception("Unexpected valuation error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error inesperado al tasar propiedad",
        ) from e
    response = ValuationResponse.model_validate(result, from_attributes=True)
    if sii_closing_layer_enabled() and isinstance(payload.address, str) and payload.address.strip():
        from services.sii.closing_opinion import build_opinion

        try:
            opinion = await run_in_threadpool(
                build_opinion,
                address=payload.address,
                comuna=payload.comuna,
                property_type=payload.property_type,
                area=payload.usable_area_m2 or payload.built_area_m2 or payload.m2,
            )
            response.sii_closing_opinion = SiiClosingOpinionOut.model_validate(opinion)
        except Exception:
            _log.warning("SII second opinion unavailable; canonical result preserved")
            response.sii_closing_opinion = SiiClosingOpinionOut(
                status="unavailable",
                reason_code="data_unavailable",
                message="La segunda opinión SII no está disponible en este momento.",
            )
    try:
        await _record_valuation_completed_event(
            session=session,
            user_id=current_user.id,
            payload=payload,
            response=response,
        )
    except Exception:
        _log.exception("Failed to record valuation_completed usage event")
    return response


async def _record_valuation_completed_event(
    *,
    session: DbSession,
    user_id: int | None,
    payload: ValuationRequest,
    response: ValuationResponse,
) -> None:
    if user_id is None:
        return
    raw_metadata = {
        "comuna": payload.comuna,
        "property_type": payload.property_type,
        "m2": payload.m2,
        "built_area_m2": payload.built_area_m2,
        "land_area_m2": payload.land_area_m2,
        "precio_publicado_uf": payload.precio_publicado_uf,
        "precio_publicado_clp": payload.precio_publicado_clp,
        "estimated_value_uf": response.estimated_price_uf,
        "range_low_uf": response.price_range_low_uf,
        "range_high_uf": response.price_range_high_uf,
        "comparable_count": response.comparable_count,
        "comparables_used": response.comparable_count,
        "confidence": response.confidence,
        "confidence_score": response.confidence_score,
        "status": response.status,
    }
    metadata = sanitize_properties(
        {key: value for key, value in raw_metadata.items() if value is not None}
    )
    session.add(
        UsageLogORM(
            user_id=user_id,
            event_type="valuation_completed",
            payload={"feature": "tasar_playground", "metadata": metadata},
        )
    )
    await session.commit()


@router.post("/feedback", response_model=ValuationFeedbackResponse)
async def submit_feedback(
    payload: ValuationFeedbackRequest,
    settings: AppSettings,
) -> ValuationFeedbackResponse:
    if (settings.is_cloud_beta or not settings.valuation_feedback_enabled
            or settings.environment not in {"local", "development"}):
        raise HTTPException(
            status_code=403,
            detail="Valuation feedback is disabled for this runtime profile",
        )
    try:
        result = submit_valuation_feedback(
            valuation_result=payload.valuation_result,
            valuation_payload=payload.valuation_payload,
            feedback=payload.feedback,
            comment=payload.comment,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        _log.exception("Unexpected valuation feedback error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error inesperado al guardar feedback de tasacion",
        ) from e
    return ValuationFeedbackResponse.model_validate({"status": "ok", **result})
