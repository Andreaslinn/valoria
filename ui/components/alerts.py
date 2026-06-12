"""Demo Alert Center UI components."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.components.autofact import render_demo_autofact_report
from ui.components.decision_board import render_demo_decision_property_control
from ui.components.feedback import render_lab_feedback_widget
from ui.components.layout import metric_card
from ui.components.market_context import render_demo_market_context
from ui.components.risk_report import render_demo_risk_report
from ui.components.theme import html_escape, inject_theme, tone_class
from ui.demo_alerts import mark_demo_alert_read
from ui.demo_data import get_demo_listings, get_demo_portfolio
from ui.demo_decision_board import ensure_demo_decision_board_state
from ui.demo_market import get_demo_market_context
from ui.demo_portfolio import ensure_demo_portfolio_state
from ui.demo_providers import get_demo_autofact_report, get_demo_risk_report
from ui.formatting import format_uf


def render_demo_alert_summary(alerts: list[dict[str, Any]]) -> None:
    unread = sum(1 for alert in alerts if not alert.get("is_read"))
    critical = sum(1 for alert in alerts if alert["severity"] == "critical")
    opportunity = sum(1 for alert in alerts if alert["category"] in {"oportunidad", "precio", "negociacion"})
    cols = st.columns(3, gap="small")
    with cols[0]:
        metric_card("No leidas", unread, caption="Alertas Lab", tone="warning" if unread else "positive")
    with cols[1]:
        metric_card("Criticas demo", critical, caption="Revisar reportes", tone="negative" if critical else "neutral")
    with cols[2]:
        metric_card("Accionables", opportunity, caption="Precio y negociacion", tone="premium")


def render_demo_alert_list(
    alerts: list[dict[str, Any]],
    state: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
    *,
    key_prefix: str,
    limit: int | None = None,
) -> None:
    if not alerts:
        st.caption("Sin alertas demo para estos filtros.")
        return
    for index, alert in enumerate(alerts[:limit]):
        _render_alert_card(alert, state, by_id, key=f"{key_prefix}-{index}-{alert['id']}")
    render_lab_feedback_widget("alert_center", key_prefix=f"{key_prefix}-feedback")


def _render_alert_card(
    alert: dict[str, Any],
    state: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
    *,
    key: str,
) -> None:
    inject_theme()
    read_badge = _badge("Leida", "neutral") if alert.get("is_read") else _badge("Nueva", "warning")
    st.markdown(
        f"""
        <div class="avm-lab-insight-row">
            <div>
                <strong>{html_escape(alert["title"])}</strong>
                <p>{html_escape(alert["body"])}</p>
                <p>{html_escape(alert["created_at"])} / {html_escape(alert["category"])}</p>
            </div>
            <div style="display:flex; gap:0.35rem; flex-wrap:wrap; justify-content:flex-end;">
                {_badge(alert["severity"], _severity_tone(alert["severity"]))}
                {read_badge}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="avm-lab-evidence-group" style="padding-top:0.1rem; padding-bottom:0.1rem;">
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns([1, 1], gap="small")
    if not alert.get("is_read") and cols[0].button("Marcar como leida", key=f"read-{key}"):
        mark_demo_alert_read(state, alert["id"])
        st.success("Alerta marcada como leida.")
        st.rerun()
    elif alert.get("is_read"):
        cols[0].button("Ya leida", disabled=True, key=f"read-disabled-{key}")

    if cols[1].button(alert["action_label"], key=f"action-{key}"):
        st.session_state[f"alert_action_{key}"] = True
    st.markdown("</div>", unsafe_allow_html=True)
    if st.session_state.get(f"alert_action_{key}"):
        _render_action_target(alert, by_id, key)
    return
    st.markdown(
        f"""
        <div class="avm-card">
            <div style="display:flex; justify-content:space-between; gap:0.75rem; align-items:flex-start;">
                <div>
                    <div style="font-weight:800; color:var(--avm-text);">{html_escape(alert["title"])}</div>
                    <div style="color:var(--avm-muted); margin-top:0.3rem;">{html_escape(alert["body"])}</div>
                    <div style="color:var(--avm-muted); font-size:0.85rem; margin-top:0.45rem;">
                        {html_escape(alert["created_at"])} · {html_escape(alert["category"])}
                    </div>
                </div>
                <div style="display:flex; gap:0.35rem; flex-wrap:wrap; justify-content:flex-end;">
                    {_badge(alert["severity"], _severity_tone(alert["severity"]))}
                    {read_badge}
                    {_badge("Demo", "premium")}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns([1, 1], gap="small")
    if not alert.get("is_read") and cols[0].button("Marcar como leida", key=f"read-{key}"):
        mark_demo_alert_read(state, alert["id"])
        st.success("Alerta marcada como leida.")
        st.rerun()
    elif alert.get("is_read"):
        cols[0].button("Ya leida", disabled=True, key=f"read-disabled-{key}")

    if cols[1].button(alert["action_label"], key=f"action-{key}"):
        st.session_state[f"alert_action_{key}"] = True
    if st.session_state.get(f"alert_action_{key}"):
        _render_action_target(alert, by_id, key)


def _render_action_target(alert: dict[str, Any], by_id: dict[int, dict[str, Any]], key: str) -> None:
    target = alert["action_target"]
    target_type = target.get("type")
    property_id = target.get("property_id")
    prop = by_id.get(int(property_id)) if property_id is not None else None
    if target_type == "property" and prop is not None:
        with st.expander("Propiedad demo", expanded=True):
            st.write(prop["short_summary"])
            st.caption(f"{prop['comuna']} · {format_uf(prop['price_uf'])}")
            render_demo_autofact_report(
                get_demo_autofact_report(int(prop["listing_id"]), demo_mode=True),
                expanded=False,
                key_suffix=f"alert-{key}",
                use_expander=False,
            )
        return
    if target_type == "risk_report" and property_id is not None:
        render_demo_risk_report(
            get_demo_risk_report(int(property_id), demo_mode=True),
            expanded=True,
            key_suffix=f"alert-{key}",
            use_expander=False,
        )
        return
    if target_type == "buyer_journey" and prop is not None:
        st.info(f"Abre Buyer Journey y usa esta propiedad para simular oferta: {prop['title']}.")
        return
    if target_type == "decision_board" and prop is not None:
        portfolio_state = ensure_demo_portfolio_state(st.session_state, get_demo_portfolio())
        board_state = ensure_demo_decision_board_state(st.session_state, get_demo_listings(), portfolio_state)
        render_demo_decision_property_control(
            prop,
            board_state,
            portfolio_state=portfolio_state,
            key_prefix=f"alert-board-{key}",
        )
        return
    if target_type == "market_context":
        render_demo_market_context(get_demo_market_context(str(target.get("comuna")), demo_mode=True), expanded=True)
        return
    st.caption("Accion demo no disponible para esta alerta.")


def _badge(label: str, tone: str) -> str:
    return f'<span class="avm-badge {tone_class("avm-badge", tone)}">{html_escape(label)}</span>'


def _severity_tone(severity: str) -> str:
    if severity == "critical":
        return "negative"
    if severity == "warning":
        return "warning"
    if severity == "positive":
        return "positive"
    return "neutral"
