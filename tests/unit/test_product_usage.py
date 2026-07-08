from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from scripts.product_usage_report import build_usage_report, load_events, write_usage_report
from services.product_usage import (
    hash_identifier,
    new_session_context,
    sanitize_properties,
    track_event,
)


def test_sanitize_properties_keeps_only_safe_product_fields() -> None:
    clean = sanitize_properties(
        {
            "comuna": "Nunoa",
            "property_type": "Apartment",
            "precio_publicado_uf": 6000,
            "estimated_value_uf": 6294,
            "address": "Secret 123",
            "url": "https://example.com/listing",
            "free_text": "private note",
        }
    )

    assert clean == {
        "comuna": "nunoa",
        "property_type": "apartment",
        "precio_publicado_uf": 6000,
        "estimated_value_uf": 6294,
    }


def test_hash_identifier_is_stable_and_not_raw() -> None:
    first = hash_identifier("User@Example.com")
    second = hash_identifier("user@example.com")

    assert first == second
    assert first != "user@example.com"


def test_track_event_writes_jsonl_without_invasive_fields() -> None:
    temp_dir = _workspace_tmp_dir()
    context = new_session_context(user_identifier="beta@example.com", beta_role="beta")

    event = track_event(
        "valuation_submitted",
        context=context,
        properties={"comuna": "Macul", "address": "Hidden 456"},
        output_dir=temp_dir,
    )
    events = load_events(temp_dir)

    assert event is not None
    assert len(events) == 1
    assert events[0]["user_hash"]
    assert events[0]["properties"] == {"comuna": "macul"}
    shutil.rmtree(temp_dir)


def test_property_analysis_event_is_supported() -> None:
    temp_dir = _workspace_tmp_dir()
    context = new_session_context(user_identifier="beta@example.com", beta_role="beta")

    event = track_event(
        "property_analysis_submitted",
        context=context,
        properties={"comuna": "Macul", "property_type": "Apartment"},
        output_dir=temp_dir,
    )
    events = load_events(temp_dir)

    assert event is not None
    assert events[0]["event_type"] == "property_analysis_submitted"
    assert events[0]["properties"] == {"comuna": "macul", "property_type": "apartment"}
    shutil.rmtree(temp_dir)


def test_usage_report_counts_core_beta_metrics() -> None:
    events = [
        _event("session_started", "s1", "u1", "2026-05-12T10:00:00+00:00", 0),
        _event("valuation_submitted", "s1", "u1", "2026-05-12T10:01:00+00:00", 60, comuna="nunoa"),
        _event("valuation_completed", "s1", "u1", "2026-05-12T10:02:00+00:00", 120),
        _event("radar_requested", "s1", "u1", "2026-05-12T10:03:00+00:00", 180),
        _event("radar_completed", "s1", "u1", "2026-05-12T10:04:00+00:00", 240, radar_results_count=12),
        _event("session_started", "s2", "u1", "2026-05-13T10:00:00+00:00", 0),
    ]

    report = build_usage_report(events)

    assert report["summary"]["sessions"] == 2
    assert report["summary"]["identified_users"] == 1
    assert report["summary"]["returning_users"] == 1
    assert report["summary"]["valuations_submitted"] == 1
    assert report["summary"]["radar_completed"] == 1
    assert report["comunas_consulted"] == {"nunoa": 1}
    assert report["radar"]["avg_results_count"] == 12.0


def test_write_usage_report_outputs_json_csv_markdown() -> None:
    temp_dir = _workspace_tmp_dir()
    report = build_usage_report([_event("session_started", "s1", None, "2026-05-12T10:00:00+00:00", 0)])

    artifacts = write_usage_report(report, output_dir=temp_dir)

    assert artifacts["json"].exists()
    assert artifacts["csv"].exists()
    assert artifacts["markdown"].exists()
    assert json.loads(artifacts["json"].read_text(encoding="utf-8"))["summary"]["sessions"] == 1
    shutil.rmtree(temp_dir)


def _event(
    event_type: str,
    session_id: str,
    user_hash: str | None,
    occurred_at: str,
    duration: float,
    **properties,
) -> dict:
    return {
        "event_type": event_type,
        "occurred_at": occurred_at,
        "session_id": session_id,
        "session_started_at": occurred_at,
        "session_duration_seconds": duration,
        "user_hash": user_hash,
        "beta_role": "beta",
        "properties": properties,
    }


def _workspace_tmp_dir() -> Path:
    path = Path(".tmp") / "tests" / f"product_usage_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path
