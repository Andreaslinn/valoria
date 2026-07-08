"""Comparable Quality v2 challenger for guarded/shadow valuation runs."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from core.entities.listing import Listing, Property
from core.normalization.property_type import normalize_property_type
from core.value_objects.score import Score
from domain.valuation.comparable_quality_v2 import (
    build_price_m2_reference,
    built_area,
    safe_price_m2_uf,
    weighted_median,
)


@dataclass(frozen=True)
class QualityV2Config:
    mode: str = "off"
    allowed_property_types: frozenset[str] = frozenset({"apartment"})
    blocked_comunas: frozenset[str] = frozenset({"estacion central", "la reina", "macul"})
    p90_risk_comunas: frozenset[str] = frozenset({"la reina", "las condes", "maipu", "nunoa"})
    min_valid_comparables: int = 5
    max_pool_dispersion: float = 75.0
    max_delta_vs_baseline_pct: float = 0.25


@dataclass(frozen=True)
class QualityV2Result:
    estimate_clp: int | None
    estimate_uf: float | None
    used: bool
    mode: str
    fallback_reason: str | None
    delta_vs_baseline_pct: float | None
    valid_comparables: int
    outlier_count: int
    pool_dispersion: float | None
    guardrails_passed: bool
    warnings: tuple[str, ...]

    def diagnostics(self) -> dict[str, object]:
        return {
            "quality_v2_estimate_uf": self.estimate_uf,
            "quality_v2_used": self.used,
            "quality_v2_mode": self.mode,
            "quality_v2_fallback_reason": self.fallback_reason,
            "quality_v2_delta_vs_baseline_pct": self.delta_vs_baseline_pct,
            "quality_v2_valid_comparables": self.valid_comparables,
            "quality_v2_outlier_count": self.outlier_count,
            "quality_v2_pool_dispersion": self.pool_dispersion,
            "quality_v2_guardrails_passed": self.guardrails_passed,
        }


def evaluate_quality_v2_challenger(
    *,
    target: Property,
    scored_comparables: Sequence[tuple[Score, Listing]],
    uf_to_clp: Decimal,
    baseline_estimate_clp: int,
    config: QualityV2Config,
) -> QualityV2Result:
    """Evaluate robust weighted median without subject price or benchmark error."""
    if config.mode == "off":
        return _result(mode="off", fallback_reason="mode_off")

    property_type = normalize_property_type(target)
    comuna = _normalize_comuna(target.comuna)
    if property_type not in config.allowed_property_types:
        return _result(mode=config.mode, fallback_reason="property_type_not_allowed")
    if config.mode == "guarded" and comuna in config.blocked_comunas:
        return _result(mode=config.mode, fallback_reason="blocked_comuna")

    values_and_weights = []
    valid_values = []
    for score, listing in scored_comparables:
        ppm2 = safe_price_m2_uf(listing, uf_to_clp)
        if ppm2 is None:
            continue
        values_and_weights.append((ppm2, score.value))
        valid_values.append(ppm2)
    valid_count = len(valid_values)
    if valid_count < config.min_valid_comparables:
        return _result(
            mode=config.mode,
            fallback_reason="insufficient_valid_comparables",
            valid_comparables=valid_count,
        )

    reference = build_price_m2_reference(valid_values)
    pool_dispersion = _dispersion_iqr_pct(reference)
    outlier_count = _outlier_count(valid_values, reference)
    if (
        config.mode == "guarded"
        and pool_dispersion is not None
        and pool_dispersion > config.max_pool_dispersion
    ):
        return _result(
            mode=config.mode,
            fallback_reason="pool_dispersion_too_high",
            valid_comparables=valid_count,
            outlier_count=outlier_count,
            pool_dispersion=pool_dispersion,
        )

    ppm2 = weighted_median(values_and_weights)
    target_area = built_area(target)
    if ppm2 is None or target_area is None or target_area <= 0:
        return _result(
            mode=config.mode,
            fallback_reason="robust_estimate_unavailable",
            valid_comparables=valid_count,
            outlier_count=outlier_count,
            pool_dispersion=pool_dispersion,
        )
    estimate_clp = round(Decimal(str(ppm2)) * Decimal(str(target_area)) * uf_to_clp)
    delta_pct = _delta_pct(estimate_clp, baseline_estimate_clp)
    if (
        config.mode == "guarded"
        and delta_pct is not None
        and abs(delta_pct) > config.max_delta_vs_baseline_pct
    ):
        return _result(
            mode=config.mode,
            estimate_clp=estimate_clp,
            estimate_uf=_clp_to_uf(estimate_clp, uf_to_clp),
            fallback_reason="delta_vs_baseline_too_high",
            delta_vs_baseline_pct=delta_pct,
            valid_comparables=valid_count,
            outlier_count=outlier_count,
            pool_dispersion=pool_dispersion,
        )

    warnings = []
    if comuna in config.p90_risk_comunas:
        warnings.append("quality_v2_p90_risk_comuna")
    return QualityV2Result(
        estimate_clp=estimate_clp,
        estimate_uf=_clp_to_uf(estimate_clp, uf_to_clp),
        used=config.mode == "guarded",
        mode=config.mode,
        fallback_reason=None,
        delta_vs_baseline_pct=delta_pct,
        valid_comparables=valid_count,
        outlier_count=outlier_count,
        pool_dispersion=pool_dispersion,
        guardrails_passed=True,
        warnings=tuple(warnings),
    )


def _result(
    *,
    mode: str,
    estimate_clp: int | None = None,
    estimate_uf: float | None = None,
    fallback_reason: str | None,
    delta_vs_baseline_pct: float | None = None,
    valid_comparables: int = 0,
    outlier_count: int = 0,
    pool_dispersion: float | None = None,
) -> QualityV2Result:
    return QualityV2Result(
        estimate_clp=estimate_clp,
        estimate_uf=estimate_uf,
        used=False,
        mode=mode,
        fallback_reason=fallback_reason,
        delta_vs_baseline_pct=delta_vs_baseline_pct,
        valid_comparables=valid_comparables,
        outlier_count=outlier_count,
        pool_dispersion=pool_dispersion,
        guardrails_passed=False,
        warnings=(fallback_reason,) if fallback_reason else (),
    )


def _dispersion_iqr_pct(reference) -> float | None:
    if reference.median is None or reference.median <= 0 or reference.iqr is None:
        return None
    return round(reference.iqr / reference.median * 100, 4)


def _outlier_count(values: Sequence[float], reference) -> int:
    if reference.median is None or reference.median <= 0:
        return 0
    lower = reference.median * 0.65
    upper = reference.median * 1.55
    return sum(value < lower or value > upper for value in values)


def _delta_pct(estimate_clp: int, baseline_estimate_clp: int) -> float | None:
    if baseline_estimate_clp <= 0:
        return None
    return round((estimate_clp - baseline_estimate_clp) / baseline_estimate_clp, 6)


def _clp_to_uf(value: int, uf_to_clp: Decimal) -> float:
    return round(float(Decimal(str(value)) / uf_to_clp), 2)


def _normalize_comuna(value: str | None) -> str:
    return str(value or "").strip().lower().replace("_", " ")
