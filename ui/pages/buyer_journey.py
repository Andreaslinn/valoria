"""Guided Buyer Journey Demo page."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient
from ui.components.activity import render_demo_property_activity
from ui.components.alerts import render_demo_alert_list
from ui.components.checklist import render_demo_due_diligence_checklist
from ui.components.decision_board import render_demo_decision_property_control
from ui.components.feedback import record_lab_event, render_lab_feedback_widget
from ui.components.layout import metric_card, render_focus_property_bar, section_header
from ui.components.negotiation import render_demo_negotiation_signals
from ui.components.offer_simulator import render_demo_offer_simulator
from ui.components.risk_report import render_demo_risk_report
from ui.components.theme import html_escape, inject_theme, tone_class
from ui.demo_alerts import build_demo_alerts, ensure_demo_alert_state, with_demo_alert_read_state
from ui.demo_buyer_journey import (
    DEMO_BUYER_PROFILES,
    ensure_demo_buyer_journey_state,
    generate_decision_thesis,
    save_journey_property,
    select_journey_property,
    set_buyer_profile,
    set_journey_notes,
    set_journey_offer_strategy,
    set_journey_strategy,
)
from ui.demo_data import get_demo_listings, get_demo_portfolio
from ui.demo_decision_board import ensure_demo_decision_board_state
from ui.demo_negotiation import build_demo_negotiation_report
from ui.demo_portfolio import add_demo_property, ensure_demo_portfolio_state
from ui.demo_providers import (
    get_demo_autofact_report,
    get_demo_property_activity,
    get_demo_property_comparison,
    get_demo_risk_report,
)
from ui.formatting import format_uf
from ui.lab import LAB_DISCLAIMER
from ui.lab_focus import get_focused_demo_listing, set_focus_property


def render(client: ApiClient) -> None:
    _ = client
    listings = get_demo_listings()
    state = ensure_demo_buyer_journey_state(st.session_state, listings)
    portfolio_state = ensure_demo_portfolio_state(st.session_state, get_demo_portfolio())
    board_state = ensure_demo_decision_board_state(st.session_state, listings, portfolio_state)
    by_id = {int(item["listing_id"]): item for item in listings}
    selected_listing = by_id.get(int(state["selected_property"] or listings[0]["listing_id"]), listings[0])
    set_focus_property(int(selected_listing["listing_id"]), source="Buyer Journey")

    section_header("Buyer Journey", "Flujo demo para descubrir, analizar, comparar y cerrar una tesis de decision.")
    st.info(LAB_DISCLAIMER)
    render_focus_property_bar(get_focused_demo_listing())
    _render_profile_controls(state)
    _render_stepper()
    _render_explore_step(state, listings, selected_listing)
    selected_listing = by_id[int(state["selected_property"])]
    _render_save_step(state, portfolio_state, board_state, selected_listing)
    _render_buyer_alerts(listings, selected_listing, by_id)
    _render_activity_step(selected_listing)
    _render_risk_step(selected_listing)
    _render_negotiation_step(state, selected_listing)
    _render_compare_step(selected_listing)
    _render_thesis_step(state, selected_listing)


def _render_profile_controls(state: dict[str, Any]) -> None:
    st.markdown(
        '<div class="avm-lab-control-shell"><div class="avm-lab-control-shell__title">Preferencias del comprador</div>',
        unsafe_allow_html=True,
    )
    labels = {profile["label"]: key for key, profile in DEMO_BUYER_PROFILES.items()}
    current_label = DEMO_BUYER_PROFILES[state["buyer_profile"]]["label"]
    cols = st.columns([1.2, 0.8, 1.2], gap="medium")
    selected = cols[0].selectbox("Perfil comprador demo", list(labels), index=list(labels).index(current_label))
    if labels[selected] != state["buyer_profile"]:
        set_buyer_profile(state, labels[selected])
        st.rerun()
    state["budget_uf"] = int(cols[1].number_input("Presupuesto UF", min_value=1000, max_value=30000, value=int(state["budget_uf"]), step=250))
    communes = sorted({commune for profile in DEMO_BUYER_PROFILES.values() for commune in profile["target_communes"]})
    state["target_communes"] = cols[2].multiselect("Comunas objetivo", communes, default=state["target_communes"])
    profile = DEMO_BUYER_PROFILES[state["buyer_profile"]]
    st.caption(f"{profile['recommendation_bias']} Riesgos relevantes: {', '.join(profile['risk_focus'])}.")
    st.markdown("</div>", unsafe_allow_html=True)


def _render_stepper() -> None:
    steps = [
        "1. Explorar oportunidades",
        "2. Guardar propiedad",
        "3. Revisar historial",
        "4. Abrir Risk Report",
        "5. Elegir estrategia",
        "6. Comparar",
        "7. Guardar tesis",
    ]
    st.markdown(" ".join(_badge(step, "premium" if index == 0 else "neutral") for index, step in enumerate(steps)), unsafe_allow_html=True)


def _render_explore_step(state: dict[str, Any], listings: list[dict[str, Any]], selected_listing: dict[str, Any]) -> None:
    st.subheader("1. Explorar oportunidades")
    filtered = [
        item for item in listings
        if item["price_uf"] <= int(state["budget_uf"]) and (not state["target_communes"] or item["comuna"] in state["target_communes"])
    ] or listings
    ranked = sorted(filtered, key=lambda item: (float(item.get("discount_pct") or 0), float(item.get("score") or 0)), reverse=True)
    labels = {f"{item['title']} | {item['comuna']} | {format_uf(item['price_uf'])}": item for item in ranked[:8]}
    current = next(
        (label for label, item in labels.items() if item["listing_id"] == selected_listing["listing_id"]),
        next(iter(labels)),
    )
    selected = st.selectbox("Propiedad candidata", list(labels), index=list(labels).index(current), key="buyer-journey-property")
    select_journey_property(state, int(labels[selected]["listing_id"]))
    set_focus_property(int(labels[selected]["listing_id"]), source="Buyer Journey")
    _property_card(labels[selected])


def _render_save_step(
    state: dict[str, Any],
    portfolio_state: dict[str, Any],
    board_state: dict[str, Any],
    listing: dict[str, Any],
) -> None:
    st.subheader("2. Guardar una propiedad")
    saved = int(listing["listing_id"]) in state["saved_properties"]
    cols = st.columns(3, gap="small")
    with cols[0]:
        metric_card("Estado journey", "Guardada" if saved else "No guardada", caption="Demo", tone="positive" if saved else "warning")
    with cols[1]:
        metric_card("Precio", format_uf(listing["price_uf"]), caption="Publicado demo", tone="neutral")
    with cols[2]:
        metric_card("Score", f"{listing['score']:.1f}", caption="Radar demo", tone="premium")
    if st.button("Guardar propiedad en journey y portafolio demo", key=f"journey-save-{listing['listing_id']}"):
        save_journey_property(state, int(listing["listing_id"]))
        add_demo_property(portfolio_state, listing)
        set_focus_property(int(listing["listing_id"]), source="Buyer Journey")
        record_lab_event("saved_property_demo", module="decision_board", property_id=int(listing["listing_id"]))
        st.success("Propiedad guardada en journey y portafolio demo.")
        st.rerun()
    with st.expander("Etapa en Decision Board Lab", expanded=False):
        render_demo_decision_property_control(
            listing,
            board_state,
            portfolio_state=portfolio_state,
            key_prefix=f"buyer-board-{listing['listing_id']}",
        )


def _render_buyer_alerts(
    listings: list[dict[str, Any]],
    selected_listing: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
) -> None:
    property_id = int(selected_listing["listing_id"])
    alerts = [
        alert
        for alert in build_demo_alerts(listings, demo_mode=True)
        if alert.get("property_id") in {None, property_id}
    ]
    state = ensure_demo_alert_state(st.session_state, alerts)
    hydrated = with_demo_alert_read_state(alerts, state)
    with st.expander("Alertas Lab para esta decision", expanded=False):
        render_demo_alert_list(hydrated, state, by_id, key_prefix=f"buyer-alerts-{property_id}", limit=3)


def _render_activity_step(listing: dict[str, Any]) -> None:
    st.subheader("3. Revisar historial y actividad")
    render_demo_property_activity(get_demo_property_activity(int(listing["listing_id"]), demo_mode=True), key=f"journey-activity-{listing['listing_id']}")


def _render_risk_step(listing: dict[str, Any]) -> None:
    st.subheader("4. Abrir Risk Report")
    property_id = int(listing["listing_id"])
    risk_report = get_demo_risk_report(property_id, demo_mode=True)
    render_demo_due_diligence_checklist(
        listing,
        risk_report=risk_report,
        autofact_report=get_demo_autofact_report(property_id, demo_mode=True),
        expanded=False,
        key_prefix=f"buyer-checklist-{property_id}",
    )
    render_demo_risk_report(risk_report, expanded=False, key_suffix=f"buyer-{property_id}")


def _render_negotiation_step(state: dict[str, Any], listing: dict[str, Any]) -> None:
    st.subheader("5. Elegir estrategia y simular oferta")
    report = build_demo_negotiation_report(listing)
    risk_report = get_demo_risk_report(int(listing["listing_id"]), demo_mode=True)
    options = ["conservadora", "moderada", "agresiva"]
    selected = st.segmented_control(
        "Estrategia elegida",
        options,
        default=state.get("selected_strategy", report["strategy"]),
        key=f"journey-strategy-{listing['listing_id']}",
        label_visibility="collapsed",
    )
    selected = selected or state.get("selected_strategy", report["strategy"])
    set_journey_strategy(state, selected)
    render_demo_negotiation_signals(report, expanded=True)
    simulation = render_demo_offer_simulator(
        listing,
        buyer_profile=str(state["buyer_profile"]),
        strategy=selected,
        risk_report=risk_report,
        expanded=True,
        key_prefix=f"buyer-offer-{listing['listing_id']}",
    )
    if st.button("Guardar estrategia demo en Buyer Journey", type="primary", key=f"save-offer-{listing['listing_id']}"):
        set_journey_offer_strategy(state, simulation)
        generate_decision_thesis(state, listing)
        st.success("Estrategia demo guardada en la tesis del Buyer Journey.")


def _render_compare_step(listing: dict[str, Any]) -> None:
    st.subheader("6. Comparar con otra propiedad")
    comparison = [item for item in get_demo_property_comparison(int(listing["listing_id"])) if item["property_id"] != listing["listing_id"]]
    if not comparison:
        st.caption("Sin comparables demo para esta propiedad.")
        return
    cols = st.columns(min(3, len(comparison)), gap="medium")
    for col, item in zip(cols, comparison[:3], strict=False):
        with col:
            metric_card(item["label"], format_uf(item["price_uf"]), caption=item["fit"], tone="premium")
            st.caption(f"Liquidez {item['liquidity_score']}/100 · Legal {item['legal_score']}/100")


    render_lab_feedback_widget(
        "comparison",
        property_id=int(listing["listing_id"]),
        key_prefix=f"buyer-comparison-{listing['listing_id']}",
    )


def _render_thesis_step(state: dict[str, Any], listing: dict[str, Any]) -> None:
    st.subheader("7. Guardar tesis")
    notes = st.text_area("Notas de decisión demo", value=state.get("decision_notes", ""), key=f"journey-notes-{listing['listing_id']}")
    set_journey_notes(state, notes)
    if st.button("Generar y guardar tesis demo", type="primary", key=f"journey-thesis-{listing['listing_id']}"):
        generate_decision_thesis(state, listing)
        st.success("Tesis demo guardada.")
    thesis = state.get("decision_thesis") or generate_decision_thesis(state, listing)
    _render_thesis(thesis)


def _property_card(listing: dict[str, Any]) -> None:
    inject_theme()
    st.markdown(
        f"""
        <div class="avm-card">
            <div style="display:flex; justify-content:space-between; gap:0.75rem; align-items:flex-start;">
                <div>
                    <div style="font-weight:800; color:var(--avm-text);">{html_escape(listing["title"])}</div>
                    <div style="color:var(--avm-muted); margin-top:0.25rem;">{html_escape(listing["short_summary"])}</div>
                </div>
                {_badge(f"{listing['discount_pct']}% brecha", "positive" if listing["discount_pct"] >= 5 else "warning")}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_thesis(thesis: dict[str, Any]) -> None:
    st.markdown(
        f"""
        <div class="avm-card">
            <div style="font-weight:800; color:var(--avm-text);">Decision thesis demo</div>
            <div style="color:var(--avm-muted); margin-top:0.4rem;">{html_escape(thesis["why_this_property"])}</div>
            <div style="margin-top:0.6rem;">{_badge(thesis["confidence_level"], "positive" if thesis["confidence_level"] == "alta" else "warning")}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(3, gap="medium")
    with cols[0]:
        metric_card("Oferta sugerida", format_uf(thesis["suggested_offer_uf"]), caption=thesis["selected_strategy"], tone="premium")
    with cols[1]:
        metric_card("Perfil", thesis["profile_label"], caption="Demo", tone="neutral")
    with cols[2]:
        metric_card("Confianza", thesis["confidence_level"].title(), caption="Tesis demo", tone="positive" if thesis["confidence_level"] == "alta" else "warning")
    st.caption(
        f"Oferta guardada: {format_uf(thesis['suggested_offer_uf'])} | "
        f"Aceptacion demo {thesis.get('offer_acceptance_probability', 0)}% | "
        f"Riesgo {thesis.get('offer_risk', 'demo')}"
    )
    st.caption("Argumento de negociacion: " + thesis.get("negotiation_argument", "No guardado."))
    st.caption("Riesgos principales: " + ", ".join(thesis["main_risks"]))
    st.caption("Próximos pasos: " + " | ".join(thesis["next_steps"]))
    if thesis.get("notes"):
        st.info(thesis["notes"])
    st.caption(thesis["disclaimer"])


def _badge(label: str, tone: str) -> str:
    return f'<span class="avm-badge {tone_class("avm-badge", tone)}">{html_escape(label)}</span>'
