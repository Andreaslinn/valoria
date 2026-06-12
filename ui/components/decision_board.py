"""Decision Board Lab UI components."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.components.activity import render_demo_property_activity
from ui.components.checklist import render_demo_due_diligence_checklist
from ui.components.feedback import record_lab_event, render_lab_feedback_widget
from ui.components.layout import metric_card
from ui.components.offer_simulator import render_demo_offer_simulator
from ui.components.risk_report import render_demo_risk_report
from ui.components.theme import html_escape, inject_theme, tone_class
from ui.demo_decision_board import (
    DEMO_DECISION_BOARD_STATUSES,
    move_demo_decision_property,
    summarize_demo_decision_board,
    sync_decision_status_to_portfolio,
)
from ui.demo_providers import (
    get_demo_autofact_report,
    get_demo_property_activity,
    get_demo_risk_report,
)
from ui.formatting import format_uf


def render_demo_decision_summary(cards: list[dict[str, Any]]) -> None:
    summary = summarize_demo_decision_board(cards)
    cols = st.columns(4, gap="small")
    with cols[0]:
        metric_card("Decisiones pendientes", summary["pending_decisions"], caption="Descubrir, seguir o contactar", tone="warning")
    with cols[1]:
        metric_card("Riesgos abiertos", summary["open_risks"], caption="No descartadas", tone="negative" if summary["open_risks"] else "positive")
    with cols[2]:
        metric_card("Favoritas", summary["counts_by_status"]["favorita"], caption="Candidatas priorizadas", tone="positive")
    with cols[3]:
        metric_card("En negociacion", summary["counts_by_status"]["negociar"], caption="Con oferta por preparar", tone="premium")
    best = summary["best_candidates"]
    if best:
        st.caption("Mejores candidatas: " + " | ".join(f"{item['title']} ({item['score']:.1f})" for item in best))


def render_demo_decision_board(
    cards: list[dict[str, Any]],
    board_state: dict[str, Any],
    *,
    portfolio_state: dict[str, Any] | None = None,
    key_prefix: str = "decision-board",
) -> None:
    inject_theme()
    status_items = list(DEMO_DECISION_BOARD_STATUSES.items())
    for row_start in range(0, len(status_items), 3):
        cols = st.columns(3, gap="medium")
        for col, (status, label) in zip(cols, status_items[row_start:row_start + 3], strict=False):
            with col:
                stage_cards = [card for card in cards if card["status"] == status]
                st.subheader(f"{label} ({len(stage_cards)})")
                if not stage_cards:
                    st.caption("Sin propiedades en esta etapa.")
                for card in stage_cards:
                    _render_card(card, board_state, portfolio_state, key_prefix)


def render_demo_decision_property_control(
    listing: dict[str, Any],
    board_state: dict[str, Any],
    *,
    portfolio_state: dict[str, Any] | None = None,
    key_prefix: str = "decision-control",
) -> None:
    property_id = int(listing["listing_id"])
    current = board_state["items"].get(str(property_id), {}).get("status", "descubierta")
    labels = {label: status for status, label in DEMO_DECISION_BOARD_STATUSES.items()}
    st.markdown(
        '<div class="avm-lab-control-shell"><div class="avm-lab-control-shell__title">Mover etapa</div>',
        unsafe_allow_html=True,
    )
    selected = st.selectbox(
        "Etapa en Decision Board",
        list(labels),
        index=list(labels.values()).index(current) if current in labels.values() else 0,
        key=f"{key_prefix}-{property_id}",
        label_visibility="collapsed",
    )
    st.markdown("</div>", unsafe_allow_html=True)
    status = labels[selected]
    if status != current:
        move_demo_decision_property(board_state, property_id, status)
        record_lab_event(
            "moved_decision_card_demo",
            module="decision_board",
            property_id=property_id,
            metadata={"from": current, "to": status},
        )
        if portfolio_state is not None:
            sync_decision_status_to_portfolio(status, portfolio_state, listing)
        st.success("Decision Board actualizado.")
        st.rerun()


def _render_card(
    card: dict[str, Any],
    board_state: dict[str, Any],
    portfolio_state: dict[str, Any] | None,
    key_prefix: str,
) -> None:
    listing = card["listing"]
    property_id = int(card["property_id"])
    st.markdown(
        f"""
        <div class="avm-card avm-decision-compact-card">
            <div style="display:flex; justify-content:space-between; gap:0.75rem; align-items:flex-start;">
                <div>
                    <div style="font-weight:800; color:var(--avm-text);">{html_escape(card["title"])}</div>
                    <div style="color:var(--avm-muted); margin-top:0.25rem;">
                        {html_escape(card["comuna"])} · {format_uf(card["price_uf"])}
                    </div>
                </div>
                <div style="display:flex; gap:0.35rem; flex-wrap:wrap; justify-content:flex-end;">
                    {_badge(f"Score {card['score']:.1f}", "premium")}
                    {_badge(card["risk"], card["risk_tone"])}
                </div>
            </div>
            <div style="color:var(--avm-muted); margin-top:0.55rem;">{html_escape(card["main_signal"])}</div>
            <div style="color:var(--avm-text); font-weight:650; margin-top:0.45rem;">{html_escape(card["next_action"])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_demo_decision_property_control(
        listing,
        board_state,
        portfolio_state=portfolio_state,
        key_prefix=f"{key_prefix}-move",
    )
    with st.expander("Abrir acciones", expanded=False):
        risk_report = get_demo_risk_report(property_id, demo_mode=True)
        autofact_report = get_demo_autofact_report(property_id, demo_mode=True)
        render_demo_risk_report(risk_report, expanded=False, key_suffix=f"{key_prefix}-actions", use_expander=False)
        render_demo_due_diligence_checklist(
            listing,
            risk_report=risk_report,
            autofact_report=autofact_report,
            expanded=False,
            key_prefix=f"{key_prefix}-checklist-{property_id}",
            use_expander=False,
        )
        render_demo_offer_simulator(
            listing,
            buyer_profile="primer_comprador",
            strategy=risk_report.get("negotiation_signals", {}).get("strategy", "moderada"),
            risk_report=risk_report,
            expanded=False,
            key_prefix=f"{key_prefix}-offer-{property_id}",
            use_expander=False,
        )
        render_demo_property_activity(
            get_demo_property_activity(property_id, demo_mode=True),
            key=f"{key_prefix}-timeline-{property_id}",
            use_expander=False,
        )
        render_lab_feedback_widget("decision_board", property_id=property_id, key_prefix=f"{key_prefix}-feedback")


def _badge(label: str, tone: str) -> str:
    return f'<span class="avm-badge {tone_class("avm-badge", tone)}">{html_escape(label)}</span>'
