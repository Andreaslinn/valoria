from __future__ import annotations

from ui.beta_gate import (
    BetaPasswordConfig,
    get_beta_password_config,
    is_production_environment,
    validate_beta_password,
)


def test_beta_password_config_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("BETA_PASSWORD", "beta-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-secret")

    config = get_beta_password_config()

    assert config.beta_password == "beta-secret"
    assert config.admin_password == "admin-secret"
    assert config.is_configured is True


def test_validate_beta_password_supports_beta_and_admin() -> None:
    config = BetaPasswordConfig(beta_password="beta-secret", admin_password="admin-secret")

    assert validate_beta_password("beta-secret", config) == "beta"
    assert validate_beta_password("admin-secret", config) == "admin"
    assert validate_beta_password("wrong", config) is None


def test_missing_password_config_is_unconfigured() -> None:
    config = BetaPasswordConfig(beta_password=None, admin_password=None)

    assert config.is_configured is False
    assert validate_beta_password("anything", config) is None


def test_missing_environment_is_treated_as_production(monkeypatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("STREAMLIT_ENV", raising=False)

    assert is_production_environment() is True


def test_local_environment_is_not_production(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "local")

    assert is_production_environment() is False


def test_staging_environment_is_production(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")

    assert is_production_environment() is True
