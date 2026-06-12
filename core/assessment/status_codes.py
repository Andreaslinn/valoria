"""Stable status and risk codes shared by assessment/reporting layers.

This module intentionally centralizes string contracts only. Threshold values
stay in the reports that own those checks.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from core.assessment.beta_status import (
    COVERAGE_WEAK_BETA_STATUS_CODES,
    DatasetBetaStatus,
    PropertyTypeCoverageStatus,
    BetaStatus,
)

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_MISSING = "MISSING"
STATUS_NO_DATA = "NO_DATA"
STATUS_UNKNOWN = "UNKNOWN"

STATUS_ORDER = {STATUS_OK: 0, STATUS_WARNING: 1, STATUS_CRITICAL: 2}


class PipelineAlertCode:
    ACTIVE_LISTINGS_LOW = "active_listings_low"
    NEW_LISTINGS_LOW = "new_listings_low"
    PRICE_PARSE_RATE_LOW = "price_parse_rate_low"
    M2_PARSE_RATE_LOW = "m2_parse_rate_low"
    ROOMS_PARSE_RATE_LOW = "rooms_parse_rate_low"
    COMUNA_COVERAGE_LOW = "comuna_coverage_low"
    TOP_COMUNA_CONCENTRATION_HIGH = "top_comuna_concentration_high"
    USEFUL_COORDS_LOW = "useful_coords_low"
    MICROZONE_RATE_LOW = "microzone_rate_low"
    PRICE_HISTORY_USABLE_LOW = "price_history_usable_low"
    SINGLE_SOURCE_DEPENDENCY_HIGH = "single_source_dependency_high"


PIPELINE_ALERT_CODES = frozenset(
    {
        PipelineAlertCode.ACTIVE_LISTINGS_LOW,
        PipelineAlertCode.NEW_LISTINGS_LOW,
        PipelineAlertCode.PRICE_PARSE_RATE_LOW,
        PipelineAlertCode.M2_PARSE_RATE_LOW,
        PipelineAlertCode.ROOMS_PARSE_RATE_LOW,
        PipelineAlertCode.COMUNA_COVERAGE_LOW,
        PipelineAlertCode.TOP_COMUNA_CONCENTRATION_HIGH,
        PipelineAlertCode.USEFUL_COORDS_LOW,
        PipelineAlertCode.MICROZONE_RATE_LOW,
        PipelineAlertCode.PRICE_HISTORY_USABLE_LOW,
        PipelineAlertCode.SINGLE_SOURCE_DEPENDENCY_HIGH,
    }
)

PIPELINE_ALERT_ALIASES = {
    "m2_parse_rate_critical": PipelineAlertCode.M2_PARSE_RATE_LOW,
    "covered_comunas_low": PipelineAlertCode.COMUNA_COVERAGE_LOW,
}

PIPELINE_OPERATIONAL_BLOCKER_ALERT_CODES = frozenset(
    {
        PipelineAlertCode.ACTIVE_LISTINGS_LOW,
        PipelineAlertCode.PRICE_PARSE_RATE_LOW,
        PipelineAlertCode.M2_PARSE_RATE_LOW,
        PipelineAlertCode.COMUNA_COVERAGE_LOW,
    }
)


class ReadinessVerdict:
    READY_FOR_PRIVATE_BETA = "READY_FOR_PRIVATE_BETA"
    READY_WITH_LIMITATIONS = "READY_WITH_LIMITATIONS"
    NOT_READY = "NOT_READY"


class ReadinessCode:
    MISSING_PIPELINE_HEALTH = "missing_pipeline_health"
    PIPELINE_UNSTABLE = "pipeline_unstable"
    PIPELINE_OPERATIONAL_CRITICAL = "pipeline_operational_critical"
    PARSE_RATE_LOW = "parse_rate_low"
    SINGLE_SOURCE_DEPENDENCY = "single_source_dependency"
    LOW_NEW_LISTING_FLOW = "low_new_listing_flow"
    ACTIVE_LISTING_POOL_TOO_SMALL = "active_listing_pool_too_small"
    MISSING_DATASET_COVERAGE = "missing_dataset_coverage"
    LIMITED_RM_COVERAGE = "limited_rm_coverage"
    TOO_FEW_BETA_SUPPORTED_SEGMENTS = "too_few_beta_supported_segments"
    DATASET_TOO_SMALL = "dataset_too_small"
    HOUSES_WEAK_COVERAGE = "houses_weak_coverage"
    MISSING_GEOCODING_READINESS = "missing_geocoding_readiness"
    WEAK_GEOLOCATION = "weak_geolocation"
    DISTANCE_FEATURE_DEGRADED = "distance_feature_degraded"
    COMUNA_CENTROID_DOMINANCE = "comuna_centroid_dominance"
    MISSING_HOLDOUT_BENCHMARK = "missing_holdout_benchmark"
    HOLDOUT_BENCHMARK_NOT_OK = "holdout_benchmark_not_ok"
    HOLDOUT_TOO_SMALL = "holdout_too_small"
    HOLDOUT_COVERAGE_TOO_LOW = "holdout_coverage_too_low"
    HOLDOUT_ERROR_HIGH = "holdout_error_high"
    HOLDOUT_ERROR_ELEVATED = "holdout_error_elevated"
    HOUSE_HOLDOUT_ERROR_HIGH = "house_holdout_error_high"
    WEAK_HOLDOUT_SEGMENTS = "weak_holdout_segments"
    MISSING_CONFIDENCE_AUDIT = "missing_confidence_audit"
    CONFIDENCE_UNCALIBRATED = "confidence_uncalibrated"
    CONFIDENCE_NOT_PREDICTIVE = "confidence_not_predictive"
    CONFIDENCE_PARTIALLY_PREDICTIVE_ONLY = "confidence_partially_predictive_only"
    MISSING_COMPARABLE_QUALITY_EVIDENCE = "missing_comparable_quality_evidence"
    WEAK_COMPARABLE_QUALITY_DISTRIBUTION = "weak_comparable_quality_distribution"
    MIXED_COMPARABLE_QUALITY_DISTRIBUTION = "mixed_comparable_quality_distribution"
    HIGH_COMPARABLE_DISPERSION = "high_comparable_dispersion"
    RADAR_BETA_SAFETY_UNAVAILABLE = "radar_beta_safety_unavailable"
    RADAR_BETA_SAFE_RULES_NOT_VERIFIED = "radar_beta_safe_rules_not_verified"
    FEEDBACK_LOOP_NO_DATA_YET = "feedback_loop_no_data_yet"
    TEST_STATUS_UNKNOWN = "test_status_unknown"
    TESTS_FAILING = "tests_failing"


class CoverageBetaStatus:
    """Compatibility export for older imports.

    New code should import ``BetaStatus`` or ``DatasetBetaStatus`` from
    ``core.assessment.beta_status``.
    """

    BETA_READY = DatasetBetaStatus.BETA_READY
    CAUTION = DatasetBetaStatus.CAUTION
    HIDE_IN_BETA = DatasetBetaStatus.HIDE_IN_BETA
    NO_DATA = BetaStatus.NO_DATA
    WEAK_DATA = BetaStatus.WEAK_DATA
    EXPLORATORY = BetaStatus.EXPLORATORY
    BETA_SUPPORTED = BetaStatus.BETA_SUPPORTED
    STRONG_SAMPLE = BetaStatus.STRONG_SAMPLE


def normalize_pipeline_alert_code(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return PIPELINE_ALERT_ALIASES.get(text, text)


def pipeline_alert_codes_from_alerts(alerts: Iterable[Mapping[str, Any]]) -> set[str]:
    codes: set[str] = set()
    for alert in alerts:
        code = normalize_pipeline_alert_code(alert.get("code"))
        if code:
            codes.add(code)
    return codes


def is_pipeline_operational_blocker_alert(code: Any) -> bool:
    return normalize_pipeline_alert_code(code) in PIPELINE_OPERATIONAL_BLOCKER_ALERT_CODES
