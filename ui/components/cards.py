"""Small reusable card-like Streamlit components."""
from __future__ import annotations

import streamlit as st

from ui.formatting import format_clp, format_confidence, format_m2, format_pct, format_uf, none_dash


def status_badge(label: str | None) -> None:
    st.caption(f"Estado: {format_confidence(label)}")


def warning_box(warnings: list[str] | None) -> None:
    if not warnings:
        return
    st.warning(" | ".join(str(w) for w in warnings))


def listing_card(listing: dict) -> None:
    with st.container(border=True):
        st.subheader(none_dash(listing.get("title")))
        c1, c2, c3 = st.columns(3)
        c1.metric("Precio", format_uf(listing.get("price_uf")))
        c2.metric("CLP", format_clp(listing.get("price_clp")))
        c3.metric("Superficie", format_m2(listing.get("m2")))
        st.caption(
            f"{none_dash(listing.get('comuna'))} | "
            f"{none_dash(listing.get('source'))} | {none_dash(listing.get('status'))}"
        )
        if listing.get("url"):
            st.link_button("Abrir publicación", listing["url"])


def opportunity_card(opportunity: dict) -> None:
    with st.container(border=True):
        st.subheader(none_dash(opportunity.get("title")))
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Publicado", format_uf(opportunity.get("price_uf")))
        c2.metric("Estimado", format_uf(opportunity.get("estimated_price_uf")))
        c3.metric("Descuento", format_pct(opportunity.get("discount_pct")))
        c4.metric("Score", none_dash(opportunity.get("score")))
        st.caption(
            f"{none_dash(opportunity.get('comuna'))} | "
            f"{format_m2(opportunity.get('m2'))} | "
            f"Confianza {format_confidence(opportunity.get('confidence'))} | "
            f"Beta scope {none_dash(opportunity.get('beta_scope_status'))}"
        )
        warning_box(opportunity.get("warnings"))
        cols = st.columns([1, 1])
        if opportunity.get("url"):
            cols[0].link_button("Abrir publicación", opportunity["url"])
        cols[1].button("Risk Report IA", disabled=True, key=f"risk-{opportunity.get('listing_id')}")
