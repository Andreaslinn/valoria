"""Valuation page landing, side context and demo sections."""
from __future__ import annotations

import streamlit as st

from ui.api_client import ApiClient, ApiError
from ui.components.layout import metric_card, premium_feature_card
from ui.components.theme import html_escape, inject_theme
from ui.demo_data import DEMO_DISCLAIMER
from ui.demo_providers import (
    get_demo_autofact_report,
    get_demo_market_timing,
    get_demo_negotiation_signals,
    get_demo_owner_recommendations,
    get_demo_price_history,
    get_demo_risk_report,
)
from ui.feature_flags import (
    DEMO_AUTOFACT_REPORT,
    DEMO_MARKET_TIMING,
    DEMO_NEGOTIATION_SIGNALS,
    DEMO_OWNER_RECOMMENDATIONS,
    DEMO_PRICE_HISTORY,
    DEMO_RISK_REPORT,
    is_feature_enabled,
)
from ui.state import get_token


def render_demo_notice() -> None:
    st.info(f"Demo Vision activo. {DEMO_DISCLAIMER}")


def render_home_hero() -> None:
    inject_theme()
    st.markdown(
        """
        <div class="avm-home-hero">
            <div class="avm-hero-kicker">Fintech inmobiliaria para Chile</div>
            <div class="avm-hero-title">Decide con datos antes de comprar, vender o seguir una propiedad.</div>
            <div class="avm-hero-copy">
                Tasa propiedades, detecta oportunidades y construye una watchlist inmobiliaria con señales simples.
            </div>
            <div class="avm-hero-benefits">
                <span>Valor estimado</span>
                <span>Radar premium</span>
                <span>Portafolio personal</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_quick_access() -> None:
    cols = st.columns(4, gap="medium")
    cards = [
        ("Tasar propiedad", "Valor de referencia en UF y CLP", "Activo"),
        ("Radar premium", "Oportunidades bajo mercado", "Premium"),
        ("Portafolio", "Watchlist y mercado observado", "Beta"),
        ("Risk Report", "Riesgo y antecedentes", "Próximamente"),
    ]
    for col, (title, body, status) in zip(cols, cards, strict=True):
        with col:
            quick_card(title, body, status)


def quick_card(title: str, body: str, status: str) -> None:
    st.markdown(
        f"""
        <div class="avm-card avm-quick-card">
            <div class="avm-premium-card__status">{html_escape(status)}</div>
            <div class="avm-premium-card__title">{html_escape(title)}</div>
            <div class="avm-premium-card__description">{html_escape(body)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_demo_future_sections() -> None:
    if is_feature_enabled(DEMO_RISK_REPORT):
        risk = get_demo_risk_report()
        st.subheader("Risk Report Demo")
        st.caption("Vista simulada de una futura capa de análisis. No usa datos reales.")
        c1, c2, c3, c4 = st.columns(4, gap="medium")
        with c1:
            metric_card(
                "Riesgo",
                f"{risk['risk_score']}/100",
                caption=risk["interpretation"],
                tone=risk["risk_tone"],
            )
        with c2:
            metric_card("Liquidez", risk["liquidity"], caption=risk["market"], tone="positive")
        with c3:
            metric_card("Señales legales", risk["legal_signals"], caption=risk["cbr_future"], tone="warning")
        with c4:
            metric_card("Comuna", "Ñuñoa", caption="Mercado demo", tone="premium")

    if is_feature_enabled(DEMO_AUTOFACT_REPORT):
        autofact = get_demo_autofact_report()
        premium_feature_card(
            "Autofact inmobiliario demo",
            f"{autofact['cbr_status']} | Score legal {autofact['legal_score']}/100",
            status="demo",
        )

    if is_feature_enabled(DEMO_NEGOTIATION_SIGNALS):
        signals = get_demo_negotiation_signals()
        premium_feature_card(
            "Negociación demo",
            " | ".join(signal["suggested_action"] for signal in signals),
            status="simulación",
        )

    if is_feature_enabled(DEMO_MARKET_TIMING):
        timing = get_demo_market_timing()
        premium_feature_card("Timing de mercado demo", timing["summary"], status=timing["buyer"])

    if is_feature_enabled(DEMO_PRICE_HISTORY):
        history = get_demo_price_history()
        if history:
            premium_feature_card(
                "Historial de precio demo",
                " -> ".join(
                    f"{item['date']}: UF {item['price_uf']:,.0f} ({item['event']})".replace(",", ".")
                    for item in history
                ),
                status="simulación",
            )

    if is_feature_enabled(DEMO_OWNER_RECOMMENDATIONS):
        recs = get_demo_owner_recommendations()
        premium_feature_card(
            "Estrategias demo para propietario",
            " | ".join(item["recommendation"].replace("_", " ") for item in recs),
            status="simulación",
        )


def render_context_panel(client: ApiClient, *, demo_mode: bool) -> None:
    premium_feature_card(
        "Risk Report",
        "Próximamente: señales de riesgo, historial y antecedentes para mirar la propiedad con más contexto.",
        status="premium",
    )
    premium_feature_card(
        "Radar premium",
        "Detecta oportunidades bajo mercado y prioriza propiedades por score cuando quieras pasar de tasar a invertir.",
        status="soon",
    )
    if demo_mode:
        return

    token = get_token()
    if not token:
        premium_feature_card(
            "Alertas reales",
            "Inicia sesion para ver alertas nuevas de tu watchlist.",
            status="login",
        )
        return

    try:
        alerts = client.get_alerts(token, limit=50)
    except ApiError:
        premium_feature_card(
            "Alertas reales",
            "No pudimos cargar tus alertas nuevas en este momento.",
            status="revisar",
        )
        return

    count = len(alerts)
    premium_feature_card(
        "Alertas reales",
        f"{count} alertas nuevas en tu watchlist." if count else "No tienes alertas nuevas.",
        status="live" if count else "sin novedades",
    )


_render_demo_notice = render_demo_notice
_render_home_hero = render_home_hero
_render_quick_access = render_quick_access
_quick_card = quick_card
_render_demo_future_sections = render_demo_future_sections
_render_context_panel = render_context_panel
