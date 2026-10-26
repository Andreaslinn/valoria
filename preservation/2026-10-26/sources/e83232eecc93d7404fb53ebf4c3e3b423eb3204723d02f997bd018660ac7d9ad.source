"""Structural quality assessment for the comparable set used by a valuation.

This module is intentionally read-only from the pricing perspective: it scores
the health of the comparable set but does not change the estimated value.
It also does not apply confidence penalties; that belongs to reliability.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median
from typing import Any

from core.assessment.contracts import ComparableQualityMetricsPayload
from core.entities.listing import Listing, Property
from core.value_objects.score import Score
from domain.valuation.comparable_metrics import (
    HIGH_PRICE_M2_DISPERSION_PCT,
    LOW_COMPARABLE_COUNT_THRESHOLD,
    MIN_ADDRESS_LEVEL_RATIO,
    address_level_geo_ratio,
    listings_from_scored,
    m2_bucket_coverage,
    microzone_tokens,
    price_m2_iqr_pct,
    price_m2_values,
    property_type_consistency,
    ratio,
    round_optional,
    safe_mean,
    same_microzone_ratio,
    score_values,
    outlier_pressure as comparable_outlier_pressure,
)
from domain.valuation.price_surface import m2_bucket_for

QUALITY_LEVELS = {"poor", "weak", "acceptable", "strong"}


@dataclass(frozen=True)
class ComparableQuality:
    level: str
    risk_flags: tuple[str, ...]
    metrics: ComparableQualityMetricsPayload


def assess_comparable_quality(
    *,
    target: Property,
    scored_comparables: Sequence[tuple[Score, Listing]],
) -> ComparableQuality:
    """Return comparable-set quality metrics and explicit risk flags."""
    n = len(scored_comparables)
    scores = score_values(scored_comparables)
    listings = listings_from_scored(scored_comparables)
    comparable_price_m2_values = price_m2_values(listings)

    target_bucket = m2_bucket_for(target)
    target_microzones = microzone_tokens(target)

    same_comuna_count = sum(1 for listing in listings if listing.comuna == target.comuna)
    same_microzone_value = same_microzone_ratio(target_microzones, listings)

    dispersion = price_m2_iqr_pct(comparable_price_m2_values)
    outlier_pressure = comparable_outlier_pressure(comparable_price_m2_values)
    avg_score = safe_mean(scores)

    metrics: ComparableQualityMetricsPayload = {
        "n_comparables": n,
        "avg_similarity_score": round_optional(avg_score),
        "median_similarity_score": round_optional(median(scores) if scores else None),
        "price_per_m2_dispersion": round_optional(dispersion),
        "same_comuna_ratio": ratio(same_comuna_count, n),
        "same_microzone_ratio": round_optional(same_microzone_value),
        "address_level_geo_ratio": address_level_geo_ratio(listings),
        "m2_bucket_coverage": m2_bucket_coverage(target, listings),
        "target_m2_bucket": target_bucket,
        "property_type_consistency": property_type_consistency(target, listings),
        "outlier_pressure": round_optional(outlier_pressure),
    }

    flags = _risk_flags(metrics)
    level = _quality_level(metrics, flags)
    return ComparableQuality(level=level, risk_flags=tuple(flags), metrics=metrics)


def _risk_flags(metrics: ComparableQualityMetricsPayload) -> list[str]:
    flags: list[str] = []
    if metrics["n_comparables"] < LOW_COMPARABLE_COUNT_THRESHOLD:
        flags.append("low_comparable_count")
    dispersion = metrics["price_per_m2_dispersion"]
    if dispersion is not None and dispersion >= HIGH_PRICE_M2_DISPERSION_PCT:
        flags.append("high_dispersion")
    if (metrics["address_level_geo_ratio"] or 0.0) < MIN_ADDRESS_LEVEL_RATIO:
        flags.append("weak_geolocation")
    if (metrics["property_type_consistency"] or 0.0) < 1.0:
        flags.append("mixed_property_type")
    microzone_ratio = metrics["same_microzone_ratio"]
    if microzone_ratio is None or microzone_ratio < 0.20:
        flags.append("weak_microzone")
    if (metrics["m2_bucket_coverage"] or 0.0) < 0.50:
        flags.append("sparse_m2_bucket")
    return flags


def _quality_level(metrics: ComparableQualityMetricsPayload, flags: Sequence[str]) -> str:
    score = 100.0
    n = metrics["n_comparables"]
    avg_similarity = metrics["avg_similarity_score"] or 0.0
    dispersion = metrics["price_per_m2_dispersion"]
    outlier_pressure = metrics["outlier_pressure"] or 0.0

    if n < 5:
        score -= 45
    elif n < LOW_COMPARABLE_COUNT_THRESHOLD:
        score -= 35

    if avg_similarity < 0.55:
        score -= 20
    elif avg_similarity < 0.70:
        score -= 10

    if dispersion is not None:
        if dispersion >= 90:
            score -= 35
        elif dispersion >= HIGH_PRICE_M2_DISPERSION_PCT:
            score -= 25
        elif dispersion >= 35:
            score -= 10

    if outlier_pressure >= 0.25:
        score -= 15

    penalties = {
        "weak_geolocation": 15,
        "mixed_property_type": 40,
        "weak_microzone": 10,
        "sparse_m2_bucket": 15,
    }
    for flag in flags:
        score -= penalties.get(flag, 0)

    if score >= 80:
        return "strong"
    if score >= 60:
        return "acceptable"
    if score >= 40:
        return "weak"
    return "poor"
