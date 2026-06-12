"""Guided Owner Journey Demo page."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient
from ui.components.layout import metric_card, section_header
from ui.components.market_context import render_demo_market_context
from ui.components.theme import html_escape, inject_theme, tone_class
from ui.demo_data import get_demo_listings
from ui.demo_owner_journey import (
    DEMO_OWNER_SCENARIOS,
    build_owner_journey_report,
    ensure_demo_owner_journey_state,
    select_owner_property,
    set_owner_scenario,
)
from ui.formatting import format_uf
from ui.lab import LAB_DISCLAIMER


def render(client: ApiClient) -> None:
    _ = client
    listings = get_demo_listings()
    state = ensure_demo_owner_journey_state(st.session_state, listings)
    by_id = {int(item["listing_id"]): item for item in listings}
    selected_listing = by_id.get(int(state["selected_property"] or listings[0]["listing_id"]), listings[0])

    section_header("Owner Journey", "Juega escenarios demo: vender ahora, esperar, arrendar o preparar venta.")
    st.info(LAB_DISCLAIMER)
    _render_controls(state, listings, selected_listing)
    selected_listing = by_id[int(state["selected_property"])]
    report = build_owner_journey_report(
        selected_listing,
        improvement_budget_uf=int(state["improvement_budget_uf"]),
        rent_yield_pct=float(state["rent_yield_pct"]),
        holding_months=int(state["holding_months"]),
    )
    st.caption(report["disclaimer"])
    _render_property_summary(report, selected_listing)
    render_demo_market_context(report["market_context"], expanded=True)
    _render_simulator(report)
    _render_recommendations(report, state)


def _render_controls(state: dict[str, Any], listings: list[dict[str, Any]], selected_listing: dict[str, Any]) -> None:
    labels = {f"{item['title']} | {item['comuna']} | {format_uf(item['estimated_value_uf'])}": item for item in listings}
    current = next(
        (label for label, item in labels.items() if item["listing_id"] == selected_listing["listing_id"]),
        next(iter(labels)),
    )
    selected = st.selectbox("Propiedad demo del propietario", list(labels), index=list(labels).index(current), key="owner-journey-property")
    select_owner_property(state, int(labels[selected]["listing_id"]))
    cols = st.columns(4, gap="small")
    state["improvement_budget_uf"] = int(cols[0].number_input("Mejoras UF", min_value=0, max_value=2000, value=int(state["improvement_budget_uf"]), step=25))
    state["rent_yield_pct"] = float(cols[1].number_input("Yield arriendo %", min_value=1.0, max_value=8.0, value=float(state["rent_yield_pct"]), step=0.1))
    state["holding_months"] = int(cols[2].number_input("Meses espera", min_value=1, max_value=18, value=int(state["holding_months"]), step=1))
    scenario_options = sorted(DEMO_OWNER_SCENARIOS)
    selected_scenario = cols[3].selectbox(
        "Escenario foco",
        scenario_options,
        index=scenario_options.index(state["selected_scenario"]),
        key="owner-scenario-focus",
    )
    set_owner_scenario(state, selected_scenario)


def _render_property_summary(report: dict[str, Any], listing: dict[str, Any]) -> None:
    st.subheader("Resumen de propiedad")
    cols = st.columns(4, gap="small")
    with cols[0]:
        metric_card("Valor estimado", format_uf(report["estimated_value_uf"]), caption="Demo", tone="premium")
    with cols[1]:
        metric_card("Liquidez", f"{report['liquidity']}/100", caption="Comuna", tone="positive" if report["liquidity"] >= 78 else "warning")
    with cols[2]:
        metric_card("Demanda", str(report["demand"]).title(), caption="Market Context", tone="positive")
    with cols[3]:
        metric_card("Competencia", str(report["competition"]).title(), caption="Compradores", tone="warning")
    cols2 = st.columns(3, gap="small")
    with cols2[0]:
        metric_card("Riesgo esperar", str(report["wait_risk"]).title(), caption="Simulado", tone=_risk_tone(report["wait_risk"]))
    with cols2[1]:
        metric_card("Potencial arriendo", str(report["rental_potential"]).title(), caption="Demo", tone="premium")
    with cols2[2]:
        metric_card("Tipo", listing["property_type"], caption=listing["comuna"], tone="neutral")


def _render_simulator(report: dict[str, Any]) -> None:
    sim = report["simulator"]
    st.subheader("Simulador simple")
    cols = st.columns(4, gap="small")
    with cols[0]:
        metric_card("Vender ahora", format_uf(sim["sell_now_price_uf"]), caption="Precio esperado", tone="positive")
    with cols[1]:
        metric_card("Esperar", format_uf(sim["wait_price_uf"]), caption=f"{sim['holding_months']} meses", tone="premium")
    with cols[2]:
        metric_card("Arriendo anual", format_uf(sim["annual_rent_income_uf"]), caption="Ingreso estimado", tone="positive")
    with cols[3]:
        metric_card("Costos simulados", format_uf(sim["simulated_costs_uf"]), caption="Mejoras + espera", tone="warning")
    sensitivity = sim["sensitivity"]
    st.caption(
        "Sensibilidad demo: "
        f"downside {format_uf(sensitivity['downside_uf'])} | "
        f"base {format_uf(sensitivity['base_uf'])} | "
        f"upside {format_uf(sensitivity['upside_uf'])}"
    )


def _render_recommendations(report: dict[str, Any], state: dict[str, Any]) -> None:
    st.subheader("Recomendaciones demo")
    focused = state["selected_scenario"]
    for item in report["recommendations"]:
        expanded = item["scenario"] == focused
        with st.expander(item["label"], expanded=expanded):
            st.markdown(_badge(f"riesgo {item['risk']}", _risk_tone(item["risk"])), unsafe_allow_html=True)
            cols = st.columns(3, gap="medium")
            with cols[0]:
                _list_card("Pros", item["pros"], "positive")
            with cols[1]:
                _list_card("Contras", item["contras"], "warning")
            with cols[2]:
                _list_card("Supuestos", item["assumptions"], "neutral")
            st.caption(f"Confianza demo: {item['demo_confidence']}. {report['disclaimer']}")


def _list_card(title: str, items: list[str], tone: str) -> None:
    body = "".join(f"<li>{html_escape(item)}</li>" for item in items)
    st.markdown(
        f"""
        <div class="avm-card">
            <div style="font-weight:750; color:var(--avm-text);">{html_escape(title)}</div>
            <ul style="margin:0.55rem 0 0 1.1rem; color:var(--avm-muted);">{body}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _ = tone


def _badge(label: str, tone: str) -> str:
    inject_theme()
    return f'<span class="avm-badge {tone_class("avm-badge", tone)}">{html_escape(label)}</span>'


def _risk_tone(value: str) -> str:
    if value == "alto":
        return "negative"
    if value == "medio":
        return "warning"
    return "positive"
