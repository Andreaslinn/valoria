"""Alert Center Demo page."""
from __future__ import annotations

import streamlit as st

from ui.api_client import ApiClient
from ui.components.alerts import render_demo_alert_list, render_demo_alert_summary
from ui.components.layout import section_header
from ui.demo_alerts import (
    DEMO_ALERT_CATEGORIES,
    DEMO_ALERT_DISCLAIMER,
    DEMO_ALERT_SEVERITIES,
    build_demo_alerts,
    ensure_demo_alert_state,
    filter_demo_alerts,
    with_demo_alert_read_state,
)
from ui.demo_data import get_demo_listings
from ui.lab import LAB_DISCLAIMER
from ui.state import is_demo_mode


def render(client: ApiClient) -> None:
    _ = client
    if not is_demo_mode():
        st.info("Activa Product Lab para ver Alertas Lab. En modo real no se muestran alertas demo.")
        return

    listings = get_demo_listings()
    alerts = build_demo_alerts(listings, demo_mode=True)
    state = ensure_demo_alert_state(st.session_state, alerts)
    hydrated = with_demo_alert_read_state(alerts, state)
    by_id = {int(item["listing_id"]): item for item in listings}

    section_header("Alertas Lab", "Centro demo para seguir movimientos, riesgos y oportunidades accionables.")
    st.info(LAB_DISCLAIMER)
    st.caption(DEMO_ALERT_DISCLAIMER)
    render_demo_alert_summary(hydrated)

    filters = _render_filters(hydrated)
    filtered = filter_demo_alerts(hydrated, **filters)
    render_demo_alert_list(filtered, state, by_id, key_prefix="alert-center")


def _render_filters(alerts: list[dict]) -> dict[str, object]:
    categories = ["Todas", *sorted(DEMO_ALERT_CATEGORIES)]
    severities = ["Todas", *sorted(DEMO_ALERT_SEVERITIES)]
    cols = st.columns([1, 1, 0.8], gap="small")
    category = cols[0].selectbox("Categoria", categories, key="alert-category-filter")
    severity = cols[1].selectbox("Severidad", severities, key="alert-severity-filter")
    unread_only = cols[2].checkbox("Solo no leidas", value=False, key="alert-unread-filter")
    st.caption(f"{len(alerts)} alertas demo generadas para esta sesion.")
    return {
        "category": None if category == "Todas" else category,
        "severity": None if severity == "Todas" else severity,
        "unread_only": unread_only,
    }
