"""Demo due diligence checklist UI."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.components.feedback import record_lab_event, render_lab_feedback_widget
from ui.components.layout import metric_card
from ui.components.theme import html_escape, inject_theme, tone_class
from ui.demo_checklist import (
    DEMO_CHECKLIST_CATEGORIES,
    build_demo_due_diligence_checklist,
    ensure_demo_checklist_state,
    hydrate_demo_checklist,
    set_demo_checklist_item_note,
    set_demo_checklist_item_status,
)


def render_demo_due_diligence_checklist(
    listing: dict[str, Any],
    *,
    risk_report: dict[str, Any] | None = None,
    autofact_report: dict[str, Any] | None = None,
    expanded: bool = True,
    key_prefix: str = "checklist",
    use_expander: bool = True,
) -> dict[str, Any]:
    checklist = build_demo_due_diligence_checklist(
        listing,
        risk_report=risk_report,
        autofact_report=autofact_report,
        demo_mode=True,
    )
    state = ensure_demo_checklist_state(st.session_state, checklist)
    hydrated = hydrate_demo_checklist(checklist, state)
    inject_theme()
    property_id = int(hydrated["property_id"])
    record_lab_event("used_checklist_demo", module="checklist", property_id=property_id)
    if use_expander:
        with st.expander("Checklist Lab", expanded=expanded):
            _render_checklist_content(hydrated, state, key_prefix, property_id)
    else:
        st.markdown("#### Checklist Lab")
        with st.container(border=True):
            _render_checklist_content(hydrated, state, key_prefix, property_id)
    return hydrate_demo_checklist(checklist, state)


def _render_checklist_content(
    hydrated: dict[str, Any],
    state: dict[str, Any],
    key_prefix: str,
    property_id: int,
) -> None:
    st.caption(hydrated["disclaimer"])
    _render_progress(hydrated["progress"])
    category = st.selectbox(
        "Categoria",
        ["Todas", *DEMO_CHECKLIST_CATEGORIES],
        key=f"{key_prefix}-category",
    )
    items = hydrated["items"] if category == "Todas" else [item for item in hydrated["items"] if item["category"] == category]
    for item in items:
        _render_item(item, hydrated["property_id"], state, key_prefix)
    render_lab_feedback_widget("checklist", property_id=property_id, key_prefix=f"{key_prefix}-feedback")


def _render_progress(progress: dict[str, Any]) -> None:
    cols = st.columns(4, gap="small")
    with cols[0]:
        metric_card("Completado", f"{progress['completion_pct']}%", caption="Checklist demo", tone="positive" if progress["completion_pct"] >= 70 else "warning")
    with cols[1]:
        metric_card("Items", f"{progress['completed_items']}/{progress['total_items']}", caption="Revisados o no aplica", tone="neutral")
    with cols[2]:
        metric_card("Riesgos pendientes", progress["risks_pending"], caption="Marcados como riesgo", tone="negative" if progress["risks_pending"] else "positive")
    with cols[3]:
        metric_card("Criticos pendientes", progress["critical_pending"], caption="Prioridad critica", tone="negative" if progress["critical_pending"] else "positive")


def _render_item(item: dict[str, Any], property_id: int, state: dict[str, Any], key_prefix: str) -> None:
    status_tone = _status_tone(item["status"])
    st.markdown(
        f"""
        <div class="avm-card">
            <div style="display:flex; justify-content:space-between; gap:0.75rem; align-items:flex-start;">
                <div>
                    <div style="font-weight:800; color:var(--avm-text);">{html_escape(item["title"])}</div>
                    <div style="color:var(--avm-muted); margin-top:0.3rem;">{html_escape(item["description"])}</div>
                    <div style="color:var(--avm-text); font-weight:650; margin-top:0.45rem;">{html_escape(item["action_hint"])}</div>
                </div>
                <div style="display:flex; gap:0.35rem; flex-wrap:wrap; justify-content:flex-end;">
                    {_badge(item["category"], "neutral")}
                    {_badge(item["priority"], _priority_tone(item["priority"]))}
                    {_badge(item["status"], status_tone)}
                </div>
            </div>
            <div style="color:var(--avm-muted); font-size:0.85rem; margin-top:0.45rem;">
                Senal relacionada: {html_escape(item["related_signal"])}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns([0.9, 1.6, 0.8], gap="small")
    status_options = ["pendiente", "revisado", "riesgo", "no aplica"]
    selected = cols[0].selectbox(
        "Status",
        status_options,
        index=status_options.index(item["status"]) if item["status"] in status_options else 0,
        key=f"{key_prefix}-status-{property_id}-{item['id']}",
    )
    if selected != item["status"]:
        set_demo_checklist_item_status(state, property_id, item["id"], selected)
        st.rerun()
    note = cols[1].text_input(
        "Nota demo",
        value=str(item.get("note") or ""),
        key=f"{key_prefix}-note-{property_id}-{item['id']}",
    )
    if cols[2].button("Guardar nota", key=f"{key_prefix}-note-save-{property_id}-{item['id']}"):
        set_demo_checklist_item_note(state, property_id, item["id"], note)
        st.success("Nota demo guardada.")
        st.rerun()


def _badge(label: str, tone: str) -> str:
    return f'<span class="avm-badge {tone_class("avm-badge", tone)}">{html_escape(label)}</span>'


def _status_tone(status: str) -> str:
    if status == "revisado":
        return "positive"
    if status == "riesgo":
        return "negative"
    if status == "no aplica":
        return "neutral"
    return "warning"


def _priority_tone(priority: str) -> str:
    if priority == "critica":
        return "negative"
    if priority == "alta":
        return "warning"
    if priority == "media":
        return "premium"
    return "neutral"
