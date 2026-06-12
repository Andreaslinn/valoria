"""Beta readiness report for AVM-v2.

Read-only operational audit. It aggregates existing reports and emits a blunt
verdict for private beta readiness without changing AVM behavior.

Usage:
    python scripts/beta_readiness_report.py
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.assessment.beta_status import (  # noqa: E402
    COVERAGE_WEAK_BETA_STATUS_CODES,
    BetaStatus,
    PropertyTypeCoverageStatus,
    dataset_beta_status_to_canonical,
)
from core.assessment.contracts import BetaReadinessReportPayload, ReadinessSectionPayload  # noqa: E402
from core.assessment.status_codes import (  # noqa: E402
    PIPELINE_OPERATIONAL_BLOCKER_ALERT_CODES,
    STATUS_CRITICAL,
    STATUS_MISSING,
    STATUS_NO_DATA,
    STATUS_OK,
    STATUS_UNKNOWN,
    STATUS_WARNING,
    ReadinessCode,
    ReadinessVerdict,
    pipeline_alert_codes_from_alerts,
)

DEFAULT_REPORTS_DIR = Path("reports")
DEFAULT_OUTPUT_DIR = Path("reports/beta_readiness")

READY_FOR_PRIVATE_BETA = ReadinessVerdict.READY_FOR_PRIVATE_BETA
READY_WITH_LIMITATIONS = ReadinessVerdict.READY_WITH_LIMITATIONS
NOT_READY = ReadinessVerdict.NOT_READY

CRITICAL_OPERATIONAL_PIPELINE_CODES = PIPELINE_OPERATIONAL_BLOCKER_ALERT_CODES


@dataclass(frozen=True)
class InputArtifact:
    key: str
    path: str | None
    found: bool
    error: str | None = None


def main() -> int:
    args = _parse_args()
    reports_dir = Path(args.reports_dir)
    output_dir = Path(args.output_dir)
    inputs, artifacts = collect_inputs(reports_dir)
    report = build_beta_readiness_report(inputs, artifacts=artifacts)
    md_path, json_path = write_report(report, output_dir=output_dir)
    print("== AVM Beta Readiness ==")
    print(f"verdict\t{report['verdict']}")
    print(f"blocking_risks\t{len(report['blocking_risks'])}")
    print(f"critical_risks\t{len(report['critical_risks'])}")
    print(f"markdown\t{md_path}")
    print(f"json\t{json_path}")
    return 0


def collect_inputs(reports_dir: Path = DEFAULT_REPORTS_DIR) -> tuple[dict[str, Any], dict[str, InputArtifact]]:
    specs = {
        "pipeline_health": reports_dir / "pipeline_health" / "latest.json",
        "dataset_coverage": _latest_matching(reports_dir / "dataset_coverage_audit", "dataset_coverage_audit_*.json"),
        "holdout_benchmark": reports_dir / "benchmark" / "holdout_report.json",
        "confidence_audit": reports_dir / "confidence" / "confidence_audit.json",
        "geocoding_readiness": reports_dir / "geocoding" / "geocoding_readiness.json",
        "feedback_summary": reports_dir / "valuation_feedback" / "valuation_feedback_summary.json",
        "test_status": _first_existing(
            [
                reports_dir / "test_status" / "latest.json",
                reports_dir / "pytest" / "latest.json",
                reports_dir / "test_results" / "latest.json",
            ]
        ),
    }
    inputs: dict[str, Any] = {}
    artifacts: dict[str, InputArtifact] = {}
    for key, path in specs.items():
        if path is None:
            artifacts[key] = InputArtifact(key=key, path=None, found=False)
            inputs[key] = None
            continue
        data, error = _read_json(path)
        artifacts[key] = InputArtifact(key=key, path=str(path), found=data is not None, error=error)
        inputs[key] = data
    return inputs, artifacts


def build_beta_readiness_report(
    inputs: dict[str, Any],
    *,
    artifacts: dict[str, InputArtifact] | None = None,
    generated_at: str | None = None,
) -> BetaReadinessReportPayload:
    artifacts = artifacts or {}
    sections = {
        "pipeline_health": evaluate_pipeline_health(inputs.get("pipeline_health")),
        "dataset_coverage": evaluate_dataset_coverage(inputs.get("dataset_coverage")),
        "geoquality": evaluate_geoquality(inputs.get("geocoding_readiness"), inputs.get("pipeline_health")),
        "benchmark": evaluate_benchmark(inputs.get("holdout_benchmark")),
        "confidence": evaluate_confidence(inputs.get("confidence_audit")),
        "comparable_quality": evaluate_comparable_quality(inputs.get("confidence_audit")),
        "radar_safety": evaluate_radar_safety(),
        "feedback": evaluate_feedback(inputs.get("feedback_summary")),
        "test_status": evaluate_test_status(inputs.get("test_status")),
    }
    flags = _unique_flag_list(sections, "flags")
    blocking_risks = _unique_flag_list(sections, "blocking_risks")
    critical_risks = _unique_flag_list(sections, "critical_risks")
    limitations = _unique_flag_list(sections, "limitations")
    verdict = decide_verdict(blocking_risks=blocking_risks, critical_risks=critical_risks, limitations=limitations)
    recommended_scope = recommended_beta_scope(sections)
    report = {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "decision_rules": decision_rules(),
        "flags": flags,
        "blocking_risks": blocking_risks,
        "critical_risks": critical_risks,
        "limitations": limitations,
        "recommended_scope": recommended_scope,
        "strongest_segments": strongest_segments(sections),
        "weakest_segments": weakest_segments(sections),
        "sections": sections,
        "inputs": {key: artifact.__dict__ for key, artifact in artifacts.items()},
    }
    return report


def evaluate_pipeline_health(data: dict[str, Any] | None) -> ReadinessSectionPayload:
    if not data:
        return _missing_section("pipeline_health", ReadinessCode.MISSING_PIPELINE_HEALTH)
    metrics = _dict(data.get("metrics"))
    alerts = [item for item in (data.get("alerts") or []) if isinstance(item, dict)]
    alert_codes = pipeline_alert_codes_from_alerts(alerts)
    flags: list[str] = []
    blocking: list[str] = []
    critical: list[str] = []
    limitations: list[str] = []

    status = str(data.get("status") or STATUS_UNKNOWN).upper()
    if status == STATUS_CRITICAL:
        flags.append(ReadinessCode.PIPELINE_UNSTABLE)
    if alert_codes & CRITICAL_OPERATIONAL_PIPELINE_CODES:
        blocking.append(ReadinessCode.PIPELINE_OPERATIONAL_CRITICAL)
    if _num(metrics.get("price_parse_rate_pct"), 100) < 95 or _num(metrics.get("m2_parse_rate_pct"), 100) < 90:
        flags.append(ReadinessCode.PARSE_RATE_LOW)
        critical.append(ReadinessCode.PARSE_RATE_LOW)
    if _num(metrics.get("top_source_pct"), 0) >= 95:
        flags.append(ReadinessCode.SINGLE_SOURCE_DEPENDENCY)
        critical.append(ReadinessCode.SINGLE_SOURCE_DEPENDENCY)
        limitations.append(ReadinessCode.SINGLE_SOURCE_DEPENDENCY)
    if _num(metrics.get("new_active_listings_since_baseline"), 1) < 5 and _dict(data.get("baseline")).get("available"):
        flags.append(ReadinessCode.LOW_NEW_LISTING_FLOW)
        critical.append(ReadinessCode.LOW_NEW_LISTING_FLOW)
    if _num(metrics.get("active_listings"), 0) < 500:
        blocking.append(ReadinessCode.ACTIVE_LISTING_POOL_TOO_SMALL)

    return {
        "status": status,
        "summary": {
            "active_listings": metrics.get("active_listings"),
            "new_active_listings_since_baseline": metrics.get("new_active_listings_since_baseline"),
            "price_parse_rate_pct": metrics.get("price_parse_rate_pct"),
            "m2_parse_rate_pct": metrics.get("m2_parse_rate_pct"),
            "rooms_parse_rate_pct": metrics.get("rooms_parse_rate_pct"),
            "top_source": metrics.get("top_source"),
            "top_source_pct": metrics.get("top_source_pct"),
            "useful_coords_pct": metrics.get("useful_coords_pct"),
            "useful_microzone_pct": metrics.get("useful_microzone_pct"),
        },
        "alerts": alerts,
        "flags": flags,
        "blocking_risks": blocking,
        "critical_risks": critical,
        "limitations": limitations,
    }


def evaluate_dataset_coverage(data: dict[str, Any] | None) -> ReadinessSectionPayload:
    if not data:
        return _missing_section("dataset_coverage", ReadinessCode.MISSING_DATASET_COVERAGE)
    summary = _dict(data.get("summary"))
    beta_rows = [row for row in (data.get("beta_readiness") or []) if isinstance(row, dict)]
    viability = [row for row in (data.get("property_type_viability") or []) if isinstance(row, dict)]
    conclusion = _dict(data.get("conclusion"))
    flags: list[str] = []
    critical: list[str] = []
    limitations: list[str] = []

    beta_status_counts = _count_by(beta_rows, "beta_status")
    canonical_beta_status_counts = _canonical_beta_status_counts(beta_rows)
    weak_segments = [
        _segment_name(row)
        for row in beta_rows
        if _beta_status_for_readiness(row) in COVERAGE_WEAK_BETA_STATUS_CODES
    ]
    if _num(summary.get("rm_target_coverage_pct"), 0) < 70:
        flags.append(ReadinessCode.LIMITED_RM_COVERAGE)
        limitations.append(ReadinessCode.LIMITED_RM_COVERAGE)
    if _num(summary.get("beta_ready_segments"), 0) < 5:
        critical.append(ReadinessCode.TOO_FEW_BETA_SUPPORTED_SEGMENTS)
    if _num(summary.get("active_listings"), 0) < 500:
        flags.append(ReadinessCode.DATASET_TOO_SMALL)
        critical.append(ReadinessCode.DATASET_TOO_SMALL)
    if _num(summary.get("top_source_pct"), 0) >= 95:
        flags.append(ReadinessCode.SINGLE_SOURCE_DEPENDENCY)
        limitations.append(ReadinessCode.SINGLE_SOURCE_DEPENDENCY)
    for row in viability:
        if row.get("property_type") == "house" and row.get("status") not in {
            PropertyTypeCoverageStatus.BROAD_BETA_CANDIDATE,
            PropertyTypeCoverageStatus.LIMITED_BETA_CANDIDATE,
        }:
            flags.append(ReadinessCode.HOUSES_WEAK_COVERAGE)
            critical.append(ReadinessCode.HOUSES_WEAK_COVERAGE)

    return {
        "status": STATUS_OK if not critical else STATUS_WARNING,
        "summary": {
            "active_listings": summary.get("active_listings"),
            "avm_useful_listings": summary.get("avm_useful_listings"),
            "avm_useful_pct": summary.get("avm_useful_pct"),
            "rm_target_coverage_pct": summary.get("rm_target_coverage_pct"),
            "usable_coords_pct": summary.get("usable_coords_pct"),
            "useful_microzone_pct": summary.get("useful_microzone_pct"),
            "price_history_usable_pct": summary.get("price_history_usable_pct"),
            "beta_ready_segments": summary.get("beta_ready_segments"),
            "hide_in_beta_segments": summary.get("hide_in_beta_segments"),
            "overfitting_risk": summary.get("overfitting_risk"),
        },
        "beta_status_counts": beta_status_counts,
        "canonical_beta_status_counts": canonical_beta_status_counts,
        "property_type_viability": viability,
        "segments_to_hide_or_treat_carefully": weak_segments[:20],
        "where_avm_serves": list(conclusion.get("where_avm_serves") or [])[:20],
        "where_avm_is_still_misleading": list(conclusion.get("where_avm_is_still_misleading") or [])[:20],
        "flags": flags,
        "blocking_risks": [],
        "critical_risks": critical,
        "limitations": limitations,
    }


def evaluate_geoquality(
    geocoding: dict[str, Any] | None,
    pipeline: dict[str, Any] | None = None,
) -> ReadinessSectionPayload:
    if not geocoding:
        return _missing_section("geoquality", ReadinessCode.MISSING_GEOCODING_READINESS)
    summary = _dict(geocoding.get("summary"))
    active = max(_num(summary.get("active_listings"), 0), 1)
    address_pct = round((_num(summary.get("address_level_coords"), 0) / active) * 100, 2)
    street_or_better_ceiling = _num(summary.get("estimated_street_or_better_gain_ceiling_pct"), 0)
    pipeline_coords = _num(_dict((pipeline or {}).get("metrics")).get("useful_coords_pct"), address_pct)
    flags: list[str] = []
    critical: list[str] = []
    limitations: list[str] = []
    if address_pct < 10:
        flags.append(ReadinessCode.WEAK_GEOLOCATION)
        critical.append(ReadinessCode.WEAK_GEOLOCATION)
        limitations.append(ReadinessCode.WEAK_GEOLOCATION)
    if pipeline_coords < 15:
        flags.append(ReadinessCode.DISTANCE_FEATURE_DEGRADED)
        critical.append(ReadinessCode.DISTANCE_FEATURE_DEGRADED)
        limitations.append(ReadinessCode.DISTANCE_FEATURE_DEGRADED)
    if _num(summary.get("comuna_centroid_coords"), 0) > _num(summary.get("address_level_coords"), 0):
        flags.append(ReadinessCode.COMUNA_CENTROID_DOMINANCE)
    return {
        "status": STATUS_WARNING if critical else STATUS_OK,
        "summary": {
            "active_listings": summary.get("active_listings"),
            "address_level_coords": summary.get("address_level_coords"),
            "address_level_coords_pct": address_pct,
            "approximate_coords": summary.get("approximate_coords"),
            "comuna_centroid_coords": summary.get("comuna_centroid_coords"),
            "no_coords": summary.get("no_coords"),
            "estimated_address_level_gain_ceiling_pct": summary.get("estimated_address_level_gain_ceiling_pct"),
            "estimated_street_or_better_gain_ceiling_pct": street_or_better_ceiling,
            "backfill_candidate_pct_total": summary.get("backfill_candidate_pct_total"),
        },
        "recoverability": {
            "probable_street": summary.get("probable_street"),
            "probable_intersection": summary.get("probable_intersection"),
            "probable_landmark_or_metro": summary.get("probable_landmark_or_metro"),
            "impossible_to_geocode_confidently": summary.get("impossible_to_geocode_confidently"),
        },
        "flags": flags,
        "blocking_risks": [],
        "critical_risks": critical,
        "limitations": limitations,
    }


def evaluate_benchmark(data: dict[str, Any] | None) -> ReadinessSectionPayload:
    if not data:
        return _missing_section("benchmark", ReadinessCode.MISSING_HOLDOUT_BENCHMARK, blocking=True)
    holdout = _dict(data.get("holdout"))
    summary = _dict(data.get("summary"))
    metrics = _dict(holdout.get("metrics"))
    by_property_type = _dict(holdout.get("by_property_type"))
    by_segment = _dict(holdout.get("by_comuna_property_type"))
    flags: list[str] = []
    blocking: list[str] = []
    critical: list[str] = []
    limitations: list[str] = []

    n_evaluated = _num(holdout.get("n_evaluated"), 0)
    coverage = _num(holdout.get("coverage_pct"), 0)
    mape = _num(metrics.get("mape_pct"), 999)
    if summary.get("status") != "ok" or holdout.get("status") != "ok":
        blocking.append(ReadinessCode.HOLDOUT_BENCHMARK_NOT_OK)
    if n_evaluated < 100:
        blocking.append(ReadinessCode.HOLDOUT_TOO_SMALL)
    if coverage < 70:
        blocking.append(ReadinessCode.HOLDOUT_COVERAGE_TOO_LOW)
    if mape > 35:
        critical.append(ReadinessCode.HOLDOUT_ERROR_HIGH)
    elif mape > 25:
        flags.append(ReadinessCode.HOLDOUT_ERROR_ELEVATED)
        limitations.append(ReadinessCode.HOLDOUT_ERROR_ELEVATED)
    if _num(_dict(by_property_type.get("house")).get("mape_pct"), 0) > 30:
        flags.append(ReadinessCode.HOUSE_HOLDOUT_ERROR_HIGH)
        limitations.append(ReadinessCode.HOUSE_HOLDOUT_ERROR_HIGH)

    weak_segments = _weak_benchmark_segments(by_segment)
    if weak_segments:
        flags.append(ReadinessCode.WEAK_HOLDOUT_SEGMENTS)
        limitations.append(ReadinessCode.WEAK_HOLDOUT_SEGMENTS)

    return {
        "status": STATUS_OK if not blocking and not critical else STATUS_WARNING,
        "summary": {
            "holdout_listings": summary.get("holdout_listings"),
            "training_listings": summary.get("training_listings"),
            "n_evaluated": holdout.get("n_evaluated"),
            "coverage_pct": holdout.get("coverage_pct"),
            "insufficient_data_rate_pct": holdout.get("insufficient_data_rate_pct"),
            "mae_clp": metrics.get("mae_clp"),
            "mape_pct": metrics.get("mape_pct"),
            "median_ape_pct": metrics.get("median_ape_pct"),
        },
        "by_property_type": by_property_type,
        "weak_segments": weak_segments[:20],
        "flags": flags,
        "blocking_risks": blocking,
        "critical_risks": critical,
        "limitations": limitations,
    }


def evaluate_confidence(data: dict[str, Any] | None) -> ReadinessSectionPayload:
    if not data:
        return _missing_section("confidence", ReadinessCode.MISSING_CONFIDENCE_AUDIT)
    summary = _dict(data.get("summary"))
    correlations = _dict(data.get("correlations"))
    corr = correlations.get("confidence_vs_ape_pearson")
    flags: list[str] = []
    critical: list[str] = []
    limitations: list[str] = []
    if str(summary.get("conclusion") or "").strip().lower() not in {"serves", "validated"}:
        flags.append(ReadinessCode.CONFIDENCE_UNCALIBRATED)
        limitations.append(ReadinessCode.CONFIDENCE_UNCALIBRATED)
    if corr is None or _num(corr, 1) > -0.15:
        flags.append(ReadinessCode.CONFIDENCE_NOT_PREDICTIVE)
        critical.append(ReadinessCode.CONFIDENCE_NOT_PREDICTIVE)
    elif _num(corr, 1) > -0.4:
        if ReadinessCode.CONFIDENCE_UNCALIBRATED not in flags:
            flags.append(ReadinessCode.CONFIDENCE_UNCALIBRATED)
            limitations.append(ReadinessCode.CONFIDENCE_UNCALIBRATED)
        flags.append(ReadinessCode.CONFIDENCE_PARTIALLY_PREDICTIVE_ONLY)
        limitations.append(ReadinessCode.CONFIDENCE_PARTIALLY_PREDICTIVE_ONLY)
    return {
        "status": STATUS_WARNING if flags else STATUS_OK,
        "summary": {
            "conclusion": summary.get("conclusion"),
            "n_evaluated": summary.get("n_evaluated"),
            "coverage_pct": summary.get("coverage_pct"),
            "insufficient_data_rate_pct": summary.get("insufficient_data_rate_pct"),
            "confidence_vs_ape_pearson": corr,
            "confidence_vs_absolute_error_pearson": correlations.get("confidence_vs_absolute_error_pearson"),
        },
        "by_confidence_bucket": data.get("by_confidence_bucket") or {},
        "flags": flags,
        "blocking_risks": [],
        "critical_risks": critical,
        "limitations": limitations,
    }


def evaluate_comparable_quality(confidence: dict[str, Any] | None) -> ReadinessSectionPayload:
    if not confidence:
        return _missing_section("comparable_quality", ReadinessCode.MISSING_COMPARABLE_QUALITY_EVIDENCE)
    rows = [row for row in (confidence.get("rows") or []) if isinstance(row, dict)]
    counts = _count_by(rows, "comparable_quality_level")
    total = max(sum(counts.values()), 1)
    weak_n = counts.get("poor", 0) + counts.get("weak", 0) + counts.get("unknown", 0)
    weak_pct = round((weak_n / total) * 100, 2)
    dispersion_values = [
        _num(_dict(row.get("coverage_metrics")).get("price_per_m2_dispersion"), None)
        for row in rows
    ]
    dispersion_values = [value for value in dispersion_values if value is not None]
    avg_dispersion = round(sum(dispersion_values) / len(dispersion_values), 2) if dispersion_values else None
    flags: list[str] = []
    critical: list[str] = []
    limitations: list[str] = []
    if weak_pct >= 40:
        flags.append(ReadinessCode.WEAK_COMPARABLE_QUALITY_DISTRIBUTION)
        critical.append(ReadinessCode.WEAK_COMPARABLE_QUALITY_DISTRIBUTION)
        limitations.append(ReadinessCode.WEAK_COMPARABLE_QUALITY_DISTRIBUTION)
    elif weak_pct >= 20:
        flags.append(ReadinessCode.MIXED_COMPARABLE_QUALITY_DISTRIBUTION)
        limitations.append(ReadinessCode.MIXED_COMPARABLE_QUALITY_DISTRIBUTION)
    if avg_dispersion is not None and avg_dispersion >= 45:
        flags.append(ReadinessCode.HIGH_COMPARABLE_DISPERSION)
        limitations.append(ReadinessCode.HIGH_COMPARABLE_DISPERSION)
    return {
        "status": STATUS_WARNING if flags else STATUS_OK,
        "summary": {
            "total_rows": len(rows),
            "quality_counts": counts,
            "weak_or_poor_pct": weak_pct,
            "avg_price_per_m2_dispersion": avg_dispersion,
        },
        "flags": flags,
        "blocking_risks": [],
        "critical_risks": critical,
        "limitations": limitations,
    }


def evaluate_radar_safety() -> ReadinessSectionPayload:
    try:
        from domain.radar.beta_safety import assess_radar_safety
    except Exception as exc:  # pragma: no cover - defensive import boundary
        return {
            "status": STATUS_CRITICAL,
            "summary": {"error": str(exc)},
            "flags": [ReadinessCode.RADAR_BETA_SAFETY_UNAVAILABLE],
            "blocking_risks": [ReadinessCode.RADAR_BETA_SAFETY_UNAVAILABLE],
            "critical_risks": [ReadinessCode.RADAR_BETA_SAFETY_UNAVAILABLE],
            "limitations": [],
        }
    no_data = assess_radar_safety(beta_scope_status=BetaStatus.NO_DATA, comparable_quality_level="strong")
    weak = assess_radar_safety(beta_scope_status=BetaStatus.WEAK_DATA, comparable_quality_level="strong")
    poor = assess_radar_safety(beta_scope_status=BetaStatus.BETA_SUPPORTED, comparable_quality_level="weak")
    enabled = no_data.show is False and weak.verdict == "revisar" and poor.verdict == "revisar"
    flags = [] if enabled else [ReadinessCode.RADAR_BETA_SAFE_RULES_NOT_VERIFIED]
    return {
        "status": STATUS_OK if enabled else STATUS_CRITICAL,
        "summary": {
            "no_data_hidden": no_data.show is False,
            "weak_data_downgraded_to_review": weak.verdict == "revisar",
            "weak_comparable_quality_downgraded_to_review": poor.verdict == "revisar",
        },
        "flags": flags,
        "blocking_risks": flags,
        "critical_risks": flags,
        "limitations": [],
    }


def evaluate_feedback(data: dict[str, Any] | None) -> ReadinessSectionPayload:
    if not data:
        return {
            "status": STATUS_NO_DATA,
            "summary": {"total_feedback": 0},
            "flags": [ReadinessCode.FEEDBACK_LOOP_NO_DATA_YET],
            "blocking_risks": [],
            "critical_risks": [],
            "limitations": [ReadinessCode.FEEDBACK_LOOP_NO_DATA_YET],
        }
    summary = _dict(data.get("summary"))
    by_feedback = _dict(data.get("by_feedback"))
    total = _num(summary.get("total_feedback"), 0)
    return {
        "status": STATUS_OK if total > 0 else STATUS_NO_DATA,
        "summary": {
            "total_feedback": total,
            "latest_feedback_at": summary.get("latest_feedback_at"),
            "reasonable": by_feedback.get("reasonable", 0),
            "too_high": by_feedback.get("too_high", 0),
            "too_low": by_feedback.get("too_low", 0),
            "unsure": by_feedback.get("unsure", 0),
        },
        "recent_comments": list(data.get("comments") or [])[-10:],
        "flags": [] if total else [ReadinessCode.FEEDBACK_LOOP_NO_DATA_YET],
        "blocking_risks": [],
        "critical_risks": [],
        "limitations": [] if total else [ReadinessCode.FEEDBACK_LOOP_NO_DATA_YET],
    }


def evaluate_test_status(data: dict[str, Any] | None) -> ReadinessSectionPayload:
    if not data:
        return {
            "status": STATUS_UNKNOWN,
            "summary": {"message": "No persisted pytest result found. The report did not run tests automatically."},
            "flags": [ReadinessCode.TEST_STATUS_UNKNOWN],
            "blocking_risks": [],
            "critical_risks": [],
            "limitations": [ReadinessCode.TEST_STATUS_UNKNOWN],
        }
    failed = _num(data.get("failed") or data.get("failures"), 0)
    errors = _num(data.get("errors"), 0)
    blocking = [ReadinessCode.TESTS_FAILING] if failed or errors else []
    return {
        "status": STATUS_CRITICAL if blocking else STATUS_OK,
        "summary": data,
        "flags": blocking,
        "blocking_risks": blocking,
        "critical_risks": blocking,
        "limitations": [],
    }


def decide_verdict(*, blocking_risks: list[str], critical_risks: list[str], limitations: list[str]) -> str:
    if blocking_risks:
        return NOT_READY
    severe = set(critical_risks)
    if {
        ReadinessCode.MISSING_HOLDOUT_BENCHMARK,
        ReadinessCode.WEAK_GEOLOCATION,
        ReadinessCode.DATASET_TOO_SMALL,
    } <= severe:
        return NOT_READY
    if critical_risks or limitations:
        return READY_WITH_LIMITATIONS
    return READY_FOR_PRIVATE_BETA


def recommended_beta_scope(sections: dict[str, Any]) -> dict[str, Any]:
    coverage = _dict(sections.get("dataset_coverage"))
    benchmark = _dict(sections.get("benchmark"))
    serves = list(coverage.get("where_avm_serves") or [])
    misleading = list(coverage.get("where_avm_is_still_misleading") or [])
    weak_benchmark = list(benchmark.get("weak_segments") or [])
    return {
        "recommended": serves[:15],
        "hide_or_label_as_misleading": misleading[:15],
        "manual_review_required": weak_benchmark[:15],
        "default_user_copy": "Private beta: reference estimate only, not a purchase recommendation.",
    }


def strongest_segments(sections: dict[str, Any]) -> list[str]:
    benchmark = _dict(sections.get("benchmark"))
    by_type = _dict(benchmark.get("by_property_type"))
    result = []
    for key, value in by_type.items():
        if isinstance(value, dict) and _num(value.get("n_evaluated"), 0) >= 30 and _num(value.get("mape_pct"), 999) <= 25:
            result.append(f"{key}: MAPE {value.get('mape_pct')}%, n={value.get('n_evaluated')}")
    result.extend(_dict(sections.get("dataset_coverage")).get("where_avm_serves") or [])
    return result[:15]


def weakest_segments(sections: dict[str, Any]) -> list[str]:
    result = []
    result.extend(_dict(sections.get("benchmark")).get("weak_segments") or [])
    result.extend(_dict(sections.get("dataset_coverage")).get("where_avm_is_still_misleading") or [])
    return result[:20]


def decision_rules() -> list[str]:
    return [
        "NOT_READY if blocking risks exist: missing holdout, critical operational pipeline failure, too small dataset, low holdout coverage, or failing persisted tests.",
        "READY_WITH_LIMITATIONS if no blockers but critical risks/limitations remain: weak geolocation, single-source dependency, elevated holdout error, uncalibrated confidence, weak comparable distribution.",
        "READY_FOR_PRIVATE_BETA only if pipeline, holdout, radar safety, coverage, confidence evidence and tests are all acceptable with no critical limitations.",
    ]


def write_report(report: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    latest_json = output_dir / "latest.json"
    latest_md = output_dir / "latest.md"
    snapshot_json = output_dir / f"beta_readiness_{stamp}.json"
    snapshot_md = output_dir / f"beta_readiness_{stamp}.md"
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    markdown = markdown_report(report)
    latest_json.write_text(payload, encoding="utf-8")
    latest_md.write_text(markdown, encoding="utf-8")
    snapshot_json.write_text(payload, encoding="utf-8")
    snapshot_md.write_text(markdown, encoding="utf-8")
    return latest_md, latest_json


def markdown_report(report: dict[str, Any]) -> str:
    sections = _dict(report.get("sections"))
    lines = [
        "# Beta Readiness Report",
        "",
        "## Executive Verdict",
        "",
        f"- Verdict: **{report['verdict']}**",
        f"- Generated at: `{report['generated_at']}`",
        f"- Blocking risks: {len(report['blocking_risks'])}",
        f"- Critical risks: {len(report['critical_risks'])}",
        "",
        "## Critical Risks",
        "",
        _bullet_list(report.get("critical_risks") or report.get("flags") or ["No critical risks detected."]),
        "",
        "## Strongest Segments",
        "",
        _bullet_list(report.get("strongest_segments") or ["No strong segment identified from current reports."]),
        "",
        "## Weakest Segments",
        "",
        _bullet_list(report.get("weakest_segments") or ["No weak segment identified from current reports."]),
        "",
        "## Pipeline Health",
        "",
        _section_summary(sections.get("pipeline_health")),
        "",
        "## Coverage Summary",
        "",
        _section_summary(sections.get("dataset_coverage")),
        "",
        "## Geocoding Quality",
        "",
        _section_summary(sections.get("geoquality")),
        "",
        "## Benchmark Summary",
        "",
        _section_summary(sections.get("benchmark")),
        "",
        "## Confidence Audit Summary",
        "",
        _section_summary(sections.get("confidence")),
        "",
        "## Comparable Quality Summary",
        "",
        _section_summary(sections.get("comparable_quality")),
        "",
        "## Radar Safety",
        "",
        _section_summary(sections.get("radar_safety")),
        "",
        "## Feedback Summary",
        "",
        _section_summary(sections.get("feedback")),
        "",
        "## Test Status",
        "",
        _section_summary(sections.get("test_status")),
        "",
        "## Recommended Scope For Beta",
        "",
        _recommended_scope_markdown(_dict(report.get("recommended_scope"))),
        "",
        "## Blocking Risks",
        "",
        _bullet_list(report.get("blocking_risks") or ["None from persisted reports."]),
        "",
        "## Next Priorities",
        "",
        _bullet_list(next_priorities(report)),
    ]
    return "\n".join(lines) + "\n"


def next_priorities(report: dict[str, Any]) -> list[str]:
    flags = set(report.get("flags") or [])
    priorities = []
    if ReadinessCode.SINGLE_SOURCE_DEPENDENCY in flags:
        priorities.append("Add or validate a second listing source before broadening beta.")
    if ReadinessCode.WEAK_GEOLOCATION in flags or ReadinessCode.DISTANCE_FEATURE_DEGRADED in flags:
        priorities.append("Continue conservative geocoding/backfill and keep distance scoring downgraded.")
    if ReadinessCode.CONFIDENCE_UNCALIBRATED in flags:
        priorities.append("Calibrate confidence against holdout error before presenting it as reliability.")
    if ReadinessCode.HOUSE_HOLDOUT_ERROR_HIGH in flags:
        priorities.append("Keep houses in manual-review scope until holdout MAPE improves.")
    if ReadinessCode.FEEDBACK_LOOP_NO_DATA_YET in flags:
        priorities.append("Collect private beta feedback and review high/low bias weekly.")
    return priorities or ["Maintain reports and rerun readiness after each scraper or valuation change."]


def _section_summary(section: Any) -> str:
    if not isinstance(section, dict):
        return "_No data._"
    lines = [f"- Status: `{section.get('status', 'UNKNOWN')}`"]
    summary = _dict(section.get("summary"))
    for key, value in summary.items():
        if isinstance(value, (dict, list)):
            continue
        lines.append(f"- {key}: {value}")
    flags = section.get("flags") or []
    if flags:
        lines.append(f"- Flags: {', '.join(str(flag) for flag in flags)}")
    return "\n".join(lines)


def _recommended_scope_markdown(scope: dict[str, Any]) -> str:
    lines = ["Recommended:"]
    lines.append(_bullet_list(scope.get("recommended") or ["No recommended segment from current reports."]))
    lines.append("")
    lines.append("Hide or label as misleading:")
    lines.append(_bullet_list(scope.get("hide_or_label_as_misleading") or ["None listed."]))
    lines.append("")
    lines.append("Manual review required:")
    lines.append(_bullet_list(scope.get("manual_review_required") or ["None listed."]))
    return "\n".join(lines)


def _weak_benchmark_segments(by_segment: dict[str, Any]) -> list[str]:
    weak = []
    for key, value in by_segment.items():
        if not isinstance(value, dict):
            continue
        n = _num(value.get("n_evaluated"), 0)
        mape = _num(value.get("mape_pct"), 0)
        coverage = _num(value.get("coverage_pct"), 100)
        if n < 10 or mape > 35 or coverage < 80:
            weak.append(f"{key}: n={n}, MAPE={mape}%, coverage={coverage}%")
    return sorted(weak)


def _missing_section(name: str, flag: str, *, blocking: bool = False) -> ReadinessSectionPayload:
    return {
        "status": STATUS_MISSING,
        "summary": {"message": f"{name} report not found"},
        "flags": [flag],
        "blocking_risks": [flag] if blocking else [],
        "critical_risks": [flag],
        "limitations": [flag],
    }


def _latest_matching(directory: Path, pattern: str) -> Path | None:
    try:
        matches = [path for path in directory.glob(pattern) if path.is_file()]
    except OSError:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime, default=None)


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return None, str(exc)


def _unique_flag_list(sections: dict[str, Any], key: str) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for section in sections.values():
        if not isinstance(section, dict):
            continue
        for item in section.get(key) or []:
            text = str(item)
            if text not in seen:
                seen.add(text)
                values.append(text)
    return values


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _num(value: Any, default: float | None = 0) -> float:
    if value is None:
        return default  # type: ignore[return-value]
    try:
        return float(value)
    except (TypeError, ValueError):
        return default  # type: ignore[return-value]


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _canonical_beta_status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = _beta_status_for_readiness(row)
        counts[value] = counts.get(value, 0) + 1
    return counts


def _beta_status_for_readiness(row: dict[str, Any]) -> str:
    return dataset_beta_status_to_canonical(row.get("canonical_beta_status") or row.get("beta_status"))


def _segment_name(row: dict[str, Any]) -> str:
    return f"{row.get('comuna', 'unknown')} / {row.get('property_type', 'unknown')}: {row.get('reason', row.get('beta_status', ''))}"


def _bullet_list(items: list[Any]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate AVM beta readiness report from existing audit artifacts.")
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORTS_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
