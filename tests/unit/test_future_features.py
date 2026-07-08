from __future__ import annotations

from services.future_features import FutureFeatureStatus, get_default_future_feature_registry


def test_future_feature_contract_exposes_common_fields() -> None:
    registry = get_default_future_feature_registry()
    feature = registry.get_feature("negotiation_recommendation")

    assert feature is not None
    payload = feature.to_payload()
    assert {
        "feature_key",
        "title",
        "status",
        "message",
        "required_data",
        "next_backend_step",
        "safe_to_show_in_beta",
        "source",
        "last_checked_at",
    } <= set(payload)
    assert payload["status"] == FutureFeatureStatus.REQUIRES_PRICE_HISTORY.value
    assert payload["safe_to_show_in_beta"] is False


def test_future_feature_registry_covers_lab_surfaces() -> None:
    keys = set(get_default_future_feature_registry().feature_keys())

    assert {
        "alert_rules",
        "autofact_real_estate",
        "buyer_journey",
        "checklist_lab",
        "decision_cards",
        "lab_feedback",
        "listing_explainer_ai",
        "market_context_timeseries",
        "negotiation_recommendation",
        "portfolio_analytics",
        "property_experience",
        "radar_market_map",
        "risk_report_lab",
    } <= keys


def test_future_feature_registry_covers_tasar_playground_context_shell() -> None:
    registry = get_default_future_feature_registry()
    feature = registry.get_feature("tasar_playground_context_panels")

    assert feature is not None
    payload = feature.to_payload()
    assert payload["classification"] == "playground_backend_shell"
    assert payload["status"] == FutureFeatureStatus.REQUIRES_DATA.value
    assert "ui/redesign/tasar_playground.py" in payload["related_ui_files"]
    assert "location_intelligence" in payload["future_fields"]
    assert "price_trend" in payload["future_fields"]
    assert "risk_summary" in payload["future_fields"]
    assert payload["safe_to_show_in_beta"] is False


def test_future_feature_registry_covers_alerts_playground_shells() -> None:
    registry = get_default_future_feature_registry()
    keys = set(registry.feature_keys())

    assert {
        "alert_active_zones",
        "alert_ai_prioritization",
        "alert_filter_capabilities",
        "alert_notification_settings",
        "alert_rules",
        "alert_trends_history",
    } <= keys

    expected_statuses = {
        FutureFeatureStatus.NOT_CONFIGURED.value,
        FutureFeatureStatus.REQUIRES_ALERT_HISTORY.value,
        FutureFeatureStatus.REQUIRES_NOTIFICATION_PROVIDER.value,
        FutureFeatureStatus.REQUIRES_PROPERTY_TYPE_INDEX.value,
    }
    payloads = [
        registry.get_feature(feature_key).to_payload()
        for feature_key in (
            "alert_active_zones",
            "alert_ai_prioritization",
            "alert_filter_capabilities",
            "alert_notification_settings",
            "alert_rules",
            "alert_trends_history",
        )
    ]

    assert {payload["status"] for payload in payloads} == expected_statuses
    for payload in payloads:
        assert payload["classification"] == "alerts_playground_backend_shell"
        assert "ui/redesign/alerts_view.py" in payload["related_ui_files"]
        assert payload["safe_to_show_in_beta"] is False


def test_alert_rules_shell_covers_visible_rule_actions() -> None:
    registry = get_default_future_feature_registry()
    feature = registry.get_feature("alert_rules")

    assert feature is not None
    payload = feature.to_payload()
    assert payload["status"] == FutureFeatureStatus.NOT_CONFIGURED.value
    assert "user_rule_config" in payload["required_data"]
    assert "rule_state" in payload["required_data"]
    assert "rule_id" in payload["future_fields"]
    assert "status" in payload["future_fields"]
    assert "Ver mis reglas" in payload["message"]
    assert "Nueva regla de alerta" in payload["message"]


def test_future_feature_stubs_do_not_return_fake_product_values() -> None:
    registry = get_default_future_feature_registry()
    contract_keys = {
        "feature_key",
        "title",
        "status",
        "message",
        "required_data",
        "next_backend_step",
        "safe_to_show_in_beta",
        "source",
        "last_checked_at",
        "classification",
        "future_fields",
        "related_ui_files",
        "backend_notes",
    }

    for feature in registry.list_features():
        payload = feature.to_payload()
        for future_field in payload["future_fields"]:
            if future_field not in contract_keys:
                assert future_field not in payload
        assert "estimated_value_uf" not in payload
        assert "suggested_offer_range" not in payload
        assert payload["status"] in {status.value for status in FutureFeatureStatus}


def test_unknown_future_feature_returns_none() -> None:
    registry = get_default_future_feature_registry()

    assert registry.get_feature("does_not_exist") is None
