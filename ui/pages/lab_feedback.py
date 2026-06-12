"""Internal Product Lab feedback panel."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient
from ui.components.layout import metric_card, section_header
from ui.demo_feedback import ensure_demo_feedback_state, summarize_demo_feedback
from ui.lab import LAB_DISCLAIMER
from ui.state import is_demo_mode


def render(client: ApiClient) -> None:
    _ = client
    if not is_demo_mode():
        st.info("Activa Product Lab para ver Lab Feedback. En modo real no se muestran metricas demo.")
        return
    state = ensure_demo_feedback_state(st.session_state)
    summary = summarize_demo_feedback(state)
    section_header("Lab Feedback", "Panel interno para decidir que ideas demo merecen convertirse en producto real.")
    st.info(LAB_DISCLAIMER)
    _render_topline(summary)
    _render_rankings(summary)
    _render_raw(summary, state)


def _render_topline(summary: dict[str, Any]) -> None:
    cols = st.columns(4, gap="small")
    with cols[0]:
        metric_card("Feedback", summary["total_feedback"], caption="Clicks registrados", tone="premium")
    with cols[1]:
        metric_card("Eventos", summary["total_events"], caption="Uso Lab", tone="neutral")
    with cols[2]:
        metric_card("Premium", _top_label(summary["features_premium"]), caption="Lo pagaria", tone="positive")
    with cols[3]:
        metric_card("Confuso", _top_label(summary["modules_confusing"]), caption="A revisar", tone="warning")


def _render_rankings(summary: dict[str, Any]) -> None:
    cols = st.columns(2, gap="large")
    with cols[0]:
        _rank_card("Modulos mas usados", summary["modules_most_used"])
        _rank_card("Feedback positivo", summary["modules_positive"])
        _rank_card("Features premium", summary["features_premium"])
    with cols[1]:
        _rank_card("Modulos confusos", summary["modules_confusing"])
        _rank_card("Candidatas a eliminar", summary["features_to_remove"])
        st.subheader("Eventos")
        st.dataframe(
            [{"evento": name, "cantidad": count} for name, count in summary["event_counts"].items()],
            use_container_width=True,
            hide_index=True,
        )


def _render_raw(summary: dict[str, Any], state: dict[str, Any]) -> None:
    with st.expander("Detalle de sesion", expanded=False):
        st.caption("Datos locales de session_state, solo para Product Lab.")
        st.dataframe(state.get("feedback", []), use_container_width=True, hide_index=True)
        st.dataframe(state.get("events", []), use_container_width=True, hide_index=True)
        st.json(summary)


def _rank_card(title: str, rows: list[dict[str, Any]]) -> None:
    st.subheader(title)
    if not rows:
        st.caption("Sin datos todavia.")
        return
    st.dataframe(
        [{"modulo": row["module_label"], "cantidad": row["count"]} for row in rows],
        use_container_width=True,
        hide_index=True,
    )


def _top_label(rows: list[dict[str, Any]]) -> str:
    return rows[0]["module_label"] if rows else "Sin datos"
