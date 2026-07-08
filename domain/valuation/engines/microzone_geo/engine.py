"""Experimental microzone/geography valuation engine."""
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

MIN_CLEAN_LISTINGS = 5
MIN_MICROZONE_DEPTH = 3
ABSURD_MIN_PRICE_M2_UF = Decimal("5")
ABSURD_MAX_PRICE_M2_UF = Decimal("500")
WEAK_GEOCODE_RANK = geocode_precision_rank("street")


@dataclass(frozen=True)
class _GeoSample:
    listing: Listing
    price_m2_uf: Decimal
    microzone_id: str | None
    price_source: str
    price_confidence: str | None


class MicrozoneGeoV1Engine:
    """Read-only territorial price/m2 engine.

    The engine consumes only the target and candidate listings supplied in the
    EngineContext. It does not fetch data, mutate repositories, or participate
    in productive valuation unless explicitly wired by a caller.
    """

    name = "microzone_geo_v1"
    version = "microzone_geo_v1"

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        target = ValuationEngineInput.from_context(context)
        target_microzone_id = _microzone_id(context.target)
        target_precision = canonical_geocode_precision(target.geocode_precision)
        target_area = _positive_decimal(target.built_area_m2)
        if not target.property_type or not target.comuna or target_area is None:
            return _abstained(
                target=target,
                target_microzone_id=target_microzone_id,
                reason="insufficient_target_data",
                message="Target is missing property_type, comuna or built_area_m2",
            )

        same_comuna = _clean_samples(
            context.candidates,
            property_type=target.property_type,
            comuna=target.comuna,
        )
        if len(same_comuna) < MIN_CLEAN_LISTINGS:
            return _abstained(
                target=target,
                target_microzone_id=target_microzone_id,
                reason="insufficient_clean_listings",
                message="Not enough clean listings for territorial valuation",
                extra_diagnostics={
                    "same_comuna_count": len(same_comuna),
                    "clean_listings_count": len(same_comuna),
                    "target_geocode_precision": target_precision,
                },
            )

        same_comuna = _trim_outliers(same_comuna)
        same_microzone = [
            sample for sample in same_comuna if target_microzone_id and sample.microzone_id == target_microzone_id
        ]
        use_microzone = len(same_microzone) >= MIN_MICROZONE_DEPTH
        market_samples = same_microzone if use_microzone else same_comuna
        market_level = "microzone" if use_microzone else "comuna"

        prices = [sample.price_m2_uf for sample in market_samples]
        comuna_prices = [sample.price_m2_uf for sample in same_comuna]
        p25 = _percentile(prices, 0.25) if len(prices) >= 4 else None
        p75 = _percentile(prices, 0.75) if len(prices) >= 4 else None
        median_price = median(prices)
        comuna_median = median(comuna_prices)
        estimate_uf = median_price * target_area
        low_uf, high_uf = _range_uf(
            estimate_uf=estimate_uf,
            target_area=target_area,
            p25=p25,
            p75=p75,
            sample_count=len(market_samples),
        )
        warnings = _warnings(
            target_microzone_id=target_microzone_id,
            use_microzone=use_microzone,
            target_precision=target_precision,
            samples=market_samples,
            p25=p25,
            p75=p75,
            median_price=median_price,
        )
        confidence_components = _confidence_components(
            use_microzone=use_microzone,
            sample_count=len(market_samples),
            target_precision=target_precision,
            p25=p25,
            p75=p75,
            median_price=median_price,
            samples=market_samples,
        )
        confidence = _combine_confidence(confidence_components)
        diagnostics = {
            "method_version": self.version,
            "target_microzone_id": target_microzone_id,
            "target_geocode_precision": target_precision,
            "market_level_used": market_level,
            "clean_listings_count": len(same_comuna),
            "same_microzone_count": len(same_microzone),
            "same_comuna_count": len(same_comuna),
            "median_price_m2_uf": _float(median_price),
            "p25_price_m2_uf": _float(p25),
            "p75_price_m2_uf": _float(p75),
            "range_low_uf": _float(low_uf),
            "range_high_uf": _float(high_uf),
            "comuna_median_price_m2_uf": _float(comuna_median),
            "premium_vs_comuna_pct": _pct_delta(median_price, comuna_median),
            "dispersion_iqr": _dispersion_iqr(p25, p75, median_price),
            "provenance_breakdown": dict(Counter(sample.price_source for sample in market_samples)),
            "confidence_components": confidence_components,
            "data_quality": _data_quality(confidence),
            "coverage": _coverage(market_level, len(market_samples)),
            "explanation": _explanation(market_level, len(market_samples), target_microzone_id),
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
        "method_version": MicrozoneGeoV1Engine.version,
        "target_microzone_id": target_microzone_id,
        "target_geocode_precision": canonical_geocode_precision(target.geocode_precision),
        "market_level_used": None,
        "data_quality": "insufficient",
        "coverage": "abstained",
        "explanation": message,
        "read_only": True,
    }
    diagnostics.update(extra_diagnostics or {})
    return EngineResult(
        engine_name=MicrozoneGeoV1Engine.name,
        engine_version=MicrozoneGeoV1Engine.version,
        status=EngineStatus.ABSTAINED,
        warnings=(reason,),
        diagnostics=diagnostics,
        error_code=reason,
        error_message=message,
        coverage_status="abstained",
    )


def _clean_samples(candidates: Sequence[Listing], *, property_type: str, comuna: str) -> list[_GeoSample]:
    samples: list[_GeoSample] = []
    for listing in candidates:
        if not getattr(listing, "is_active", False):
            continue
        if str(listing.property_type or "").strip().lower() != str(property_type).strip().lower():
            continue
        if str(listing.comuna or "").strip().lower() != str(comuna).strip().lower():
            continue
        price_uf = _positive_decimal(listing.price_uf)
        area = _positive_decimal(listing.built_area_m2 or listing.usable_area_m2 or listing.m2)
        if price_uf is None or area is None:
            continue
        source = str(listing.price_uf_source or "unknown").strip().lower()
        if source == "legacy_unrecoverable":
            continue
        price_m2 = price_uf / area
        if price_m2 < ABSURD_MIN_PRICE_M2_UF or price_m2 > ABSURD_MAX_PRICE_M2_UF:
            continue
        samples.append(
            _GeoSample(
                listing=listing,
                price_m2_uf=price_m2,
                microzone_id=_microzone_id(listing),
                price_source=source,
                price_confidence=listing.price_uf_confidence,
            )
        )
    return samples


def _trim_outliers(samples: list[_GeoSample]) -> list[_GeoSample]:
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


def _warnings(
    *,
    target_microzone_id: str | None,
    use_microzone: bool,
    target_precision: str,
    samples: list[_GeoSample],
    p25: Decimal | None,
    p75: Decimal | None,
    median_price: Decimal,
) -> list[str]:
    warnings: list[str] = []
    if not target_microzone_id:
        warnings.extend(["weak_microzone", "comuna_level_fallback"])
    elif not use_microzone:
        warnings.append("insufficient_microzone_depth")
    if geocode_precision_rank(target_precision) < WEAK_GEOCODE_RANK:
        warnings.append("weak_geocoding")
    if _dispersion_iqr(p25, p75, median_price) is not None and _dispersion_iqr(p25, p75, median_price) > 0.35:
        warnings.append("high_microzone_dispersion")
    weak_sources = sum(1 for sample in samples if _weak_provenance(sample))
    if samples and weak_sources / len(samples) > 0.35:
        warnings.append("weak_price_provenance")
    return list(dict.fromkeys(warnings))


def _confidence_components(
    *,
    use_microzone: bool,
    sample_count: int,
    target_precision: str,
    p25: Decimal | None,
    p75: Decimal | None,
    median_price: Decimal,
    samples: list[_GeoSample],
) -> dict[str, float]:
    sample_component = min(1.0, sample_count / 20)
    geography_component = 1.0 if use_microzone else 0.45
    geocode_component = geocode_precision_rank(target_precision) / geocode_precision_rank("address")
    dispersion = _dispersion_iqr(p25, p75, median_price)
    dispersion_component = 0.65 if dispersion is None else max(0.25, min(1.0, 1.0 - dispersion))
    weak_sources = sum(1 for sample in samples if _weak_provenance(sample))
    provenance_component = 1.0 if not samples else max(0.35, 1.0 - weak_sources / len(samples))
    return {
        "sample_depth": round(sample_component, 3),
        "territorial_specificity": round(geography_component, 3),
        "geocode_precision": round(geocode_component, 3),
        "dispersion": round(dispersion_component, 3),
        "price_provenance": round(provenance_component, 3),
    }


def _combine_confidence(components: dict[str, float]) -> float:
    weights = {
        "sample_depth": 0.25,
        "territorial_specificity": 0.25,
        "geocode_precision": 0.15,
        "dispersion": 0.20,
        "price_provenance": 0.15,
    }
    return round(sum(components[key] * weight for key, weight in weights.items()), 3)


def _data_quality(confidence: float) -> str:
    if confidence >= 0.75:
        return "strong"
    if confidence >= 0.55:
        return "acceptable"
    if confidence >= 0.35:
        return "weak"
    return "poor"


def _coverage(market_level: str, sample_count: int) -> str:
    if market_level == "microzone" and sample_count >= 10:
        return "strong_microzone"
    if market_level == "microzone":
        return "thin_microzone"
    if sample_count >= 10:
        return "comuna_fallback"
    return "thin_comuna_fallback"


def _range_uf(
    *,
    estimate_uf: Decimal,
    target_area: Decimal,
    p25: Decimal | None,
    p75: Decimal | None,
    sample_count: int,
) -> tuple[Decimal, Decimal]:
    if p25 is not None and p75 is not None:
        return p25 * target_area, p75 * target_area
    spread = Decimal("0.15") if sample_count >= 10 else Decimal("0.25")
    return estimate_uf * (Decimal("1") - spread), estimate_uf * (Decimal("1") + spread)


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


def _pct_delta(value: Decimal, benchmark: Decimal) -> float | None:
    if benchmark <= 0:
        return None
    return round(float((value - benchmark) / benchmark * Decimal("100")), 2)


def _dispersion_iqr(p25: Decimal | None, p75: Decimal | None, median_price: Decimal) -> float | None:
    if p25 is None or p75 is None or median_price <= 0:
        return None
    return round(float((p75 - p25) / median_price), 4)


def _weak_provenance(sample: _GeoSample) -> bool:
    source = sample.price_source
    confidence = str(sample.price_confidence or "").strip().lower()
    return source in {"unknown", "estimated", "fallback"} or confidence in {"low", "very_low"}


def _explanation(market_level: str, sample_count: int, target_microzone_id: str | None) -> str:
    if market_level == "microzone":
        return f"Microzone median UF/m2 from {sample_count} clean active listings in {target_microzone_id}"
    return f"Comuna fallback median UF/m2 from {sample_count} clean active listings"


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
