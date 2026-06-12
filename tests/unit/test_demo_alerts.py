from __future__ import annotations

import pytest

from ui.demo_alerts import (
    DEMO_ALERT_CATEGORIES,
    DEMO_ALERT_SEVERITIES,
    build_demo_alerts,
    ensure_demo_alert_state,
    filter_demo_alerts,
    mark_demo_alert_read,
    with_demo_alert_read_state,
)
from ui.demo_data import get_demo_listings


def test_demo_alerts_are_generated_with_contract() -> None:
    listings = get_demo_listings()
    property_ids = {int(item["listing_id"]) for item in listings}

    alerts = build_demo_alerts(listings, demo_mode=True)

    assert alerts
    for alert in alerts:
        assert set(alert) >= {
            "id",
            "property_id",
            "title",
            "body",
            "severity",
            "category",
            "created_at",
            "action_label",
            "action_target",
            "is_demo",
        }
        assert alert["severity"] in DEMO_ALERT_SEVERITIES
        assert alert["category"] in DEMO_ALERT_CATEGORIES
        assert alert["action_target"]["type"] in {
            "property",
            "risk_report",
            "buyer_journey",
            "market_context",
            "decision_board",
        }
        if alert["property_id"] is not None:
            assert int(alert["property_id"]) in property_ids


def test_mark_alert_read_updates_demo_state() -> None:
    alerts = build_demo_alerts(get_demo_listings(), demo_mode=True)
    session: dict[str, object] = {}
    state = ensure_demo_alert_state(session, alerts)

    mark_demo_alert_read(state, alerts[0]["id"])
    hydrated = with_demo_alert_read_state(alerts, state)

    assert hydrated[0]["is_read"] is True


def test_alert_filters_work() -> None:
    alerts = build_demo_alerts(get_demo_listings(), demo_mode=True)
    state = ensure_demo_alert_state({}, alerts)
    mark_demo_alert_read(state, alerts[0]["id"])
    hydrated = with_demo_alert_read_state(alerts, state)

    category = hydrated[-1]["category"]
    severity = hydrated[-1]["severity"]

    assert all(alert["category"] == category for alert in filter_demo_alerts(hydrated, category=category))
    assert all(alert["severity"] == severity for alert in filter_demo_alerts(hydrated, severity=severity))
    assert all(not alert["is_read"] for alert in filter_demo_alerts(hydrated, unread_only=True))


def test_alert_engine_is_demo_only() -> None:
    assert build_demo_alerts(get_demo_listings(), demo_mode=False) == []


def test_invalid_alert_state_is_rejected() -> None:
    with pytest.raises(ValueError):
        mark_demo_alert_read({"is_demo": False}, "alert")
