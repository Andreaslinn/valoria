"""Streamlit entrypoint for the AVM UI."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

st.set_page_config(
    page_title="AVM Chile",
    page_icon=":house:",
    layout="wide",
    initial_sidebar_state=(
        "expanded"
        if os.getenv("AVM_UI_VERSION", "").strip().lower()
        in {"tasar_playground", "demo_redesign", "neo_dark_demo", "ui_playground"}
        else "collapsed"
    ),
)

from ui.api_client import ApiClient, ApiError  # noqa: E402
from ui.app_shell import (  # noqa: E402
    BETA_NAV_ITEMS,
    DEMO_NAV_ITEMS,
    NAV_ITEMS,
    inject_shell_styles,
    render_app_shell,
)
from ui.auth import render_auth  # noqa: E402
from ui.components.metrics import health_metrics  # noqa: E402
from ui.components.theme import inject_theme, theme_toggle  # noqa: E402
from ui.feature_flags import (  # noqa: E402
    BETA_SHOW_PRODUCT_LAB,
    get_demo_feature_flags,
    get_demo_scenario,
    get_demo_scenarios,
    get_enabled_demo_features,
    get_ui_version,
    get_ui_version_label,
    get_ui_version_options,
    is_beta_feature_enabled,
    is_beta_mode,
    is_demo_dataset_loaded,
    is_demo_mode,
    is_demo_ui_version,
    is_feature_enabled,
    is_tasar_playground_mode,
    mark_demo_dataset_loaded,
    set_demo_mode,
    set_demo_scenario,
    set_feature_flag,
    set_ui_version,
)
from ui.lab import LAB_DISCLAIMER  # noqa: E402
from ui.pages import (  # noqa: E402
    alerts_lab,
    alerts_real,
    buyer_journey,
    checklist_lab,
    dashboard,
    decision_board_lab,
    lab_feedback,
    lab_reports,
    owner_journey,
    property_experience,
    radar,
    tasacion,
    tracking,
)
from ui.pages.lab import radar_lab, tracking_lab  # noqa: E402
from ui.product_usage import track_page_view, track_session  # noqa: E402
from ui.state import get_api_base_url, get_token, set_api_base_url  # noqa: E402

__all__ = ["BETA_NAV_ITEMS", "DEMO_NAV_ITEMS", "NAV_ITEMS", "main", "render_health"]


def main() -> None:
    st.session_state["avm_color_mode"] = "dark"
    inject_theme()
    inject_shell_styles()

    base_url = _render_technical_sidebar()
    client = ApiClient(base_url=base_url)
    if not get_token():
        render_auth(client, container=st)
        return
    track_session()
    page = render_app_shell()
    track_page_view(page)
    _render_page(page, client, base_url)


def _render_page(page: str, client: ApiClient, base_url: str) -> None:
    if page == "Dashboard Lab":
        dashboard.render(client)
    elif page == "Alertas Lab":
        if is_tasar_playground_mode():
            from ui.redesign.alerts_view import render as render_alerts_playground

            render_alerts_playground(client)
        else:
            alerts_lab.render(client)
    elif page == "Checklist Lab":
        checklist_lab.render(client)
    elif page == "Decision Board Lab":
        decision_board_lab.render(client)
    elif page == "Lab Feedback":
        lab_feedback.render(client)
    elif page == "Buyer Journey":
        buyer_journey.render(client)
    elif page == "Owner Journey":
        owner_journey.render(client)
    elif page == "Property Experience":
        property_experience.render(client)
    elif page == "Risk Report":
        lab_reports.render_risk_report(client)
    elif page == "Autofact Demo":
        lab_reports.render_autofact(client)
    elif page == "Portfolio Demo":
        tracking_lab.render(client)
    elif page == "Tasar propiedad":
        tasacion.render(client)
    elif page == "Radar":
        if is_tasar_playground_mode():
            from ui.redesign.radar_view import render as render_radar_playground

            render_radar_playground(client)
        elif is_demo_mode():
            radar_lab.render(client)
        else:
            radar.render(client)
    elif page == "Portafolio":
        if is_tasar_playground_mode():
            from ui.redesign.portfolio_view import render as render_portfolio_playground

            render_portfolio_playground(client)
        elif is_demo_mode():
            tracking_lab.render(client)
        else:
            tracking.render(client)
    elif page == "Alertas":
        if is_tasar_playground_mode():
            from ui.redesign.alerts_view import render as render_alerts_playground

            render_alerts_playground(client)
        else:
            alerts_real.render(client)
    else:
        render_health(client, base_url)


def _render_technical_sidebar() -> str:
    dev_mode = _is_dev_mode()
    base_url = get_api_base_url()
    if is_tasar_playground_mode():
        set_demo_mode(True)
        from ui.redesign.tasar_playground import render_sidebar_shell

        render_sidebar_shell(base_url)
        if dev_mode:
            st.sidebar.caption("Dev mode activo")
            base_url = _render_developer_tools(base_url)
        return base_url

    _render_ui_version_sidebar()

    with st.sidebar.expander("Apariencia", expanded=False):
        theme_toggle()
    _render_demo_mode_sidebar(force_demo=is_demo_ui_version())

    if dev_mode:
        st.sidebar.caption("Dev mode activo")
        base_url = _render_developer_tools(base_url)

    token = get_token()
    with st.sidebar.expander("Cuenta", expanded=bool(token)):
        if token:
            client = ApiClient(base_url=base_url)
            render_auth(client, container=st)
        else:
            st.caption("Inicia sesión para acceder a la app.")

    return base_url


def _render_ui_version_sidebar() -> None:
    options = list(get_ui_version_options())
    current = get_ui_version()
    with st.sidebar.expander("Version UI", expanded=False):
        selected = st.selectbox(
            "Seleccionar variante",
            options,
            index=options.index(current) if current in options else 0,
            format_func=get_ui_version_label,
        )
        set_ui_version(selected)
        if is_demo_ui_version():
            set_demo_mode(True)
            st.caption("Carga el modo demo/Product Lab actual.")
        elif is_tasar_playground_mode():
            st.caption("Carga solo la nueva pantalla experimental de Tasar.")
        else:
            st.caption("Carga la UI actual sin redisenar.")


def _is_dev_mode() -> bool:
    try:
        value = st.query_params.get("dev")
    except Exception:
        return False
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value) == "1"


def render_health(client: ApiClient, base_url: str) -> None:
    st.subheader("Estado / Admin")
    st.caption("Herramientas técnicas discretas para verificar conectividad.")

    health: dict | None = None
    error: str | None = None
    try:
        health = client.health()
    except ApiError as e:
        error = e.message

    health_metrics(health, base_url, error)
    with st.expander("Comando backend", expanded=False):
        st.code("python -m uvicorn api.main:app --reload", language="bash")


def _render_demo_mode_sidebar(*, force_demo: bool = False) -> None:
    if is_beta_mode() and not is_beta_feature_enabled(BETA_SHOW_PRODUCT_LAB):
        set_demo_mode(False)
        with st.sidebar.expander("Modo demo", expanded=False):
            st.caption("Product Lab oculto en BETA_MODE para mantener una beta factual.")
        return

    with st.sidebar.expander("Modo demo", expanded=False):
        if force_demo:
            set_demo_mode(True)
            st.toggle("Modo demo", value=True, disabled=True)
            st.caption("Activo por la version UI demo.")
            demo_enabled = True
        else:
            demo_enabled = st.toggle("Modo demo", value=is_demo_mode())
            set_demo_mode(demo_enabled)
        if not demo_enabled:
            st.caption("Activa una experiencia simulada para explorar el Product Lab.")
            return

        st.caption(LAB_DISCLAIMER)
        scenario = st.selectbox(
            "Escenario demo",
            get_demo_scenarios(),
            index=get_demo_scenarios().index(get_demo_scenario()),
        )
        set_demo_scenario(scenario)
        if st.button("Cargar datos demo", type="secondary"):
            mark_demo_dataset_loaded()
            st.success("Datos demo cargados para esta sesión.")
        if is_demo_dataset_loaded():
            st.caption(f"Dataset activo: {scenario}.")


def _render_developer_tools(base_url: str) -> str:
    with st.sidebar.expander("Panel desarrollador", expanded=False):
        base_url = st.text_input("API base URL", value=base_url)
        st.caption("Solo para desarrollo o despliegues con API externa.")
        set_api_base_url(base_url)

        enabled_features = get_enabled_demo_features()
        st.divider()
        st.caption(f"Feature flags demo activas: {len(enabled_features)}")
        for flag in get_demo_feature_flags():
            value = st.toggle(
                flag.label,
                value=is_feature_enabled(flag.name),
                help=flag.description,
                key=f"toggle_{flag.name}",
            )
            set_feature_flag(flag.name, value)
    return base_url


if __name__ == "__main__":
    main()
