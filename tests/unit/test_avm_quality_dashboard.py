from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from scripts.avm_quality_dashboard import build_dashboard, load_json_reports, write_dashboard


def _current_report() -> dict:
    return {
        "summary": {
            "generated_at": "2026-05-12T10:00:00+00:00",
            "active_total": 10,
            "avm_useful_total": 8,
            "valid_m2_total": 9,
            "valid_price_total": 9,
            "low_data_comunas": 1,
            "sufficient_data_comunas": 2,
        },
        "by_comuna": [
            {
                "comuna": "nunoa",
                "active_listings": 6,
                "avm_useful_listings": 6,
                "valid_m2_listings": 6,
                "valid_price_listings": 6,
                "known_property_type_listings": 6,
                "low_data_mode": False,
                "data_sufficient": True,
            },
            {
                "comuna": "macul",
                "active_listings": 4,
                "avm_useful_listings": 2,
                "valid_m2_listings": 3,
                "valid_price_listings": 3,
                "known_property_type_listings": 2,
                "low_data_mode": True,
                "data_sufficient": False,
            },
        ],
        "by_property_type": {"apartment": 8, "unknown": 2},
        "geocode_precision": {"address": 2, "comuna": 3, "unknown": 5},
        "top_discard_reasons": {"property_type_mismatch": 12, "comuna_mismatch": 8},
    }


def _benchmark_report() -> dict:
    return {
        "summary": {
            "generated_at": "2026-05-12T10:30:00+00:00",
            "status": "ok",
            "total_active_listings": 10,
            "unique_eval_targets": 8,
            "successful_valuations": 6,
            "failed_valuations": 2,
            "coverage_pct": 75.0,
            "avg_comparables_used": 6.5,
            "low_data_mode_rate_pct": 20.0,
            "metrics": {"mape_pct": 18.4},
        }
    }


def test_dashboard_combines_current_quality_and_benchmark_history() -> None:
    dashboard = build_dashboard(_current_report(), benchmark_history=[_benchmark_report()])

    assert dashboard["summary"]["active_listings"] == 10
    assert dashboard["summary"]["useful_listings"] == 8
    assert dashboard["summary"]["useful_coverage_pct"] == 80.0
    assert dashboard["summary"]["latest_mape_pct"] == 18.4
    assert dashboard["current"]["property_types"] == {"apartment": 8, "unknown": 2}
    assert dashboard["current"]["low_data_mode_comunas"][0]["comuna"] == "macul"
    assert dashboard["history"]["mape"][0]["mape_pct"] == 18.4


def test_dashboard_tracks_db_growth_with_current_snapshot() -> None:
    previous = _current_report()
    previous["summary"] = {
        **previous["summary"],
        "generated_at": "2026-05-11T10:00:00+00:00",
        "active_total": 7,
        "avm_useful_total": 5,
    }

    dashboard = build_dashboard(_current_report(), data_sufficiency_history=[previous])

    assert dashboard["history"]["db_growth"] == [
        {
            "generated_at": "2026-05-11T10:00:00+00:00",
            "active_listings": 7,
            "useful_listings": 5,
            "low_data_mode_comunas": 1,
            "sufficient_data_comunas": 2,
        },
        {
            "generated_at": "2026-05-12T10:00:00+00:00",
            "active_listings": 10,
            "useful_listings": 8,
            "low_data_mode_comunas": 1,
            "sufficient_data_comunas": 2,
        },
    ]


def test_load_json_reports_skips_invalid_files() -> None:
    temp_dir = _workspace_tmp_dir()
    good = temp_dir / "data_sufficiency_good.json"
    bad = temp_dir / "data_sufficiency_bad.json"
    good.write_text(json.dumps(_current_report()), encoding="utf-8")
    bad.write_text("{not-json", encoding="utf-8")

    reports = load_json_reports(temp_dir, "data_sufficiency_*.json")

    assert len(reports) == 1
    assert reports[0]["summary"]["active_total"] == 10
    shutil.rmtree(temp_dir)


def test_write_dashboard_outputs_json_csv_and_markdown() -> None:
    temp_dir = _workspace_tmp_dir()
    dashboard = build_dashboard(_current_report(), benchmark_history=[_benchmark_report()])
    artifacts = write_dashboard(dashboard, output_dir=temp_dir)

    assert artifacts.json_path.exists()
    assert artifacts.csv_path.exists()
    assert artifacts.markdown_path.exists()
    assert "AVM Quality Dashboard" in artifacts.markdown_path.read_text(encoding="utf-8")
    shutil.rmtree(temp_dir)


def _workspace_tmp_dir() -> Path:
    path = Path(".tmp") / "tests" / f"avm_quality_dashboard_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path
