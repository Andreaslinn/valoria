"""Demo market context UI components."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.components.evidence import evidence_chip, insight_row, metadata_row, stat_cluster
from ui.components.theme import html_escape, inject_theme
from ui.formatting import format_uf


def render_demo_market_context(context: dict[str, Any], *, expanded: bool = False, use_expander: bool = True) -> None:
    if not context or context.get("is_demo") is not True:
        return
    inject_theme()
    title = f"Contexto de comuna / {context['label']}"
    if use_expander:
        with st.expander(title, expanded=expanded):
            _render_market_context_content(context)
        return
    st.markdown(f"#### {html_escape(title)}")
    with st.container(border=True):
        _render_market_context_content(context)


def _render_market_context_content(context: dict[str, Any]) -> None:
    st.caption(context["disclaimer"])
    insight_row(
        "Resumen de mercado",
        context["short_market_summary"],
        value=context["market_temperature"].title(),
        tone="premium",
        priority="high",
    )
    st.markdown(
        '<div class="avm-evidence-chip-row">'
        + "".join(evidence_chip(label, _badge_tone(label)) for label in context["badges"])
        + "</div>",
        unsafe_allow_html=True,
    )
    stat_cluster(
        [
            ("Inventario", context["inventory_level"].title(), "neutral"),
            ("Comparables", context["active_comparables"], "premium"),
            ("Precio mediano", format_uf(context["median_price_uf"]), "premium"),
            ("Liquidez", f"{context['liquidity_score']}/100", _liquidity_tone(context["liquidity_score"])),
            ("Dias mercado", context["average_days_on_market"], "neutral"),
            ("UF/m2", context["median_price_per_m2_uf"], "neutral"),
            ("Tendencia", context["recent_price_trend"], "warning"),
            ("Presion", context["negotiation_pressure"].title(), "warning"),
        ]
    )
    insight_row("Para comprador", context["buyer_meaning"], value=context["demand_level"].title(), tone="positive")
    metadata_row([("Propietario", context["owner_meaning"])])


def _badge_tone(label: str) -> str:
    if label in {"Mercado caliente", "Liquidez alta"}:
        return "positive"
    if label in {"Inventario alto", "Buen momento para negociar", "Alta competencia"}:
        return "warning"
    if label == "Liquidez baja":
        return "negative"
    return "neutral"


def _liquidity_tone(score: int) -> str:
    if score >= 78:
        return "positive"
    if score <= 55:
        return "negative"
    return "warning"
