"""Factual beta-scope assessment for AVM valuation segments.

The goal is not to block results. It labels the data support behind a valuation
so beta users do not mistake exploratory output for robust market evidence.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from core.assessment.contracts import BetaScopeMetricsPayload, ComparableQualityMetricsPayload
from core.entities.listing import Listing, Property
from core.assessment.beta_status import BETA_STATUS_CODES, BetaStatus, beta_status_message
from core.normalization.property_type import normalize_property_type
from domain.valuation.comparable_quality import ComparableQuality
from domain.valuation.price_surface import m2_bucket_for

BETA_SCOPE_LEVELS = BETA_STATUS_CODES


@dataclass(frozen=True)
class BetaScopeAssessment:
    status: str
    flags: tuple[str, ...]
    metrics: BetaScopeMetricsPayload
    message: str


def assess_beta_scope(
    *,
    target: Property,
    candidate_pool: Sequence[Listing],
    comparable_quality: ComparableQuality | None = None,
    comparable_quality_level: str | None = None,
    comparable_quality_metrics: ComparableQualityMetricsPayload | None = None,
) -> BetaScopeAssessment:
    """Classify whether a comuna/property_type/m2 segment is beta-ready."""
    metrics = dict(comparable_quality_metrics or {})
    if comparable_quality is not None:
        comparable_quality_level = comparable_quality.level
        metrics.update(comparable_quality.metrics)

    target_type = normalize_property_type(target)
    target_bucket = m2_bucket_for(target)
    segment = [
        listing
        for listing in candidate_pool
        if listing.is_active
        and listing.comuna == target.comuna
        and normalize_property_type(listing) == target_type
    ]
    bucket_segment = [listing for listing in segment if m2_bucket_for(listing) == target_bucket]

    n_comparables = _int(metrics.get("n_comparables"))
    dispersion = _float(metrics.get("price_per_m2_dispersion"))
    address_ratio = _float(metrics.get("address_level_geo_ratio"))
    property_type_consistency = _float(metrics.get("property_type_consistency"))
    quality_level = str(comparable_quality_level or "unknown")

    scope_metrics: BetaScopeMetricsPayload = {
        "segment_sample_count": len(segment),
        "m2_bucket_sample_count": len(bucket_segment),
        "target_m2_bucket": target_bucket,
        "property_type": target_type,
        "comparable_quality_level": quality_level,
        "n_comparables": n_comparables,
        "price_per_m2_dispersion": dispersion,
        "address_level_geo_ratio": address_ratio,
        "property_type_consistency": property_type_consistency,
    }

    flags = _flags(scope_metrics)
    status = _status(scope_metrics, flags)
    return BetaScopeAssessment(
        status=status,
        flags=tuple(flags),
        metrics=scope_metrics,
        message=_message(status),
    )


def _flags(metrics: BetaScopeMetricsPayload) -> list[str]:
    flags: list[str] = []
    if metrics["segment_sample_count"] <= 0:
        flags.append("no_segment_sample")
    elif metrics["segment_sample_count"] < 8:
        flags.append("low_segment_sample")
    elif metrics["segment_sample_count"] < 30:
        flags.append("limited_segment_sample")

    if metrics["m2_bucket_sample_count"] < 5:
        flags.append("sparse_m2_bucket")

    if metrics["n_comparables"] < 5:
        flags.append("low_comparable_count")

    if metrics["comparable_quality_level"] in {"poor", "weak", "unknown"}:
        flags.append("weak_comparable_quality")

    dispersion = metrics["price_per_m2_dispersion"]
    if dispersion is not None and dispersion >= 60:
        flags.append("high_dispersion")

    address_ratio = metrics["address_level_geo_ratio"]
    if address_ratio is None or address_ratio < 0.05:
        flags.append("weak_geocode_quality")

    consistency = metrics["property_type_consistency"]
    if consistency is not None and consistency < 1.0:
        flags.append("mixed_property_type")
    return flags


def _status(metrics: BetaScopeMetricsPayload, flags: Sequence[str]) -> str:
    segment_count = metrics["segment_sample_count"]
    bucket_count = metrics["m2_bucket_sample_count"]
    n_comparables = metrics["n_comparables"]
    quality_level = metrics["comparable_quality_level"]
    dispersion = metrics["price_per_m2_dispersion"]
    address_ratio = metrics["address_level_geo_ratio"] or 0.0

    if segment_count <= 0 or n_comparables <= 0:
        return BetaStatus.NO_DATA
    if segment_count < 8 or n_comparables < 5:
        return BetaStatus.WEAK_DATA
    if (
        segment_count < 30
        or bucket_count < 8
        or quality_level in {"poor", "weak", "unknown"}
        or "mixed_property_type" in flags
        or (dispersion is not None and dispersion >= 60)
    ):
        return BetaStatus.EXPLORATORY
    if (
        segment_count >= 80
        and bucket_count >= 20
        and quality_level == "strong"
        and (dispersion is None or dispersion <= 35)
        and address_ratio >= 0.05
    ):
        return BetaStatus.STRONG_SAMPLE
    return BetaStatus.BETA_SUPPORTED


def _message(status: str) -> str:
    return beta_status_message(status)


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
