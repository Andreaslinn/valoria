from __future__ import annotations

import pytest

from ui.demo_feedback import (
    DEMO_FEEDBACK_STATE_KEY,
    ensure_demo_feedback_state,
    record_demo_event,
    record_demo_feedback,
    summarize_demo_feedback,
)


def test_feedback_is_registered() -> None:
    session: dict[str, object] = {}
    state = ensure_demo_feedback_state(session)

    record_demo_feedback(state, "risk_report", "util", property_id=9101)

    assert session[DEMO_FEEDBACK_STATE_KEY] is state
    assert state["feedback"][0]["module"] == "risk_report"
    assert state["feedback"][0]["feedback"] == "util"
    assert state["feedback"][0]["is_demo"] is True


def test_events_are_registered() -> None:
    state = ensure_demo_feedback_state({})

    record_demo_event(state, "opened_risk_report", module="risk_report", property_id=9101)

    assert state["events"][0]["event_name"] == "opened_risk_report"
    assert state["events"][0]["module"] == "risk_report"
    assert state["events"][0]["is_demo"] is True


def test_feedback_summary_is_calculated() -> None:
    state = ensure_demo_feedback_state({})
    record_demo_feedback(state, "risk_report", "util")
    record_demo_feedback(state, "risk_report", "lo_pagaria")
    record_demo_feedback(state, "autofact", "confuso")
    record_demo_feedback(state, "alert_center", "no_me_sirve")
    record_demo_event(state, "opened_risk_report", module="risk_report")
    record_demo_event(state, "opened_autofact_demo", module="autofact")

    summary = summarize_demo_feedback(state)

    assert summary["total_feedback"] == 4
    assert summary["total_events"] == 2
    assert summary["modules_positive"][0]["module"] == "risk_report"
    assert summary["modules_confusing"][0]["module"] == "autofact"
    assert summary["features_premium"][0]["module"] == "risk_report"
    assert summary["features_to_remove"][0]["module"] == "alert_center"


def test_feedback_and_events_are_demo_only() -> None:
    state = ensure_demo_feedback_state({})

    record_demo_feedback(state, "risk_report", "util", demo_mode=False)
    record_demo_event(state, "opened_risk_report", module="risk_report", demo_mode=False)

    assert state["feedback"] == []
    assert state["events"] == []


def test_invalid_feedback_is_rejected() -> None:
    state = ensure_demo_feedback_state({})

    with pytest.raises(ValueError):
        record_demo_feedback(state, "risk_report", "meh")

    with pytest.raises(ValueError):
        record_demo_event(state, "opened_real_report", module="risk_report")
