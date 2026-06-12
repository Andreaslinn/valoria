"""Opportunity radar page."""
from __future__ import annotations

from collections import Counter
from typing import Any

import streamlit as st

from core.assessment.beta_status import beta_status_display_label, beta_status_tone
from ui.api_client import ApiClient, ApiError
from ui.components.cards import warning_box
from ui.components.layout import (
    empty_state,
    metric_card,
    premium_feature_card,
    section_header,
)
from ui.components.risk_report_html import build_radar_risk_report_data, build_risk_report_html
from ui.components.theme import html_escape, inject_theme, tone_class
from ui.formatting import format_clp, format_confidence, format_uf, none_dash
from ui.product_usage import track_usage_event
from ui.state import get_token


def render(client: ApiClient) -> None:
    token = get_token()
    if token is None:
        st.info("Inicia sesión para usar el radar de oportunidades.")
        return

    section_header(
        "Radar de oportunidades",
        "Scanner premium para detectar propiedades bajo mercado con seÃ±ales simples de confianza.",
    )

    controls_col, premium_col = st.columns([1.45, 1], gap="large")
    with controls_col:
        limit = st.slider("Resultados", min_value=5, max_value=100, value=20, step=5)
        view = st.radio("Vista", ["Cards", "Tabla"], horizontal=True)
        refresh = st.button("Actualizar radar", type="primary")

    with premium_col:
        _render_premium_teasers()

    if refresh or "radar_results" not in st.session_state:
        track_usage_event(
            "radar_requested",
            {"radar_limit": limit, "radar_view": view},
        )
        try:
            st.session_state["radar_results"] = client.get_radar_opportunities(
                token=token,
                limit=limit,
            )
        except ApiError as e:
            track_usage_event(
                "radar_failed",
                {
                    "radar_limit": limit,
                    "radar_view": view,
                    "error_status_code": e.status_code,
                },
            )
            _render_api_error(e)
            return
        opportunities = st.session_state.get("radar_results", [])
        track_usage_event(
            "radar_completed",
            {
                "radar_limit": limit,
                "radar_view": view,
                "radar_results_count": len(opportunities),
                "radar_comunas_count": len({item.get("comuna") for item in opportunities if item.get("comuna")}),
            },
        )
    else:
        opportunities = st.session_state.get("radar_results", [])

    if not opportunities:
        _render_empty_radar()
        return

    saved_ids = _load_saved_listing_ids(client, token)

    _render_summary(opportunities)

    st.subheader("Oportunidades destacadas")
    st.caption("Cards pensadas para escanear rÃ¡pido: precio, estimaciÃ³n, descuento y confianza.")

    if view == "Tabla":
        _render_opportunities_table(opportunities)
        return

    for index, item in enumerate(opportunities):
        _render_opportunity_card(item, index, client, token, saved_ids)

def _render_summary(opportunities: list[dict[str, Any]]) -> None:
    avg_discount = _average_number(item.get("discount_pct") for item in opportunities)
    best_score = _max_number(item.get("score") for item in opportunities)
    confidence = _predominant_confidence(opportunities)
    confidence_label, confidence_tone = _confidence_signal(confidence)

    c1, c2, c3, c4 = st.columns(4, gap="medium")
    with c1:
        metric_card("Oportunidades", len(opportunities), caption="Detectadas", tone="premium")
    with c2:
        metric_card(
            "Descuento promedio",
            _format_pct(avg_discount),
            caption="Brecha vs valor estimado",
            tone=_discount_tone(avg_discount),
        )
    with c3:
        metric_card(
            "Mejor score",
            _format_score(best_score),
            caption="Mayor prioridad del radar",
            tone="positive" if best_score is not None else "neutral",
        )
    with c4:
        metric_card(
            "Confianza predominante",
            _format_confidence(confidence),
            caption=confidence_label,
            tone=confidence_tone,
        )


def _render_opportunity_card(
    opportunity: dict[str, Any],
    index: int,
    client: ApiClient,
    token: str | None,
    saved_ids: set[int],
) -> None:
    inject_theme()
    confidence = str(opportunity.get("confidence_label") or opportunity.get("confidence") or "").lower()
    confidence_label, confidence_tone = _confidence_signal(confidence)
    discount = _to_float(opportunity.get("discount_pct"))
    score = _to_float(opportunity.get("score"))
    verdict = str(opportunity.get("radar_verdict") or "").strip().lower()
    verdict_label, verdict_tone = _verdict_signal(verdict)
    discount_label, discount_tone = _discount_signal(discount, verdict=verdict)
    uf_gap = _uf_gap(opportunity)
    avm = opportunity.get("demo_avm") if isinstance(opportunity.get("demo_avm"), dict) else {}
    comparables_used = opportunity.get("comparables_used") or avm.get("comparables_used")
    avm_caption = f"{comparables_used} comparables" if comparables_used else "Comparables no informados"
    fresh_badge = _badge_html("Nueva oportunidad", "premium") if index == 0 else ""
    listing_id = opportunity.get("listing_id")
    is_saved = isinstance(listing_id, int) and listing_id in saved_ids
    saved_badge = _badge_html("Guardado", "positive") if is_saved else ""
    beta_scope = str(opportunity.get("beta_scope_status") or "").strip().lower()
    beta_badge = _badge_html(_beta_scope_label(beta_scope), _beta_scope_tone(beta_scope)) if beta_scope else ""

    with st.container(border=True):
        header_col, badge_col = st.columns([0.68, 0.32], gap="medium")
        with header_col:
            st.markdown(f"#### {none_dash(opportunity.get('title'))}")
            st.caption(f"{none_dash(opportunity.get('comuna'))} | {_format_m2(opportunity.get('m2'))}")
        with badge_col:
            badges = " ".join(
                badge
                for badge in [
                    _badge_html(discount_label, discount_tone),
                    _badge_html(verdict_label, verdict_tone),
                    _badge_html(confidence_label, confidence_tone),
                    beta_badge,
                    fresh_badge,
                    saved_badge,
                ]
                if badge
            )
            st.markdown(badges, unsafe_allow_html=True)

        facts = st.columns([1.2, 1.25, 1.15, 0.9], gap="medium")
        _render_fact(facts[0], "Precio publicado", _format_uf(opportunity.get("price_uf")), _format_clp(opportunity.get("price_clp")))
        _render_fact(facts[1], "Valor estimado", _format_uf(opportunity.get("estimated_price_uf")), avm_caption)
        _render_fact(facts[2], "Diferencia", _format_pct(discount), uf_gap)
        _render_fact(facts[3], "Veredicto", verdict_label, f"Score {_format_score(score)}")

        warning_box(opportunity.get("warnings"))
        risk_summary = _risk_flags_summary(opportunity.get("risk_flags"))
        if risk_summary:
            st.caption(f"Risk flags: {risk_summary}")
        if opportunity.get("beta_scope_message"):
            st.caption(f"Beta scope: {opportunity.get('beta_scope_message')}")
        if opportunity.get("radar_verdict_message"):
            st.caption(str(opportunity.get("radar_verdict_message")))
        _render_signal_chips(opportunity.get("signals", []))

        action_col, watch_col, risk_col = st.columns([1, 1, 1], gap="small")
        if opportunity.get("url"):
            action_col.link_button("Abrir publicacion", opportunity["url"])
        else:
            action_col.button("Sin enlace", disabled=True, key=f"no-url-{index}")
        _render_watchlist_button(watch_col, client, token, listing_id, is_saved, index)
        report_data = build_radar_risk_report_data(opportunity)
        report_html = build_risk_report_html(report_data)
        risk_col.download_button(
            "Risk Report",
            data=report_html,
            file_name=f"risk_report_{listing_id or index}.html",
            mime="text/html",
            key=f"risk-report-download-{listing_id}-{index}",
        )
    return

def _render_signal_chips(signals: list[dict[str, str]]) -> None:
    if not signals:
        return
    chips = " ".join(
        _badge_html(str(signal.get("label") or "Senal"), signal.get("tone", "neutral"))
        for signal in signals
        if isinstance(signal, dict)
    )
    if not chips:
        return
    st.markdown(f"<div style='margin:0.15rem 0 0.75rem 0;'>{chips}</div>", unsafe_allow_html=True)


def _render_fact(column: Any, label: str, value: str, caption: str) -> None:
    with column:
        st.caption(label)
        st.markdown(f"**{value}**")
        st.caption(caption)


def _render_opportunities_table(opportunities: list[dict[str, Any]]) -> None:
    rows = [
        {
            "ID": item.get("listing_id"),
            "Título": item.get("title"),
            "Comuna": item.get("comuna"),
            "Publicado": _format_uf(item.get("price_uf")),
            "Estimado": _format_uf(item.get("estimated_price_uf")),
            "Descuento": _format_pct(item.get("discount_pct")),
            "Score": item.get("score"),
            "Confianza": _format_confidence(item.get("confidence_label") or item.get("confidence")),
            "Confidence score": item.get("confidence_score"),
            "Veredicto": _verdict_signal(item.get("radar_verdict"))[0],
            "Risk flags": _risk_flags_summary(item.get("risk_flags")),
            "Beta scope": _beta_scope_label(item.get("beta_scope_status")),
            "Comparables": item.get("comparables_used") or (item.get("demo_avm") or {}).get("comparables_used"),
            "Fuente AVM": item.get("avm_source"),
            "URL": item.get("url"),
        }
        for item in opportunities
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _load_saved_listing_ids(client: ApiClient, token: str | None) -> set[int]:
    if token is None:
        return set()
    try:
        items = client.list_watchlist(token)
    except ApiError as e:
        st.warning(f"No pudimos cargar tu watchlist: {e.message}")
        return set()
    return {int(item["listing_id"]) for item in items if item.get("listing_id") is not None}


def _render_watchlist_button(
    column: Any,
    client: ApiClient,
    token: str | None,
    listing_id: Any,
    is_saved: bool,
    index: int,
) -> None:
    if token is None:
        column.button("Requiere sesión", disabled=True, key=f"watchlist-login-{index}")
        return
    if not isinstance(listing_id, int):
        column.button("Sin listing", disabled=True, key=f"watchlist-missing-{index}")
        return
    if is_saved:
        column.button("Guardado", disabled=True, key=f"watchlist-saved-{listing_id}-{index}")
        return
    if column.button("Guardar", key=f"watchlist-save-{listing_id}-{index}"):
        try:
            client.save_to_watchlist(listing_id, token)
            st.success("Propiedad guardada en watchlist.")
            st.rerun()
        except ApiError as e:
            st.error(f"No se pudo guardar: {e.message}")


def _render_premium_teasers() -> None:
    premium_feature_card(
        "Alertas inteligentes",
        "Avisos cuando aparezcan oportunidades con descuento y confianza relevantes.",
        status="soon",
    )
    premium_feature_card(
        "Watchlist premium",
        "Guarda oportunidades, sigue cambios de precio y arma una vista de inversión inmobiliaria.",
        status="premium",
    )


def _render_empty_radar() -> None:
    empty_state(
        "Sin oportunidades claras por ahora",
        "No encontramos publicaciones bajo mercado con suficiente señal en esta corrida.",
        action_label="Prueba actualizar el radar o ampliar el límite de resultados.",
    )


def _render_api_error(error: ApiError) -> None:
    if error.status_code == 401:
        empty_state(
            "Sesion requerida para actualizar el radar",
            "Tu sesion expiro, no es valida o no se envio al backend. Inicia sesion nuevamente.",
            action_label=error.message,
        )
        return
    if error.status_code == 403:
        empty_state(
            "No tienes permiso para usar el radar",
            "Tu usuario no tiene autorizacion suficiente para esta accion.",
            action_label=error.message,
        )
        return
    if error.status_code is None:
        if "no respondio a tiempo" in error.message.lower():
            empty_state(
                "El radar tardo demasiado en responder",
                "FastAPI esta disponible, pero el calculo del radar excedio el tiempo de espera.",
                action_label=error.message,
            )
            return
        empty_state(
            "No pudimos conectar con la API",
            "Verifica que FastAPI este corriendo y que la URL de API sea correcta.",
            action_label=error.message,
        )
        return
    if error.status_code >= 500:
        empty_state(
            "El backend no pudo actualizar el radar",
            "La API respondio con un error interno. Revisa los logs de FastAPI.",
            action_label=error.message,
        )
        return
    empty_state(
        "No pudimos actualizar el radar",
        "Verifica que la API esté disponible y vuelve a intentarlo.",
        action_label=error.message,
    )


def _badge_html(label: str, tone: str = "neutral") -> str:
    return (
        f'<span class="avm-badge {tone_class("avm-badge", tone)}">'
        f"{html_escape(label)}</span>"
    )


def _fact_html(label: str, value: str, caption: str, tone: str = "neutral") -> str:
    return f"""
        <div>
            <div class="avm-metric-card__label">{html_escape(label)}</div>
            <div class="avm-metric-card__value" style="font-size:1.1rem;">
                {html_escape(value)}
            </div>
            <div class="avm-metric-card__caption {tone_class("avm-metric-card", tone)}">
                {html_escape(caption)}
            </div>
        </div>
    """


def _predominant_confidence(opportunities: list[dict[str, Any]]) -> str | None:
    values = [
        str(item.get("confidence_label") or item.get("confidence")).lower()
        for item in opportunities
        if item.get("confidence_label") is not None or item.get("confidence") is not None
    ]
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def _confidence_signal(confidence: str | None) -> tuple[str, str]:
    if confidence == "high":
        return "Alta confianza", "positive"
    if confidence == "medium":
        return "Confianza media", "warning"
    if confidence == "low":
        return "Baja confianza", "negative"
    return "Confianza por revisar", "neutral"


def _verdict_signal(value: Any) -> tuple[str, str]:
    text = str(value or "").strip().lower()
    if text == "senal_fuerte":
        return "Senal fuerte", "positive"
    if text == "senal_beta":
        return "Senal beta", "premium"
    if text == "revisar":
        return "Revisar", "warning"
    if text == "no_data":
        return "Sin datos", "negative"
    return "Revisar", "neutral"


def _beta_scope_label(value: Any) -> str:
    return beta_status_display_label(value)


def _beta_scope_tone(value: Any) -> str:
    return beta_status_tone(value)


def _discount_signal(discount: float | None, *, verdict: str | None = None) -> tuple[str, str]:
    if str(verdict or "").strip().lower() == "revisar":
        return "Revisar brecha", "warning"
    if discount is None:
        return "Descuento por revisar", "neutral"
    if discount >= 10:
        return "Bajo mercado", "positive"
    if discount >= 5:
        return "Oportunidad moderada", "warning"
    return "Margen estrecho", "neutral"


def _discount_tone(discount: float | None) -> str:
    return _discount_signal(discount)[1]


def _risk_flags_summary(value: Any) -> str:
    if not isinstance(value, list | tuple):
        return ""
    labels = [str(item).strip() for item in value if str(item or "").strip()]
    return ", ".join(labels[:5])


def _score_tone(score: float | None) -> str:
    if score is None:
        return "neutral"
    if score >= 75:
        return "positive"
    if score >= 50:
        return "warning"
    return "neutral"


def _uf_gap(opportunity: dict[str, Any]) -> str:
    published = _to_float(opportunity.get("price_uf"))
    estimated = _to_float(opportunity.get("estimated_price_uf"))
    if published is None or estimated is None:
        return "Brecha UF no disponible"
    gap = estimated - published
    if gap <= 0:
        return "Sin brecha positiva"
    return f"Potencial aprox. UF {gap:,.0f}".replace(",", ".")


def _average_number(values: Any) -> float | None:
    numbers = [_to_float(value) for value in values]
    clean = [value for value in numbers if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _max_number(values: Any) -> float | None:
    numbers = [_to_float(value) for value in values]
    clean = [value for value in numbers if value is not None]
    if not clean:
        return None
    return max(clean)


def _format_score(score: float | None) -> str:
    if score is None:
        return "—"
    return f"{score:.1f}".replace(".", ",")


def _format_uf(value: Any) -> str:
    return _clean_empty(format_uf(value))


def _format_clp(value: Any) -> str:
    return _clean_empty(format_clp(value))


def _format_pct(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "—"
    return f"{number:.2f}%".replace(".", ",")


def _format_confidence(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return _clean_empty(format_confidence(value))


def _format_m2(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "—"
    return f"{number:.1f} m²".replace(".", ",")


def _clean_empty(value: str) -> str:
    return "—" if value in {"\u00e2\u20ac\u201d", "—"} else value


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
