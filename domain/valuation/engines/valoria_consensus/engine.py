"""Valoria consensus engine.

The consensus engine combines already-computed engine results. It does not run
base engines, query repositories, or mutate production behavior.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from core.normalization.geocode_precision import canonical_geocode_precision
from core.normalization.property_type import normalize_property_type
from domain.valuation.engines.contracts import (
    EngineContext,
    EngineRequest,
    EngineResult,
    EngineStatus,
)
from domain.valuation.engines.valoria_consensus.agreement import assess_agreement
from domain.valuation.engines.valoria_consensus.combination import (
    confidence_weights,
    normalize_weights,
    weighted_average,
    weighted_median,
)
from domain.valuation.engines.valoria_consensus.config import (
    CONSENSUS_ENGINE_NAME,
    CONSENSUS_ENGINE_VERSION,
    DEFAULT_CONFIG,
    ConsensusConfig,
)
from domain.valuation.engines.valoria_consensus.explain import build_explanations


class ValoriaConsensusEngine:
    name = CONSENSUS_ENGINE_NAME
    version = CONSENSUS_ENGINE_VERSION

    def __init__(self, config: ConsensusConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        engine_results = _engine_results_from_context(request, context)
        if not engine_results:
            return _failed(
                "no_engine_results",
                "No base engine results were provided",
                engine_name=self.name,
                engine_version=self.version,
                diagnostics={
                    "engines_received": [],
                    "engines_used": [],
                    "engines_abstained": {},
                    "disagreement_level": None,
                    "weights": {},
                },
            )

        target = context.target
        property_type = normalize_property_type(target) if target is not None else "unknown"
        segments = _segments_for_context(context, property_type=property_type)
        included, excluded = self._filter_results(engine_results, property_type=property_type)
        if not included:
            return _failed(
                "no_eligible_engines",
                "No base engine result passed consensus eligibility rules",
                engine_name=self.name,
                engine_version=self.version,
                diagnostics={
                    "engines_received": [result.engine_name for result in engine_results],
                    "engines_used": [],
                    "engines_abstained": excluded,
                    "excluded_engines": excluded,
                    "segments": segments,
                    "disagreement_level": None,
                    "weights": {},
                },
            )

        estimates = {result.engine_name: result.estimated_price_clp for result in included}
        estimates = {name: value for name, value in estimates.items() if value is not None}
        agreement = assess_agreement(
            estimates,
            moderate_threshold=self.config.moderate_disagreement_pct,
            weak_threshold=self.config.weak_disagreement_pct,
        )
        calibrated_weights = _calibrated_weights_for_segments(
            context.config,
            segments=segments,
            eligible_engines=tuple(estimates),
            min_validation_n=self.config.min_validation_n,
        )
        confidence_based = confidence_weights({result.engine_name: result.confidence for result in included})

        weight_reasons: dict[str, str] = {}
        warnings: list[str] = []
        if len(included) == 1:
            weights = {included[0].engine_name: 1.0}
            strategy = "single_engine"
            weight_reasons[included[0].engine_name] = "only eligible engine"
            estimate = included[0].estimated_price_clp
        elif agreement.max_relative_difference_pct >= self.config.extreme_disagreement_pct:
            weights = confidence_based or _equal_weights(estimates)
            strategy = "weighted_median_extreme_disagreement"
            estimate = weighted_median(estimates, weights)
            warnings.append("consensus_extreme_disagreement")
            weight_reasons = dict.fromkeys(estimates, "robust median due to extreme disagreement")
        elif calibrated_weights is not None:
            weights = calibrated_weights["weights"]
            strategy = f"calibrated:{calibrated_weights['segment']}"
            estimate = weighted_average(estimates, weights)
            weight_reasons = dict.fromkeys(estimates, f"validation-calibrated for {calibrated_weights['segment']}")
        else:
            weights = confidence_based or _equal_weights(estimates)
            strategy = "confidence_weighted_fallback"
            estimate = weighted_average(estimates, weights)
            warnings.append("consensus_missing_calibrated_weights")
            weight_reasons = dict.fromkeys(estimates, "confidence-weighted fallback")

        if estimate is None:
            return _failed(
                "missing_consensus_estimate",
                "Consensus estimate could not be calculated",
                engine_name=self.name,
                engine_version=self.version,
            )

        low, high = _combined_range(included, estimate=estimate, agreement_level=agreement.level)
        confidence = _consensus_confidence(included, weights, agreement.level)
        uf = _estimate_uf(estimate, context.uf_to_clp)

        diagnostics = {
            "config_version": self.config.version,
            "strategy": strategy,
            "segments": segments,
            "agreement": agreement.as_dict(),
            "disagreement_level": agreement.level,
            "engines_received": [result.engine_name for result in engine_results],
            "engines_used": [result.engine_name for result in included],
            "engines_abstained": excluded,
            "engines_excluded": excluded,
            "engine_estimates": {
                result.engine_name: {
                    "engine_version": result.engine_version,
                    "estimated_price_clp": float(result.estimated_price_clp or 0),
                    "range_low_clp": float(result.range_low_clp) if result.range_low_clp is not None else None,
                    "range_high_clp": float(result.range_high_clp) if result.range_high_clp is not None else None,
                    "confidence": result.confidence,
                    "status": result.status,
                    "warnings": list(result.warnings),
                }
                for result in included
            },
            "weights": weights,
            "weight_reasons": weight_reasons,
            "explanation": build_explanations(
                weights=weights,
                weight_reasons=weight_reasons,
                excluded=excluded,
                agreement_level=agreement.level,
            ),
        }
        warnings.extend(_agreement_warnings(agreement.level))

        return EngineResult(
            engine_name=self.name,
            engine_version=self.version,
            status=EngineStatus.OK,
            estimated_price_clp=estimate,
            estimated_price_uf=uf,
            range_low_clp=low,
            range_high_clp=high,
            confidence=confidence,
            comparables_used=sum((result.comparables_used or 0) for result in included),
            warnings=tuple(_dedupe(warnings)),
            diagnostics=diagnostics,
            coverage_status=agreement.level,
        )

    def _filter_results(
        self,
        results: Sequence[EngineResult],
        *,
        property_type: str,
    ) -> tuple[list[EngineResult], dict[str, str]]:
        included: list[EngineResult] = []
        excluded: dict[str, str] = {}
        for result in results:
            reason = self._exclusion_reason(result, property_type=property_type)
            if reason is not None:
                excluded[result.engine_name] = reason
                continue
            included.append(result)
        return included, excluded

    def _exclusion_reason(self, result: EngineResult, *, property_type: str) -> str | None:
        if result.engine_name == self.name:
            return "self_result_not_allowed"
        if result.status == EngineStatus.NOT_APPLICABLE:
            return "not_applicable"
        if result.status not in {EngineStatus.OK, EngineStatus.SUCCESS}:
            return "status_not_successful"
        if result.estimated_price_clp is None:
            return "missing_estimate"
        if result.confidence is None or result.confidence < self.config.min_confidence:
            return "low_confidence"
        if result.engine_name == "house_land_building" and property_type != "house":
            return "not_applicable_to_property_type"
        expected_version = self.config.expected_versions.get(result.engine_name)
        if expected_version and result.engine_version != expected_version:
            return "artifact_version_mismatch"
        if set(result.warnings) & set(self.config.blocking_warnings):
            return "blocking_warning"
        diagnostics = dict(result.diagnostics or {})
        if diagnostics.get("out_of_distribution") is True:
            return "out_of_distribution"
        if str(diagnostics.get("ood_status") or "").lower() in {"severe", "out_of_distribution"}:
            return "out_of_distribution"
        if diagnostics.get("missing_critical_data") is True:
            return "missing_critical_data"
        return None


def _engine_results_from_context(request: EngineRequest, context: EngineContext) -> list[EngineResult]:
    raw = context.metadata.get("engine_results") or request.metadata.get("engine_results") or []
    if isinstance(raw, Mapping):
        raw = list(raw.values())
    return [_coerce_result(item) for item in raw]


def _coerce_result(value: Any) -> EngineResult:
    if isinstance(value, EngineResult):
        return value
    if isinstance(value, Mapping):
        return EngineResult(**dict(value))
    raise TypeError(f"Unsupported engine result: {type(value).__name__}")


def _segments_for_context(context: EngineContext, *, property_type: str) -> list[str]:
    target = context.target
    metadata = dict(context.metadata or {})
    segments = ["global", property_type]
    if property_type == "house":
        land = getattr(target, "land_area_m2", None) if target is not None else None
        segments.append("house_with_land" if land and land > 0 else "house_without_land")

    precision = canonical_geocode_precision(getattr(target, "geocode_precision", None) if target is not None else None)
    segments.append("high_precision_geo" if precision == "address" else "low_precision_geo")

    density = str(metadata.get("density_level") or context.geo.get("density_level") or "unknown_density")
    if density in {"high", "low"}:
        segments.append(f"{density}_density_comuna")

    product = str(metadata.get("product_classification") or "unknown_product")
    if product == "standard_residential":
        segments.append("standard_product")
    elif product != "unknown_product":
        segments.append("special_product")

    if metadata.get("out_of_distribution") is True:
        segments.append("out_of_distribution")
    else:
        segments.append("in_distribution")
    return segments


def _calibrated_weights_for_segments(
    config: Mapping[str, Any],
    *,
    segments: Sequence[str],
    eligible_engines: tuple[str, ...],
    min_validation_n: int,
) -> dict[str, Any] | None:
    raw = config.get("consensus_weights") or config.get("consensus_calibration") or {}
    segment_map = raw.get("segments") if isinstance(raw, Mapping) else None
    if not isinstance(segment_map, Mapping):
        segment_map = raw if isinstance(raw, Mapping) else {}

    for segment in segments:
        row = segment_map.get(segment) if isinstance(segment_map, Mapping) else None
        if not isinstance(row, Mapping):
            continue
        n = int(row.get("n_validation") or row.get("n") or 0)
        weights = row.get("weights")
        if n < min_validation_n or not isinstance(weights, Mapping):
            continue
        normalized = normalize_weights({
            engine: float(weights.get(engine, 0.0))
            for engine in eligible_engines
        })
        if normalized:
            return {"segment": segment, "n_validation": n, "weights": normalized}
    return None


def _equal_weights(estimates: Mapping[str, Decimal]) -> dict[str, float]:
    if not estimates:
        return {}
    value = 1.0 / len(estimates)
    return dict.fromkeys(estimates, value)


def _combined_range(
    results: Sequence[EngineResult],
    *,
    estimate: Decimal,
    agreement_level: str,
) -> tuple[Decimal, Decimal]:
    lows = [result.range_low_clp or result.estimated_price_clp for result in results]
    highs = [result.range_high_clp or result.estimated_price_clp for result in results]
    lows = [value for value in lows if value is not None]
    highs = [value for value in highs if value is not None]
    low = min(lows) if lows else estimate
    high = max(highs) if highs else estimate
    if agreement_level == "weak":
        spread = max(high - low, Decimal("0"))
        low = max(Decimal("0"), low - spread * Decimal("0.25"))
        high = high + spread * Decimal("0.25")
    elif agreement_level == "moderate":
        spread = max(high - low, Decimal("0"))
        low = max(Decimal("0"), low - spread * Decimal("0.10"))
        high = high + spread * Decimal("0.10")
    return min(low, estimate), max(high, estimate)


def _consensus_confidence(
    results: Sequence[EngineResult],
    weights: Mapping[str, float],
    agreement_level: str,
) -> float:
    if not results:
        return 0.0
    confidence = sum((result.confidence or 0.0) * weights.get(result.engine_name, 0.0) for result in results)
    if confidence <= 0:
        confidence = sum(result.confidence or 0.0 for result in results) / len(results)
    factor = {"strong": 1.0, "moderate": 0.85, "weak": 0.60}.get(agreement_level, 0.75)
    return max(0.0, min(1.0, confidence * factor))


def _estimate_uf(estimate: Decimal, uf_to_clp: Decimal | None) -> Decimal | None:
    if uf_to_clp is None or uf_to_clp <= 0:
        return None
    return estimate / uf_to_clp


def _agreement_warnings(level: str) -> list[str]:
    if level == "weak":
        return ["consensus_weak_agreement"]
    if level == "moderate":
        return ["consensus_moderate_agreement"]
    return []


def _failed(
    code: str,
    message: str,
    *,
    engine_name: str = CONSENSUS_ENGINE_NAME,
    engine_version: str = CONSENSUS_ENGINE_VERSION,
    diagnostics: Mapping[str, Any] | None = None,
) -> EngineResult:
    return EngineResult(
        engine_name=engine_name,
        engine_version=engine_version,
        status=EngineStatus.INSUFFICIENT_DATA,
        warnings=(code,),
        diagnostics=dict(diagnostics or {}),
        error_code=code,
        error_message=message,
    )


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
