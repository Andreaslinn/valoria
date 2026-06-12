"""Small Product Lab feedback widgets."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.demo_feedback import (
    DEMO_FEEDBACK_MODULES,
    DEMO_FEEDBACK_OPTIONS,
    ensure_demo_feedback_state,
    record_demo_event,
    record_demo_feedback,
)


def render_lab_feedback_widget(
    module: str,
    *,
    property_id: int | None = None,
    key_prefix: str = "lab-feedback",
) -> None:
    if module not in DEMO_FEEDBACK_MODULES:
        return
    state = ensure_demo_feedback_state(st.session_state)
    st.caption(f"Feedback Lab · {DEMO_FEEDBACK_MODULES[module]}")
    cols = st.columns(len(DEMO_FEEDBACK_OPTIONS), gap="small")
    for col, (value, config) in zip(cols, DEMO_FEEDBACK_OPTIONS.items(), strict=False):
        if col.button(config["label"], key=f"{key_prefix}-{module}-{property_id}-{value}"):
            record_demo_feedback(state, module, value, property_id=property_id, demo_mode=True)
            st.success("Feedback Lab registrado para esta sesion.")


def record_lab_event(
    event_name: str,
    *,
    module: str | None = None,
    property_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    state = ensure_demo_feedback_state(st.session_state)
    record_demo_event(
        state,
        event_name,
        module=module,
        property_id=property_id,
        metadata=metadata,
        demo_mode=True,
    )
