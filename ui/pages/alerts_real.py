"""Real authenticated alerts page."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient, ApiError
from ui.components.layout import empty_state, section_header
from ui.components.theme import html_escape, inject_theme, tone_class
from ui.formatting import format_clp
from ui.state import get_token, is_demo_mode


def render(client: ApiClient) -> None:
    if is_demo_mode():
        st.info("Las alertas reales estan ocultas en Demo Mode.")
        return
    inject_theme()
    _inject_alert_styles()
    section_header(
        "Alertas",
        "Movimientos reales detectados en propiedades guardadas en tu watchlist.",
    )
    token = get_token()
    if token is None:
        empty_state(
            "Inicia sesion para ver alertas",
            "Las alertas reales solo se muestran para propiedades guardadas por tu usuario.",
        )
        return
    try:
        alerts = client.get_alerts(token, limit=50)
    except ApiError as e:
        st.warning(f"No pudimos cargar tus alertas: {e.message}")
        return
    if not alerts:
        empty_state("No tienes alertas nuevas.", "Te avisaremos cuando una propiedad guardada tenga movimientos relevantes.")
        return
    for alert in alerts:
        _render_alert(client, token, alert)


def _render_alert(client: ApiClient, token: str, alert: dict[str, Any]) -> None:
    alert_id = int(alert["id"])
    st.markdown(
        f"""
        <div class="avm-real-alert-row">
            <div>
                <div class="avm-real-alert-row__meta">
                    {_badge(str(alert.get("alert_type") or "alerta"), "premium")}
                    <span>{html_escape(_date_label(alert.get("created_at")))}</span>
                </div>
                <strong>{html_escape(str(alert.get("title") or "Propiedad guardada"))}</strong>
                <p>{html_escape(_alert_message(alert))}</p>
                <small>{html_escape(str(alert.get("comuna") or ""))} {html_escape(_price_label(alert))}</small>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Marcar como leida", key=f"real-alert-read-{alert_id}"):
        try:
            client.mark_alert_read(alert_id, token)
            st.success("Alerta marcada como leida.")
            st.rerun()
        except ApiError as e:
            st.warning(f"No pudimos actualizar la alerta: {e.message}")


def _alert_message(alert: dict[str, Any]) -> str:
    if alert.get("message"):
        return str(alert["message"])
    payload = alert.get("payload") if isinstance(alert.get("payload"), dict) else {}
    if alert.get("alert_type") == "price_drop":
        previous = payload.get("previous_price_clp")
        new = payload.get("new_price_clp")
        drop_pct = payload.get("drop_pct")
        if previous is not None and new is not None and drop_pct is not None:
            return f"La propiedad bajo de {format_clp(previous)} a {format_clp(new)} (-{float(drop_pct):.2f}%)."
        return "La propiedad bajo de precio."
    return "Nueva alerta de la propiedad."


def _price_label(alert: dict[str, Any]) -> str:
    price = alert.get("price_clp")
    return f"/ {format_clp(price)}" if price is not None else ""


def _date_label(value: Any) -> str:
    return str(value or "Fecha no disponible")


def _badge(label: str, tone: str) -> str:
    return f'<span class="avm-badge {tone_class("avm-badge", tone)}">{html_escape(label)}</span>'


def _inject_alert_styles() -> None:
    st.markdown(
        """
        <style>
        .avm-real-alert-row {
            border: 1px solid var(--avm-border);
            background: var(--avm-surface);
            border-radius: 12px;
            padding: 0.9rem;
            margin: 0.65rem 0 0.25rem;
        }
        .avm-real-alert-row strong {
            display: block;
            color: var(--avm-text);
            margin-top: 0.35rem;
        }
        .avm-real-alert-row p,
        .avm-real-alert-row small,
        .avm-real-alert-row__meta span {
            color: var(--avm-muted);
        }
        .avm-real-alert-row p {
            margin: 0.25rem 0;
        }
        .avm-real-alert-row__meta {
            display: flex;
            gap: 0.45rem;
            align-items: center;
            flex-wrap: wrap;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
