"""Demo real-estate Autofact UI."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.components.feedback import record_lab_event, render_lab_feedback_widget
from ui.components.layout import metric_card
from ui.components.theme import html_escape, inject_theme, tone_class


def render_demo_autofact_report(
    report: dict[str, Any],
    *,
    expanded: bool = False,
    key_suffix: str = "",
    use_expander: bool = True,
) -> None:
    if not report or report.get("is_demo") is not True:
        return
    inject_theme()
    property_id = int(report["property_id"])
    record_lab_event("opened_autofact_demo", module="autofact", property_id=property_id)
    identity = report["property_identity"]
    title = f"Autofact inmobiliario demo · {identity['title']}"
    if use_expander:
        with st.expander(title, expanded=expanded):
            _render_autofact_content(report, property_id=property_id, key_suffix=key_suffix)
        return
    st.markdown(f"#### {html_escape(title)}")
    with st.container(border=True):
        _render_autofact_content(report, property_id=property_id, key_suffix=key_suffix)


def _render_autofact_content(report: dict[str, Any], *, property_id: int, key_suffix: str) -> None:
    st.error("Datos simulados · No reemplaza estudio de títulos · No usar para decisiones reales")
    _render_top_summary(report)
    _render_flags(report)
    _render_timeline(report["legal_timeline"])
    _render_recommendations(report["review_recommendations"])
    st.button(
        "Revisar con abogado / CBR real próximamente",
        disabled=True,
        key=f"autofact-demo-cta-{report['property_id']}-{key_suffix}",
    )
    render_lab_feedback_widget("autofact", property_id=property_id, key_prefix=f"autofact-feedback-{key_suffix}")


def _render_top_summary(report: dict[str, Any]) -> None:
    identity = report["property_identity"]
    st.markdown(
        f"""
        <div class="avm-card">
            <div style="display:flex; justify-content:space-between; gap:0.75rem; align-items:flex-start;">
                <div>
                    <div style="font-weight:800; color:var(--avm-text);">Resumen superior</div>
                    <div style="color:var(--avm-muted); margin-top:0.35rem;">
                        {html_escape(report["ownership_summary"])}
                    </div>
                    <div style="color:var(--avm-muted); margin-top:0.35rem;">
                        {html_escape(identity["address_label"])} · {html_escape(identity["property_type"])} · {html_escape(identity["comuna"])}
                    </div>
                </div>
                {_badge_html("DEMO", "premium")}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(4, gap="small")
    with cols[0]:
        metric_card("Score legal", f"{report['legal_score']}/100", caption="Simulado", tone=_risk_tone(report["risk_level"]))
    with cols[1]:
        metric_card("Riesgo", str(report["risk_level"]).title(), caption="Demo", tone=_risk_tone(report["risk_level"]))
    with cols[2]:
        metric_card("Confianza data", str(report["data_confidence"]).title(), caption="Dataset demo", tone="neutral")
    with cols[3]:
        metric_card("CBR", "Simulado", caption=report["simulated_cbr_status"], tone="warning")


def _render_flags(report: dict[str, Any]) -> None:
    st.subheader("Flags criticas")
    groups = [
        ("Gravamenes", report["liens_flags"]),
        ("Hipotecas", report["mortgage_flags"]),
        ("Prohibiciones", report["prohibition_flags"]),
        ("Contribuciones", report["tax_flags"]),
        ("Permisos", report["permits_flags"]),
        ("Municipal", report["municipal_flags"]),
    ]
    cols = st.columns(3, gap="medium")
    for index, (title, flags) in enumerate(groups):
        with cols[index % 3]:
            _flag_card(title, flags)
    regularization = report["building_regularization"]
    st.caption(
        f"Regularizacion: {regularization['status']} · {regularization['summary']} · severidad {regularization['severity']}"
    )


def _render_timeline(events: list[dict[str, str]]) -> None:
    st.subheader("Timeline legal simulado")
    for event in events:
        st.markdown(
            f"""
            <div style="display:grid; grid-template-columns:7rem 1fr; gap:0.85rem; margin:0.65rem 0;">
                <div style="color:var(--avm-muted); font-size:0.85rem;">{html_escape(event["date"])}</div>
                <div>
                    {_badge_html(event["event"], _severity_tone(event["severity"]))}
                    <div style="color:var(--avm-muted); margin-top:0.25rem;">{html_escape(event["description"])}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_recommendations(items: list[str]) -> None:
    body = "".join(f"<li>{html_escape(item)}</li>" for item in items)
    st.markdown(
        f"""
        <div class="avm-card">
            <div style="font-weight:800; color:var(--avm-text);">Recomendaciones de revision</div>
            <ul style="margin:0.55rem 0 0 1.1rem; color:var(--avm-muted);">{body}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _flag_card(title: str, flags: list[dict[str, str]]) -> None:
    body = "".join(
        f"<li>{html_escape(flag['label'])} {_badge_html(flag['severity'], _severity_tone(flag['severity']))}</li>"
        for flag in flags
    )
    st.markdown(
        f"""
        <div class="avm-card">
            <div style="font-weight:750; color:var(--avm-text);">{html_escape(title)}</div>
            <ul style="margin:0.55rem 0 0 1.1rem; color:var(--avm-muted);">{body}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _badge_html(label: str, tone: str) -> str:
    return f'<span class="avm-badge {tone_class("avm-badge", tone)}">{html_escape(label)}</span>'


def _risk_tone(risk_level: str) -> str:
    if risk_level == "high":
        return "negative"
    if risk_level == "medium":
        return "warning"
    return "positive"


def _severity_tone(severity: str) -> str:
    if severity == "high":
        return "negative"
    if severity == "medium":
        return "warning"
    if severity == "low":
        return "positive"
    return "neutral"
