"""Standalone Product Lab report pages."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient
from ui.components.autofact import render_demo_autofact_report
from ui.components.checklist import render_demo_due_diligence_checklist
from ui.components.layout import section_header
from ui.components.offer_simulator import render_demo_offer_simulator
from ui.components.risk_report import render_demo_risk_report
from ui.demo_data import get_demo_listings
from ui.demo_providers import get_demo_autofact_report, get_demo_risk_report
from ui.lab import LAB_DISCLAIMER
from ui.state import is_demo_mode


def render_risk_report(client: ApiClient) -> None:
    _ = client
    if not _guard_lab():
        return
    section_header(
        "Risk Report",
        "Reporte demo para revisar mercado, liquidez, señales, comparables y riesgos simulados.",
    )
    st.info(LAB_DISCLAIMER)
    selected = _property_selector("risk-report-demo-selector")
    property_id = _listing_id(selected)
    report = get_demo_risk_report(property_id, demo_mode=True)
    autofact = get_demo_autofact_report(property_id, demo_mode=True)
    render_demo_offer_simulator(
        selected,
        buyer_profile="primer_comprador",
        strategy=report.get("negotiation_signals", {}).get("strategy", "moderada"),
        risk_report=report,
        expanded=True,
        key_prefix=f"risk-offer-{selected['listing_id']}",
    )
    render_demo_due_diligence_checklist(
        selected,
        risk_report=report,
        autofact_report=autofact,
        expanded=True,
        key_prefix=f"risk-checklist-{property_id}",
    )
    render_demo_risk_report(report, expanded=True, key_suffix=f"lab-report-{property_id}")


def render_autofact(client: ApiClient) -> None:
    _ = client
    if not _guard_lab():
        return
    section_header(
        "Autofact Demo",
        "Revisión inmobiliaria simulada para explorar una futura capa premium legal y municipal.",
    )
    st.info(LAB_DISCLAIMER)
    st.warning("Datos simulados. No reemplaza estudio de títulos, CBR real ni revisión legal.")
    selected = _property_selector("autofact-demo-selector")
    property_id = _listing_id(selected)
    autofact = get_demo_autofact_report(property_id, demo_mode=True)
    render_demo_due_diligence_checklist(
        selected,
        risk_report=get_demo_risk_report(property_id, demo_mode=True),
        autofact_report=autofact,
        expanded=True,
        key_prefix=f"autofact-checklist-{property_id}",
    )
    render_demo_autofact_report(autofact, expanded=True)


def _guard_lab() -> bool:
    if is_demo_mode():
        return True
    st.info("Activa Product Lab para abrir reportes demo. En modo real esta experiencia sigue oculta.")
    return False


def _property_selector(key: str) -> dict[str, Any]:
    listings = get_demo_listings()
    labels = {
        f"{item['title']} | {item['comuna']} | UF {item['price_uf']:,.0f}".replace(",", "."): item
        for item in listings
    }
    selected = st.selectbox("Propiedad demo", list(labels), key=key)
    return labels[selected]


def _listing_id(listing: dict[str, Any]) -> int:
    return int(listing["listing_id"])
