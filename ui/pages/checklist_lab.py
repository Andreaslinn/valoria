"""Standalone Checklist Lab page."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient
from ui.components.checklist import render_demo_due_diligence_checklist
from ui.components.decision_board import render_demo_decision_property_control
from ui.components.layout import section_header
from ui.demo_data import get_demo_listings, get_demo_portfolio
from ui.demo_decision_board import ensure_demo_decision_board_state
from ui.demo_portfolio import ensure_demo_portfolio_state
from ui.demo_providers import get_demo_autofact_report, get_demo_risk_report
from ui.lab import LAB_DISCLAIMER
from ui.state import is_demo_mode


def render(client: ApiClient) -> None:
    _ = client
    if not is_demo_mode():
        st.info("Activa Product Lab para abrir Checklist Lab. En modo real esta experiencia sigue oculta.")
        return
    section_header("Checklist Lab", "Convierte los riesgos demo en tareas concretas de revision.")
    st.info(LAB_DISCLAIMER)
    selected = _property_selector()
    property_id = int(selected["listing_id"])
    portfolio_state = ensure_demo_portfolio_state(st.session_state, get_demo_portfolio())
    board_state = ensure_demo_decision_board_state(st.session_state, get_demo_listings(), portfolio_state)
    with st.expander("Etapa en Decision Board Lab", expanded=False):
        render_demo_decision_property_control(
            selected,
            board_state,
            portfolio_state=portfolio_state,
            key_prefix=f"checklist-board-{property_id}",
        )
    render_demo_due_diligence_checklist(
        selected,
        risk_report=get_demo_risk_report(property_id, demo_mode=True),
        autofact_report=get_demo_autofact_report(property_id, demo_mode=True),
        expanded=True,
        key_prefix=f"page-checklist-{property_id}",
    )


def _property_selector() -> dict[str, Any]:
    listings = get_demo_listings()
    labels = {
        f"{item['title']} | {item['comuna']} | UF {item['price_uf']:,.0f}".replace(",", "."): item
        for item in listings
    }
    selected = st.selectbox("Propiedad demo", list(labels), key="checklist-demo-selector")
    return labels[selected]
