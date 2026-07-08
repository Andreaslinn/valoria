"""Read-only experimental runner for Valoria valuation engines.

This module is intentionally not wired to productive services or endpoints. It
lets lab scripts/tests run multiple engines over the same preloaded context and
optionally combine successful results with valoria_consensus_v1.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from statistics import median
from typing import Any

from core.normalization.property_type import normalize_property_type
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

DEFAULT_LAB_ENGINE_NAMES = (
    "comparables_canonical_outliers",
    "microzone_geo_v1",
    "hedonic_baseline_v1",
    "land_building_v1",
    "market_trends_v1",
)
CONSENSUS_ENGINE_NAME = "valoria_consensus_v1"
LAB_CONSENSUS_METHOD_VERSION = "experimental_consensus_lab_v1"
CRITICAL_WEIGHT_WARNINGS = frozenset({
    "weak_microzone",
    "poor_geocoding_comparables",
    "single_source_comparables",
    "extreme_price_m2_dispersion",
    "missing_land_area",
    "insufficient_land_area_data",
})
BASE_WEIGHTS = {
    "apartment": {
        "comparables_canonical_outliers": 0.45,
        "hedonic_baseline_v1": 0.25,
        "microzone_geo_v1": 0.20,
        "land_building_v1": 0.00,
        "market_trends_v1": 0.10,
    },
    "house": {
        "comparables_canonical_outliers": 0.30,
        "hedonic_baseline_v1": 0.20,
        "microzone_geo_v1": 0.15,
        "land_building_v1": 0.25,
        "market_trends_v1": 0.10,
    },
}


@dataclass(frozen=True)
class ExperimentalLabRun:
    """Container for an experimental lab execution."""

    engine_results: list[EngineResult]
    consensus_result: EngineResult | None
    weight_audit: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_results": [result.to_dict() for result in self.engine_results],
            "consensus_result": self.consensus_result.to_dict() if self.consensus_result else None,
            "weight_audit": list(self.weight_audit),
            "valuation_verdict": _valuation_verdict(self.consensus_result),
            "engine_breakdown": _engine_breakdown(self.engine_results, self.weight_audit),
            "consensus_audit": _consensus_audit(self.consensus_result, self.weight_audit),
        }


def run_experimental_engine_lab(
    context: EngineContext,
    *,
    engine_names: list[str] | tuple[str, ...] = DEFAULT_LAB_ENGINE_NAMES,
    include_consensus: bool = True,
    registry: EngineRegistry | None = None,
    request_metadata: dict[str, Any] | None = None,
) -> ExperimentalLabRun:
    """Run experimental engines over a shared context.

    The caller must provide candidates/UF/target in ``context``. This function
    never fetches data or mutates repositories.
    """
    engine_registry = registry or experimental_engine_registry()
    names = [name for name in engine_names if name != CONSENSUS_ENGINE_NAME]
    results = [
        _run_one_engine(
            engine_registry,
            engine_name,
            context=context,
            request_metadata=request_metadata or {},
        )
        for engine_name in names
    ]
    weight_audit = build_weight_audit(context, results)
    consensus = None
    if include_consensus:
        consensus = _run_consensus(
            engine_registry,
            context=context,
            engine_results=results,
            weight_audit=weight_audit,
            request_metadata=request_metadata or {},
        )
    return ExperimentalLabRun(engine_results=results, consensus_result=consensus, weight_audit=weight_audit)


def build_weight_audit(context: EngineContext, engine_results: list[EngineResult]) -> list[dict[str, Any]]:
    """Build auditable experimental weights for future consensus/UI work."""
    property_type = normalize_property_type(context.target) if context.target is not None else "unknown"
    base_weights = BASE_WEIGHTS.get(property_type, {})
    useful_results = [result for result in engine_results if result.is_successful]
    fallback_equal_base = bool(useful_results) and not any(
        float(base_weights.get(result.engine_name, 0.0)) > 0 for result in useful_results
    )
    center = _successful_estimate_center(engine_results)
    rows: list[dict[str, Any]] = []
    raw_weights: dict[str, float] = {}
    for result in engine_results:
        base_weight = (
            1.0 / len(useful_results)
            if fallback_equal_base and result.is_successful
            else float(base_weights.get(result.engine_name, 0.0))
        )
        applicability_modifier = _applicability_modifier(result, property_type)
        confidence_modifier = _confidence_modifier(result.confidence)
        coverage_modifier = _coverage_modifier(result.coverage_status or result.diagnostics.get("coverage"))
        data_quality_modifier = _data_quality_modifier(result.diagnostics.get("data_quality"))
        disagreement_modifier = _disagreement_modifier(result, center)
        critical_warning_modifier = _critical_warning_modifier(result.warnings)
        if not result.is_successful:
            raw_weight = 0.0
            reason = f"not used: status={result.status}"
        elif applicability_modifier == 0.0:
            raw_weight = 0.0
            reason = "not applicable to property type"
        elif base_weight == 0.0:
            raw_weight = 0.0
            reason = "base weight is zero for this property type"
        else:
            raw_weight = (
                base_weight
                * applicability_modifier
                * confidence_modifier
                * coverage_modifier
                * data_quality_modifier
                * disagreement_modifier
                * critical_warning_modifier
            )
            reason = _weight_reason(
                confidence_modifier=confidence_modifier,
                coverage_modifier=coverage_modifier,
                data_quality_modifier=data_quality_modifier,
                disagreement_modifier=disagreement_modifier,
                critical_warning_modifier=critical_warning_modifier,
            )
        raw_weights[result.engine_name] = raw_weight
        rows.append({
            "engine_name": result.engine_name,
            "status": result.status,
            "estimate_uf": _decimal_float(result.estimated_price_uf),
            "confidence": result.confidence,
            "coverage": result.coverage_status,
            "data_quality": result.diagnostics.get("data_quality"),
            "base_weight": round(base_weight, 6),
            "applicability_modifier": round(applicability_modifier, 6),
            "confidence_modifier": round(confidence_modifier, 6),
            "coverage_modifier": round(coverage_modifier, 6),
            "data_quality_modifier": round(data_quality_modifier, 6),
            "disagreement_modifier": round(disagreement_modifier, 6),
            "critical_warning_modifier": round(critical_warning_modifier, 6),
            "raw_weight": round(raw_weight, 6),
            "final_normalized_weight": 0.0,
            "weight_reason": reason,
        })
    total = sum(raw_weights.values())
    if total > 0:
        for row in rows:
            row["final_normalized_weight"] = round(raw_weights[row["engine_name"]] / total, 6)
    return rows


def _run_one_engine(
    registry: EngineRegistry,
    engine_name: str,
    *,
    context: EngineContext,
    request_metadata: dict[str, Any],
) -> EngineResult:
    try:
        engine = registry.get(engine_name)
    except UnknownValuationEngineError:
        return _failed_engine_result(
            engine_name=engine_name,
            engine_version="unavailable",
            code="engine_not_registered",
            message="Experimental engine is not registered",
        )

    request = EngineRequest(
        engine_name=engine_name,
        metadata={
            **request_metadata,
            "orchestrator": "experimental_engine_lab",
            "read_only": True,
        },
    )
    try:
        return engine.valuate(request, context)
    except Exception as exc:  # pragma: no cover - exercised with test double
        return _failed_engine_result(
            engine_name=engine_name,
            engine_version=getattr(engine, "version", "unknown"),
            code="engine_execution_failed",
            message="Experimental engine failed during lab execution",
            exc=exc,
        )


def _run_consensus(
    registry: EngineRegistry,
    *,
    context: EngineContext,
    engine_results: list[EngineResult],
    weight_audit: list[dict[str, Any]],
    request_metadata: dict[str, Any],
) -> EngineResult:
    useful = [result for result in engine_results if result.is_successful]
    if len(useful) < 2:
        return _abstained_consensus(engine_results, weight_audit, code="insufficient_successful_engines")

    try:
        consensus_engine = registry.get(CONSENSUS_ENGINE_NAME)
    except UnknownValuationEngineError:
        return _failed_engine_result(
            engine_name=CONSENSUS_ENGINE_NAME,
            engine_version="unavailable",
            code="engine_not_registered",
            message="Experimental consensus engine is not registered",
        )
    consensus_context = replace(
        context,
        metadata={
            **dict(context.metadata or {}),
            "engine_results": list(engine_results),
            "orchestrator": "experimental_engine_lab",
        },
        config={
            **dict(context.config or {}),
            "consensus_weights": {
                "segments": {
                    "global": {
                        "n_validation": 999,
                        "weights": _normalized_weights_for_consensus(weight_audit),
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
            "orchestrator": "experimental_engine_lab",
            "read_only": True,
        },
    )
    try:
        raw = consensus_engine.valuate(request, consensus_context)
    except Exception as exc:  # pragma: no cover - defensive lab boundary
        return _failed_engine_result(
            engine_name=CONSENSUS_ENGINE_NAME,
            engine_version=getattr(consensus_engine, "version", "unknown"),
            code="consensus_execution_failed",
            message="Experimental consensus failed during lab execution",
            exc=exc,
        )
    return _with_lab_consensus_diagnostics(raw, engine_results, weight_audit)


def _abstained_consensus(engine_results: list[EngineResult], weight_audit: list[dict[str, Any]], *, code: str) -> EngineResult:
    diagnostics = _lab_consensus_diagnostics(engine_results)
    diagnostics.update({
        "disagreement_level": None,
        "weights": {},
        "engine_weights": {},
        "weight_audit": list(weight_audit),
        "consensus_method_version": LAB_CONSENSUS_METHOD_VERSION,
        "final_explanation": "Experimental consensus requires at least two successful engines",
        "explanation": "Experimental consensus requires at least two successful engines",
    })
    return EngineResult(
        engine_name=CONSENSUS_ENGINE_NAME,
        engine_version="valoria_consensus_v1",
        status=EngineStatus.ABSTAINED,
        warnings=(code,),
        diagnostics=diagnostics,
        error_code=code,
        error_message="Experimental consensus requires at least two successful engines",
        coverage_status="abstained",
    )


def _with_lab_consensus_diagnostics(
    raw: EngineResult,
    engine_results: list[EngineResult],
    weight_audit: list[dict[str, Any]],
) -> EngineResult:
    audited_weights = _normalized_weights_for_consensus(weight_audit)
    raw_diagnostics = dict(raw.diagnostics or {})
    diagnostics = {
        **raw_diagnostics,
        **_lab_consensus_diagnostics(engine_results),
        "engine_estimates": raw_diagnostics.get("engine_estimates", {}),
        "engine_weights": audited_weights,
        "weights": audited_weights,
        "weight_audit": list(weight_audit),
        "disagreement_level": raw_diagnostics.get("disagreement_level"),
        "consensus_method_version": LAB_CONSENSUS_METHOD_VERSION,
        "final_explanation": raw_diagnostics.get("explanation"),
        "range_low_uf": _clp_to_uf_from_result(raw.range_low_clp, raw),
        "range_high_uf": _clp_to_uf_from_result(raw.range_high_clp, raw),
    }
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


def _lab_consensus_diagnostics(engine_results: list[EngineResult]) -> dict[str, Any]:
    return {
        "engines_received": [result.engine_name for result in engine_results],
        "engines_used": [result.engine_name for result in engine_results if result.is_successful],
        "engines_abstained": {
            result.engine_name: result.error_code or result.status
            for result in engine_results
            if result.status in {
                EngineStatus.ABSTAINED,
                EngineStatus.INSUFFICIENT_DATA,
                EngineStatus.NOT_APPLICABLE,
                EngineStatus.VALIDATION_ERROR,
            }
        },
        "engines_failed": {
            result.engine_name: result.error_code or result.status
            for result in engine_results
            if result.status in {EngineStatus.FAILED, EngineStatus.ERROR}
        },
    }


def _failed_engine_result(
    *,
    engine_name: str,
    engine_version: str,
    code: str,
    message: str,
    exc: Exception | None = None,
) -> EngineResult:
    diagnostics = {
        "read_only": True,
        "orchestrator": "experimental_engine_lab",
    }
    if exc is not None:
        diagnostics.update({
            "error_type": type(exc).__name__,
            "error_message": _safe_error_message(exc),
        })
    return EngineResult(
        engine_name=engine_name,
        engine_version=engine_version,
        status=EngineStatus.FAILED,
        warnings=(code,),
        diagnostics=diagnostics,
        error_code=code,
        error_message=message,
    )


def _safe_error_message(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        return type(exc).__name__
    return text[:240]


def _normalized_weights_for_consensus(weight_audit: list[dict[str, Any]]) -> dict[str, float]:
    return {
        str(row["engine_name"]): float(row["final_normalized_weight"])
        for row in weight_audit
        if float(row.get("final_normalized_weight") or 0.0) > 0
    }


def _successful_estimate_center(engine_results: list[EngineResult]) -> Decimal | None:
    estimates = [
        result.estimated_price_clp
        for result in engine_results
        if result.is_successful and result.estimated_price_clp is not None
    ]
    if not estimates:
        return None
    return median(estimates)


def _applicability_modifier(result: EngineResult, property_type: str) -> float:
    if result.engine_name == "land_building_v1" and property_type != "house":
        return 0.0
    return 1.0


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
    if not text:
        return 0.75
    if "strong" in text:
        return 1.0
    if "acceptable" in text or "moderate" in text:
        return 0.85
    if "thin" in text or "fallback" in text or "weak" in text:
        return 0.65
    if "abstained" in text or "insufficient" in text:
        return 0.0
    return 0.75


def _data_quality_modifier(data_quality: Any) -> float:
    text = str(data_quality or "").lower()
    if text in {"strong", "good", "high"}:
        return 1.0
    if text in {"acceptable", "medium"}:
        return 0.85
    if text in {"weak", "low"}:
        return 0.60
    if text in {"poor", "insufficient"}:
        return 0.35
    return 0.75


def _disagreement_modifier(result: EngineResult, center: Decimal | None) -> float:
    if center is None or center <= 0 or result.estimated_price_clp is None:
        return 1.0
    delta = abs(result.estimated_price_clp - center) / center
    if delta >= Decimal("0.35"):
        return 0.35
    if delta >= Decimal("0.25"):
        return 0.50
    if delta >= Decimal("0.15"):
        return 0.75
    return 1.0


def _critical_warning_modifier(warnings: tuple[str, ...]) -> float:
    hits = set(warnings) & CRITICAL_WEIGHT_WARNINGS
    if not hits:
        return 1.0
    if len(hits) >= 2:
        return 0.55
    return 0.75


def _weight_reason(
    *,
    confidence_modifier: float,
    coverage_modifier: float,
    data_quality_modifier: float,
    disagreement_modifier: float,
    critical_warning_modifier: float,
) -> str:
    reasons: list[str] = []
    if confidence_modifier < 1:
        reasons.append("confidence adjusted")
    if coverage_modifier < 1:
        reasons.append("coverage adjusted")
    if data_quality_modifier < 1:
        reasons.append("data quality adjusted")
    if disagreement_modifier < 1:
        reasons.append("disagreement adjusted")
    if critical_warning_modifier < 1:
        reasons.append("critical warning adjusted")
    return ", ".join(reasons) if reasons else "full base weight retained"


def _valuation_verdict(consensus_result: EngineResult | None) -> dict[str, Any] | None:
    if consensus_result is None:
        return None
    return {
        "estimate_uf": _decimal_float(consensus_result.estimated_price_uf),
        "low_uf": _decimal_float(consensus_result.diagnostics.get("range_low_uf")),
        "high_uf": _decimal_float(consensus_result.diagnostics.get("range_high_uf")),
        "confidence": consensus_result.confidence,
        "explanation": consensus_result.diagnostics.get("final_explanation")
        or consensus_result.diagnostics.get("explanation")
        or consensus_result.error_message,
    }


def _engine_breakdown(engine_results: list[EngineResult], weight_audit: list[dict[str, Any]]) -> list[dict[str, Any]]:
    weight_by_name = {row["engine_name"]: row for row in weight_audit}
    return [
        {
            "engine_name": result.engine_name,
            "label": _engine_label(result.engine_name),
            "role": _engine_role(result.engine_name),
            "estimate_uf": _decimal_float(result.estimated_price_uf),
            "confidence": result.confidence,
            "weight": float(weight_by_name.get(result.engine_name, {}).get("final_normalized_weight", 0.0)),
            "status": result.status,
            "explanation": result.diagnostics.get("explanation") or result.error_message,
            "warning_flags": list(result.warnings),
        }
        for result in engine_results
    ]


def _consensus_audit(consensus_result: EngineResult | None, weight_audit: list[dict[str, Any]]) -> dict[str, Any]:
    diagnostics = dict(consensus_result.diagnostics or {}) if consensus_result else {}
    return {
        "weight_audit": list(weight_audit),
        "disagreement_level": diagnostics.get("disagreement_level"),
        "engines_used": diagnostics.get("engines_used", []),
        "engines_abstained": diagnostics.get("engines_abstained", {}),
        "engines_failed": diagnostics.get("engines_failed", {}),
    }


def _engine_label(engine_name: str) -> str:
    return {
        "comparables_canonical_outliers": "Comparables",
        "microzone_geo_v1": "Microzona",
        "hedonic_baseline_v1": "Hedonico",
        "land_building_v1": "Suelo/construccion",
        "market_trends_v1": "Tendencias",
    }.get(engine_name, engine_name)


def _engine_role(engine_name: str) -> str:
    if engine_name == "comparables_canonical_outliers":
        return "market_comparables"
    if engine_name == "microzone_geo_v1":
        return "territorial_signal"
    if engine_name == "hedonic_baseline_v1":
        return "structural_signal"
    if engine_name == "land_building_v1":
        return "house_land_building_signal"
    if engine_name == "market_trends_v1":
        return "time_trend_signal"
    return "experimental_signal"


def _decimal_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clp_to_uf_from_result(value: Any, result: EngineResult) -> float | None:
    if value is None or result.estimated_price_clp is None or result.estimated_price_uf is None:
        return None
    try:
        uf_to_clp = result.estimated_price_clp / result.estimated_price_uf
        if uf_to_clp <= 0:
            return None
        return float(Decimal(str(value)) / uf_to_clp)
    except Exception:
        return None
