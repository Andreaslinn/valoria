"""Shared UI for demo property activity timelines."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.components.evidence import timeline_item
from ui.components.theme import inject_theme
from ui.demo_providers import get_demo_activity_disclaimer


def render_demo_property_activity(events: list[dict[str, Any]], *, key: str, use_expander: bool = True) -> None:
    if not events:
        return
    inject_theme()
    if use_expander:
        with st.expander("Actividad de la propiedad", expanded=False):
            _render_activity_content(events)
    else:
        st.markdown("#### Actividad de la propiedad")
        with st.container(border=True):
            _render_activity_content(events)
    st.caption(f"Timeline demo: {len(events)} eventos simulados.")
    _ = key


def _render_activity_content(events: list[dict[str, Any]]) -> None:
    st.caption(get_demo_activity_disclaimer())
    for event in events:
        timeline_item(
            event.get("date") or "",
            event.get("title") or event.get("event_type") or "Evento demo",
            event.get("description") or "",
            tone=str(event.get("tone") or "neutral"),
            meta=event.get("event_type") or event.get("source"),
        )
