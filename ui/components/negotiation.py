"""Demo negotiation signal UI."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.components.evidence import insight_row, signal_row, stat_cluster
from ui.components.theme import inject_theme
from ui.formatting import format_uf


def render_demo_negotiation_signals(report: dict[str, Any], *, expanded: bool = False, use_expander: bool = True) -> None:
    if not report or report.get("is_demo") is not True:
        return
    inject_theme()
    if use_expander:
        with st.expander("Senales de negociacion demo", expanded=expanded):
            _render_negotiation_content(report)
        return
    st.markdown("#### Senales de negociacion demo")
    with st.container(border=True):
        _render_negotiation_content(report)


def _render_negotiation_content(report: dict[str, Any]) -> None:
    st.caption(report["disclaimer"])
    stat_cluster(
        [
            ("Score", f"{report['negotiation_score']}/100", _score_tone(report["negotiation_score"])),
            ("Estrategia", report["strategy"].title(), "premium"),
            ("Riesgo", report["suggested_strategy"]["risk_of_losing_opportunity"], "warning"),
        ]
    )
    _render_strategy(report["suggested_strategy"])
    for signal in report["signals"][:5]:
        signal_row(signal)


def _render_strategy(strategy: dict[str, Any]) -> None:
    st.subheader("Estrategia sugerida demo")
    low, high = strategy["estimated_range_uf"]
    stat_cluster(
        [
            ("Conservadora", _uf(strategy["conservative_offer_uf"]), "neutral"),
            ("Moderada", _uf(strategy["moderate_offer_uf"]), "positive"),
            ("Agresiva", _uf(strategy["aggressive_offer_uf"]), "warning"),
            ("Rango", f"{_uf(low)} - {_uf(high)}", "premium"),
        ]
    )
    insight_row("Racional de oferta", strategy["explanation"], value="demo", tone="premium", priority="supporting")


def _score_tone(score: int) -> str:
    if score >= 75:
        return "positive"
    if score >= 50:
        return "warning"
    return "neutral"


def _uf(value: Any) -> str:
    return format_uf(value)
