"""Shared focused-property state for Product Lab."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import streamlit as st

from ui.demo_data import get_demo_listings

GLOBAL_FOCUS_PROPERTY_ID_KEY = "avm_global_focus_property_id"
GLOBAL_FOCUS_SOURCE_KEY = "avm_global_focus_source"
LAB_ACTIVE_PAGE_KEY = "avm_lab_active_page"


def truncate_title(title: Any, max_len: int = 45) -> str:
    text = str(title or "Propiedad demo").strip() or "Propiedad demo"
    if max_len <= 1 or len(text) <= max_len:
        return text
    return f"{text[: max_len - 1].rstrip()}…"


def set_focus_property(property_id: Any, source: str | None = None, state: MutableMapping[str, Any] | None = None) -> None:
    target_state = state if state is not None else st.session_state
    try:
        target_state[GLOBAL_FOCUS_PROPERTY_ID_KEY] = int(property_id)
    except (TypeError, ValueError):
        return
    if source:
        target_state[GLOBAL_FOCUS_SOURCE_KEY] = source
    target_state[LAB_ACTIVE_PAGE_KEY] = source or target_state.get(LAB_ACTIVE_PAGE_KEY, "")


def clear_focus_property(state: MutableMapping[str, Any] | None = None) -> None:
    target_state = state if state is not None else st.session_state
    target_state.pop(GLOBAL_FOCUS_PROPERTY_ID_KEY, None)
    target_state.pop(GLOBAL_FOCUS_SOURCE_KEY, None)


def get_focused_demo_listing(state: MutableMapping[str, Any] | None = None) -> dict[str, Any] | None:
    target_state = state if state is not None else st.session_state
    focus_id = target_state.get(GLOBAL_FOCUS_PROPERTY_ID_KEY)
    try:
        property_id = int(focus_id)
    except (TypeError, ValueError):
        clear_focus_property(target_state)
        return None
    for listing in get_demo_listings():
        if int(listing.get("listing_id", 0)) == property_id:
            return listing
    clear_focus_property(target_state)
    return None


def navigate_to_decision_board(state: MutableMapping[str, Any] | None = None) -> None:
    target_state = state if state is not None else st.session_state
    focus_id = target_state.get(GLOBAL_FOCUS_PROPERTY_ID_KEY)
    if focus_id is not None:
        target_state["decision_board_focus_property_id"] = focus_id
    target_state["decision_board_context_panel"] = "Resumen"
    target_state["avm_lab_previous_page"] = target_state.get("avm_lab_nav_page")
    target_state["avm_lab_nav_page"] = "Decision Board Lab"
    target_state["avm_lab_nav_group"] = "portfolio"
    target_state[LAB_ACTIVE_PAGE_KEY] = "Decision Board Lab"
