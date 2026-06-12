"""Table components for the Streamlit UI."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.components.layout import empty_state
from ui.formatting import format_clp, format_m2, format_pct, format_uf


def listings_table(listings: list[dict[str, Any]]) -> None:
    if not listings:
        empty_state(
            "Sin publicaciones disponibles",
            "Aún no hay publicaciones para mostrar con los filtros actuales.",
        )
        return
    rows = [
        {
            "ID": item.get("id"),
            "Título": item.get("title"),
            "Comuna": item.get("comuna"),
            "Precio UF": format_uf(item.get("price_uf")),
            "Precio CLP": format_clp(item.get("price_clp")),
            "m²": format_m2(item.get("m2")),
            "Dorm.": item.get("dormitorios"),
            "Baños": item.get("banos"),
            "Est.": item.get("estacionamientos"),
            "Fuente": item.get("source"),
            "Estado": item.get("status"),
            "URL": item.get("url"),
        }
        for item in listings
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def comparables_table(comparables: list[dict[str, Any]]) -> None:
    if not comparables:
        empty_state(
            "Sin comparables",
            "No hay comparables suficientes para mostrar en esta tasación.",
        )
        return
    rows = [
        {
            "ID": item.get("listing_id"),
            "Título": item.get("title"),
            "Comuna": item.get("comuna"),
            "Precio UF": format_uf(item.get("price_uf")),
            "Precio CLP": format_clp(item.get("price_clp")),
            "m²": format_m2(item.get("m2")),
            "Similitud": item.get("similarity"),
            "URL": item.get("url"),
        }
        for item in comparables
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def opportunities_table(opportunities: list[dict[str, Any]]) -> None:
    if not opportunities:
        empty_state(
            "Sin oportunidades disponibles",
            "Aún no hay oportunidades detectadas para mostrar.",
        )
        return
    rows = [
        {
            "ID": item.get("listing_id"),
            "Título": item.get("title"),
            "Comuna": item.get("comuna"),
            "Publicado": format_uf(item.get("price_uf")),
            "Estimado": format_uf(item.get("estimated_price_uf")),
            "Descuento": format_pct(item.get("discount_pct")),
            "Score": item.get("score"),
            "Confianza": item.get("confidence_label") or item.get("confidence"),
            "Confidence score": item.get("confidence_score"),
            "URL": item.get("url"),
        }
        for item in opportunities
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
