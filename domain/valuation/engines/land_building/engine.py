"""Experimental read-only land/building split engine for houses."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
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

MIN_LAND_CANDIDATES = 5
ABSURD_MIN_PRICE_M2_BUILT_UF = Decimal("5")
ABSURD_MAX_PRICE_M2_BUILT_UF = Decimal("500")
MIN_REASONABLE_BUILT_LAND_RATIO = Decimal("0.03")
MAX_REASONABLE_BUILT_LAND_RATIO = Decimal("2.50")
LAND_EQUIVALENT_WEIGHT = Decimal("0.25")


@dataclass(frozen=True)
class _LandBuildingSample:
    listing: Listing
    price_uf: Decimal
    built_area_m2: Decimal
    land_area_m2: Decimal
    built_land_ratio: Decimal
    price_m2_built_uf: Decimal
    equivalent_unit_uf: Decimal
    land_proxy_unit_uf: Decimal
    microzone_id: str | None
    price_source: str
    price_confidence: str | None


class LandBuildingV1Engine:
    """House-only split proxy for land and building value.

    The split is intentionally a local proxy, not a pure land appraisal model.
    It consumes only preloaded target/candidates and performs no writes.
    """

    name = "land_building_v1"
    version = "land_building_v1"

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        target = ValuationEngineInput.from_context(context)
        property_type = str(target.property_type or "").strip().lower()
        target_microzone_id = _microzone_id(context.target)
        if property_type != "house":
            return _abstained(
                target=target,
                reason="unsupported_property_type",
                message="land_building_v1 only supports houses",
                target_microzone_id=target_microzone_id,
            )

        target_built = _positive_decimal(target.built_area_m2)
        if target_built is None:
            return _abstained(
                target=target,
                reason="insufficient_target_data",
                message="Target house is missing built_area_m2",
                target_microzone_id=target_microzone_id,
            )
        target_land = _positive_decimal(target.land_area_m2)
        if target_land is None:
            return _abstained(
                target=target,
                reason="missing_land_area",
                message="Target house is missing land_area_m2, so land/building split is unsafe",
                target_microzone_id=target_microzone_id,
                warnings=("missing_land_area", "house_land_area_weak"),
                extra_diagnostics={"target_built_area_m2": _float(target_built)},
            )

        target_ratio = target_built / target_land
        if target_ratio < MIN_REASONABLE_BUILT_LAND_RATIO or target_ratio > MAX_REASONABLE_BUILT_LAND_RATIO:
            return _abstained(
                target=target,
                reason="insufficient_target_data",
                message="Target built/land ratio is outside supported range",
                target_microzone_id=target_microzone_id,
                warnings=("outlier_land_ratio",),
                extra_diagnostics={
                    "target_built_area_m2": _float(target_built),
                    "target_land_area_m2": _float(target_land),
                    "target_built_land_ratio": _float(target_ratio),
                },
            )

        samples, counts = _clean_samples(context.candidates, comuna=target.comuna or "")
        if len(samples) < MIN_LAND_CANDIDATES:
            return _abstained(
                target=target,
                reason="insufficient_land_area_data",
                message="Not enough clean house candidates with land_area_m2",
                target_microzone_id=target_microzone_id,
                extra_diagnostics={
                    **counts,
                    "target_built_area_m2": _float(target_built),
                    "target_land_area_m2": _float(target_land),
                    "target_built_land_ratio": _float(target_ratio),
                },
            )

        trimmed = _trim_outliers(samples)
        outliers_excluded = counts["outliers_excluded"] + len(samples) - len(trimmed)
        if len(trimmed) < MIN_LAND_CANDIDATES:
            return _abstained(
                target=target,
                reason="insufficient_land_area_data",
                message="Not enough clean house candidates after outlier filtering",
                target_microzone_id=target_microzone_id,
                extra_diagnostics={
                    **counts,
                    "outliers_excluded": outliers_excluded,
                    "target_built_area_m2": _float(target_built),
                    "target_land_area_m2": _float(target_land),
                    "target_built_land_ratio": _float(target_ratio),
                },
            )

        equivalent_units = [sample.equivalent_unit_uf for sample in trimmed]
        p25_unit = _percentile(equivalent_units, 0.25) if len(equivalent_units) >= 4 else None
        p75_unit = _percentile(equivalent_units, 0.75) if len(equivalent_units) >= 4 else None
        median_unit = median(equivalent_units)
        building_unit = median_unit
        land_unit = median_unit * LAND_EQUIVALENT_WEIGHT
        building_component_uf = building_unit * target_built
        land_component_uf = land_unit * target_land
        estimate_uf = building_component_uf + land_component_uf
        low_uf, high_uf = _range_uf(
            target_built=target_built,
            target_land=target_land,
            estimate_uf=estimate_uf,
            p25_unit=p25_unit,
            p75_unit=p75_unit,
        )
        median_ratio = median([sample.built_land_ratio for sample in trimmed])
        median_built = median([sample.built_area_m2 for sample in trimmed])
        median_land = median([sample.land_area_m2 for sample in trimmed])
        median_price_m2_built = median([sample.price_m2_built_uf for sample in trimmed])
        median_land_proxy = median([sample.land_proxy_unit_uf for sample in trimmed])
        land_share = land_component_uf / estimate_uf * Decimal("100") if estimate_uf > 0 else Decimal("0")
        building_share = Decimal("100") - land_share
        ratio_class = _ratio_classification(target_ratio, median_ratio)
        warnings = _warnings(
            target=target,
            target_microzone_id=target_microzone_id,
            target_ratio=target_ratio,
            median_ratio=median_ratio,
            samples=trimmed,
            p25_unit=p25_unit,
            p75_unit=p75_unit,
            median_unit=median_unit,
        )
        confidence_components = _confidence_components(
            target=target,
            sample_count=len(trimmed),
            samples=trimmed,
            p25_unit=p25_unit,
            p75_unit=p75_unit,
            median_unit=median_unit,
            target_ratio=target_ratio,
            median_ratio=median_ratio,
            warnings=warnings,
        )
        confidence = _combine_confidence(confidence_components)
        diagnostics = {
            "method_version": self.version,
            "model_type_used": "local_land_building_proxy",
            "property_type": property_type,
            "target_comuna": target.comuna,
            "target_microzone_id": target_microzone_id,
            "target_geocode_precision": canonical_geocode_precision(target.geocode_precision),
            "target_built_area_m2": _float(target_built),
            "target_land_area_m2": _float(target_land),
            "target_built_land_ratio": _float(target_ratio),
            "target_land_ratio_class": ratio_class,
            "clean_house_candidates_count": len(trimmed),
            "candidates_with_land_area_count": counts["candidates_with_land_area_count"],
            "candidates_without_land_area_count": counts["candidates_without_land_area_count"],
            "median_land_area_m2": _float(median_land),
            "median_built_area_m2": _float(median_built),
            "median_built_land_ratio": _float(median_ratio),
            "median_price_m2_built_uf": _float(median_price_m2_built),
            "median_price_m2_land_proxy_uf": _float(median_land_proxy),
            "equivalent_unit_uf": _float(median_unit),
            "estimated_land_component_uf": _float(land_component_uf),
            "estimated_building_component_uf": _float(building_component_uf),
            "land_component_share_pct": round(float(land_share), 2),
            "building_component_share_pct": round(float(building_share), 2),
            "range_low_uf": _float(low_uf),
            "range_high_uf": _float(high_uf),
            "outliers_excluded": outliers_excluded,
            "price_provenance_breakdown": dict(Counter(sample.price_source for sample in trimmed)),
            "confidence_components": confidence_components,
            "coverage": _coverage(len(trimmed), ratio_class),
            "data_quality": _data_quality(confidence),
            "explanation": _explanation(len(trimmed), ratio_class),
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
    reason: str,
    message: str,
    target_microzone_id: str | None,
    warnings: tuple[str, ...] | None = None,
    extra_diagnostics: dict[str, Any] | None = None,
) -> EngineResult:
    diagnostics = {
        "method_version": LandBuildingV1Engine.version,
        "model_type_used": None,
        "property_type": target.property_type,
        "target_comuna": target.comuna,
        "target_microzone_id": target_microzone_id,
        "target_land_area_m2": target.land_area_m2,
        "target_built_area_m2": target.built_area_m2,
        "coverage": "abstained",
        "data_quality": "insufficient",
        "explanation": message,
        "read_only": True,
    }
    diagnostics.update(extra_diagnostics or {})
    return EngineResult(
        engine_name=LandBuildingV1Engine.name,
        engine_version=LandBuildingV1Engine.version,
        status=EngineStatus.ABSTAINED,
        warnings=warnings or (reason,),
        diagnostics=diagnostics,
        error_code=reason,
        error_message=message,
        coverage_status="abstained",
    )


def _clean_samples(candidates: Sequence[Listing], *, comuna: str) -> tuple[list[_LandBuildingSample], dict[str, int]]:
    samples: list[_LandBuildingSample] = []
    counts = {
        "candidates_with_land_area_count": 0,
        "candidates_without_land_area_count": 0,
        "outliers_excluded": 0,
    }
    for listing in candidates:
        if not getattr(listing, "is_active", False):
            continue
        if str(listing.property_type or "").strip().lower() != "house":
            continue
        if str(listing.comuna or "").strip().lower() != str(comuna).strip().lower():
            continue
        if _positive_decimal(listing.land_area_m2) is None:
            counts["candidates_without_land_area_count"] += 1
            continue
        counts["candidates_with_land_area_count"] += 1
        sample = _sample_from_listing(listing)
        if sample is None:
            counts["outliers_excluded"] += 1
            continue
        samples.append(sample)
    return samples, counts


def _sample_from_listing(listing: Listing) -> _LandBuildingSample | None:
    price_uf = _positive_decimal(listing.price_uf)
    built = _positive_decimal(listing.built_area_m2 or listing.usable_area_m2 or listing.m2)
    land = _positive_decimal(listing.land_area_m2)
    if price_uf is None or built is None or land is None:
        return None
    source = str(listing.price_uf_source or "unknown").strip().lower()
    if source == "legacy_unrecoverable":
        return None
    if built < Decimal("20") or built > Decimal("1200") or land < Decimal("40") or land > Decimal("10000"):
        return None
    ratio = built / land
    if ratio < MIN_REASONABLE_BUILT_LAND_RATIO or ratio > MAX_REASONABLE_BUILT_LAND_RATIO:
        return None
    price_m2_built = price_uf / built
    if price_m2_built < ABSURD_MIN_PRICE_M2_BUILT_UF or price_m2_built > ABSURD_MAX_PRICE_M2_BUILT_UF:
        return None
    equivalent_area = built + land * LAND_EQUIVALENT_WEIGHT
    equivalent_unit = price_uf / equivalent_area
    return _LandBuildingSample(
        listing=listing,
        price_uf=price_uf,
        built_area_m2=built,
        land_area_m2=land,
        built_land_ratio=ratio,
        price_m2_built_uf=price_m2_built,
        equivalent_unit_uf=equivalent_unit,
        land_proxy_unit_uf=equivalent_unit * LAND_EQUIVALENT_WEIGHT,
        microzone_id=_microzone_id(listing),
        price_source=source,
        price_confidence=listing.price_uf_confidence,
    )


def _trim_outliers(samples: list[_LandBuildingSample]) -> list[_LandBuildingSample]:
    if len(samples) < 8:
        return samples
    units = [sample.equivalent_unit_uf for sample in samples]
    ratios = [sample.built_land_ratio for sample in samples]
    unit_low, unit_high = _iqr_bounds(units)
    ratio_low, ratio_high = _iqr_bounds(ratios)
    return [
        sample
        for sample in samples
        if unit_low <= sample.equivalent_unit_uf <= unit_high
        and ratio_low <= sample.built_land_ratio <= ratio_high
    ]


def _warnings(
    *,
    target: ValuationEngineInput,
    target_microzone_id: str | None,
    target_ratio: Decimal,
    median_ratio: Decimal,
    samples: list[_LandBuildingSample],
    p25_unit: Decimal | None,
    p75_unit: Decimal | None,
    median_unit: Decimal,
) -> list[str]:
    warnings: list[str] = []
    if not target_microzone_id:
        warnings.append("weak_microzone")
    if geocode_precision_rank(canonical_geocode_precision(target.geocode_precision)) < geocode_precision_rank("street"):
        warnings.append("weak_geocoding")
    if _dispersion_iqr(p25_unit, p75_unit, median_unit) is not None and _dispersion_iqr(p25_unit, p75_unit, median_unit) > 0.35:
        warnings.append("high_land_building_dispersion")
    weak_sources = sum(1 for sample in samples if _weak_provenance(sample))
    if samples and weak_sources / len(samples) > 0.35:
        warnings.append("weak_price_provenance")
    ratio_delta = abs(float(target_ratio / median_ratio) - 1.0) if median_ratio > 0 else 0.0
    if ratio_delta > 0.75:
        warnings.append("outlier_land_ratio")
    return list(dict.fromkeys(warnings))


def _confidence_components(
    *,
    target: ValuationEngineInput,
    sample_count: int,
    samples: list[_LandBuildingSample],
    p25_unit: Decimal | None,
    p75_unit: Decimal | None,
    median_unit: Decimal,
    target_ratio: Decimal,
    median_ratio: Decimal,
    warnings: list[str],
) -> dict[str, float]:
    land_area_signal = 1.0 if target.land_area_m2 and target.land_area_m2 > 0 else 0.0
    sample_depth = min(1.0, sample_count / 18)
    ratio_dispersion = _relative_iqr([sample.built_land_ratio for sample in samples])
    ratio_stability = 0.65 if ratio_dispersion is None else max(0.25, min(1.0, 1.0 - ratio_dispersion))
    price_dispersion = _dispersion_iqr(p25_unit, p75_unit, median_unit)
    price_stability = 0.65 if price_dispersion is None else max(0.25, min(1.0, 1.0 - price_dispersion))
    weak_sources = sum(1 for sample in samples if _weak_provenance(sample))
    provenance = 1.0 if not samples else max(0.35, 1.0 - weak_sources / len(samples))
    geocode = geocode_precision_rank(canonical_geocode_precision(target.geocode_precision)) / geocode_precision_rank("address")
    ratio_similarity = max(0.35, min(1.0, 1.0 - abs(float(target_ratio / median_ratio) - 1.0) * 0.35))
    fallback_penalty = 0.75 if "outlier_land_ratio" in warnings else 1.0
    return {
        "land_area_signal": round(land_area_signal, 3),
        "sample_depth": round(sample_depth, 3),
        "built_land_ratio_stability": round(ratio_stability, 3),
        "price_stability": round(price_stability, 3),
        "price_provenance": round(provenance, 3),
        "geocode_precision": round(geocode, 3),
        "target_ratio_similarity": round(ratio_similarity, 3),
        "fallback_penalty": round(fallback_penalty, 3),
    }


def _combine_confidence(components: dict[str, float]) -> float:
    weights = {
        "land_area_signal": 0.20,
        "sample_depth": 0.20,
        "built_land_ratio_stability": 0.15,
        "price_stability": 0.15,
        "price_provenance": 0.10,
        "geocode_precision": 0.10,
        "target_ratio_similarity": 0.10,
    }
    base = sum(components[key] * weight for key, weight in weights.items())
    return round(base * components["fallback_penalty"], 3)


def _coverage(sample_count: int, ratio_class: str) -> str:
    if sample_count >= 12 and ratio_class in {"standard_house", "large_land_house"}:
        return "strong_land_building"
    if sample_count >= MIN_LAND_CANDIDATES:
        return "thin_land_building"
    return "insufficient_land_building"


def _data_quality(confidence: float) -> str:
    if confidence >= 0.75:
        return "strong"
    if confidence >= 0.55:
        return "acceptable"
    if confidence >= 0.35:
        return "weak"
    return "poor"


def _ratio_classification(target_ratio: Decimal, median_ratio: Decimal) -> str:
    if target_ratio < median_ratio * Decimal("0.45"):
        return "land_dominant"
    if target_ratio < median_ratio * Decimal("0.75"):
        return "large_land_house"
    if target_ratio > median_ratio * Decimal("2.25"):
        return "possible_outlier"
    if target_ratio > median_ratio * Decimal("1.60"):
        return "building_dominant"
    return "standard_house"


def _range_uf(
    *,
    target_built: Decimal,
    target_land: Decimal,
    estimate_uf: Decimal,
    p25_unit: Decimal | None,
    p75_unit: Decimal | None,
) -> tuple[Decimal, Decimal]:
    equivalent_area = target_built + target_land * LAND_EQUIVALENT_WEIGHT
    if p25_unit is not None and p75_unit is not None:
        return p25_unit * equivalent_area, p75_unit * equivalent_area
    return estimate_uf * Decimal("0.75"), estimate_uf * Decimal("1.25")


def _iqr_bounds(values: list[Decimal]) -> tuple[Decimal, Decimal]:
    p25 = _percentile(values, 0.25)
    p75 = _percentile(values, 0.75)
    iqr = p75 - p25
    if iqr <= 0:
        return min(values), max(values)
    return p25 - iqr * Decimal("1.5"), p75 + iqr * Decimal("1.5")


def _relative_iqr(values: list[Decimal]) -> float | None:
    if len(values) < 4:
        return None
    p25 = _percentile(values, 0.25)
    p75 = _percentile(values, 0.75)
    med = median(values)
    return _dispersion_iqr(p25, p75, med)


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


def _dispersion_iqr(p25: Decimal | None, p75: Decimal | None, median_value: Decimal) -> float | None:
    if p25 is None or p75 is None or median_value <= 0:
        return None
    return round(float((p75 - p25) / median_value), 4)


def _weak_provenance(sample: _LandBuildingSample) -> bool:
    source = sample.price_source
    confidence = str(sample.price_confidence or "").strip().lower()
    return source in {"unknown", "estimated", "fallback"} or confidence in {"low", "very_low"}


def _explanation(sample_count: int, ratio_class: str) -> str:
    return f"Land/building proxy for house using {sample_count} clean land-area candidates; target class={ratio_class}"


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
