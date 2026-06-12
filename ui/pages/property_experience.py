"""Product Lab unified property experience page."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient
from ui.components.layout import render_focus_property_bar, section_header
from ui.components.property_experience import render_property_experience
from ui.demo_data import get_demo_listings
from ui.lab import LAB_DISCLAIMER
from ui.lab_focus import get_focused_demo_listing, set_focus_property
from ui.state import is_demo_mode

SELECTED_PROPERTY_KEY = "property_experience_selected_id"


def render(client: ApiClient) -> None:
    _ = client
    if not is_demo_mode():
        st.info("Activa Product Lab para abrir Property Experience. En modo real esta vista sigue oculta.")
        return

    listings = get_demo_listings()
    selected = _select_property(listings)
    section_header(
        "Property Experience",
        "Pagina demo para analizar una propiedad como activo vivo: precio, riesgo, actividad y accion.",
    )
    st.info(LAB_DISCLAIMER)
    set_focus_property(int(selected["listing_id"]), source="Property Experience")
    render_focus_property_bar(get_focused_demo_listing())
    render_property_experience(selected)


def _select_property(listings: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {int(item["listing_id"]): item for item in listings}
    default_id = int(st.session_state.get(SELECTED_PROPERTY_KEY) or listings[0]["listing_id"])
    if default_id not in by_id:
        default_id = int(listings[0]["listing_id"])
    labels = {
        f"{item['title']} / {str(item['comuna']).title()} / UF {item['price_uf']:,.0f}".replace(",", "."): int(item["listing_id"])
        for item in listings
    }
    default_label = next(label for label, property_id in labels.items() if property_id == default_id)
    st.markdown(
        '<div class="avm-lab-control-shell"><div class="avm-lab-control-shell__title">Activo en foco</div>',
        unsafe_allow_html=True,
    )
    selected_label = st.selectbox(
        "Propiedad demo",
        list(labels),
        index=list(labels).index(default_label),
        key="property-experience-selector",
        label_visibility="collapsed",
    )
    st.markdown("</div>", unsafe_allow_html=True)
    selected_id = labels[selected_label]
    st.session_state[SELECTED_PROPERTY_KEY] = selected_id
    set_focus_property(selected_id, source="Property Experience")
    return by_id[selected_id]
