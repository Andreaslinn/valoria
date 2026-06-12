from __future__ import annotations

import streamlit as st

from ui.feature_flags import (
    BETA_SHOW_ALERTS,
    BETA_SHOW_PORTFOLIO,
    BETA_SHOW_PRODUCT_LAB,
    DEMO_RISK_REPORT,
    TASAR_PLAYGROUND_DEMO_MODE_ENV,
    UI_VERSION_ENV,
    UI_VERSION_LEGACY,
    UI_VERSION_TASAR_PLAYGROUND,
    beta_hidden_pages,
    get_enabled_demo_features,
    get_ui_version,
    is_beta_feature_enabled,
    is_beta_mode,
    is_demo_mode,
    is_feature_enabled,
    is_tasar_playground_mode,
    normalize_ui_version,
    set_demo_mode,
    set_feature_flag,
    set_ui_version,
)


def setup_function() -> None:
    st.session_state.clear()


def test_demo_mode_is_off_by_default():
    assert is_demo_mode() is False
    assert is_feature_enabled(DEMO_RISK_REPORT) is False
    assert get_enabled_demo_features() == []


def test_can_enable_and_disable_demo_mode():
    set_demo_mode(True)
    assert is_demo_mode() is True

    set_demo_mode(False)
    assert is_demo_mode() is False


def test_can_enable_and_disable_specific_feature():
    set_demo_mode(True)
    assert is_feature_enabled(DEMO_RISK_REPORT) is True

    set_feature_flag(DEMO_RISK_REPORT, False)
    assert is_feature_enabled(DEMO_RISK_REPORT) is False

    set_feature_flag(DEMO_RISK_REPORT, True)
    assert is_feature_enabled(DEMO_RISK_REPORT) is True


def test_demo_features_do_not_leak_into_real_mode():
    set_demo_mode(False)
    set_feature_flag(DEMO_RISK_REPORT, True)

    assert is_feature_enabled(DEMO_RISK_REPORT) is False
    assert get_enabled_demo_features() == []


def test_beta_mode_can_be_enabled_from_env(monkeypatch):
    monkeypatch.setenv("BETA_MODE", "true")

    assert is_beta_mode() is True
    assert is_beta_feature_enabled(BETA_SHOW_PRODUCT_LAB) is False
    assert is_beta_feature_enabled(BETA_SHOW_PORTFOLIO) is False
    assert is_beta_feature_enabled(BETA_SHOW_ALERTS) is False
    assert "Dashboard Lab" in beta_hidden_pages()
    assert "Portafolio" in beta_hidden_pages()


def test_beta_feature_flags_are_overridable(monkeypatch):
    monkeypatch.setenv("BETA_MODE", "true")
    monkeypatch.setenv(BETA_SHOW_PRODUCT_LAB, "true")
    monkeypatch.setenv(BETA_SHOW_PORTFOLIO, "true")

    assert is_beta_feature_enabled(BETA_SHOW_PRODUCT_LAB) is True
    assert is_beta_feature_enabled(BETA_SHOW_PORTFOLIO) is True
    assert "Dashboard Lab" not in beta_hidden_pages()
    assert "Portafolio" not in beta_hidden_pages()


def test_demo_mode_cannot_enable_product_lab_when_beta_hides_it(monkeypatch):
    monkeypatch.setenv("BETA_MODE", "true")
    monkeypatch.delenv(BETA_SHOW_PRODUCT_LAB, raising=False)

    set_demo_mode(True)

    assert is_demo_mode() is False


def test_tasar_playground_uses_real_mode_by_default(monkeypatch):
    monkeypatch.setenv(UI_VERSION_ENV, "tasar_playground")
    monkeypatch.delenv(TASAR_PLAYGROUND_DEMO_MODE_ENV, raising=False)

    set_demo_mode(True)

    assert get_ui_version() == UI_VERSION_TASAR_PLAYGROUND
    assert is_tasar_playground_mode() is True
    assert is_demo_mode() is False


def test_tasar_playground_demo_mode_requires_explicit_env(monkeypatch):
    monkeypatch.setenv(UI_VERSION_ENV, "tasar_playground")
    monkeypatch.setenv(TASAR_PLAYGROUND_DEMO_MODE_ENV, "true")

    set_demo_mode(True)

    assert is_demo_mode() is True


def test_ui_version_defaults_to_legacy(monkeypatch):
    monkeypatch.delenv(UI_VERSION_ENV, raising=False)

    assert get_ui_version() == UI_VERSION_LEGACY
    assert is_tasar_playground_mode() is False


def test_ui_version_supports_env_and_aliases(monkeypatch):
    monkeypatch.setenv(UI_VERSION_ENV, "neo_dark_demo")

    assert get_ui_version() == UI_VERSION_TASAR_PLAYGROUND
    assert normalize_ui_version("demo_redesign") == UI_VERSION_TASAR_PLAYGROUND


def test_ui_version_session_overrides_env(monkeypatch):
    monkeypatch.setenv(UI_VERSION_ENV, "legacy")

    set_ui_version("tasar_playground")

    assert get_ui_version() == UI_VERSION_TASAR_PLAYGROUND
    assert is_tasar_playground_mode() is True
