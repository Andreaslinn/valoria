"""Shared comparable-set metric utilities.

These helpers are deliberately assessment-neutral: they measure the comparable
set, but they do not assign quality levels, warnings, confidence penalties, or
pricing adjustments.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from statistics import median

from core.entities.listing import Listing, Property
from core.normalization.property_type import normalize_property_type
from core.value_objects.score import Score
from domain.geocoding.microzones import signals_from_value
from domain.geocoding.quality import normalized_precision_for
from domain.valuation.price_surface import m2_bucket_for, price_per_m2

LOW_COMPARABLE_COUNT_THRESHOLD = 8
MIN_ADDRESS_LEVEL_RATIO = 0.30
HIGH_PRICE_M2_DISPERSION_PCT = 60.0


def listings_from_scored(scored_comparables: Sequence[tuple[Score, Listing]]) -> list[Listing]:
    return [listing for _, listing in scored_comparables]


def score_values(scored_comparables: Sequence[tuple[Score, Listing]]) -> list[float]:
    return [score.value for score, _ in scored_comparables]


def unique_source_count(listings: Sequence[Listing]) -> int:
    return len({str(listing.source or "unknown").strip().lower() for listing in listings})


def address_level_geo_ratio(values: Sequence[Property | Listing]) -> float | None:
    if not values:
        return None
    address_count = sum(1 for value in values if normalized_precision_for(value) == "address")
    return ratio(address_count, len(values))


def address_geocode_share(target: Property, comparables: Sequence[Listing]) -> float:
    share = address_level_geo_ratio([target, *comparables])
    return share if share is not None else 0.0


def price_m2_values(listings: Sequence[Listing]) -> list[float]:
    return [value for listing in listings if (value := price_per_m2(listing)) is not None]


def price_m2_iqr_pct(values: Sequence[float]) -> float | None:
    clean = sorted(value for value in values if value > 0)
    if len(clean) < 4:
        return None
    q1 = percentile(clean, 0.25)
    q3 = percentile(clean, 0.75)
    med = median(clean)
    if med <= 0:
        return None
    return ((q3 - q1) / med) * 100.0


def comparable_price_m2_iqr_pct(comparables: Sequence[Listing]) -> float | None:
    return price_m2_iqr_pct(price_m2_values(comparables))


def outlier_pressure(values: Sequence[float]) -> float:
    clean = sorted(value for value in values if value > 0)
    if len(clean) < 4:
        return 0.0
    q1 = percentile(clean, 0.25)
    q3 = percentile(clean, 0.75)
    iqr = q3 - q1
    if iqr <= 0:
        return 0.0
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    outliers = sum(1 for value in clean if value < low or value > high)
    return outliers / len(clean)


def same_microzone_ratio(target_tokens: set[str], listings: Sequence[Listing]) -> float | None:
    if not target_tokens:
        return None
    comparable_tokens = [microzone_tokens(listing) for listing in listings]
    usable = [tokens for tokens in comparable_tokens if tokens]
    if not usable:
        return None
    shared = sum(1 for tokens in usable if target_tokens & tokens)
    return shared / len(listings) if listings else None


def microzone_tokens(value: Property | Listing) -> set[str]:
    signals = signals_from_value(value)
    if signals.confidence < 0.55:
        return set()
    tokens = set(signals.landmark_tokens)
    if signals.nearby_metro:
        tokens.add(f"metro:{signals.nearby_metro}")
    if signals.nearby_avenue:
        tokens.add(f"avenue:{signals.nearby_avenue}")
    if signals.neighborhood_hint:
        tokens.add(f"neighborhood:{signals.neighborhood_hint}")
    if signals.intersection_hint:
        tokens.add(f"intersection:{signals.intersection_hint}")
    return tokens


def near_duplicate_share(comparables: Sequence[Listing]) -> float:
    if not comparables:
        return 0.0
    keys = Counter(near_duplicate_key(listing) for listing in comparables)
    duplicate_rows = sum(count - 1 for key, count in keys.items() if key and count > 1)
    return duplicate_rows / len(comparables)


def near_duplicate_key(listing: Listing) -> str | None:
    title = normalize_title(listing.title)
    area = built_area(listing)
    if not title or area is None or listing.price.clp <= 0:
        return None
    area_bucket = round(float(area) / 5.0) * 5
    price_bucket = round(float(listing.price.clp) / 500_000.0) * 500_000
    return "|".join(
        [
            str(listing.source or "").lower(),
            str(listing.comuna or "").lower(),
            normalize_property_type(listing),
            title[:80],
            str(area_bucket),
            str(price_bucket),
        ]
    )


def house_land_area_share(target: Property, comparables: Sequence[Listing]) -> float | None:
    if normalize_property_type(target) != "house":
        return None
    if not comparables:
        return 0.0
    with_land = sum(1 for listing in comparables if listing.land_area_m2 is not None and listing.land_area_m2 > 0)
    return with_land / len(comparables)


def built_area(value: Property | Listing) -> float | None:
    return getattr(value, "built_area_m2", None) or getattr(value, "usable_area_m2", None) or value.m2


def normalize_title(value: str | None) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def safe_mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round_optional(numerator / denominator)


def round_optional(value: float | None, *, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def percentile(sorted_values: Sequence[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = (len(sorted_values) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def m2_bucket_coverage(target: Property, listings: Sequence[Listing]) -> float | None:
    target_bucket = m2_bucket_for(target)
    same_bucket_count = sum(1 for listing in listings if m2_bucket_for(listing) == target_bucket)
    return ratio(same_bucket_count, len(listings))


def property_type_consistency(target: Property, listings: Sequence[Listing]) -> float | None:
    target_type = normalize_property_type(target)
    same_type_count = sum(1 for listing in listings if normalize_property_type(listing) == target_type)
    return ratio(same_type_count, len(listings))
