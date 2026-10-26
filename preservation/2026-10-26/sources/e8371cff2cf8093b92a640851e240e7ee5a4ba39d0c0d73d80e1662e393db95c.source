"""Experimental read-only market trends engine."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from core.entities.listing import Listing
from domain.valuation.engines.contracts import (
    EngineContext,
    EngineRequest,
    EngineResult,
    EngineStatus,
    ValuationEngineInput,
)

RECENT_WINDOW_DAYS = 60
PREVIOUS_WINDOW_DAYS = 120
MIN_WINDOW_COUNT = 3
ABSURD_MIN_PRICE_M2_UF = Decimal("5")
ABSURD_MAX_PRICE_M2_UF = Decimal("500")


@dataclass(frozen=True)
class _TrendSample:
    listing: Listing
    observed_at: datetime
    price_m2_uf: Decimal
    microzone_id: str | None
    price_source: str
    price_confidence: str | None


class MarketTrendsV1Engine:
    """Local temporal trend signal from preloaded candidates."""

    name = "market_trends_v1"
    version = "market_trends_v1"

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        target = ValuationEngineInput.from_context(context)
        target_area = _positive_decimal(target.built_area_m2)
        target_microzone_id = _microzone_id(context.target)
        if not target.property_type or not target.comuna or target_area is None:
            return _abstained(
                target=target,
                target_microzone_id=target_microzone_id,
                reason="insufficient_target_data",
                message="Target is missing property_type, comuna or built_area_m2",
            )

        samples = _clean_samples(
            context.candidates,
            property_type=str(target.property_type),
            comuna=str(target.comuna),
        )
        if not samples:
            return _abstained(
                target=target,
                target_microzone_id=target_microzone_id,
                reason="insufficient_trend_data",
                message="No candidates with usable date and price for trend analysis",
            )

        anchor = max(sample.observed_at for sample in samples)
        microzone_samples = [
            sample for sample in samples if target_microzone_id and sample.microzone_id == target_microzone_id
        ]
        selected = microzone_samples if _has_two_windows(microzone_samples, anchor) else samples
        market_level = "microzone" if selected is microzone_samples else "comuna"
        recent, previous = _split_windows(selected, anchor)
        if len(recent) < MIN_WINDOW_COUNT or len(previous) < MIN_WINDOW_COUNT:
            return _abstained(
                target=target,
                target_microzone_id=target_microzone_id,
                reason="insufficient_trend_data",
                message="Not enough observations in recent and previous windows",
                extra_diagnostics={
                    "market_level_used": market_level,
                    "recent_count": len(recent),
                    "previous_count": len(previous),
                    "clean_candidates_count": len(samples),
                },
            )

        recent_prices = [sample.price_m2_uf for sample in recent]
        previous_prices = [sample.price_m2_uf for sample in previous]
        recent_median = median(recent_prices)
        previous_median = median(previous_prices)
        trend_pct = (recent_median - previous_median) / previous_median * Decimal("100")
        trend_direction = _trend_direction(trend_pct)
        volatility = _volatility_proxy(recent_prices + previous_prices)
        estimate_uf = recent_median * target_area
        low_uf, high_uf = _range_uf(estimate_uf=estimate_uf, volatility=volatility)
        warnings = _warnings(
            market_level=market_level,
            target_microzone_id=target_microzone_id,
            volatility=volatility,
            samples=selected,
            anchor=anchor,
        )
        confidence_components = _confidence_components(
            market_level=market_level,
            recent_count=len(recent),
            previous_count=len(previous),
            volatility=volatility,
            samples=selected,
            warnings=warnings,
        )
        confidence = _combine_confidence(confidence_components)
        diagnostics = {
            "method_version": self.version,
            "market_level_used": market_level,
            "target_microzone_id": target_microzone_id,
            "recent_window_days": RECENT_WINDOW_DAYS,
            "previous_window_days": PREVIOUS_WINDOW_DAYS,
            "recent_count": len(recent),
            "previous_count": len(previous),
            "recent_median_price_m2_uf": _float(recent_median),
            "previous_median_price_m2_uf": _float(previous_median),
            "trend_pct": round(float(trend_pct), 2),
            "trend_direction": trend_direction,
            "volatility_proxy": volatility,
            "freshness_breakdown": _freshness_breakdown(selected, anchor),
            "price_provenance_breakdown": dict(Counter(sample.price_source for sample in selected)),
            "confidence_components": confidence_components,
            "coverage": _coverage(market_level, len(recent), len(previous)),
            "data_quality": _data_quality(confidence),
            "explanation": _explanation(market_level, trend_direction, trend_pct),
            "range_low_uf": _float(low_uf),
            "range_high_uf": _float(high_uf),
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
        "method_version": MarketTrendsV1Engine.version,
        "target_microzone_id": target_microzone_id,
        "market_level_used": None,
        "coverage": "abstained",
        "data_quality": "insufficient",
        "explanation": message,
        "read_only": True,
    }
    diagnostics.update(extra_diagnostics or {})
    return EngineResult(
        engine_name=MarketTrendsV1Engine.name,
        engine_version=MarketTrendsV1Engine.version,
        status=EngineStatus.ABSTAINED,
        warnings=(reason,),
        diagnostics=diagnostics,
        error_code=reason,
        error_message=message,
        coverage_status="abstained",
    )


def _clean_samples(candidates: Sequence[Listing], *, property_type: str, comuna: str) -> list[_TrendSample]:
    samples: list[_TrendSample] = []
    for listing in candidates:
        if not getattr(listing, "is_active", False):
            continue
        if str(listing.property_type or "").strip().lower() != property_type.strip().lower():
            continue
        if str(listing.comuna or "").strip().lower() != comuna.strip().lower():
            continue
        observed_at = _observed_at(listing)
        price_uf = _positive_decimal(listing.price_uf)
        area = _positive_decimal(listing.built_area_m2 or listing.usable_area_m2 or listing.m2)
        if observed_at is None or price_uf is None or area is None:
            continue
        source = str(listing.price_uf_source or "unknown").strip().lower()
        if source == "legacy_unrecoverable":
            continue
        price_m2 = price_uf / area
        if price_m2 < ABSURD_MIN_PRICE_M2_UF or price_m2 > ABSURD_MAX_PRICE_M2_UF:
            continue
        samples.append(
            _TrendSample(
                listing=listing,
                observed_at=observed_at,
                price_m2_uf=price_m2,
                microzone_id=_microzone_id(listing),
                price_source=source,
                price_confidence=listing.price_uf_confidence,
            )
        )
    return samples


def _observed_at(listing: Listing) -> datetime | None:
    for value in (
        getattr(listing, "last_seen_at", None),
        getattr(listing, "scraped_at", None),
        (getattr(listing, "raw_metadata", None) or {}).get("observed_at"),
        (getattr(listing, "raw_metadata", None) or {}).get("created_at"),
        (getattr(listing, "raw_metadata", None) or {}).get("updated_at"),
    ):
        parsed = _datetime_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _datetime_or_none(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _has_two_windows(samples: list[_TrendSample], anchor: datetime) -> bool:
    recent, previous = _split_windows(samples, anchor)
    return len(recent) >= MIN_WINDOW_COUNT and len(previous) >= MIN_WINDOW_COUNT


def _split_windows(samples: list[_TrendSample], anchor: datetime) -> tuple[list[_TrendSample], list[_TrendSample]]:
    recent_cutoff = anchor - timedelta(days=RECENT_WINDOW_DAYS)
    previous_cutoff = recent_cutoff - timedelta(days=PREVIOUS_WINDOW_DAYS)
    recent = [sample for sample in samples if sample.observed_at >= recent_cutoff]
    previous = [sample for sample in samples if previous_cutoff <= sample.observed_at < recent_cutoff]
    return recent, previous


def _warnings(
    *,
    market_level: str,
    target_microzone_id: str | None,
    volatility: float | None,
    samples: list[_TrendSample],
    anchor: datetime,
) -> list[str]:
    warnings: list[str] = []
    if market_level == "comuna":
        warnings.append("comuna_level_fallback")
        if not target_microzone_id:
            warnings.append("weak_microzone")
    if volatility is not None and volatility > 0.30:
        warnings.append("high_trend_volatility")
    if any((anchor - sample.observed_at).days > RECENT_WINDOW_DAYS + PREVIOUS_WINDOW_DAYS for sample in samples):
        warnings.append("stale_market_data")
    weak_sources = sum(1 for sample in samples if _weak_provenance(sample))
    if samples and weak_sources / len(samples) > 0.35:
        warnings.append("weak_price_provenance")
    if market_level == "comuna":
        warnings.append("fallback_used")
    return list(dict.fromkeys(warnings))


def _confidence_components(
    *,
    market_level: str,
    recent_count: int,
    previous_count: int,
    volatility: float | None,
    samples: list[_TrendSample],
    warnings: list[str],
) -> dict[str, float]:
    depth = min(1.0, (recent_count + previous_count) / 20)
    locality = 1.0 if market_level == "microzone" else 0.55
    stability = 0.65 if volatility is None else max(0.25, min(1.0, 1.0 - volatility))
    weak_sources = sum(1 for sample in samples if _weak_provenance(sample))
    provenance = 1.0 if not samples else max(0.35, 1.0 - weak_sources / len(samples))
    fallback = 0.75 if "fallback_used" in warnings else 1.0
    return {
        "window_depth": round(depth, 3),
        "locality": round(locality, 3),
        "trend_stability": round(stability, 3),
        "price_provenance": round(provenance, 3),
        "fallback_penalty": round(fallback, 3),
    }


def _combine_confidence(components: dict[str, float]) -> float:
    base = (
        components["window_depth"] * 0.30
        + components["locality"] * 0.20
        + components["trend_stability"] * 0.25
        + components["price_provenance"] * 0.25
    )
    return round(base * components["fallback_penalty"], 3)


def _coverage(market_level: str, recent_count: int, previous_count: int) -> str:
    total = recent_count + previous_count
    if market_level == "microzone" and total >= 12:
        return "strong_trend"
    if total >= 8:
        return "acceptable_trend"
    return "thin_trend"


def _data_quality(confidence: float) -> str:
    if confidence >= 0.75:
        return "strong"
    if confidence >= 0.55:
        return "acceptable"
    if confidence >= 0.35:
        return "weak"
    return "poor"


def _range_uf(*, estimate_uf: Decimal, volatility: float | None) -> tuple[Decimal, Decimal]:
    spread = Decimal(str(max(0.10, min(0.30, volatility or 0.18))))
    return estimate_uf * (Decimal("1") - spread), estimate_uf * (Decimal("1") + spread)


def _volatility_proxy(values: list[Decimal]) -> float | None:
    if len(values) < 4:
        return None
    p25 = _percentile(values, 0.25)
    p75 = _percentile(values, 0.75)
    med = median(values)
    if med <= 0:
        return None
    return round(float((p75 - p25) / med), 4)


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


def _freshness_breakdown(samples: list[_TrendSample], anchor: datetime) -> dict[str, int]:
    return {
        "0_30_days": sum(1 for sample in samples if (anchor - sample.observed_at).days <= 30),
        "31_60_days": sum(1 for sample in samples if 30 < (anchor - sample.observed_at).days <= 60),
        "61_180_days": sum(1 for sample in samples if 60 < (anchor - sample.observed_at).days <= 180),
        "older": sum(1 for sample in samples if (anchor - sample.observed_at).days > 180),
    }


def _trend_direction(trend_pct: Decimal) -> str:
    if trend_pct >= Decimal("2"):
        return "up"
    if trend_pct <= Decimal("-2"):
        return "down"
    return "flat"


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


def _weak_provenance(sample: _TrendSample) -> bool:
    source = sample.price_source
    confidence = str(sample.price_confidence or "").strip().lower()
    return source in {"unknown", "estimated", "fallback"} or confidence in {"low", "very_low"}


def _explanation(market_level: str, direction: str, trend_pct: Decimal) -> str:
    return f"{market_level} asking-price trend is {direction} ({round(float(trend_pct), 2)}%)"


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
