# Product Lab only. No real data.
"""Opportunity radar page."""
from __future__ import annotations

from collections import Counter
from typing import Any

import streamlit as st

from ui.api_client import ApiClient
from ui.components.activity import render_demo_property_activity
from ui.components.autofact import render_demo_autofact_report
from ui.components.cards import warning_box
from ui.components.feedback import record_lab_event, render_lab_feedback_widget
from ui.components.layout import (
    empty_state,
    metric_card,
    premium_feature_card,
    render_focus_property_bar,
    section_header,
)
from ui.components.market_context import render_demo_market_context
from ui.components.negotiation import render_demo_negotiation_signals
from ui.components.risk_report import render_demo_risk_report
from ui.components.theme import html_escape, inject_theme, tone_class
from ui.demo_data import get_demo_opportunities, get_demo_portfolio
from ui.demo_market import get_demo_market_context
from ui.demo_portfolio import add_demo_property, ensure_demo_portfolio_state, remove_demo_property
from ui.demo_providers import (
    get_demo_autofact_report,
    get_demo_avm_score,
    get_demo_negotiation_report,
    get_demo_negotiation_signals,
    get_demo_portal_presence,
    get_demo_property_activity,
    get_demo_property_comparison,
    get_demo_risk_report,
)
from ui.feature_flags import (
    DEMO_AUTOFACT_REPORT,
    DEMO_NEGOTIATION_SIGNALS,
    DEMO_PORTAL_PRESENCE,
    DEMO_PROPERTY_COMPARISON,
    DEMO_RISK_REPORT,
    is_feature_enabled,
)
from ui.formatting import format_clp, format_confidence, format_uf, none_dash
from ui.lab import LAB_DISCLAIMER
from ui.lab_focus import get_focused_demo_listing, set_focus_property


def render(client: ApiClient) -> None:
    section_header(
        "Radar Lab",
        "Explora oportunidades simuladas y guardalas en tu Portfolio Demo.",
    )
    st.info(LAB_DISCLAIMER)
    render_focus_property_bar(get_focused_demo_listing())

    controls_col, premium_col = st.columns([1.45, 1], gap="large")
    with controls_col:
        limit = st.slider("Resultados", min_value=5, max_value=100, value=20, step=5)
        view = st.radio("Vista", ["Cards", "Tabla"], horizontal=True)
        st.button("Actualizar radar", type="primary", disabled=True)

    with premium_col:
        _render_premium_teasers(True)

    opportunities = _with_demo_avm_scores(get_demo_opportunities())[:limit]
    demo_state = ensure_demo_portfolio_state(st.session_state, get_demo_portfolio())

    if not opportunities:
        _render_empty_radar()
        return

    saved_ids = {int(item["property_id"]) for item in demo_state["items"].values()}

    _render_summary(opportunities)

    st.subheader("Oportunidades destacadas")
    st.caption("Cards pensadas para escanear rÃ¡pido: precio, estimaciÃ³n, descuento y confianza.")
    st.caption("AVM demo calculado con lÃ³gica de dominio sobre datos simulados.")

    if view == "Tabla":
        _render_opportunities_table(opportunities)
        return

    for index, item in enumerate(opportunities):
        _render_opportunity_card(item, index, client, None, saved_ids, True, demo_state)

    if is_feature_enabled(DEMO_RISK_REPORT):
        _render_demo_risk_report()
    if is_feature_enabled(DEMO_PROPERTY_COMPARISON):
        _render_demo_comparison()

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
    demo_mode: bool,
    demo_state: dict[str, Any] | None = None,
) -> None:
    inject_theme()
    confidence = str(opportunity.get("confidence_label") or opportunity.get("confidence") or "").lower()
    confidence_label, confidence_tone = _confidence_signal(confidence)
    discount = _to_float(opportunity.get("discount_pct"))
    score = _to_float(opportunity.get("score"))
    discount_label, discount_tone = _discount_signal(discount)
    uf_gap = _uf_gap(opportunity)
    avm = opportunity.get("demo_avm") if isinstance(opportunity.get("demo_avm"), dict) else {}
    comparables_used = avm.get("comparables_used")
    avm_caption = f"{comparables_used} comparables demo" if comparables_used else "Fallback demo estático"
    fresh_badge = _badge_html("Nueva oportunidad", "premium") if index == 0 else ""
    listing_id = opportunity.get("listing_id")
    is_saved = isinstance(listing_id, int) and listing_id in saved_ids
    saved_badge = _badge_html("Guardado", "positive") if is_saved else ""
    property_id = _safe_int(listing_id)

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
                    _badge_html(confidence_label, confidence_tone),
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
        _render_fact(facts[3], "Confianza", _format_confidence(confidence), f"Score {_format_score(score)}")

        warning_box(opportunity.get("warnings"))
        if is_feature_enabled(DEMO_NEGOTIATION_SIGNALS):
            _render_signal_chips(opportunity.get("signals", []))

        action_col, focus_col, watch_col, risk_col = st.columns([1, 1, 1, 1], gap="small")
        if opportunity.get("url"):
            action_col.link_button("Abrir publicacion", opportunity["url"])
        else:
            action_col.button("Sin enlace", disabled=True, key=f"no-url-{index}")
        if property_id is not None and focus_col.button("Analizar en Lab", key=f"radar-focus-{property_id}-{index}"):
            set_focus_property(property_id, source="Radar")
            st.success("Propiedad fijada como foco del Lab.")
            st.rerun()
        _render_demo_watchlist_button(watch_col, opportunity, listing_id, is_saved, demo_state, index)
        if risk_col.button("Risk Report", key=f"radar-risk-card-{property_id}-{index}"):
            if property_id is None:
                st.warning("No hay identificador suficiente para abrir Risk Report de esta oportunidad.")
            elif not is_feature_enabled(DEMO_RISK_REPORT):
                st.info("Risk Report esta desactivado en los feature flags del Product Lab.")
            else:
                st.session_state[f"radar-risk-open-{property_id}-{index}"] = True

        if property_id is not None and st.session_state.get(f"radar-risk-open-{property_id}-{index}"):
            render_demo_risk_report(
                get_demo_risk_report(property_id, demo_mode=True),
                expanded=True,
                key_suffix=f"radar-card-{property_id}-{index}",
            )
    return

def _render_signal_chips(signals: list[dict[str, str]]) -> None:
    if not signals:
        return
    chips = " ".join(_badge_html(signal["label"], signal.get("tone", "neutral")) for signal in signals)
    st.markdown(f"<div style='margin:0.15rem 0 0.75rem 0;'>{chips}</div>", unsafe_allow_html=True)


def _render_fact(column: Any, label: str, value: str, caption: str) -> None:
    with column:
        st.caption(label)
        st.markdown(f"**{value}**")
        st.caption(caption)


def _render_demo_watchlist_button(
    column: Any,
    opportunity: dict[str, Any],
    listing_id: Any,
    is_saved: bool,
    demo_state: dict[str, Any] | None,
    index: int,
) -> None:
    property_id = _safe_int(listing_id)
    if demo_state is None or property_id is None:
        column.button("No disponible", disabled=True, key=f"demo-watchlist-missing-{index}")
        return
    if is_saved:
        if column.button("Quitar de Portfolio Demo", key=f"demo-watchlist-remove-{property_id}-{index}"):
            remove_demo_property(demo_state, property_id)
            st.warning("Propiedad quitada del Portfolio Demo.")
            st.rerun()
        return
    if column.button("Guardar en Portfolio Demo", type="primary", key=f"demo-watchlist-save-{property_id}-{index}"):
        add_demo_property(demo_state, opportunity)
        set_focus_property(property_id, source="Radar")
        record_lab_event("saved_property_demo", module="decision_board", property_id=property_id)
        st.success("Propiedad guardada en Portfolio Demo.")
        st.rerun()


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
            "Comparables": (item.get("demo_avm") or {}).get("comparables_used"),
            "Fuente AVM": item.get("avm_source"),
            "URL": item.get("url"),
        }
        for item in opportunities
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    render_lab_feedback_widget("comparison", key_prefix="radar-comparison-feedback")


def _with_demo_avm_scores(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in opportunities:
        row = dict(item)
        avm = get_demo_avm_score(item)
        row["demo_avm"] = avm
        row["avm_source"] = avm["avm_source"]
        if avm["estimated_value_uf"] is not None:
            row["estimated_value_uf"] = avm["estimated_value_uf"]
            row["estimated_price_uf"] = avm["estimated_value_uf"]
            row["estimated_value_clp"] = avm["estimated_value_clp"]
            row["estimated_price_clp"] = avm["estimated_value_clp"]
            row["confidence"] = avm["confidence_label"]
            row["confidence_score"] = avm["confidence_score"]
            row["discount_pct"] = avm["discount_pct"]
            row["score"] = _demo_domain_score(avm)
        else:
            row["confidence_label"] = avm["confidence_label"]
        enriched.append(row)
    return sorted(enriched, key=lambda item: float(item.get("score") or 0), reverse=True)


def _demo_domain_score(avm: dict[str, Any]) -> float:
    discount = max(_to_float(avm.get("discount_pct")) or 0.0, 0.0)
    confidence = max(min(_to_float(avm.get("confidence_score")) or 0.0, 1.0), 0.0)
    discount_component = min(discount, 20.0) / 20.0 * 100.0
    return round((discount_component * 0.65) + (confidence * 100.0 * 0.35), 1)


def _render_premium_teasers(demo_mode: bool) -> None:
    status = "demo" if demo_mode else "soon"
    premium_feature_card(
        "Alertas inteligentes",
        "Avisos cuando aparezcan oportunidades con descuento y confianza relevantes.",
        status=status,
    )
    premium_feature_card(
        "Watchlist premium",
        "Guarda oportunidades, sigue cambios de precio y arma una vista de inversión inmobiliaria.",
        status="premium",
    )


def _render_demo_risk_report() -> None:
    st.subheader("Risk Report Demo")
    st.caption("Simulación visual de la futura capa de riesgo. No usa CBR ni datos reales.")
    options = get_demo_opportunities()
    labels = {f"{item['title']} | UF {item['price_uf']:,.0f}".replace(",", "."): item for item in options}
    selected = st.selectbox("Propiedad para Risk Report Demo", list(labels), key="radar-risk-report-demo-property")
    set_focus_property(int(labels[selected]["listing_id"]), source="Radar")
    report = get_demo_risk_report(labels[selected]["listing_id"], demo_mode=True)
    render_demo_risk_report(report, expanded=True, key_suffix=f"radar-section-{labels[selected]['listing_id']}")
    if is_feature_enabled(DEMO_AUTOFACT_REPORT):
        autofact = get_demo_autofact_report(labels[selected]["listing_id"])
        premium_feature_card(
            "Autofact inmobiliario simulado",
            f"{autofact['cbr_status']} | Score legal {autofact['legal_score']}/100",
            status="demo",
        )
    if is_feature_enabled(DEMO_PORTAL_PRESENCE):
        presence = get_demo_portal_presence(labels[selected]["listing_id"])
        active = sum(1 for item in presence if item["is_active"])
        premium_feature_card(
            "Presencia en portales",
            f"{active} portales activos de {len(presence)} detectados en simulación.",
            status="demo",
        )
    if is_feature_enabled(DEMO_NEGOTIATION_SIGNALS):
        signals = get_demo_negotiation_signals(labels[selected]["listing_id"])
        premium_feature_card(
            "Señales de vendedor",
            " | ".join(signal["label"] for signal in signals),
            status="simulación",
        )


def _render_demo_comparison() -> None:
    comparison = get_demo_property_comparison()
    st.subheader("Comparación demo")
    st.caption("Vista simulada para comparar activos por liquidez, riesgo legal y mercado.")
    rows = [
        {
            "Propiedad": item["label"],
            "Precio UF": _format_uf(item["price_uf"]),
            "Liquidez": item["liquidity_score"],
            "Legal": item["legal_score"],
            "Mercado": item["market_score"],
            "Fit": item["fit"],
        }
        for item in comparison
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_empty_radar() -> None:
    empty_state(
        "Sin oportunidades claras por ahora",
        "No encontramos publicaciones bajo mercado con suficiente señal en esta corrida.",
        action_label="Prueba actualizar el radar o ampliar el límite de resultados.",
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


def _discount_signal(discount: float | None) -> tuple[str, str]:
    if discount is None:
        return "Descuento por revisar", "neutral"
    if discount >= 10:
        return "Bajo mercado", "positive"
    if discount >= 5:
        return "Oportunidad moderada", "warning"
    return "Margen estrecho", "neutral"


def _discount_tone(discount: float | None) -> str:
    return _discount_signal(discount)[1]


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
