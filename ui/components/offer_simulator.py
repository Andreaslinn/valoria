"""Demo offer simulator UI."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.components.feedback import record_lab_event, render_lab_feedback_widget
from ui.components.layout import metric_card
from ui.components.theme import html_escape, inject_theme, tone_class
from ui.demo_offer import build_demo_offer_simulation
from ui.formatting import format_uf


def render_demo_offer_simulator(
    listing: dict[str, Any],
    *,
    buyer_profile: str,
    strategy: str,
    risk_report: dict[str, Any] | None = None,
    expanded: bool = True,
    key_prefix: str = "offer-simulator",
    use_expander: bool = True,
) -> dict[str, Any]:
    inject_theme()
    property_id = int(listing["listing_id"])
    initial = build_demo_offer_simulation(
        listing,
        buyer_profile=buyer_profile,
        strategy=strategy,
        risk_report=risk_report,
    )
    manual_offer: int | None = None
    if use_expander:
        with st.expander("Simulador de oferta Lab", expanded=expanded):
            manual_offer = _render_offer_inputs(initial, strategy=strategy, key_prefix=key_prefix)
            simulation = _render_offer_result(listing, buyer_profile, strategy, manual_offer, risk_report, property_id, key_prefix)
        return simulation
    st.markdown("#### Simulador de oferta Lab")
    with st.container(border=True):
        manual_offer = _render_offer_inputs(initial, strategy=strategy, key_prefix=key_prefix)
        return _render_offer_result(listing, buyer_profile, strategy, manual_offer, risk_report, property_id, key_prefix)


def _render_offer_inputs(initial: dict[str, Any], *, strategy: str, key_prefix: str) -> int | None:
    st.caption(initial["disclaimer"])
    cols = st.columns([1, 1, 1], gap="small")
    with cols[0]:
        metric_card("Precio publicado", _uf(initial["published_price_uf"]), caption="UF demo", tone="neutral")
    with cols[1]:
        metric_card("Valor estimado", _uf(initial["estimated_value_uf"]), caption="Referencia demo", tone="premium")
    with cols[2]:
        metric_card("Oferta sugerida", _uf(initial["suggested_offer_uf"]), caption=strategy.title(), tone="positive")

    mode = st.segmented_control(
        "Modo de oferta",
        ["Sugerida", "Manual"],
        default="Sugerida",
        key=f"{key_prefix}-manual-mode",
        label_visibility="collapsed",
    )
    if mode != "Manual":
        return None
    return int(
        st.number_input(
            "Oferta manual UF",
            min_value=1,
            max_value=max(int(initial["published_price_uf"] * 1.15), 1),
            value=int(initial["suggested_offer_uf"]),
            step=50,
            key=f"{key_prefix}-manual-offer",
        )
    )


def _render_offer_result(
    listing: dict[str, Any],
    buyer_profile: str,
    strategy: str,
    manual_offer: int | None,
    risk_report: dict[str, Any] | None,
    property_id: int,
    key_prefix: str,
) -> dict[str, Any]:
    simulation = build_demo_offer_simulation(
        listing,
        buyer_profile=buyer_profile,
        strategy=strategy,
        manual_offer_uf=manual_offer,
        risk_report=risk_report,
    )
    _render_outputs(simulation)
    record_lab_event(
        "generated_offer_demo",
        module="offer_simulator",
        property_id=property_id,
        metadata={"strategy": strategy, "manual": manual_offer is not None},
    )
    render_lab_feedback_widget("offer_simulator", property_id=property_id, key_prefix=f"{key_prefix}-feedback")
    return simulation


def _render_outputs(simulation: dict[str, Any]) -> None:
    cols = st.columns(4, gap="small")
    with cols[0]:
        metric_card("Oferta a evaluar", _uf(simulation["selected_offer_uf"]), caption="Editable demo", tone="premium")
    with cols[1]:
        metric_card(
            "Descuento publicado",
            f"{simulation['discount_vs_price_pct']}%",
            caption="Vs precio actual",
            tone="positive" if simulation["discount_vs_price_pct"] > 0 else "warning",
        )
    with cols[2]:
        metric_card(
            "Brecha estimada",
            f"{simulation['difference_vs_estimate_pct']}%",
            caption="Vs valor demo",
            tone="positive" if simulation["difference_vs_estimate_pct"] > 0 else "negative",
        )
    with cols[3]:
        metric_card(
            "Aceptacion demo",
            f"{simulation['acceptance_probability']}%",
            caption=f"Riesgo {simulation['risk_of_losing_opportunity']}",
            tone=simulation["risk_tone"],
        )

    risk = simulation["risk_report_read"]
    st.markdown(
        f"""
        <div class="avm-card">
            <div style="display:flex; justify-content:space-between; gap:0.75rem; align-items:flex-start;">
                <div>
                    <div style="font-weight:800; color:var(--avm-text);">Lectura de negociacion</div>
                    <div style="color:var(--avm-muted); margin-top:0.35rem;">{html_escape(simulation["feedback"])}</div>
                    <div style="color:var(--avm-text); margin-top:0.55rem;">{html_escape(simulation["negotiation_argument"])}</div>
                </div>
                <span class="avm-badge {tone_class("avm-badge", risk["tone"])}">{html_escape(risk["label"])}</span>
            </div>
            <div style="color:var(--avm-muted); margin-top:0.55rem;">{html_escape(risk["message"])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Evidencia demo: " + " | ".join(simulation["evidence"]))
    st.caption("Proximos pasos: " + " | ".join(simulation["next_steps"]))


def _uf(value: Any) -> str:
    return format_uf(value)
