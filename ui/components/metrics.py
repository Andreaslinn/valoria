"""KPI components for the Streamlit UI."""
from __future__ import annotations

import streamlit as st

from ui.formatting import format_clp, format_confidence, format_pct, format_uf, none_dash


def valuation_metrics(result: dict) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Estimado UF", format_uf(result.get("estimated_price_uf")))
    c2.metric("Estimado CLP", format_clp(result.get("estimated_price_clp")))
    c3.metric("Confianza", format_confidence(result.get("confidence")))
    c4.metric("Comparables", none_dash(result.get("comparable_count")))
    c5, c6 = st.columns(2)
    c5.metric("Precio/m2 UF", format_uf(result.get("price_m2_uf")))
    c6.metric("Estado", format_confidence(result.get("status")))


def opportunity_metrics(item: dict) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Publicado", format_uf(item.get("price_uf")))
    c2.metric("Estimado", format_uf(item.get("estimated_price_uf")))
    c3.metric("Descuento", format_pct(item.get("discount_pct")))
    c4.metric("Score", none_dash(item.get("score")))
    c5.metric("Confianza", format_confidence(item.get("confidence")))


def health_metrics(health: dict | None, base_url: str, error: str | None = None) -> None:
    c1, c2 = st.columns(2)
    c1.metric("API", "Disponible" if health and not error else "No disponible")
    c2.metric("Base URL", base_url)
    if error:
        st.error(error)
    elif health:
        st.success(f"Health: {health.get('status', 'ok')}")


def listing_summary_metrics(listings: list[dict]) -> None:
    active = [item for item in listings if item.get("status") == "active"]
    prices = [item.get("price_clp") for item in active if isinstance(item.get("price_clp"), int | float)]
    c1, c2, c3 = st.columns(3)
    c1.metric("Listings", len(listings))
    c2.metric("Activos", len(active))
    c3.metric("Precio promedio", format_clp(sum(prices) / len(prices) if prices else None))
