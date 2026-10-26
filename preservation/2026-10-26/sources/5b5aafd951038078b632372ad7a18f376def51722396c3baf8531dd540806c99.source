"""Product-safe orchestration for Valoria Consensus v1."""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from decimal import Decimal
from math import isfinite
from statistics import median
from typing import Any

from core.entities.listing import Listing, Property
from core.normalization.property_type import normalize_property_type
from domain.valuation.engines.consensus import ValoriaConsensusV1Engine
from domain.valuation.engines.contracts import (
    EngineContext,
    EngineRequest,
    EngineResult,
    EngineStatus,
)
from domain.valuation.engines.registry import (
    EngineRegistry,
    UnknownValuationEngineError,
    experimental_engine_registry,
)

CONSENSUS_METHOD = "valoria_consensus_v1_min_two_families"
CONSENSUS_ENGINE_NAME = "valoria_consensus_v1"
MIN_DISTINCT_FAMILIES = 2

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EngineSpec:
    name: str
    family: str
    role: str
    label: str


_ENGINE_SPECS = (
    _EngineSpec("comparables_canonical_outliers", "market_comparables", "market_comparables", "Mercado comparable"),
    _EngineSpec("microzone_geo_v1", "territorial_signal", "territorial_signal", "Microzona"),
    _EngineSpec("hedonic_baseline_v1", "structural_signal", "structural_signal", "Modelo hedonico"),
    _EngineSpec("land_building_v1", "house_land_building_signal", "house_land_building_signal", "Suelo y construccion"),
    _EngineSpec("market_trends_v1", "time_trend_signal", "time_trend_signal", "Tendencia de mercado"),
)


@dataclass(frozen=True)
class BetaEngineResult:
    engine_name: str
    engine_version: str
    role: str
    status: str
    estimate_uf: float | None
    estimate_clp: int | None
    range_low_uf: float | None
    range_high_uf: float | None
    confidence: float | None
    comparables_count: int | None
    selected_for_final: bool
    warnings: list[str]
    safe_error_message: str | None
    diagnostics: dict[str, Any] | None = None
    engine_family: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "engine_name": self.engine_name,
            "engine_version": self.engine_version,
            "engine_family": self.engine_family,
            "role": self.role,
            "status": self.status,
            "estimate_uf": self.estimate_uf,
            "estimate_clp": self.estimate_clp,
            "range_low_uf": self.range_low_uf,
            "range_high_uf": self.range_high_uf,
            "confidence": self.confidence,
            "comparables_count": self.comparables_count,
            "selected_for_final": self.selected_for_final,
            "warnings": list(self.warnings),
            "safe_error_message": self.safe_error_message,
            "diagnostics": dict(self.diagnostics or {}),
        }


@dataclass(frozen=True)
class BetaConsensus:
    status: str
    method: str
    estimate_uf: float | None
    estimate_clp: int | None
    range_low_uf: float | None
    range_high_uf: float | None
    confidence: float | None
    selected_engine_names: list[str]
    engine_weights: dict[str, float]
    consensus_used: bool = False
    valid_engine_count: int = 0
    engine_family_count: int = 0
    engine_families: list[str] | None = None
    fallback_reason: str | None = None
    fallback_engine_used: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "method": self.method,
            "estimate_uf": self.estimate_uf,
            "estimate_clp": self.estimate_clp,
            "range_low_uf": self.range_low_uf,
            "range_high_uf": self.range_high_uf,
            "confidence": self.confidence,
            "selected_engine_names": list(self.selected_engine_names),
            "engine_weights": dict(self.engine_weights),
            "consensus_used": self.consensus_used,
            "valid_engine_count": self.valid_engine_count,
            "engine_family_count": self.engine_family_count,
            "engine_families": list(self.engine_families or []),
            "fallback_reason": self.fallback_reason,
            "fallback_engine_used": self.fallback_engine_used,
        }


@dataclass(frozen=True)
class BetaConsensusRun:
    selected_result: EngineResult | None
    raw_results: list[EngineResult]
    engine_results: list[BetaEngineResult]
    consensus: BetaConsensus
    weight_audit: list[dict[str, Any]]

    @property
    def selected_engine_names(self) -> list[str]:
        if self.selected_result is None:
            return []
        return [self.selected_result.engine_name]


def run_beta_consensus(
    *,
    target: Property,
    candidates: list[Listing],
    uf_to_clp: Decimal,
    published_price_provided: bool,
    registry: EngineRegistry | None = None,
) -> BetaConsensusRun:
    """Run read-only engines and use Consensus v1 only with two valid families."""
    engine_registry = registry or experimental_engine_registry()
    request = EngineRequest(
        published_price_provided=published_price_provided,
        metadata={"orchestrator": CONSENSUS_METHOD, "read_only": True},
    )
    context = EngineContext(
        target=target,
        candidates=tuple(candidates),
        uf_to_clp=uf_to_clp,
        metadata={"source": "valuation_service", "read_only": True},
    )
    raw_results = [
        _run_engine(engine_registry, spec, request=request, context=context)
        for spec in _ENGINE_SPECS
    ]
    valid_by_family = _valid_results_by_family(raw_results)
    valid_results = list(valid_by_family.values())
    valid_families = [spec.family for spec in _ENGINE_SPECS if spec.family in valid_by_family]
    weight_audit = _build_weight_audit(context, raw_results, valid_results)
    selected: EngineResult | None = None
    fallback_reason: str | None = None
    if len(valid_families) >= MIN_DISTINCT_FAMILIES:
        selected = _run_consensus_engine(
            engine_registry,
            context=context,
            engine_results=valid_results,
            weight_audit=weight_audit,
            request_metadata={"published_price_provided": published_price_provided},
        )
        if selected is None or not _valid_engine_output(selected):
            fallback_reason = "consensus_engine_unavailable"
            selected = None
    else:
        fallback_reason = "insufficient_distinct_engine_families"

    selected_name = selected.engine_name if selected is not None else None
    normalized = [
        _normalize_result(
            result,
            spec=spec,
            uf_to_clp=uf_to_clp,
            selected_name=selected_name,
        )
        for spec, result in zip(_ENGINE_SPECS, raw_results, strict=True)
    ]
    weights = _weights_from_consensus(selected, weight_audit)
    consensus = BetaConsensus(
        status="ok" if selected is not None else "insufficient_data",
        method=CONSENSUS_METHOD,
        estimate_uf=_decimal_float(selected.estimated_price_uf) if selected else None,
        estimate_clp=_decimal_int(selected.estimated_price_clp) if selected else None,
        range_low_uf=_clp_to_uf(selected.range_low_clp, uf_to_clp) if selected else None,
        range_high_uf=_clp_to_uf(selected.range_high_clp, uf_to_clp) if selected else None,
        confidence=selected.confidence if selected else None,
        selected_engine_names=[selected_name] if selected_name is not None else [],
        engine_weights=weights,
        consensus_used=selected is not None,
        valid_engine_count=len(valid_results),
        engine_family_count=len(valid_families),
        engine_families=valid_families,
        fallback_reason=fallback_reason,
    )
    _log.info(
        "valuation_consensus_completed method=%s selected=%s valid_families=%s statuses=%s",
        CONSENSUS_METHOD,
        selected_name or "fallback",
        valid_families,
        {item.engine_name: item.status for item in normalized},
    )
    return BetaConsensusRun(
        selected_result=selected,
        raw_results=raw_results,
        engine_results=normalized,
        consensus=consensus,
        weight_audit=weight_audit,
    )


def _run_engine(
    registry: EngineRegistry,
    spec: _EngineSpec,
    *,
    request: EngineRequest,
    context: EngineContext,
) -> EngineResult:
    try:
        engine = registry.get(spec.name)
    except UnknownValuationEngineError:
        return EngineResult(
            engine_name=spec.name,
            engine_version="unavailable",
            status=EngineStatus.NOT_APPLICABLE,
            warnings=("engine_not_registered",),
            error_code="engine_not_registered",
            error_message="Configured valuation engine is not registered",
        )
    try:
        return engine.valuate(replace(request, engine_name=spec.name), context)
    except Exception:  # pragma: no cover - defensive orchestration boundary
        _log.exception("valuation_consensus_engine_failed engine=%s", spec.name)
        return EngineResult(
            engine_name=spec.name,
            engine_version=engine.version,
            status=EngineStatus.ERROR,
            warnings=("unexpected_error",),
            error_code="unexpected_error",
            error_message="Valuation engine failed unexpectedly",
        )


def _run_consensus_engine(
    registry: EngineRegistry,
    *,
    context: EngineContext,
    engine_results: list[EngineResult],
    weight_audit: list[dict[str, Any]],
    request_metadata: dict[str, Any],
) -> EngineResult | None:
    try:
        consensus_engine = registry.get(CONSENSUS_ENGINE_NAME)
    except UnknownValuationEngineError:
        consensus_engine = ValoriaConsensusV1Engine()
    consensus_context = replace(
        context,
        metadata={
            **dict(context.metadata or {}),
            "engine_results": list(engine_results),
            "orchestrator": CONSENSUS_METHOD,
        },
        config={
            **dict(context.config or {}),
            "consensus_weights": {
                "segments": {
                    "global": {
                        "n_validation": 999,
                        "weights": _normalized_weights(weight_audit),
                    }
                }
            },
        },
    )
    request = EngineRequest(
        engine_name=CONSENSUS_ENGINE_NAME,
        metadata={
            **request_metadata,
            "engine_results": list(engine_results),
            "orchestrator": CONSENSUS_METHOD,
            "read_only": True,
        },
    )
    try:
        raw = consensus_engine.valuate(request, consensus_context)
    except Exception:  # pragma: no cover - defensive orchestration boundary
        _log.exception("valuation_consensus_engine_failed engine=%s", CONSENSUS_ENGINE_NAME)
        return None
    diagnostics = dict(raw.diagnostics or {})
    diagnostics.update({
        "engine_weights": _normalized_weights(weight_audit),
        "weights": _normalized_weights(weight_audit),
        "weight_audit": list(weight_audit),
        "consensus_method_version": CONSENSUS_METHOD,
        "range_low_uf": _clp_to_uf(raw.range_low_clp, context.uf_to_clp) if context.uf_to_clp else None,
        "range_high_uf": _clp_to_uf(raw.range_high_clp, context.uf_to_clp) if context.uf_to_clp else None,
    })
    return EngineResult(
        engine_name=raw.engine_name,
        engine_version=raw.engine_version,
        status=raw.status,
        estimated_price_clp=raw.estimated_price_clp,
        estimated_price_uf=raw.estimated_price_uf,
        range_low_clp=raw.range_low_clp,
        range_high_clp=raw.range_high_clp,
        confidence=raw.confidence,
        comparables_used=raw.comparables_used,
        warnings=raw.warnings,
        diagnostics=diagnostics,
        error_code=raw.error_code,
        error_message=raw.error_message,
        selected_comparables=raw.selected_comparables,
        coverage_status=raw.coverage_status,
    )


def _valid_results_by_family(results: list[EngineResult]) -> dict[str, EngineResult]:
    by_family: dict[str, EngineResult] = {}
    family_by_name = {spec.name: spec.family for spec in _ENGINE_SPECS}
    for result in results:
        family = family_by_name.get(result.engine_name)
        if family is None or not _valid_engine_output(result):
            continue
        current = by_family.get(family)
        if current is None or (result.confidence or 0.0) > (current.confidence or 0.0):
            by_family[family] = result
    return by_family


def _valid_engine_output(result: EngineResult) -> bool:
    if result.status not in {EngineStatus.OK, EngineStatus.SUCCESS}:
        return False
    estimate = _decimal_float(result.estimated_price_clp)
    if estimate is None or not isfinite(estimate) or estimate <= 0:
        return False
    return not result.error_code


def _build_weight_audit(
    context: EngineContext,
    raw_results: list[EngineResult],
    valid_results: list[EngineResult],
) -> list[dict[str, Any]]:
    property_type = normalize_property_type(context.target) if context.target is not None else "unknown"
    base_weights = _base_weights(property_type)
    center = _successful_estimate_center(valid_results)
    raw_weights: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    valid_names = {result.engine_name for result in valid_results}
    for result in raw_results:
        base_weight = float(base_weights.get(result.engine_name, 0.0))
        confidence_modifier = _confidence_modifier(result.confidence)
        coverage_modifier = _coverage_modifier(result.coverage_status or result.diagnostics.get("coverage"))
        disagreement_modifier = _disagreement_modifier(result, center)
        raw_weight = (
            base_weight * confidence_modifier * coverage_modifier * disagreement_modifier
            if result.engine_name in valid_names
            else 0.0
        )
        raw_weights[result.engine_name] = raw_weight
        rows.append({
            "engine_name": result.engine_name,
            "engine_family": _family_for_engine(result.engine_name),
            "status": result.status,
            "estimate_uf": _decimal_float(result.estimated_price_uf),
            "confidence": result.confidence,
            "coverage": result.coverage_status,
            "base_weight": round(base_weight, 6),
            "confidence_modifier": round(confidence_modifier, 6),
            "coverage_modifier": round(coverage_modifier, 6),
            "disagreement_modifier": round(disagreement_modifier, 6),
            "raw_weight": round(raw_weight, 6),
            "final_normalized_weight": 0.0,
            "weight_reason": "eligible" if raw_weight > 0 else "not eligible for consensus",
        })
    total = sum(raw_weights.values())
    if total <= 0 and valid_results:
        equal = 1.0 / len(valid_results)
        for row in rows:
            if row["engine_name"] in valid_names:
                row["final_normalized_weight"] = round(equal, 6)
        return rows
    if total > 0:
        for row in rows:
            row["final_normalized_weight"] = round(raw_weights[row["engine_name"]] / total, 6)
    return rows


def _base_weights(property_type: str) -> dict[str, float]:
    if property_type == "house":
        return {
            "comparables_canonical_outliers": 0.30,
            "microzone_geo_v1": 0.15,
            "hedonic_baseline_v1": 0.20,
            "land_building_v1": 0.25,
            "market_trends_v1": 0.10,
        }
    return {
        "comparables_canonical_outliers": 0.45,
        "microzone_geo_v1": 0.20,
        "hedonic_baseline_v1": 0.25,
        "land_building_v1": 0.00,
        "market_trends_v1": 0.10,
    }


def _normalize_result(
    result: EngineResult,
    *,
    spec: _EngineSpec,
    uf_to_clp: Decimal,
    selected_name: str | None,
) -> BetaEngineResult:
    selected = result.engine_name == selected_name
    return BetaEngineResult(
        engine_name=result.engine_name,
        engine_version=result.engine_version,
        engine_family=spec.family,
        role=spec.role,
        status=_public_status(result),
        estimate_uf=_decimal_float(result.estimated_price_uf),
        estimate_clp=_decimal_int(result.estimated_price_clp),
        range_low_uf=_clp_to_uf(result.range_low_clp, uf_to_clp),
        range_high_uf=_clp_to_uf(result.range_high_clp, uf_to_clp),
        confidence=result.confidence,
        comparables_count=result.comparables_used,
        selected_for_final=selected,
        warnings=_dedupe(result.warnings),
        safe_error_message=_safe_error_message(result),
        diagnostics={"family": spec.family, **dict(result.diagnostics or {})},
    )


def _public_status(result: EngineResult) -> str:
    if _valid_engine_output(result):
        return "ok"
    if result.status in {EngineStatus.ABSTAINED, EngineStatus.INSUFFICIENT_DATA}:
        return "insufficient_data"
    if result.status == EngineStatus.NOT_APPLICABLE:
        return "skipped"
    return "failed"


def _safe_error_message(result: EngineResult) -> str | None:
    status = _public_status(result)
    if status == "ok":
        return None
    if status == "insufficient_data":
        return "No hubo evidencia suficiente para que este motor participe."
    if status == "skipped":
        return "Este motor no aplica para esta tasacion."
    if result.status == EngineStatus.VALIDATION_ERROR:
        return "El motor no pudo validar los datos de entrada."
    return "El motor no pudo completar la tasacion."


def _weights_from_consensus(selected: EngineResult | None, weight_audit: list[dict[str, Any]]) -> dict[str, float]:
    if selected is not None:
        raw = selected.diagnostics.get("weights") or selected.diagnostics.get("engine_weights")
        if isinstance(raw, dict):
            return {str(key): float(value) for key, value in raw.items()}
    return _normalized_weights(weight_audit)


def _normalized_weights(weight_audit: list[dict[str, Any]]) -> dict[str, float]:
    return {
        str(row["engine_name"]): float(row["final_normalized_weight"])
        for row in weight_audit
        if float(row.get("final_normalized_weight") or 0.0) > 0
    }


def _successful_estimate_center(results: list[EngineResult]) -> Decimal | None:
    estimates = [
        result.estimated_price_clp
        for result in results
        if result.estimated_price_clp is not None and _valid_engine_output(result)
    ]
    return median(estimates) if estimates else None


def _confidence_modifier(confidence: float | None) -> float:
    if confidence is None:
        return 0.65
    if confidence < 0.35:
        return 0.35
    if confidence < 0.55:
        return 0.65
    if confidence < 0.75:
        return 0.85
    return 1.0


def _coverage_modifier(coverage: Any) -> float:
    text = str(coverage or "").lower()
    if "strong" in text:
        return 1.0
    if "acceptable" in text or "moderate" in text:
        return 0.85
    if "thin" in text or "fallback" in text or "weak" in text:
        return 0.65
    if "abstained" in text or "insufficient" in text:
        return 0.0
    return 0.75


def _disagreement_modifier(result: EngineResult, center: Decimal | None) -> float:
    if center is None or center <= 0 or result.estimated_price_clp is None:
        return 1.0
    if not result.estimated_price_clp.is_finite():
        return 1.0
    delta = abs(result.estimated_price_clp - center) / center
    if delta >= Decimal("0.35"):
        return 0.35
    if delta >= Decimal("0.25"):
        return 0.50
    if delta >= Decimal("0.15"):
        return 0.75
    return 1.0


def _family_for_engine(engine_name: str) -> str | None:
    spec = next((item for item in _ENGINE_SPECS if item.name == engine_name), None)
    return spec.family if spec else None


def _clp_to_uf(value: Decimal | None, uf_to_clp: Decimal) -> float | None:
    if value is None:
        return None
    return round(float(value / uf_to_clp), 2)


def _decimal_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _decimal_int(value: Decimal | None) -> int | None:
    if value is None or not value.is_finite():
        return None
    return round(value)


def _dedupe(values: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(values))
