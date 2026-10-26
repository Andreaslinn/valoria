"""Robust local price-per-m2 filtering for canonical comparables."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median
from typing import Any

from core.entities.listing import Listing, Property
from core.normalization.property_type import normalize_property_type
from domain.geocoding.microzones import microzone_similarity_bonus
from domain.valuation.price_surface import m2_bucket_for, microzone_tokens_for
from domain.valuation.product_classification import ProductEvidence


@dataclass(frozen=True)
class RobustFilterConfig:
    min_iqr_samples: int = 8
    min_percentile_samples: int = 5
    iqr_multiplier: float = 2.0
    fallback_iqr_multiplier: float = 2.75
    max_deviation_ratio: float = 2.25
    min_deviation_ratio: float = 0.35
    house_high_tail_ratio: float = 1.85
    enable_house_high_tail: bool = True


@dataclass(frozen=True)
class LocalReference:
    level: str
    sample_count: int
    median_price_m2: float | None
    mad: float | None
    iqr: float | None
    p10: float | None
    p25: float | None
    p75: float | None
    p90: float | None
    lower_threshold: float | None
    upper_threshold: float | None
    method: str
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_reference_level": self.level,
            "local_sample_count": self.sample_count,
            "local_median_price_m2": _round(self.median_price_m2),
            "MAD": _round(self.mad),
            "IQR": _round(self.iqr),
            "p10": _round(self.p10),
            "p25": _round(self.p25),
            "p75": _round(self.p75),
            "p90": _round(self.p90),
            "lower_threshold": _round(self.lower_threshold),
            "upper_threshold": _round(self.upper_threshold),
            "method": self.method,
            "config": dict(self.config),
        }


@dataclass(frozen=True)
class RobustFilterResult:
    kept: tuple[Listing, ...]
    low_outliers: tuple[Listing, ...]
    high_outliers: tuple[Listing, ...]
    recovered: tuple[Listing, ...]
    reference: LocalReference
    fallback_used: bool = False


def robust_filter_listings(
    *,
    target: Property,
    listings: list[Listing],
    product_classes: dict[str, ProductEvidence],
    min_comparables: int,
    config: RobustFilterConfig | None = None,
) -> RobustFilterResult:
    """Filter candidate comparables using only the candidate pool distribution."""

    config = config or RobustFilterConfig()
    reference_pool = _reference_pool(target, listings, product_classes)
    reference = _local_reference(target=target, listings=reference_pool, config=config)
    if reference.lower_threshold is None or reference.upper_threshold is None:
        return RobustFilterResult(
            kept=tuple(listings),
            low_outliers=(),
            high_outliers=(),
            recovered=(),
            reference=reference,
            fallback_used=False,
        )

    kept: list[Listing] = []
    low: list[Listing] = []
    high: list[Listing] = []
    for listing in listings:
        ppm2 = price_per_m2(listing)
        if ppm2 is None:
            continue
        if ppm2 < reference.lower_threshold:
            low.append(listing)
        elif ppm2 > reference.upper_threshold:
            high.append(listing)
        else:
            kept.append(listing)

    if len(kept) >= min_comparables:
        return RobustFilterResult(
            kept=tuple(kept),
            low_outliers=tuple(low),
            high_outliers=tuple(high),
            recovered=(),
            reference=reference,
        )

    relaxed = _local_reference(target=target, listings=reference_pool, config=config, relaxed=True)
    recovered: list[Listing] = []
    recovered_kept: list[Listing] = []
    for listing in listings:
        ppm2 = price_per_m2(listing)
        if ppm2 is None:
            continue
        if relaxed.lower_threshold is not None and ppm2 < relaxed.lower_threshold:
            continue
        if relaxed.upper_threshold is not None and ppm2 > relaxed.upper_threshold:
            continue
        recovered_kept.append(listing)
        if listing not in kept:
            recovered.append(listing)

    return RobustFilterResult(
        kept=tuple(recovered_kept),
        low_outliers=tuple(item for item in listings if item not in recovered_kept and price_per_m2(item) is not None and price_per_m2(item) < (relaxed.lower_threshold or 0)),
        high_outliers=tuple(item for item in listings if item not in recovered_kept and price_per_m2(item) is not None and relaxed.upper_threshold is not None and price_per_m2(item) > relaxed.upper_threshold),
        recovered=tuple(recovered),
        reference=relaxed,
        fallback_used=True,
    )


def price_per_m2(listing: Listing) -> float | None:
    area = getattr(listing, "built_area_m2", None) or getattr(listing, "usable_area_m2", None) or listing.m2
    if area is None or area <= 0 or listing.price.clp <= 0:
        return None
    return float(Decimal(str(listing.price.clp)) / Decimal(str(area)))


def _reference_pool(
    target: Property,
    listings: list[Listing],
    product_classes: dict[str, ProductEvidence],
) -> list[Listing]:
    candidates = list(listings)
    target_tokens = set(microzone_tokens_for(target))
    if target_tokens:
        same_microzone = [
            listing
            for listing in candidates
            if target_tokens & set(microzone_tokens_for(listing))
            or microzone_similarity_bonus(target, listing)[0] > 0
        ]
        if len(same_microzone) >= 8:
            return same_microzone

    target_bucket = m2_bucket_for(target)
    bucket_product = [
        listing
        for listing in candidates
        if m2_bucket_for(listing) == target_bucket
        and product_classes.get(_key(listing), ProductEvidence("unknown", "unknown")).product_class
        in _target_product_group(product_classes)
    ]
    if len(bucket_product) >= 8:
        return bucket_product

    product = [
        listing
        for listing in candidates
        if product_classes.get(_key(listing), ProductEvidence("unknown", "unknown")).product_class
        in _target_product_group(product_classes)
    ]
    if len(product) >= 8:
        return product

    same_type = [
        listing for listing in candidates if normalize_property_type(listing) == normalize_property_type(target)
    ]
    return same_type or candidates


def _target_product_group(product_classes: dict[str, ProductEvidence]) -> set[str]:
    classes = {item.product_class for item in product_classes.values()}
    if "standard_residential" in classes:
        return {"standard_residential", "unknown"}
    return classes or {"unknown"}


def _local_reference(
    *,
    target: Property,
    listings: list[Listing],
    config: RobustFilterConfig,
    relaxed: bool = False,
) -> LocalReference:
    values = sorted(value for listing in listings if (value := price_per_m2(listing)) is not None)
    sample_count = len(values)
    config_payload = {
        "min_iqr_samples": config.min_iqr_samples,
        "min_percentile_samples": config.min_percentile_samples,
        "iqr_multiplier": config.iqr_multiplier,
        "fallback_iqr_multiplier": config.fallback_iqr_multiplier,
        "max_deviation_ratio": config.max_deviation_ratio,
        "min_deviation_ratio": config.min_deviation_ratio,
        "house_high_tail_ratio": config.house_high_tail_ratio,
        "enable_house_high_tail": config.enable_house_high_tail,
        "relaxed": relaxed,
    }
    if sample_count == 0:
        return LocalReference("insufficient", 0, None, None, None, None, None, None, None, None, None, "no_values", config_payload)

    med = float(median(values))
    p10 = _percentile(values, 10)
    p25 = _percentile(values, 25)
    p75 = _percentile(values, 75)
    p90 = _percentile(values, 90)
    mad = float(median([abs(value - med) for value in values]))
    iqr = p75 - p25

    if sample_count < config.min_percentile_samples:
        return LocalReference(
            _reference_level(target, listings),
            sample_count,
            med,
            mad,
            iqr,
            p10,
            p25,
            p75,
            p90,
            None,
            None,
            "sample_too_small",
            config_payload,
        )

    if sample_count >= config.min_iqr_samples and iqr > 0:
        multiplier = config.fallback_iqr_multiplier if relaxed else config.iqr_multiplier
        lower = p25 - multiplier * iqr
        upper = p75 + multiplier * iqr
        method = "iqr"
    elif relaxed:
        lower = min(values)
        upper = max(values)
        method = "percentile_relaxed_full_span"
    else:
        lower = p10
        upper = p90
        method = "percentile"

    lower = max(lower, med * config.min_deviation_ratio)
    upper = min(upper, med * (config.max_deviation_ratio + (0.35 if relaxed else 0.0)))
    if config.enable_house_high_tail and normalize_property_type(target) == "house":
        high_ratio = config.house_high_tail_ratio + (0.20 if relaxed else 0.0)
        upper = min(upper, med * high_ratio)
        method = f"{method}_house_high_tail"
    return LocalReference(
        _reference_level(target, listings),
        sample_count,
        med,
        mad,
        iqr,
        p10,
        p25,
        p75,
        p90,
        lower,
        upper,
        method,
        config_payload,
    )


def _reference_level(target: Property, listings: list[Listing]) -> str:
    tokens = set(microzone_tokens_for(target))
    if tokens and any(tokens & set(microzone_tokens_for(listing)) for listing in listings):
        return "microzone"
    target_bucket = m2_bucket_for(target)
    if any(m2_bucket_for(listing) == target_bucket for listing in listings):
        return "comuna_m2_bucket_product"
    return "comuna_property_type"


def _percentile(values: list[float], pct: int) -> float:
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * pct / 100
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    weight = rank - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _key(listing: Listing) -> str:
    if listing.id is not None:
        return f"id:{listing.id}"
    if listing.fingerprint:
        return f"fp:{listing.fingerprint}"
    return f"obj:{id(listing)}"


def _round(value: float | None) -> float | None:
    return round(float(value), 2) if value is not None else None
