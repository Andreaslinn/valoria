"""Product Lab feature flags for Streamlit demo experiences."""
from __future__ import annotations

import os
from dataclasses import dataclass

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

DEMO_MODE = "demo_mode"
DEMO_AUTOFACT_REPORT = "demo_autofact_report"
DEMO_RISK_REPORT = "demo_risk_report"
DEMO_PORTAL_PRESENCE = "demo_portal_presence"
DEMO_NEGOTIATION_SIGNALS = "demo_negotiation_signals"
DEMO_OWNER_RECOMMENDATIONS = "demo_owner_recommendations"
DEMO_MARKET_TIMING = "demo_market_timing"
DEMO_PRICE_HISTORY = "demo_price_history"
DEMO_ALERTS = "demo_alerts"
DEMO_PROPERTY_COMPARISON = "demo_property_comparison"

FEATURE_FLAG_PREFIX = "product_lab_feature_"
BETA_SHOW_PRODUCT_LAB = "BETA_SHOW_PRODUCT_LAB"
BETA_SHOW_PORTFOLIO = "BETA_SHOW_PORTFOLIO"
BETA_SHOW_ALERTS = "BETA_SHOW_ALERTS"
BETA_SHOW_STATUS = "BETA_SHOW_STATUS"
DEMO_MODE_KEY = f"{FEATURE_FLAG_PREFIX}{DEMO_MODE}"
DEMO_DATASET_LOADED_KEY = f"{FEATURE_FLAG_PREFIX}dataset_loaded"
DEMO_SCENARIO_KEY = f"{FEATURE_FLAG_PREFIX}scenario"
UI_VERSION_ENV = "AVM_UI_VERSION"
TASAR_PLAYGROUND_DEMO_MODE_ENV = "AVM_TASAR_PLAYGROUND_DEMO_MODE"
UI_VERSION_KEY = f"{FEATURE_FLAG_PREFIX}ui_version"
UI_VERSION_LEGACY = "legacy"
UI_VERSION_DEMO = "demo"
UI_VERSION_TASAR_PLAYGROUND = "tasar_playground"
UI_VERSION_OPTIONS = (UI_VERSION_LEGACY, UI_VERSION_DEMO, UI_VERSION_TASAR_PLAYGROUND)
UI_VERSION_LABELS = {
    UI_VERSION_LEGACY: "UI actual / legacy",
    UI_VERSION_DEMO: "Modo demo actual",
    UI_VERSION_TASAR_PLAYGROUND: "Tasar playground",
}
UI_VERSION_ALIASES = {
    "current": UI_VERSION_LEGACY,
    "default": UI_VERSION_LEGACY,
    "product_lab": UI_VERSION_DEMO,
    "lab": UI_VERSION_DEMO,
    "demo_redesign": UI_VERSION_TASAR_PLAYGROUND,
    "neo_dark_demo": UI_VERSION_TASAR_PLAYGROUND,
    "ui_playground": UI_VERSION_TASAR_PLAYGROUND,
}
DEMO_SCENARIOS = ("comprador", "propietario", "inversionista", "riesgo legal", "negociación")


@dataclass(frozen=True)
class FeatureFlag:
    name: str
    label: str
    description: str
    default: bool = True


DEMO_FEATURE_FLAGS: tuple[FeatureFlag, ...] = (
    FeatureFlag(
        DEMO_AUTOFACT_REPORT,
        "Autofact inmobiliario",
        "Reporte legal/comercial simulado para una propiedad.",
    ),
    FeatureFlag(
        DEMO_RISK_REPORT,
        "Risk Report + CBR",
        "Scores de riesgo, liquidez, mercado y CBR simulado.",
    ),
    FeatureFlag(
        DEMO_PORTAL_PRESENCE,
        "Presencia en portales",
        "Simula apariciones de una propiedad en múltiples portales.",
    ),
    FeatureFlag(
        DEMO_NEGOTIATION_SIGNALS,
        "Señales de negociación",
        "Señales de vendedor apurado y margen de negociación.",
    ),
    FeatureFlag(
        DEMO_OWNER_RECOMMENDATIONS,
        "Recomendaciones propietario",
        "Simula vender, esperar o arrendar según contexto de mercado.",
    ),
    FeatureFlag(
        DEMO_MARKET_TIMING,
        "Timing de mercado",
        "Lecturas demo sobre si conviene comprar, vender o esperar.",
    ),
    FeatureFlag(
        DEMO_PRICE_HISTORY,
        "Historial de precio",
        "Evolución simulada de precio y cambios desde guardado.",
    ),
    FeatureFlag(
        DEMO_ALERTS,
        "Alertas inteligentes",
        "Alertas demo de rebaja, permanencia, liquidez e inventario.",
    ),
    FeatureFlag(
        DEMO_PROPERTY_COMPARISON,
        "Comparación de propiedades",
        "Comparador demo para preparar una vista premium futura.",
    ),
)

_FLAG_BY_NAME = {flag.name: flag for flag in DEMO_FEATURE_FLAGS}


def is_beta_mode() -> bool:
    """Return True when the UI should use private-beta scoped navigation."""
    explicit = os.getenv("BETA_MODE")
    if explicit is not None:
        return _env_bool("BETA_MODE", default=False)
    environment = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "").strip().lower()
    return environment in {"beta", "production"}


def is_beta_feature_enabled(name: str) -> bool:
    """Beta UI feature flags. Defaults are intentionally conservative."""
    if not is_beta_mode():
        return True
    defaults = {
        BETA_SHOW_PRODUCT_LAB: False,
        BETA_SHOW_PORTFOLIO: False,
        BETA_SHOW_ALERTS: False,
        BETA_SHOW_STATUS: True,
    }
    return _env_bool(name, default=defaults.get(name, False))


def beta_hidden_pages() -> dict[str, str]:
    if not is_beta_mode():
        return {}
    hidden: dict[str, str] = {}
    if not is_beta_feature_enabled(BETA_SHOW_PRODUCT_LAB):
        hidden.update(
            {
                "Dashboard Lab": "Product Lab demo con datos hardcodeados.",
                "Alertas Lab": "Alertas demo aun no conectadas al motor real.",
                "Checklist Lab": "Workflow demo de due diligence.",
                "Decision Board Lab": "Workflow demo no validado para beta factual.",
                "Buyer Journey": "Journey demo/hardcodeado.",
                "Owner Journey": "Journey demo/hardcodeado.",
                "Property Experience": "Experiencia demo con datos simulados.",
                "Risk Report": "Pagina demo; el reporte real simple se descarga desde Tasacion/Radar.",
                "Autofact Demo": "Reporte legal demo no factual.",
                "Portfolio Demo": "Portafolio demo con datos simulados.",
            }
        )
    if not is_beta_feature_enabled(BETA_SHOW_PORTFOLIO):
        hidden["Portafolio"] = "Watchlist/portafolio queda fuera del foco inicial de beta."
    if not is_beta_feature_enabled(BETA_SHOW_ALERTS):
        hidden["Alertas"] = "Alertas reales aun no son core beta."
    return hidden


def is_demo_mode() -> bool:
    if is_tasar_playground_mode() and not is_tasar_playground_demo_mode_explicitly_enabled():
        return False
    return bool(st.session_state.get(DEMO_MODE_KEY, False))


def set_demo_mode(value: bool) -> None:
    if bool(value) and is_tasar_playground_mode() and not is_tasar_playground_demo_mode_explicitly_enabled():
        st.session_state[DEMO_MODE_KEY] = False
        return
    if bool(value) and is_beta_mode() and not is_beta_feature_enabled(BETA_SHOW_PRODUCT_LAB):
        st.session_state[DEMO_MODE_KEY] = False
        return
    st.session_state[DEMO_MODE_KEY] = bool(value)


def is_tasar_playground_demo_mode_explicitly_enabled() -> bool:
    return _env_bool(TASAR_PLAYGROUND_DEMO_MODE_ENV, default=False)


def is_known_feature(flag_name: str) -> bool:
    return flag_name in _FLAG_BY_NAME


def feature_session_key(flag_name: str) -> str:
    if not is_known_feature(flag_name):
        raise ValueError(f"Unknown Product Lab feature flag: {flag_name}")
    return f"{FEATURE_FLAG_PREFIX}{flag_name}"


def is_feature_enabled(flag_name: str) -> bool:
    """Return True only when Demo Mode and the specific feature are enabled."""
    if not is_demo_mode() or not is_known_feature(flag_name):
        return False
    flag = _FLAG_BY_NAME[flag_name]
    return bool(st.session_state.get(feature_session_key(flag_name), flag.default))


def set_feature_flag(flag_name: str, value: bool) -> None:
    st.session_state[feature_session_key(flag_name)] = bool(value)


def get_enabled_demo_features() -> list[str]:
    return [flag.name for flag in DEMO_FEATURE_FLAGS if is_feature_enabled(flag.name)]


def get_demo_feature_flags() -> tuple[FeatureFlag, ...]:
    return DEMO_FEATURE_FLAGS


def mark_demo_dataset_loaded() -> None:
    st.session_state[DEMO_DATASET_LOADED_KEY] = True


def is_demo_dataset_loaded() -> bool:
    return bool(st.session_state.get(DEMO_DATASET_LOADED_KEY, False))


def get_demo_scenarios() -> tuple[str, ...]:
    return DEMO_SCENARIOS


def get_demo_scenario() -> str:
    value = st.session_state.get(DEMO_SCENARIO_KEY, DEMO_SCENARIOS[0])
    return value if isinstance(value, str) and value in DEMO_SCENARIOS else DEMO_SCENARIOS[0]


def set_demo_scenario(value: str) -> None:
    st.session_state[DEMO_SCENARIO_KEY] = value if value in DEMO_SCENARIOS else DEMO_SCENARIOS[0]


def normalize_ui_version(value: str | None) -> str:
    text = (value or "").strip().lower()
    if text in UI_VERSION_OPTIONS:
        return text
    return UI_VERSION_ALIASES.get(text, UI_VERSION_LEGACY)


def get_ui_version_options() -> tuple[str, ...]:
    return UI_VERSION_OPTIONS


def get_ui_version_label(value: str) -> str:
    return UI_VERSION_LABELS.get(normalize_ui_version(value), UI_VERSION_LABELS[UI_VERSION_LEGACY])


def get_ui_version() -> str:
    session_value = st.session_state.get(UI_VERSION_KEY)
    if isinstance(session_value, str) and session_value.strip():
        return normalize_ui_version(session_value)
    return normalize_ui_version(os.getenv(UI_VERSION_ENV))


def set_ui_version(value: str) -> None:
    st.session_state[UI_VERSION_KEY] = normalize_ui_version(value)


def is_tasar_playground_mode() -> bool:
    return get_ui_version() == UI_VERSION_TASAR_PLAYGROUND


def is_demo_ui_version() -> bool:
    return get_ui_version() == UI_VERSION_DEMO


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
