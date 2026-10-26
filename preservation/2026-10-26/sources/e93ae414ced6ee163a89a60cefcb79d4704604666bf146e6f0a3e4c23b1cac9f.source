"""Experimental read-only hedonic baseline engine."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import log
from statistics import median
from typing import Any

from core.entities.listing import Listing
from core.normalization.geocode_precision import canonical_geocode_precision, geocode_precision_rank
from domain.valuation.engines.contracts import (
    EngineContext,
    EngineRequest,
    EngineResult,
    EngineStatus,
    ValuationEngineInput,
)

MIN_TRAINING_DATA = 6
MIN_MICROZONE_DEPTH = 4
ABSURD_MIN_PRICE_M2_UF = Decimal("5")
ABSURD_MAX_PRICE_M2_UF = Decimal("500")


@dataclass(frozen=True)
class _HedonicSample:
    listing: Listing
    price_m2_uf: Decimal
    built_area_m2: Decimal
    land_area_m2: Decimal | None
    bedrooms: int
    bathrooms: int
    parking: int
    microzone_id: str | None
    price_source: str
    price_confidence: str | None


class HedonicBaselineV1Engine:
    """Local, interpretable structural baseline.

    This engine trains nothing globally and persists no coefficients. It uses
    only the target and candidates supplied by the caller.
    """

    name = "hedonic_baseline_v1"
    version = "hedonic_baseline_v1"

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        target = ValuationEngineInput.from_context(context)
        target_microzone_id = _microzone_id(context.target)
        target_area = _positive_decimal(target.built_area_m2)
        property_type = str(target.property_type or "").strip().lower()
        if not property_type or not target.comuna or target_area is None:
            return _abstained(
                target=target,
                target_microzone_id=target_microzone_id,
                reason="insufficient_target_data",
                message="Target is missing property_type, comuna or built_area_m2",
            )

        clean, excluded_count = _clean_samples(
            context.candidates,
            property_type=property_type,
            comuna=target.comuna,
        )
        if len(clean) < MIN_TRAINING_DATA:
            return _abstained(
                target=target,
                target_microzone_id=target_microzone_id,
                reason="insufficient_training_data",
                message="Not enough clean structural candidates for hedonic baseline",
                extra_diagnostics={
                    "clean_candidates_count": len(clean),
                    "outliers_excluded": excluded_count,
                },
            )

        clean = _trim_outliers(clean)
        if len(clean) < MIN_TRAINING_DATA:
            return _abstained(
                target=target,
                target_microzone_id=target_microzone_id,
                reason="insufficient_training_data",
                message="Not enough clean candidates after outlier filtering",
                extra_diagnostics={
                    "clean_candidates_count": len(clean),
                    "outliers_excluded": excluded_count,
                },
            )

        microzone_samples = [
            sample for sample in clean if target_microzone_id and sample.microzone_id == target_microzone_id
        ]
        used_samples = microzone_samples if len(microzone_samples) >= MIN_MICROZONE_DEPTH else clean
        model_level = "microzone" if used_samples is microzone_samples else "comuna"
        prices = [sample.price_m2_uf for sample in used_samples]
        p25 = _percentile(prices, 0.25) if len(prices) >= 4 else None
        p75 = _percentile(prices, 0.75) if len(prices) >= 4 else None
        median_price = median(prices)
        adjustment = _structural_adjustment(target, used_samples, property_type=property_type)
        adjusted_price_m2 = median_price * Decimal(str(adjustment["factor"]))
        estimate_uf = adjusted_price_m2 * target_area
        low_uf, high_uf = _range_uf(
            target_area=target_area,
            factor=Decimal(str(adjustment["factor"])),
            estimate_uf=estimate_uf,
            p25=p25,
            p75=p75,
            sample_count=len(used_samples),
        )
        warnings = _warnings(
            target=target,
            property_type=property_type,
            model_level=model_level,
            target_microzone_id=target_microzone_id,
            p25=p25,
            p75=p75,
            median_price=median_price,
            samples=used_samples,
            adjustment=adjustment,
        )
        confidence_components = _confidence_components(
            target=target,
            property_type=property_type,
            sample_count=len(used_samples),
            model_level=model_level,
            p25=p25,
            p75=p75,
            median_price=median_price,
            samples=used_samples,
            adjustment=adjustment,
        )
        confidence = _combine_confidence(confidence_components)
        diagnostics = {
            "method_version": self.version,
            "model_type_used": "robust_adjusted_price_m2",
            "clean_candidates_count": len(clean),
            "property_type": property_type,
            "target_comuna": target.comuna,
            "target_microzone_id": target_microzone_id,
            "market_level_used": model_level,
            "used_features": adjustment["used_features"],
            "missing_features": adjustment["missing_features"],
            "median_price_m2_uf": _float(median_price),
            "adjusted_price_m2_uf": _float(adjusted_price_m2),
            "coefficients": None,
            "land_area_available": bool(target.land_area_m2 and target.land_area_m2 > 0),
            "land_area_candidate_count": sum(1 for sample in used_samples if sample.land_area_m2 is not None),
            "price_provenance_breakdown": dict(Counter(sample.price_source for sample in used_samples)),
            "outliers_excluded": excluded_count + (len(_clean_samples_no_trim(context.candidates, property_type, target.comuna)) - len(clean)),
            "p25_price_m2_uf": _float(p25),
            "p75_price_m2_uf": _float(p75),
            "range_low_uf": _float(low_uf),
            "range_high_uf": _float(high_uf),
            "attribute_medians": _attribute_medians(used_samples),
            "adjustment_details": adjustment,
            "confidence_components": confidence_components,
            "coverage": _coverage(len(used_samples), model_level, adjustment),
            "data_quality": _data_quality(confidence),
            "explanation": _explanation(property_type, len(used_samples), model_level),
            "asking_price_reference": True,
            "read_only": True,
            "request_engine_name": request.engine_name,
        }
        return EngineResult(
            engine_name=self.name,
            engine_version=self.version,
            status=EngineStatus.SUCCESS,
            estimated_price_uf=estimate_uf,
            estimated_price_clp=_uf_to_clp(estimate_uf, context.uf_to_clp),
            range_low_clp=_uf_to_clp(low_uf, context.uf_to_clp),
            range_high_clp=_uf_to_clp(high_uf, context.uf_to_clp),
            confidence=confidence,
            warnings=tuple(warnings),
            diagnostics=diagnostics,
            coverage_status=diagnostics["coverage"],
        )


def _abstained(
    *,
    target: ValuationEngineInput,
    target_microzone_id: str | None,
    reason: str,
    message: str,
    extra_diagnostics: dict[str, Any] | None = None,
) -> EngineResult:
    diagnostics = {
        "method_version": HedonicBaselineV1Engine.version,
        "model_type_used": None,
        "property_type": target.property_type,
        "target_comuna": target.comuna,
        "target_microzone_id": target_microzone_id,
        "coverage": "abstained",
        "data_quality": "insufficient",
        "explanation": message,
        "read_only": True,
    }
    diagnostics.update(extra_diagnostics or {})
    return EngineResult(
        engine_name=HedonicBaselineV1Engine.name,
        engine_version=HedonicBaselineV1Engine.version,
        status=EngineStatus.ABSTAINED,
        warnings=(reason,),
        diagnostics=diagnostics,
        error_code=reason,
        error_message=message,
        coverage_status="abstained",
    )


def _clean_samples(candidates: Sequence[Listing], *, property_type: str, comuna: str) -> tuple[list[_HedonicSample], int]:
    samples: list[_HedonicSample] = []
    excluded = 0
    for listing in candidates:
        sample = _sample_from_listing(listing, property_type=property_type, comuna=comuna)
        if sample is None:
            excluded += 1
            continue
        samples.append(sample)
    return samples, excluded


def _clean_samples_no_trim(candidates: Sequence[Listing], property_type: str, comuna: str) -> list[_HedonicSample]:
    return [
        sample
        for listing in candidates
        if (sample := _sample_from_listing(listing, property_type=property_type, comuna=comuna)) is not None
    ]


def _sample_from_listing(listing: Listing, *, property_type: str, comuna: str) -> _HedonicSample | None:
    if not getattr(listing, "is_active", False):
        return None
    if str(listing.property_type or "").strip().lower() != property_type:
        return None
    if str(listing.comuna or "").strip().lower() != str(comuna).strip().lower():
        return None
    price_uf = _positive_decimal(listing.price_uf)
    built_area = _positive_decimal(listing.built_area_m2 or listing.usable_area_m2 or listing.m2)
    if price_uf is None or built_area is None:
        return None
    if built_area < Decimal("15") or built_area > Decimal("1000"):
        return None
    source = str(listing.price_uf_source or "unknown").strip().lower()
    if source == "legacy_unrecoverable":
        return None
    if not _valid_int(getattr(listing, "bedrooms", None), low=0, high=12):
        return None
    if not _valid_int(getattr(listing, "bathrooms", None), low=0, high=10):
        return None
    if not _valid_int(getattr(listing, "parking", None), low=0, high=8):
        return None
    price_m2 = price_uf / built_area
    if price_m2 < ABSURD_MIN_PRICE_M2_UF or price_m2 > ABSURD_MAX_PRICE_M2_UF:
        return None
    return _HedonicSample(
        listing=listing,
        price_m2_uf=price_m2,
        built_area_m2=built_area,
        land_area_m2=_positive_decimal(listing.land_area_m2),
        bedrooms=int(listing.bedrooms or 0),
        bathrooms=int(listing.bathrooms or 0),
        parking=int(listing.parking or 0),
        microzone_id=_microzone_id(listing),
        price_source=source,
        price_confidence=listing.price_uf_confidence,
    )


def _trim_outliers(samples: list[_HedonicSample]) -> list[_HedonicSample]:
    if len(samples) < 8:
        return samples
    prices = [sample.price_m2_uf for sample in samples]
    p25 = _percentile(prices, 0.25)
    p75 = _percentile(prices, 0.75)
    iqr = p75 - p25
    if iqr <= 0:
        return samples
    low = p25 - iqr * Decimal("1.5")
    high = p75 + iqr * Decimal("1.5")
    return [sample for sample in samples if low <= sample.price_m2_uf <= high]


def _structural_adjustment(
    target: ValuationEngineInput,
    samples: list[_HedonicSample],
    *,
    property_type: str,
) -> dict[str, Any]:
    used: list[str] = ["built_area_m2"]
    missing: list[str] = []
    factors: dict[str, float] = {}
    target_area = _positive_decimal(target.built_area_m2) or Decimal("1")
    median_area = median([sample.built_area_m2 for sample in samples])
    area_factor = _clamp((float(target_area / median_area)) ** -0.08, 0.90, 1.10)
    factors["built_area_m2"] = round(area_factor, 4)

    for name, per_unit, low, high in (
        ("bedrooms", 0.015, -0.06, 0.06),
        ("bathrooms", 0.030, -0.09, 0.09),
        ("parking", 0.020, -0.06, 0.06),
    ):
        target_value = getattr(target, name)
        if target_value is None:
            missing.append(name)
            continue
        sample_median = median([getattr(sample, name) for sample in samples])
        delta = float(target_value) - float(sample_median)
        factors[name] = round(_clamp(1.0 + delta * per_unit, 1.0 + low, 1.0 + high), 4)
        used.append(name)

    if property_type == "house":
        target_land = _positive_decimal(target.land_area_m2)
        candidate_lands = [sample.land_area_m2 for sample in samples if sample.land_area_m2 is not None]
        if target_land is None:
            missing.append("land_area_m2")
            factors["land_area_m2"] = 0.88
        elif len(candidate_lands) < max(3, len(samples) // 3):
            used.append("land_area_m2")
            factors["land_area_m2"] = 0.94
        else:
            used.append("land_area_m2")
            median_land = median(candidate_lands)
            factors["land_area_m2"] = round(_clamp(1.0 + log(float(target_land / median_land)) * 0.05, 0.88, 1.12), 4)

    factor = 1.0
    for item in factors.values():
        factor *= item
    return {
        "factor": round(_clamp(factor, 0.75, 1.25), 4),
        "feature_factors": factors,
        "used_features": used,
        "missing_features": missing,
    }


def _warnings(
    *,
    target: ValuationEngineInput,
    property_type: str,
    model_level: str,
    target_microzone_id: str | None,
    p25: Decimal | None,
    p75: Decimal | None,
    median_price: Decimal,
    samples: list[_HedonicSample],
    adjustment: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if model_level != "microzone" or not target_microzone_id:
        warnings.append("weak_microzone")
    if geocode_precision_rank(canonical_geocode_precision(target.geocode_precision)) < geocode_precision_rank("street"):
        warnings.append("weak_geocoding")
    dispersion = _dispersion_iqr(p25, p75, median_price)
    if dispersion is not None and dispersion > 0.35:
        warnings.append("high_attribute_dispersion")
    weak_sources = sum(1 for sample in samples if _weak_provenance(sample))
    if samples and weak_sources / len(samples) > 0.35:
        warnings.append("weak_price_provenance")
    if property_type == "house" and "land_area_m2" in adjustment["missing_features"]:
        warnings.extend(["missing_land_area", "house_land_area_weak"])
    if len(adjustment["used_features"]) <= 2:
        warnings.extend(["weak_structural_signal", "fallback_used"])
    return list(dict.fromkeys(warnings))


def _confidence_components(
    *,
    target: ValuationEngineInput,
    property_type: str,
    sample_count: int,
    model_level: str,
    p25: Decimal | None,
    p75: Decimal | None,
    median_price: Decimal,
    samples: list[_HedonicSample],
    adjustment: dict[str, Any],
) -> dict[str, float]:
    sample_depth = min(1.0, sample_count / 25)
    dispersion = _dispersion_iqr(p25, p75, median_price)
    dispersion_component = 0.65 if dispersion is None else max(0.25, min(1.0, 1.0 - dispersion))
    feature_count = len(adjustment["used_features"])
    expected_features = 5 if property_type == "apartment" else 6
    structural_coverage = min(1.0, feature_count / expected_features)
    if property_type == "house":
        land_component = 1.0 if target.land_area_m2 and target.land_area_m2 > 0 else 0.35
    else:
        land_component = 1.0
    weak_sources = sum(1 for sample in samples if _weak_provenance(sample))
    provenance = 1.0 if not samples else max(0.35, 1.0 - weak_sources / len(samples))
    geo = 0.85 if model_level == "microzone" else 0.55
    if geocode_precision_rank(canonical_geocode_precision(target.geocode_precision)) < geocode_precision_rank("street"):
        geo *= 0.75
    fallback_penalty = 0.70 if len(adjustment["used_features"]) <= 2 else 1.0
    return {
        "sample_depth": round(sample_depth, 3),
        "price_m2_stability": round(dispersion_component, 3),
        "structural_coverage": round(structural_coverage, 3),
        "land_area_signal": round(land_component, 3),
        "price_provenance": round(provenance, 3),
        "geo_context": round(geo, 3),
        "fallback_penalty": round(fallback_penalty, 3),
    }


def _combine_confidence(components: dict[str, float]) -> float:
    weights = {
        "sample_depth": 0.20,
        "price_m2_stability": 0.20,
        "structural_coverage": 0.20,
        "land_area_signal": 0.15,
        "price_provenance": 0.15,
        "geo_context": 0.10,
    }
    base = sum(components[key] * weight for key, weight in weights.items())
    return round(base * components["fallback_penalty"], 3)


def _coverage(sample_count: int, model_level: str, adjustment: dict[str, Any]) -> str:
    if sample_count >= 15 and model_level == "microzone" and len(adjustment["used_features"]) >= 4:
        return "strong_structural_local"
    if sample_count >= 10 and len(adjustment["used_features"]) >= 4:
        return "acceptable_structural"
    return "thin_structural"


def _data_quality(confidence: float) -> str:
    if confidence >= 0.75:
        return "strong"
    if confidence >= 0.55:
        return "acceptable"
    if confidence >= 0.35:
        return "weak"
    return "poor"


def _range_uf(
    *,
    target_area: Decimal,
    factor: Decimal,
    estimate_uf: Decimal,
    p25: Decimal | None,
    p75: Decimal | None,
    sample_count: int,
) -> tuple[Decimal, Decimal]:
    if p25 is not None and p75 is not None:
        return p25 * factor * target_area, p75 * factor * target_area
    spread = Decimal("0.18") if sample_count >= 10 else Decimal("0.25")
    return estimate_uf * (Decimal("1") - spread), estimate_uf * (Decimal("1") + spread)


def _attribute_medians(samples: list[_HedonicSample]) -> dict[str, float]:
    result = {
        "built_area_m2": _float(median([sample.built_area_m2 for sample in samples])),
        "bedrooms": float(median([sample.bedrooms for sample in samples])),
        "bathrooms": float(median([sample.bathrooms for sample in samples])),
        "parking": float(median([sample.parking for sample in samples])),
    }
    lands = [sample.land_area_m2 for sample in samples if sample.land_area_m2 is not None]
    result["land_area_m2"] = _float(median(lands)) if lands else None
    return result


def _microzone_id(value: object | None) -> str | None:
    if value is None:
        return None
    direct = getattr(value, "microzone_id", None)
    if direct:
        return str(direct)
    metadata = getattr(value, "raw_metadata", None) or {}
    if not isinstance(metadata, dict):
        return None
    for key in ("microzone_id", "microzone", "microzone_key", "subcomuna", "neighborhood"):
        raw = metadata.get(key)
        if raw:
            return str(raw)
    nested = metadata.get("geographic_microzone") or metadata.get("microzone_geo") or {}
    if isinstance(nested, dict):
        raw = nested.get("microzone_id") or nested.get("id") or nested.get("key")
        if raw:
            return str(raw)
    return None


def _percentile(values: Iterable[Decimal], q: float) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(str(q)) * Decimal(len(ordered) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def _positive_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except Exception:
        return None
    if result <= 0:
        return None
    return result


def _uf_to_clp(value: Decimal, uf_to_clp: Decimal | None) -> Decimal | None:
    if uf_to_clp is None or uf_to_clp <= 0:
        return None
    return value * uf_to_clp


def _dispersion_iqr(p25: Decimal | None, p75: Decimal | None, median_price: Decimal) -> float | None:
    if p25 is None or p75 is None or median_price <= 0:
        return None
    return round(float((p75 - p25) / median_price), 4)


def _weak_provenance(sample: _HedonicSample) -> bool:
    source = sample.price_source
    confidence = str(sample.price_confidence or "").strip().lower()
    return source in {"unknown", "estimated", "fallback"} or confidence in {"low", "very_low"}


def _valid_int(value: Any, *, low: int, high: int) -> bool:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return False
    return low <= number <= high


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _explanation(property_type: str, sample_count: int, model_level: str) -> str:
    return f"Robust structural baseline for {property_type} using {sample_count} clean {model_level} candidates"


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
