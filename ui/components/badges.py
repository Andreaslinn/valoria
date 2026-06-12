"""Badge components for compact status signals."""
from __future__ import annotations

import streamlit as st

from ui.components.theme import html_escape, inject_theme, tone_class


def status_badge(label: str, tone: str = "neutral") -> None:
    inject_theme()
    st.markdown(
        f"""
        <span class="avm-badge {tone_class("avm-badge", tone)}">
            {html_escape(label)}
        </span>
        """,
        unsafe_allow_html=True,
    )
