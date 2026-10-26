"""Final valuation reliability guardrails.

This module does not estimate price or assign structural comparable quality.
It applies stability warnings and confidence penalties to the final AVM output.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from core.entities.listing import Listing, Property
from core.normalization.property_type import normalize_property_type as _property_type
from core.value_objects.score import Score
from domain.valuation.comparable_metrics import (
    HIGH_PRICE_M2_DISPERSION_PCT,
    LOW_COMPARABLE_COUNT_THRESHOLD,
    MIN_ADDRESS_LEVEL_RATIO,
    address_geocode_share,
    comparable_price_m2_iqr_pct,
    house_land_area_share,
    listings_from_scored,
    near_duplicate_share,
    unique_source_count,
)

LOW_COMPARABLE_COUNT = LOW_COMPARABLE_COUNT_THRESHOLD
MIN_SOURCE_DIVERSITY = 2
MIN_ADDRESS_SHARE = MIN_ADDRESS_LEVEL_RATIO
HIGH_DISPERSION_IQR_PCT = HIGH_PRICE_M2_DISPERSION_PCT
EXTREME_DISPERSION_IQR_PCT = 100.0
MAX_NEAR_DUPLICATE_SHARE = 0.15
MIN_HOUSE_LAND_AREA_SHARE = 0.50


@dataclass(frozen=True)
class ComparableReliability:
    confidence: Score
    warnings: tuple[str, ...]
    metrics: dict[str, float | int | str | None]


def assess_comparable_reliability(
    *,
    target: Property,
    scored_comparables: Sequence[tuple[Score, Listing]],
    base_confidence: Score,
) -> ComparableReliability:
    comparables = listings_from_scored(scored_comparables)
    warnings: list[str] = []
    n = len(comparables)

    if n < LOW_COMPARABLE_COUNT:
        warnings.append("low_comparable_count")

    source_count = unique_source_count(comparables)
    if n > 0 and source_count < MIN_SOURCE_DIVERSITY:
        warnings.append("single_source_comparables")

    address_share = address_geocode_share(target, comparables)
    if address_share < MIN_ADDRESS_SHARE:
        warnings.append("poor_geocoding_comparables")

    dispersion = comparable_price_m2_iqr_pct(comparables)
    if dispersion is not None and dispersion >= EXTREME_DISPERSION_IQR_PCT:
        warnings.append("extreme_price_m2_dispersion")
    elif dispersion is not None and dispersion >= HIGH_DISPERSION_IQR_PCT:
        warnings.append("high_price_m2_dispersion")

    duplicate_share = near_duplicate_share(comparables)
    if duplicate_share > MAX_NEAR_DUPLICATE_SHARE:
        warnings.append("near_duplicate_comparables")

    land_area_share = house_land_area_share(target, comparables)
    if land_area_share is not None and land_area_share < MIN_HOUSE_LAND_AREA_SHARE:
        warnings.append("house_land_area_weak")

    if _property_type(target) == "unknown":
        warnings.append("unknown_property_type")

    confidence = _apply_penalties(base_confidence.value, warnings)
    return ComparableReliability(
        confidence=Score.clamped(confidence),
        warnings=tuple(sorted(set(warnings))),
        metrics={
            "comparable_count": n,
            "unique_source_count": source_count,
            "address_geocode_share": round(address_share, 4),
            "price_m2_iqr_pct": round(dispersion, 2) if dispersion is not None else None,
            "near_duplicate_share": round(duplicate_share, 4),
            "house_land_area_share": round(land_area_share, 4) if land_area_share is not None else None,
        },
    )


def _apply_penalties(base: float, warnings: Sequence[str]) -> float:
    factor = 1.0
    if "low_comparable_count" in warnings:
        factor *= 0.88
    if "single_source_comparables" in warnings:
        factor *= 0.92
    if "poor_geocoding_comparables" in warnings:
        factor *= 0.86
    if "high_price_m2_dispersion" in warnings:
        factor *= 0.86
    if "extreme_price_m2_dispersion" in warnings:
        factor *= 0.72
    if "near_duplicate_comparables" in warnings:
        factor *= 0.82
    if "house_land_area_weak" in warnings:
        factor *= 0.90
    if "unknown_property_type" in warnings:
        factor *= 0.90
    return base * factor
