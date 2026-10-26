"""Valuation use case facade."""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

from config.valuation_flags import (
    experimental_engine_lab_enabled,
    valoria_consensus_enabled,
    valuation_quality_v2_allowed_property_types,
    valuation_quality_v2_apply_mode,
    valuation_quality_v2_blocked_comunas,
    valuation_quality_v2_max_delta_vs_baseline_pct,
    valuation_quality_v2_max_pool_dispersion,
    valuation_quality_v2_min_valid_comparables,
    valuation_quality_v2_p90_risk_comunas,
)
from core.assessment.beta_status import beta_scope_warning_codes
from core.assessment.confidence import build_confidence_contract
from core.assessment.contracts import (
    BetaScopeMetricsPayload,
    ComparableOutPayload,
    ComparableQualityMetricsPayload,
    ValuationResultPayload,
)
from core.entities.listing import Listing, Property
from core.exceptions import InsufficientDataError, ValidationError
from core.normalization.property_type import normalize_property_type as _normalize_property_type
from core.ports.listing_repo import ListingRepository
from core.ports.uf_service import UFService
from domain.valuation.comparables import valuate_with_comparables
from domain.valuation.engines.consensus_orchestrator import (
    CONSENSUS_METHOD,
    BetaConsensus,
    BetaEngineResult,
    run_beta_consensus,
)
from domain.valuation.engines.contracts import (
    EngineComparable,
    EngineContext,
    EngineResult,
    EngineStatus,
)
from domain.valuation.engines.experimental_lab import run_experimental_engine_lab
from domain.valuation.engines.registry import EngineRegistry
from domain.valuation.price_surface import (
    lookup_price_surface,
    maybe_apply_surface_adjustment,
    surface_warnings_for_estimate,
)
from domain.valuation.quality_v2_challenger import (
    QualityV2Config,
    QualityV2Result,
    evaluate_quality_v2_challenger,
)
from services.formatting import price_clp_int, price_uf_float
from services.uf_rate import require_real_uf_rate

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValuationInput:
    comuna: str
    property_type: str | None
    m2: float | None
    built_area_m2: float | None = None
    land_area_m2: float | None = None
    usable_area_m2: float | None = None
    dormitorios: int | None = None
    banos: int | None = None
    estacionamientos: int | None = None
    precio_publicado_uf: float | None = None
    precio_publicado_clp: int | None = None


@dataclass(frozen=True)
class ComparableDTO:
    listing_id: int | None
    title: str
    comuna: str
    price_uf: float
    price_clp: int
    m2: float
    built_area_m2: float | None
    land_area_m2: float | None
    usable_area_m2: float | None
    similarity: float
    url: str | None

    def to_payload(self) -> ComparableOutPayload:
        return {
            "listing_id": self.listing_id,
            "title": self.title,
            "comuna": self.comuna,
            "price_uf": self.price_uf,
            "price_clp": self.price_clp,
            "m2": self.m2,
            "built_area_m2": self.built_area_m2,
            "land_area_m2": self.land_area_m2,
            "usable_area_m2": self.usable_area_m2,
            "similarity": self.similarity,
            "url": self.url,
        }


@dataclass(frozen=True)
class ValuationDTO:
    base_estimated_price_uf: float | None
    base_estimated_price_clp: int | None
    estimated_price_uf: float | None
    estimated_price_clp: int | None
    price_range_low_uf: float | None
    price_range_high_uf: float | None
    price_range_low_clp: int | None
    price_range_high_clp: int | None
    confidence: str
    confidence_score: float | None
    confidence_label: str
    confidence_reasons: list[str]
    confidence_risk_flags: list[str]
    comparable_count: int
    price_m2_uf: float | None
    status: str
    warnings: list[str]
    comparable_quality_level: str | None
    comparable_quality_flags: list[str]
    comparable_quality_metrics: ComparableQualityMetricsPayload
    beta_scope_status: str | None
    beta_scope_flags: list[str]
    beta_scope_metrics: BetaScopeMetricsPayload
    beta_scope_message: str | None
    surface_adjustment_applied: bool
    surface_adjustment_weight: float
    surface_adjustment_reason: str
    comparables: list[ComparableDTO]
    consensus: BetaConsensus | None = None
    engine_results: list[BetaEngineResult] = field(default_factory=list)
    selected_engine_names: list[str] = field(default_factory=list)
    consensus_method: str | None = None
    valuation_verdict: dict[str, Any] | None = None
    engine_breakdown: list[dict[str, Any]] = field(default_factory=list)
    consensus_audit: dict[str, Any] | None = None
    weight_audit: list[dict[str, Any]] = field(default_factory=list)
    valuation_strategy: str = "current"
    consensus_used: bool = False
    consensus_unavailable_reason: str | None = None
    fallback_engine_used: str | None = None
    uf_rate_source: str | None = None
    uf_rate_date: str | None = None
    uf_rate_is_stale: bool = False

    def to_payload(self) -> ValuationResultPayload:
        return {
            "base_estimated_price_uf": self.base_estimated_price_uf,
            "base_estimated_price_clp": self.base_estimated_price_clp,
            "estimated_price_uf": self.estimated_price_uf,
            "estimated_price_clp": self.estimated_price_clp,
            "price_range_low_uf": self.price_range_low_uf,
            "price_range_high_uf": self.price_range_high_uf,
            "price_range_low_clp": self.price_range_low_clp,
            "price_range_high_clp": self.price_range_high_clp,
            "confidence": self.confidence,
            "confidence_score": self.confidence_score,
            "confidence_label": self.confidence_label,
            "confidence_reasons": list(self.confidence_reasons),
            "confidence_risk_flags": list(self.confidence_risk_flags),
            "comparable_count": self.comparable_count,
            "price_m2_uf": self.price_m2_uf,
            "status": self.status,
            "warnings": list(self.warnings),
            "comparable_quality_level": self.comparable_quality_level,
            "comparable_quality_flags": list(self.comparable_quality_flags),
            "comparable_quality_metrics": dict(self.comparable_quality_metrics),
            "beta_scope_status": self.beta_scope_status,
            "beta_scope_flags": list(self.beta_scope_flags),
            "beta_scope_metrics": dict(self.beta_scope_metrics),
            "beta_scope_message": self.beta_scope_message,
            "surface_adjustment_applied": self.surface_adjustment_applied,
            "surface_adjustment_weight": self.surface_adjustment_weight,
            "surface_adjustment_reason": self.surface_adjustment_reason,
            "comparables": [item.to_payload() for item in self.comparables],
            "consensus": self.consensus.to_payload() if self.consensus is not None else None,
            "engine_results": [item.to_payload() for item in self.engine_results],
            "selected_engine_names": list(self.selected_engine_names),
            "consensus_method": self.consensus_method,
            "valuation_verdict": dict(self.valuation_verdict) if self.valuation_verdict is not None else None,
            "engine_breakdown": [dict(item) for item in self.engine_breakdown],
            "consensus_audit": dict(self.consensus_audit) if self.consensus_audit is not None else None,
            "weight_audit": [dict(item) for item in self.weight_audit],
            "valuation_strategy": self.valuation_strategy,
            "consensus_used": self.consensus_used,
            "consensus_unavailable_reason": self.consensus_unavailable_reason,
            "fallback_engine_used": self.fallback_engine_used,
            "uf_rate_source": self.uf_rate_source,
            "uf_rate_date": self.uf_rate_date,
            "uf_rate_is_stale": self.uf_rate_is_stale,
        }


class ValuationService:
    def __init__(
        self,
        *,
        listing_repo: ListingRepository,
        uf_service: UFService,
        engine_registry: EngineRegistry | None = None,
    ) -> None:
        self._listing_repo = listing_repo
        self._uf_service = uf_service
        self._engine_registry = engine_registry

    async def valuate_property(
        self,
        data: ValuationInput,
        *,
        valuation_strategy: str = "current",
    ) -> ValuationDTO:
        property_type = _normalize_property_type(data.property_type)
        built_area_m2 = data.built_area_m2 or data.usable_area_m2 or data.m2
        usable_area_m2 = data.usable_area_m2 or built_area_m2 if property_type == "apartment" else data.usable_area_m2
        if built_area_m2 is None or built_area_m2 <= 0:
            raise ValidationError("m2, built_area_m2 o usable_area_m2 debe ser positivo")
        if property_type == "house" and data.land_area_m2 is not None and data.land_area_m2 <= 0:
            raise ValidationError("land_area_m2 debe ser positivo")

        uf_info = await require_real_uf_rate(self._uf_service)
        uf_to_clp = uf_info.rate
        target = Property(
            id=None,
            comuna=data.comuna,
            m2=built_area_m2,
            bedrooms=data.dormitorios or 0,
            bathrooms=data.banos or 0,
            parking=data.estacionamientos or 0,
            property_type=property_type,
            built_area_m2=built_area_m2,
            land_area_m2=data.land_area_m2,
            usable_area_m2=usable_area_m2,
        )
        candidates = await self._listing_repo.find_active_in_comuna(
            data.comuna,
            property_type=property_type,
        )

        valuation_run = valuate_with_comparables(target, candidates, uf_to_clp)
        result = valuation_run.result

        warnings: list[str] = []
        warnings.extend(result.reliability_warnings)
        warnings.extend(result.comparable_quality_flags)
        warnings.extend(_beta_scope_warning_codes(result.beta_scope_status))
        if result.comparables_used < 8:
            warnings.append("low_data_mode")
        if property_type == "unknown":
            warnings.append("unknown_property_type")
        if data.precio_publicado_uf is None and data.precio_publicado_clp is None:
            warnings.append("published_price_not_provided")
        estimated_price_m2_clp = price_clp_int(result.estimated_price) / built_area_m2
        surface = lookup_price_surface(target, candidates)
        warnings.extend(
            warning for warning in surface_warnings_for_estimate(
                estimated_price_m2=estimated_price_m2_clp,
                surface=surface,
            )
            if warning != "price_surface_insufficient_data"
        )
        base_estimated_clp = price_clp_int(result.estimated_price)
        adjustment = maybe_apply_surface_adjustment(
            base_estimated_clp,
            surface,
            target,
        )
        confidence_contract = build_confidence_contract(
            score=result.confidence,
            base_score=result.base_confidence,
            reliability_warnings=result.reliability_warnings,
        )
        warnings.extend(adjustment.warnings)
        adjusted_estimated_clp = round(adjustment.adjusted_estimate)
        delta_clp = adjusted_estimated_clp - base_estimated_clp
        low_clp = max(0, price_clp_int(result.price_range_low) + delta_clp)
        high_clp = max(low_clp, price_clp_int(result.price_range_high) + delta_clp)
        quality_v2 = _run_quality_v2_challenger(
            target=target,
            scored_comparables=valuation_run.scored_comparables,
            uf_to_clp=uf_to_clp,
            baseline_estimate_clp=adjusted_estimated_clp,
        )
        engine_results: list[BetaEngineResult] = []
        selected_engine_names: list[str] = []
        consensus_method = None
        final_estimated_clp = adjusted_estimated_clp
        final_low_clp = low_clp
        final_high_clp = high_clp
        if quality_v2.mode != "off":
            engine_results.append(_quality_v2_engine_result(quality_v2))
            warnings.extend(quality_v2.warnings)
        if quality_v2.used and quality_v2.estimate_clp is not None:
            final_estimated_clp = quality_v2.estimate_clp
            final_delta_clp = final_estimated_clp - adjusted_estimated_clp
            final_low_clp = max(0, low_clp + final_delta_clp)
            final_high_clp = max(final_low_clp, high_clp + final_delta_clp)
            selected_engine_names = ["comparables_quality_v2"]
            consensus_method = "quality_v2_guarded_challenger_v1"

        dto = ValuationDTO(
            base_estimated_price_uf=_clp_to_uf(base_estimated_clp, uf_to_clp),
            base_estimated_price_clp=base_estimated_clp,
            estimated_price_uf=_clp_to_uf(final_estimated_clp, uf_to_clp),
            estimated_price_clp=final_estimated_clp,
            price_range_low_uf=_clp_to_uf(final_low_clp, uf_to_clp),
            price_range_high_uf=_clp_to_uf(final_high_clp, uf_to_clp),
            price_range_low_clp=final_low_clp,
            price_range_high_clp=final_high_clp,
            confidence=confidence_contract.legacy_confidence,
            confidence_score=confidence_contract.confidence_score,
            confidence_label=confidence_contract.confidence_label,
            confidence_reasons=list(confidence_contract.confidence_reasons),
            confidence_risk_flags=list(confidence_contract.confidence_risk_flags),
            comparable_count=result.comparables_used,
            price_m2_uf=_clp_to_uf(final_estimated_clp, uf_to_clp) / built_area_m2,
            status="ok",
            warnings=_dedupe(warnings),
            comparable_quality_level=result.comparable_quality_level,
            comparable_quality_flags=list(result.comparable_quality_flags),
            comparable_quality_metrics=dict(result.comparable_quality_metrics),
            beta_scope_status=result.beta_scope_status,
            beta_scope_flags=list(result.beta_scope_flags),
            beta_scope_metrics=dict(result.beta_scope_metrics),
            beta_scope_message=result.beta_scope_message,
            surface_adjustment_applied=adjustment.adjustment_applied,
            surface_adjustment_weight=adjustment.adjustment_weight,
            surface_adjustment_reason=adjustment.adjustment_reason,
            comparables=[
                _comparable_dto(score.value, listing, uf_to_clp)
                for score, listing in valuation_run.scored_comparables
            ],
            engine_results=engine_results,
            selected_engine_names=selected_engine_names,
            consensus_method=consensus_method,
            uf_rate_source=uf_info.source,
            uf_rate_date=uf_info.rate_date.isoformat() if uf_info.rate_date else None,
            uf_rate_is_stale=uf_info.is_stale,
        )
        if valuation_strategy == "consensus_v1" and valoria_consensus_enabled():
            dto = _with_product_consensus(
                dto,
                target=target,
                candidates=candidates,
                uf_to_clp=uf_to_clp,
                published_price_provided=(
                    data.precio_publicado_uf is not None
                    or data.precio_publicado_clp is not None
                ),
                registry=self._engine_registry,
            )
        return _with_experimental_lab(
            dto,
            target=target,
            candidates=candidates,
            uf_to_clp=uf_to_clp,
        )


def _with_experimental_lab(
    dto: ValuationDTO,
    *,
    target: Property,
    candidates: Sequence[Listing],
    uf_to_clp: Decimal,
) -> ValuationDTO:
    if dto.consensus_used or not experimental_engine_lab_enabled():
        return dto
    try:
        lab = run_experimental_engine_lab(
            EngineContext(
                target=target,
                candidates=list(candidates),
                uf_to_clp=uf_to_clp,
                metadata={
                    "source": "valuation_service",
                    "read_only": True,
                },
            )
        )
    except Exception:
        _log.exception("Experimental valuation engine lab failed")
        return dto

    payload = lab.to_dict()
    consensus_verdict = _mapping_value(payload.get("valuation_verdict"))
    consensus_status = lab.consensus_result.status if lab.consensus_result is not None else None
    consensus_success = (
        lab.consensus_result is not None
        and lab.consensus_result.is_successful
        and consensus_verdict.get("estimate_uf") is not None
    )
    verdict = dict(consensus_verdict) if consensus_success else _current_valuation_verdict(dto)
    verdict["source"] = "consensus_experimental" if consensus_success else "current_valuation"
    verdict["status"] = consensus_status or "unavailable"

    return replace(
        dto,
        valuation_verdict=verdict,
        engine_breakdown=_list_of_mappings(payload.get("engine_breakdown")),
        consensus_audit=dict(_mapping_value(payload.get("consensus_audit"))),
        weight_audit=_list_of_mappings(payload.get("weight_audit")),
    )


def _current_valuation_verdict(dto: ValuationDTO) -> dict[str, Any]:
    return {
        "estimate_uf": dto.estimated_price_uf,
        "low_uf": dto.price_range_low_uf,
        "high_uf": dto.price_range_high_uf,
        "confidence": dto.confidence_score,
        "explanation": "Valoria mantiene la tasacion actual porque no hubo evidencia suficiente para formar consenso.",
    }


def _with_product_consensus(
    dto: ValuationDTO,
    *,
    target: Property,
    candidates: Sequence[Listing],
    uf_to_clp: Decimal,
    published_price_provided: bool,
    registry: EngineRegistry | None,
) -> ValuationDTO:
    consensus_run = run_beta_consensus(
        target=target,
        candidates=list(candidates),
        uf_to_clp=uf_to_clp,
        published_price_provided=published_price_provided,
        registry=registry,
    )
    consensus = consensus_run.consensus
    selected = consensus_run.selected_result
    engine_breakdown = _engine_breakdown_from_beta(
        consensus_run.engine_results,
        consensus_run.weight_audit,
    )
    consensus_audit = _consensus_audit_from_beta(consensus_run)
    if selected is None:
        verdict = _current_valuation_verdict(dto)
        verdict.update({
            "source": "current_valuation",
            "status": "fallback",
        })
        return replace(
            dto,
            consensus=consensus,
            engine_results=consensus_run.engine_results,
            consensus_method=CONSENSUS_METHOD,
            valuation_verdict=verdict,
            engine_breakdown=engine_breakdown,
            consensus_audit=consensus_audit,
            weight_audit=consensus_run.weight_audit,
            valuation_strategy="current_engine_fallback",
            consensus_used=False,
            consensus_unavailable_reason=consensus.fallback_reason or "consensus_unavailable",
            fallback_engine_used=_fallback_engine_name(dto),
        )

    estimated_clp = _decimal_int(selected.estimated_price_clp)
    low_clp = _decimal_int(selected.range_low_clp)
    high_clp = _decimal_int(selected.range_high_clp)
    if estimated_clp is None or low_clp is None or high_clp is None:
        return replace(
            dto,
            consensus=consensus,
            engine_results=consensus_run.engine_results,
            consensus_method=CONSENSUS_METHOD,
            engine_breakdown=engine_breakdown,
            consensus_audit=consensus_audit,
            weight_audit=consensus_run.weight_audit,
            valuation_strategy="current_engine_fallback",
            consensus_used=False,
            consensus_unavailable_reason="consensus_incomplete_output",
            fallback_engine_used=_fallback_engine_name(dto),
        )

    estimate_uf = _clp_to_uf(estimated_clp, uf_to_clp)
    low_uf = _clp_to_uf(low_clp, uf_to_clp)
    high_uf = _clp_to_uf(high_clp, uf_to_clp)
    price_m2_uf = estimate_uf / target.built_area_m2 if target.built_area_m2 else dto.price_m2_uf
    verdict = {
        "estimate_uf": estimate_uf,
        "low_uf": low_uf,
        "high_uf": high_uf,
        "confidence": selected.confidence,
        "explanation": selected.diagnostics.get("final_explanation")
        or selected.diagnostics.get("explanation")
        or "Consenso Valoria combino los motores disponibles.",
        "source": "consensus_v1",
        "status": selected.status,
    }
    return replace(
        dto,
        estimated_price_uf=estimate_uf,
        estimated_price_clp=estimated_clp,
        price_range_low_uf=low_uf,
        price_range_high_uf=high_uf,
        price_range_low_clp=low_clp,
        price_range_high_clp=high_clp,
        confidence_score=selected.confidence,
        price_m2_uf=price_m2_uf,
        consensus=consensus,
        engine_results=consensus_run.engine_results,
        selected_engine_names=consensus_run.selected_engine_names,
        consensus_method=CONSENSUS_METHOD,
        valuation_verdict=verdict,
        engine_breakdown=engine_breakdown,
        consensus_audit=consensus_audit,
        weight_audit=consensus_run.weight_audit,
        valuation_strategy="consensus_v1",
        consensus_used=True,
        consensus_unavailable_reason=None,
        fallback_engine_used=None,
    )


def _engine_breakdown_from_beta(
    engine_results: list[BetaEngineResult],
    weight_audit: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    weights = {row["engine_name"]: row for row in weight_audit}
    return [
        {
            "engine_name": result.engine_name,
            "label": _engine_label(result.engine_name),
            "role": result.engine_family or result.role,
            "estimate_uf": result.estimate_uf,
            "low_uf": result.range_low_uf,
            "high_uf": result.range_high_uf,
            "confidence": result.confidence,
            "weight": float(weights.get(result.engine_name, {}).get("final_normalized_weight", 0.0)),
            "status": result.status,
            "explanation": result.safe_error_message or _engine_explanation(result),
            "warning_flags": list(result.warnings),
        }
        for result in engine_results
    ]


def _consensus_audit_from_beta(run) -> dict[str, Any]:
    selected_diagnostics = dict(run.selected_result.diagnostics or {}) if run.selected_result else {}
    return {
        "engines_used": selected_diagnostics.get("engines_used", []),
        "engines_abstained": selected_diagnostics.get("engines_abstained", {}),
        "engines_failed": selected_diagnostics.get("engines_failed", {}),
        "disagreement_level": selected_diagnostics.get("disagreement_level"),
        "weight_audit": list(run.weight_audit),
        "valid_engine_count": run.consensus.valid_engine_count,
        "engine_family_count": run.consensus.engine_family_count,
        "engine_families": list(run.consensus.engine_families or []),
        "fallback_reason": run.consensus.fallback_reason,
    }


def _fallback_engine_name(dto: ValuationDTO) -> str:
    return ",".join(dto.selected_engine_names) if dto.selected_engine_names else "current_valuation"


def _engine_label(engine_name: str) -> str:
    return {
        "comparables_canonical_outliers": "Mercado comparable",
        "microzone_geo_v1": "Microzona",
        "hedonic_baseline_v1": "Modelo hedonico",
        "land_building_v1": "Suelo y construccion",
        "market_trends_v1": "Tendencia de mercado",
        "valoria_consensus_v1": "Consenso Valoria",
    }.get(engine_name, engine_name)


def _engine_explanation(result: BetaEngineResult) -> str:
    if result.status == "ok":
        return "Aporto una estimacion usable a Consenso Valoria."
    return "No hubo evidencia suficiente para que este motor participe."


def _valuation_dto_from_engine(
    *,
    result: EngineResult,
    candidates: Sequence[Listing],
    built_area_m2: float,
    uf_to_clp: Decimal,
    consensus: BetaConsensus,
    engine_results: list[BetaEngineResult],
) -> ValuationDTO:
    estimated_clp = _decimal_int(result.estimated_price_clp)
    low_clp = _decimal_int(result.range_low_clp)
    high_clp = _decimal_int(result.range_high_clp)
    if estimated_clp is None or low_clp is None or high_clp is None:
        raise InsufficientDataError("El motor seleccionado no produjo un resultado completo.")

    diagnostics = dict(result.diagnostics)
    confidence_label = str(_diagnostic_value(diagnostics, "confidence_label") or "low")
    confidence_score = result.confidence
    base_estimated_clp = _optional_int(
        _diagnostic_value(diagnostics, "base_estimated_price_clp")
    ) or estimated_clp
    surface_adjustment = _mapping_value(
        _diagnostic_value(diagnostics, "surface_adjustment")
    )
    comparable_quality_metrics = _mapping_value(
        _diagnostic_value(diagnostics, "comparable_quality_metrics")
    )
    beta_scope_metrics = _mapping_value(
        _diagnostic_value(diagnostics, "beta_scope_metrics")
    )
    selected_comparables = _selected_comparable_dtos(
        result.selected_comparables,
        candidates,
        uf_to_clp,
    )
    selected_names = [result.engine_name]

    return ValuationDTO(
        base_estimated_price_uf=_clp_to_uf(base_estimated_clp, uf_to_clp),
        base_estimated_price_clp=base_estimated_clp,
        estimated_price_uf=_clp_to_uf(estimated_clp, uf_to_clp),
        estimated_price_clp=estimated_clp,
        price_range_low_uf=_clp_to_uf(low_clp, uf_to_clp),
        price_range_high_uf=_clp_to_uf(high_clp, uf_to_clp),
        price_range_low_clp=low_clp,
        price_range_high_clp=high_clp,
        confidence=str(
            _diagnostic_value(diagnostics, "confidence_legacy_label")
            or confidence_label
        ),
        confidence_score=confidence_score,
        confidence_label=confidence_label,
        confidence_reasons=_string_list(
            _diagnostic_value(diagnostics, "confidence_reasons")
        ),
        confidence_risk_flags=_string_list(
            _diagnostic_value(diagnostics, "confidence_risk_flags")
        ),
        comparable_count=result.comparables_used or len(selected_comparables),
        price_m2_uf=_clp_to_uf(estimated_clp, uf_to_clp) / built_area_m2,
        status="ok",
        warnings=list(result.warnings),
        comparable_quality_level=_optional_str(
            _diagnostic_value(diagnostics, "comparable_quality_level")
        ),
        comparable_quality_flags=_string_list(
            _diagnostic_value(diagnostics, "comparable_quality_flags")
        ),
        comparable_quality_metrics=dict(comparable_quality_metrics),
        beta_scope_status=_optional_str(
            _diagnostic_value(diagnostics, "beta_scope_status")
        ),
        beta_scope_flags=_string_list(
            _diagnostic_value(diagnostics, "beta_scope_flags")
        ),
        beta_scope_metrics=dict(beta_scope_metrics),
        beta_scope_message=_optional_str(
            _diagnostic_value(diagnostics, "beta_scope_message")
        ),
        surface_adjustment_applied=bool(surface_adjustment.get("applied", False)),
        surface_adjustment_weight=float(surface_adjustment.get("weight", 0.0)),
        surface_adjustment_reason=str(
            surface_adjustment.get("reason") or "surface_unavailable"
        ),
        comparables=selected_comparables,
        consensus=consensus,
        engine_results=engine_results,
        selected_engine_names=selected_names,
        consensus_method=CONSENSUS_METHOD,
    )


def _comparable_dto(similarity: float, listing: Listing, uf_to_clp: Decimal) -> ComparableDTO:
    return ComparableDTO(
        listing_id=listing.id,
        title=listing.title,
        comuna=listing.comuna,
        price_uf=price_uf_float(listing.price, uf_to_clp),
        price_clp=price_clp_int(listing.price),
        m2=listing.m2,
        built_area_m2=listing.built_area_m2,
        land_area_m2=listing.land_area_m2,
        usable_area_m2=listing.usable_area_m2,
        similarity=round(similarity, 4),
        url=listing.url,
    )


def _selected_comparable_dtos(
    selected: Sequence[EngineComparable],
    candidates: Sequence[Listing],
    uf_to_clp: Decimal,
) -> list[ComparableDTO]:
    result: list[ComparableDTO] = []
    for item in selected:
        listing = _find_selected_listing(item, candidates)
        if listing is None:
            continue
        result.append(_comparable_dto(item.score, listing, uf_to_clp))
    return result


def _find_selected_listing(
    selected: EngineComparable,
    candidates: Sequence[Listing],
) -> Listing | None:
    if selected.listing_id is not None:
        by_id = next(
            (listing for listing in candidates if listing.id == selected.listing_id),
            None,
        )
        if by_id is not None:
            return by_id
    if selected.fingerprint:
        return next(
            (
                listing
                for listing in candidates
                if listing.fingerprint == selected.fingerprint
            ),
            None,
        )
    return None


def _consensus_insufficient_data(results: Sequence[EngineResult]) -> InsufficientDataError:
    legacy = next(
        (result for result in results if result.engine_name == "comparables_legacy"),
        None,
    )
    if (
        legacy is not None
        and legacy.status == EngineStatus.INSUFFICIENT_DATA
        and legacy.error_message
    ):
        return InsufficientDataError(legacy.error_message)
    return InsufficientDataError(
        "No hay suficientes comparables para completar la valorizacion."
    )


def _diagnostic_value(diagnostics: Mapping[str, Any], key: str) -> Any:
    if key in diagnostics:
        return diagnostics[key]
    nested = diagnostics.get("result")
    if isinstance(nested, Mapping):
        return nested.get(key)
    return None


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value]


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return round(Decimal(str(value)))


def _decimal_int(value: Any) -> int | None:
    return _optional_int(value)


def _clp_to_uf(value: int | float | Decimal, uf_to_clp: Decimal) -> float:
    return round(float(Decimal(str(value)) / uf_to_clp), 2)


def _with_uf_trace(dto: ValuationDTO, uf_info) -> ValuationDTO:
    return replace(
        dto,
        uf_rate_source=uf_info.source,
        uf_rate_date=uf_info.rate_date.isoformat() if uf_info.rate_date else None,
        uf_rate_is_stale=uf_info.is_stale,
    )


def _quality_v2_config() -> QualityV2Config:
    return QualityV2Config(
        mode=valuation_quality_v2_apply_mode(),
        allowed_property_types=valuation_quality_v2_allowed_property_types(),
        blocked_comunas=valuation_quality_v2_blocked_comunas(),
        p90_risk_comunas=valuation_quality_v2_p90_risk_comunas(),
        min_valid_comparables=valuation_quality_v2_min_valid_comparables(),
        max_pool_dispersion=valuation_quality_v2_max_pool_dispersion(),
        max_delta_vs_baseline_pct=valuation_quality_v2_max_delta_vs_baseline_pct(),
    )


def _run_quality_v2_challenger(
    *,
    target: Property,
    scored_comparables,
    uf_to_clp: Decimal,
    baseline_estimate_clp: int,
) -> QualityV2Result:
    return evaluate_quality_v2_challenger(
        target=target,
        scored_comparables=scored_comparables,
        uf_to_clp=uf_to_clp,
        baseline_estimate_clp=baseline_estimate_clp,
        config=_quality_v2_config(),
    )


def _quality_v2_engine_result(result: QualityV2Result) -> BetaEngineResult:
    status = "ok" if result.guardrails_passed else "skipped"
    return BetaEngineResult(
        engine_name="comparables_quality_v2",
        engine_version="robust_weighted_median_guarded_v1",
        role="shadow" if result.mode == "shadow" else "challenger",
        status=status,
        estimate_uf=result.estimate_uf,
        estimate_clp=result.estimate_clp,
        range_low_uf=None,
        range_high_uf=None,
        confidence=None,
        comparables_count=result.valid_comparables,
        selected_for_final=result.used,
        warnings=list(result.warnings),
        safe_error_message=_quality_v2_safe_message(result),
        diagnostics=result.diagnostics(),
    )


def _quality_v2_safe_message(result: QualityV2Result) -> str | None:
    if result.guardrails_passed:
        return None
    if result.fallback_reason == "blocked_comuna":
        return "CQ v2 esta deshabilitado para esta comuna por guardrail."
    if result.fallback_reason == "property_type_not_allowed":
        return "CQ v2 no esta habilitado para este tipo de propiedad."
    if result.fallback_reason == "insufficient_valid_comparables":
        return "CQ v2 no tuvo suficientes comparables validos."
    if result.fallback_reason == "pool_dispersion_too_high":
        return "CQ v2 detecto dispersion extrema en el pool."
    if result.fallback_reason == "delta_vs_baseline_too_high":
        return "CQ v2 difiere demasiado del baseline."
    if result.fallback_reason == "robust_estimate_unavailable":
        return "CQ v2 no pudo calcular una estimacion robusta."
    return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _beta_scope_warning_codes(status: str | None) -> list[str]:
    return beta_scope_warning_codes(status)
