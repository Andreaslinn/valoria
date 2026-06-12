from __future__ import annotations

from scripts.beta_readiness_report import (
    NOT_READY,
    READY_FOR_PRIVATE_BETA,
    READY_WITH_LIMITATIONS,
    build_beta_readiness_report,
    markdown_report,
)


def test_pipeline_operational_blockers_use_canonical_pipeline_alert_codes() -> None:
    inputs = _healthy_inputs()
    inputs["pipeline_health"]["alerts"] = [
        {"status": "CRITICAL", "code": "m2_parse_rate_low"},
        {"status": "CRITICAL", "code": "comuna_coverage_low"},
    ]

    report = build_beta_readiness_report(inputs, generated_at="2026-05-27T00:00:00+00:00")

    assert report["verdict"] == NOT_READY
    assert "pipeline_operational_critical" in report["blocking_risks"]


def test_pipeline_operational_blockers_keep_legacy_alias_compatibility() -> None:
    inputs = _healthy_inputs()
    inputs["pipeline_health"]["alerts"] = [
        {"status": "CRITICAL", "code": "m2_parse_rate_critical"},
        {"status": "CRITICAL", "code": "covered_comunas_low"},
    ]

    report = build_beta_readiness_report(inputs, generated_at="2026-05-27T00:00:00+00:00")

    assert report["verdict"] == NOT_READY
    assert "pipeline_operational_critical" in report["blocking_risks"]


def test_not_ready_when_holdout_benchmark_is_missing() -> None:
    report = build_beta_readiness_report(_healthy_inputs() | {"holdout_benchmark": None}, generated_at="2026-05-27T00:00:00+00:00")

    assert report["verdict"] == NOT_READY
    assert "missing_holdout_benchmark" in report["blocking_risks"]


def test_ready_with_limitations_for_single_source_and_weak_geolocation() -> None:
    inputs = _healthy_inputs()
    inputs["pipeline_health"]["metrics"]["top_source_pct"] = 100.0
    inputs["geocoding_readiness"]["summary"]["address_level_coords"] = 20

    report = build_beta_readiness_report(inputs, generated_at="2026-05-27T00:00:00+00:00")

    assert report["verdict"] == READY_WITH_LIMITATIONS
    assert "single_source_dependency" in report["critical_risks"]
    assert "weak_geolocation" in report["critical_risks"]


def test_ready_for_private_beta_requires_no_critical_limitations() -> None:
    report = build_beta_readiness_report(_healthy_inputs(), generated_at="2026-05-27T00:00:00+00:00")

    assert report["verdict"] == READY_FOR_PRIVATE_BETA
    assert report["blocking_risks"] == []
    assert report["critical_risks"] == []
    assert report["sections"]["dataset_coverage"]["canonical_beta_status_counts"] == {"beta_supported": 1}


def test_current_like_inputs_are_limited_not_ready() -> None:
    inputs = _healthy_inputs()
    inputs["pipeline_health"]["status"] = "CRITICAL"
    inputs["pipeline_health"]["metrics"]["top_source_pct"] = 100.0
    inputs["pipeline_health"]["metrics"]["useful_coords_pct"] = 2.2
    inputs["pipeline_health"]["alerts"] = [
        {"status": "CRITICAL", "code": "useful_coords_low"},
        {"status": "CRITICAL", "code": "single_source_dependency_high"},
    ]
    inputs["geocoding_readiness"]["summary"]["address_level_coords"] = 39
    inputs["holdout_benchmark"]["holdout"]["metrics"]["mape_pct"] = 24.34
    inputs["holdout_benchmark"]["holdout"]["by_property_type"]["house"]["mape_pct"] = 32.89
    inputs["confidence_audit"]["correlations"]["confidence_vs_ape_pearson"] = -0.29

    report = build_beta_readiness_report(inputs, generated_at="2026-05-27T00:00:00+00:00")

    assert report["verdict"] == READY_WITH_LIMITATIONS
    assert "single_source_dependency" in report["critical_risks"]
    assert "distance_feature_degraded" in report["critical_risks"]
    assert "house_holdout_error_high" in report["limitations"]
    assert "pipeline_operational_critical" not in report["blocking_risks"]


def test_markdown_has_required_sections() -> None:
    report = build_beta_readiness_report(_healthy_inputs(), generated_at="2026-05-27T00:00:00+00:00")
    markdown = markdown_report(report)

    for heading in [
        "# Beta Readiness Report",
        "## Executive Verdict",
        "## Critical Risks",
        "## Strongest Segments",
        "## Weakest Segments",
        "## Pipeline Health",
        "## Coverage Summary",
        "## Geocoding Quality",
        "## Benchmark Summary",
        "## Confidence Audit Summary",
        "## Comparable Quality Summary",
        "## Radar Safety",
        "## Feedback Summary",
        "## Test Status",
        "## Recommended Scope For Beta",
        "## Blocking Risks",
        "## Next Priorities",
    ]:
        assert heading in markdown


def _healthy_inputs() -> dict:
    return {
        "pipeline_health": {
            "status": "OK",
            "metrics": {
                "active_listings": 2500,
                "new_active_listings_since_baseline": 50,
                "price_parse_rate_pct": 99.0,
                "m2_parse_rate_pct": 96.0,
                "rooms_parse_rate_pct": 97.0,
                "top_source": "mixed",
                "top_source_pct": 70.0,
                "useful_coords_pct": 40.0,
                "useful_microzone_pct": 35.0,
            },
            "alerts": [],
        },
        "dataset_coverage": {
            "summary": {
                "active_listings": 2500,
                "avm_useful_listings": 2400,
                "avm_useful_pct": 96.0,
                "rm_target_coverage_pct": 85.0,
                "usable_coords_pct": 40.0,
                "useful_microzone_pct": 35.0,
                "price_history_usable_pct": 45.0,
                "beta_ready_segments": 20,
                "hide_in_beta_segments": 0,
                "top_source_pct": 70.0,
            },
            "beta_readiness": [
                {
                    "comuna": "nunoa",
                    "property_type": "apartment",
                    "beta_status": "beta_ready",
                    "reason": "sufficient",
                }
            ],
            "property_type_viability": [
                {"property_type": "apartment", "status": "broad_beta_candidate"},
                {"property_type": "house", "status": "broad_beta_candidate"},
            ],
            "conclusion": {
                "where_avm_serves": ["nunoa / apartment"],
                "where_avm_is_still_misleading": [],
            },
        },
        "geocoding_readiness": {
            "summary": {
                "active_listings": 2500,
                "address_level_coords": 1000,
                "approximate_coords": 100,
                "comuna_centroid_coords": 50,
                "no_coords": 1350,
                "estimated_address_level_gain_ceiling_pct": 10.0,
                "estimated_street_or_better_gain_ceiling_pct": 60.0,
                "backfill_candidate_pct_total": 40.0,
                "probable_street": 600,
                "probable_intersection": 200,
                "probable_landmark_or_metro": 300,
                "impossible_to_geocode_confidently": 200,
            }
        },
        "holdout_benchmark": {
            "summary": {
                "status": "ok",
                "holdout_listings": 500,
                "training_listings": 2000,
            },
            "holdout": {
                "status": "ok",
                "n_evaluated": 450,
                "coverage_pct": 90.0,
                "insufficient_data_rate_pct": 5.0,
                "metrics": {
                    "mae_clp": 25_000_000,
                    "mape_pct": 18.0,
                    "median_ape_pct": 12.0,
                },
                "by_property_type": {
                    "apartment": {"n_evaluated": 300, "mape_pct": 16.0},
                    "house": {"n_evaluated": 150, "mape_pct": 24.0},
                },
                "by_comuna_property_type": {
                    "nunoa|apartment": {"n_evaluated": 30, "mape_pct": 15.0, "coverage_pct": 90.0}
                },
            },
        },
        "confidence_audit": {
            "summary": {
                "conclusion": "serves",
                "n_evaluated": 450,
                "coverage_pct": 90.0,
                "insufficient_data_rate_pct": 5.0,
            },
            "correlations": {
                "confidence_vs_ape_pearson": -0.55,
                "confidence_vs_absolute_error_pearson": -0.5,
            },
            "by_confidence_bucket": {},
            "rows": [
                {
                    "comparable_quality_level": "strong",
                    "coverage_metrics": {"price_per_m2_dispersion": 20},
                },
                {
                    "comparable_quality_level": "acceptable",
                    "coverage_metrics": {"price_per_m2_dispersion": 25},
                },
            ],
        },
        "feedback_summary": {
            "summary": {"total_feedback": 5, "latest_feedback_at": "2026-05-27T00:00:00+00:00"},
            "by_feedback": {"reasonable": 4, "too_high": 1},
            "comments": [],
        },
        "test_status": {"passed": 700, "failed": 0, "errors": 0},
    }
