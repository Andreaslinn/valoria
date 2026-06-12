"""Typed payload contracts for critical assessment boundaries.

These contracts document the JSON-like shapes exchanged between services,
FastAPI, UI and audit scripts. They are intentionally narrow: domain entities
stay as dataclasses/value objects, while externally consumed payloads get stable
keys and optionality.
"""
from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class ConfidencePayload(TypedDict):
    confidence: str
    confidence_score: float | None
    confidence_label: str
    confidence_reasons: list[str]
    confidence_risk_flags: list[str]


class ComparableQualityMetricsPayload(TypedDict, total=False):
    n_comparables: int
    avg_similarity_score: float | None
    median_similarity_score: float | None
    price_per_m2_dispersion: float | None
    same_comuna_ratio: float | None
    same_microzone_ratio: float | None
    address_level_geo_ratio: float | None
    m2_bucket_coverage: float | None
    target_m2_bucket: str
    property_type_consistency: float | None
    outlier_pressure: float | None


class ComparableQualityPayload(TypedDict):
    comparable_quality_level: str | None
    comparable_quality_flags: list[str]
    comparable_quality_metrics: ComparableQualityMetricsPayload


class BetaScopeMetricsPayload(TypedDict, total=False):
    segment_sample_count: int
    m2_bucket_sample_count: int
    target_m2_bucket: str
    property_type: str
    comparable_quality_level: str
    n_comparables: int
    price_per_m2_dispersion: float | None
    address_level_geo_ratio: float | None
    property_type_consistency: float | None


class BetaScopePayload(TypedDict):
    beta_scope_status: str | None
    beta_scope_flags: list[str]
    beta_scope_metrics: BetaScopeMetricsPayload
    beta_scope_message: str | None


class ComparableOutPayload(TypedDict):
    listing_id: int | None
    title: str
    comuna: str
    price_uf: float
    price_clp: int
    m2: float | None
    built_area_m2: float | None
    land_area_m2: float | None
    usable_area_m2: float | None
    similarity: float
    url: str | None


class ValuationResultPayload(ConfidencePayload, ComparableQualityPayload, BetaScopePayload):
    base_estimated_price_uf: float | None
    base_estimated_price_clp: int | None
    estimated_price_uf: float | None
    estimated_price_clp: int | None
    price_range_low_uf: float | None
    price_range_high_uf: float | None
    price_range_low_clp: int | None
    price_range_high_clp: int | None
    comparable_count: int
    price_m2_uf: float | None
    status: str
    warnings: list[str]
    surface_adjustment_applied: bool
    surface_adjustment_weight: float
    surface_adjustment_reason: str | None
    comparables: list[ComparableOutPayload]


class RadarOpportunityPayload(ConfidencePayload):
    listing_id: int | None
    title: str
    comuna: str
    price_uf: float
    price_clp: int
    m2: float
    estimated_price_uf: float
    discount_pct: float
    score: float
    comparables_used: int
    url: str | None
    warnings: list[str]
    radar_verdict: str
    radar_verdict_message: str
    risk_flags: list[str]
    comparable_quality_level: str | None
    comparable_quality_flags: list[str]
    beta_scope_status: str | None
    beta_scope_message: str | None
    beta_scope_flags: list[str]
    estimated_value_uf: float | None
    estimated_value_clp: int | None
    price_currency: NotRequired[str | None]
    price_clp_snapshot: NotRequired[int | None]
    price_basis_used: NotRequired[str | None]
    price_data_quality: NotRequired[str | None]


class ReadinessSectionPayload(TypedDict, total=False):
    status: str
    summary: dict[str, Any]
    flags: list[str]
    blocking_risks: list[str]
    critical_risks: list[str]
    limitations: list[str]
    alerts: NotRequired[list[dict[str, Any]]]


class BetaReadinessReportPayload(TypedDict):
    generated_at: str
    verdict: str
    decision_rules: list[str]
    flags: list[str]
    blocking_risks: list[str]
    critical_risks: list[str]
    limitations: list[str]
    recommended_scope: dict[str, Any]
    strongest_segments: list[str]
    weakest_segments: list[str]
    sections: dict[str, ReadinessSectionPayload]
    inputs: dict[str, dict[str, Any]]
