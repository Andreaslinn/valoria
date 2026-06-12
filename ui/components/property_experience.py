"""Unified demo property experience for Product Lab."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.components.activity import render_demo_property_activity
from ui.components.checklist import render_demo_due_diligence_checklist
from ui.components.evidence import evidence_chip, insight_row, metadata_row, stat_cluster
from ui.components.negotiation import render_demo_negotiation_signals
from ui.components.offer_simulator import render_demo_offer_simulator
from ui.components.risk_report import render_demo_risk_report
from ui.components.theme import html_escape, inject_theme, tone_class
from ui.demo_alerts import build_demo_alerts
from ui.demo_data import get_demo_listings, get_demo_portfolio
from ui.demo_market import get_demo_market_context
from ui.demo_portfolio import (
    DEMO_PORTFOLIO_STATUSES,
    add_demo_property,
    add_demo_property_tag,
    ensure_demo_portfolio_state,
    remove_demo_property,
    set_demo_property_favorite,
    set_demo_property_note,
    set_demo_property_status,
)
from ui.demo_providers import (
    get_demo_autofact_report,
    get_demo_negotiation_report,
    get_demo_property_activity,
    get_demo_property_comparison,
    get_demo_risk_report,
)
from ui.formatting import format_uf

SECTION_KEY = "property_experience_section"
ALERT_STATE_KEY = "property_experience_local_alerts"
COMPARE_STATE_KEY = "property_experience_compare_ids"
SECTIONS = ["Decisión", "Negociar", "Due diligence", "Actividad"]
SECTION_ALIASES = {
    "decision": "Decisión",
    "decisión": "Decisión",
    "overview": "Decisión",
    "resumen": "Decisión",
    "mercado": "Decisión",
    "comparables": "Decisión",
    "negociar": "Negociar",
    "negociacion": "Negociar",
    "negociación": "Negociar",
    "negotiation": "Negociar",
    "offer": "Negociar",
    "oferta": "Negociar",
    "due diligence": "Due diligence",
    "due_diligence": "Due diligence",
    "risk": "Due diligence",
    "riesgo": "Due diligence",
    "legal": "Due diligence",
    "autofact": "Due diligence",
    "checklist": "Due diligence",
    "actividad": "Actividad",
    "activity": "Actividad",
    "timeline": "Actividad",
    "alertas": "Actividad",
    "alerts": "Actividad",
}


def render_property_experience(listing: dict[str, Any]) -> None:
    inject_theme()
    _inject_property_experience_styles()
    property_id = int(listing["listing_id"])
    listings = get_demo_listings()
    portfolio_state = ensure_demo_portfolio_state(st.session_state, get_demo_portfolio())
    risk_report = get_demo_risk_report(property_id, demo_mode=True)
    autofact_report = get_demo_autofact_report(property_id, demo_mode=True)
    market_context = get_demo_market_context(str(listing.get("comuna")), demo_mode=True)
    negotiation_report = get_demo_negotiation_report(property_id, demo_mode=True)
    alerts = [alert for alert in build_demo_alerts(listings, demo_mode=True) if alert.get("property_id") == property_id]
    local_alerts = _local_alerts(property_id)
    intelligence = _build_property_intelligence(
        listing,
        risk_report,
        autofact_report,
        negotiation_report,
        market_context,
        alerts,
        local_alerts,
        portfolio_state,
    )

    _render_hero(listing, risk_report, market_context)
    _render_action_rail(listing, portfolio_state)
    _render_intelligence_summary_rail(intelligence, property_id)
    section = _render_property_nav(intelligence)
    _render_contextual_transition(intelligence, section)

    if section == "Decisión":
        _render_decision_snapshot(risk_report, negotiation_report, intelligence)
        _render_overview(listing, risk_report, negotiation_report, market_context, alerts, local_alerts, intelligence)
        _render_more_context(market_context, get_demo_property_comparison(property_id), property_id)
    elif section == "Negociar":
        render_demo_negotiation_signals(negotiation_report, expanded=True, use_expander=False)
        render_demo_offer_simulator(
            listing,
            buyer_profile="primer_comprador",
            strategy=str(negotiation_report.get("strategy", "moderada")),
            risk_report=risk_report,
            expanded=True,
            key_prefix=f"property-offer-{property_id}",
            use_expander=False,
        )
    elif section == "Due diligence":
        render_demo_risk_report(
            risk_report,
            expanded=True,
            key_suffix=f"property-experience-{property_id}",
            use_expander=False,
        )
        render_demo_due_diligence_checklist(
            listing,
            risk_report=risk_report,
            autofact_report=autofact_report,
            expanded=True,
            key_prefix=f"property-experience-checklist-{property_id}",
            use_expander=False,
        )
    elif section == "Actividad":
        render_demo_property_activity(
            get_demo_property_activity(property_id, demo_mode=True),
            key=f"property-experience-activity-{property_id}",
            use_expander=False,
        )
        _render_alerts(alerts, local_alerts)


def _render_hero(listing: dict[str, Any], risk_report: dict[str, Any], market_context: dict[str, Any]) -> None:
    discount = _discount(listing)
    score = int(float(listing.get("score") or 0))
    risk_score = risk_report.get("scores", {}).get("total", "-")
    badges = [
        _badge(str(listing.get("comuna", "")).title(), "premium"),
        _badge(f"{listing.get('days_on_market', 0)} dias publicada", "warning"),
        _badge(f"Risk {risk_score}/100", "neutral"),
        _badge(str(market_context.get("market_temperature", "mercado")).title(), "positive"),
    ]
    st.markdown(
        f"""
        <div class="avm-property-hero avm-lab-shimmer">
            <div class="avm-property-hero__top">
                <div>
                    <div class="avm-property-hero__kicker"><span class="avm-lab-live-dot"></span>Property Experience Lab</div>
                    <h1>{html_escape(listing.get("title"))}</h1>
                    <p>{html_escape(listing.get("address_label"))}</p>
                </div>
                <div class="avm-property-hero__price">
                    <span>Precio publicado</span>
                    <strong>{html_escape(format_uf(listing.get("price_uf")))}</strong>
                    <small>{html_escape(str(discount))}% bajo valor demo</small>
                </div>
            </div>
            <div class="avm-property-hero__facts">
                {_fact("Valor demo", format_uf(listing.get("estimated_value_uf")), "Referencia simulada")}
                {_fact("Programa", f"{listing.get('bedrooms', 0)}D / {listing.get('bathrooms', 0)}B", f"{listing.get('m2', 0)} m2")}
                {_fact("Score oportunidad", f"{score}/100", "Ranking demo")}
                {_fact("Fuente", str(listing.get("source", "Demo")), "Multiportal simulado")}
            </div>
            <div class="avm-property-hero__badges">{"".join(badges)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_action_rail(listing: dict[str, Any], portfolio_state: dict[str, Any]) -> None:
    property_id = int(listing["listing_id"])
    saved = str(property_id) in portfolio_state["items"]
    status = portfolio_state["items"].get(str(property_id), {}).get("status", "mirando")
    favorite = bool(portfolio_state["items"].get(str(property_id), {}).get("favorite", False))
    st.markdown('<div class="avm-property-actions avm-lab-shimmer">', unsafe_allow_html=True)
    cols = st.columns([1, 1, 1, 1, 1, 1], gap="small")
    if cols[0].button("Quitar" if saved else "Guardar", type="primary", key=f"px-save-{property_id}"):
        if saved:
            remove_demo_property(portfolio_state, property_id)
            st.toast("Propiedad quitada del portafolio demo.")
        else:
            add_demo_property(portfolio_state, listing)
            st.toast("Propiedad guardada en watchlist demo.")
        st.rerun()
    selected_status = cols[1].selectbox(
        "Estado",
        sorted(DEMO_PORTFOLIO_STATUSES),
        index=sorted(DEMO_PORTFOLIO_STATUSES).index(status) if status in DEMO_PORTFOLIO_STATUSES else 0,
        key=f"px-status-{property_id}",
        disabled=not saved,
    )
    if saved and selected_status != status:
        set_demo_property_status(portfolio_state, property_id, selected_status)
        st.rerun()
    selected_favorite = cols[2].checkbox("Favorita", value=favorite, key=f"px-favorite-{property_id}", disabled=not saved)
    if saved and selected_favorite != favorite:
        set_demo_property_favorite(portfolio_state, property_id, selected_favorite)
        st.rerun()
    if cols[3].button("Negociar", key=f"px-negotiate-{property_id}"):
        st.session_state[SECTION_KEY] = "Negociar"
        st.rerun()
    if cols[4].button("Comparar", key=f"px-compare-action-{property_id}"):
        st.session_state[SECTION_KEY] = "Decisión"
        st.rerun()
    if cols[5].button("Abrir report", key=f"px-report-{property_id}"):
        st.session_state[SECTION_KEY] = "Due diligence"
        st.rerun()

    cols2 = st.columns([0.58, 0.24, 0.18], gap="small")
    current_note = portfolio_state["items"].get(str(property_id), {}).get("note", "")
    note = cols2[0].text_input("Nota demo", value=current_note, key=f"px-note-{property_id}", disabled=not saved)
    if saved and note != current_note:
        set_demo_property_note(portfolio_state, property_id, note)
    tag = cols2[1].text_input("Tag", key=f"px-tag-{property_id}", disabled=not saved)
    if cols2[2].button("Agregar alerta", key=f"px-alert-{property_id}"):
        _add_local_alert(property_id)
        st.toast("Alerta demo agregada.")
    if saved and tag.strip():
        add_demo_property_tag(portfolio_state, property_id, tag)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_property_nav(intelligence: dict[str, Any]) -> str:
    current = _normalize_section(st.session_state.get(SECTION_KEY, "Decisión"))
    if current not in SECTIONS:
        current = "Decisión"
    selected = st.segmented_control(
        "Capas de inteligencia",
        SECTIONS,
        default=current,
        label_visibility="collapsed",
    )
    if selected:
        st.session_state[SECTION_KEY] = selected
        return str(selected)
    return current


def _normalize_section(value: Any) -> str:
    section = str(value).strip()
    normalized = section.casefold().replace("_", " ")
    return SECTION_ALIASES.get(normalized, SECTION_ALIASES.get(section, section))


def _build_property_intelligence(
    listing: dict[str, Any],
    risk_report: dict[str, Any],
    autofact_report: dict[str, Any],
    negotiation_report: dict[str, Any],
    market_context: dict[str, Any],
    alerts: list[dict[str, Any]],
    local_alerts: list[dict[str, Any]],
    portfolio_state: dict[str, Any],
) -> dict[str, Any]:
    property_id = int(listing["listing_id"])
    portfolio_item = portfolio_state.get("items", {}).get(str(property_id), {})
    current_status = str(portfolio_item.get("status") or "descubierta")
    main_risks = [item for item in risk_report.get("main_risks", []) if item]
    main_opportunities = [item for item in risk_report.get("main_opportunities", []) if item]
    negotiation_score = int(negotiation_report.get("negotiation_score") or 0)
    legal_score = int(autofact_report.get("legal_score") or risk_report.get("scores", {}).get("legal_simulated") or 0)
    risk_tone = str(risk_report.get("risk_tone") or _score_tone(int(risk_report.get("risk_score") or 50)))
    market_badges = market_context.get("badges") or []
    latest_activity = get_demo_property_activity(property_id, demo_mode=True)[:1]
    alert_count = len(alerts) + len(local_alerts)
    suggested_action = _suggested_action(
        current_status=current_status,
        risk_tone=risk_tone,
        legal_score=legal_score,
        negotiation_score=negotiation_score,
        alert_count=alert_count,
    )
    return {
        "property_id": property_id,
        "current_status": current_status,
        "status_label": current_status.replace("_", " ").title(),
        "main_risk": main_risks[0] if main_risks else "Sin riesgo demo dominante.",
        "main_risk_tone": risk_tone,
        "main_opportunity": main_opportunities[0] if main_opportunities else listing.get("short_summary", "Oportunidad demo en observacion."),
        "opportunity_tone": "positive" if float(listing.get("discount_pct") or 0) >= 0 else "warning",
        "suggested_action": suggested_action["label"],
        "suggested_action_body": suggested_action["body"],
        "suggested_layer": suggested_action["layer"],
        "supporting_evidence": [
            ("Alertas", alert_count, "warning" if alert_count else "neutral"),
            ("Legal", f"{legal_score}/100", _score_tone(legal_score)),
            ("Negociacion", f"{negotiation_score}/100", _score_tone(negotiation_score)),
            ("Mercado", str(market_context.get("market_temperature", "demo")).title(), "premium"),
        ],
        "evidence_chips": [
            *(str(item) for item in market_badges[:3]),
            *[str(signal.get("label")) for signal in listing.get("signals", [])[:2]],
        ],
        "latest_activity": latest_activity[0] if latest_activity else None,
        "workflow_steps": _workflow_steps(current_status, risk_tone, legal_score, negotiation_score),
    }


def _suggested_action(
    *,
    current_status: str,
    risk_tone: str,
    legal_score: int,
    negotiation_score: int,
    alert_count: int,
) -> dict[str, str]:
    if risk_tone == "negative" or legal_score < 60:
        return {
            "label": "Desbloquear riesgo antes de avanzar",
            "body": "Revisa la capa legal/riesgo y convierte las banderas demo en checklist.",
            "layer": "Due diligence",
        }
    if current_status in {"contactar", "negociar"} or negotiation_score >= 70:
        return {
            "label": "Preparar rango de oferta",
            "body": "Usa senales de negociacion y comparables para definir una estrategia demo.",
            "layer": "Negociar",
        }
    if alert_count:
        return {
            "label": "Revisar alertas activas",
            "body": "Hay movimientos recientes que pueden cambiar la prioridad de la propiedad.",
            "layer": "Actividad",
        }
    return {
        "label": "Completar tesis de decision",
        "body": "Cruza mercado, actividad y checklist antes de moverla a contactar.",
        "layer": "Due diligence",
    }


def _workflow_steps(current_status: str, risk_tone: str, legal_score: int, negotiation_score: int) -> list[tuple[str, str, str]]:
    return [
        ("Entender", "completo" if current_status != "descubierta" else "activo", "premium"),
        ("Riesgo", "bloqueado" if risk_tone == "negative" or legal_score < 60 else "controlado", "negative" if risk_tone == "negative" else "positive"),
        ("Oferta", "lista" if negotiation_score >= 70 else "pendiente", "positive" if negotiation_score >= 70 else "warning"),
        ("Decision", current_status, "premium" if current_status in {"negociar", "favorita"} else "neutral"),
    ]


def _render_intelligence_summary_rail(intelligence: dict[str, Any], property_id: int) -> None:
    chips = "".join(evidence_chip(chip, "neutral") for chip in intelligence["evidence_chips"][:5])
    steps = "".join(
        f"""
        <div class="avm-property-step">
            <span>{html_escape(label)}</span>
            {evidence_chip(value, tone)}
        </div>
        """
        for label, value, tone in intelligence["workflow_steps"]
    )
    st.markdown(
        f"""
        <div class="avm-property-intel-rail avm-lab-motion-reveal">
            <div class="avm-property-intel-rail__primary">
                <span>Current status</span>
                <strong>{html_escape(intelligence["status_label"])}</strong>
                <p>{html_escape(intelligence["suggested_action_body"])}</p>
            </div>
            <div class="avm-property-intel-rail__item">
                <span>Main risk</span>
                <strong>{html_escape(intelligence["main_risk"])}</strong>
                {evidence_chip("riesgo", intelligence["main_risk_tone"])}
            </div>
            <div class="avm-property-intel-rail__item">
                <span>Main opportunity</span>
                <strong>{html_escape(intelligence["main_opportunity"])}</strong>
                {evidence_chip("oportunidad", intelligence["opportunity_tone"])}
            </div>
            <div class="avm-property-intel-rail__item avm-property-intel-rail__action">
                <span>Suggested action</span>
                <strong>{html_escape(intelligence["suggested_action"])}</strong>
                <div class="avm-evidence-chip-row">{chips}</div>
            </div>
            <div class="avm-property-workflow-strip">{steps}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns([1, 1, 1, 1], gap="small")
    quick_layers = [
        ("Accion sugerida", str(intelligence["suggested_layer"])),
        ("Riesgo", "Due diligence"),
        ("Checklist", "Due diligence"),
        ("Actividad", "Actividad"),
    ]
    for col, (label, layer) in zip(cols, quick_layers, strict=False):
        if col.button(label, key=f"px-intel-layer-{property_id}-{layer}", use_container_width=True):
            st.session_state[SECTION_KEY] = layer
            st.rerun()


def _render_contextual_transition(intelligence: dict[str, Any], section: str) -> None:
    layer_copy = {
        "Decisión": ("Lectura integrada", "La propiedad se interpreta como una decision abierta, no como un reporte separado."),
        "Negociar": ("Estrategia de oferta", "Senales, precio y riesgo alimentan una tactica demo."),
        "Due diligence": ("Convertir evidencia en tarea", "Checklist transforma alertas y riesgo en pasos concretos."),
        "Actividad": ("Linea viva", "Eventos y movimientos explican por que cambia la decision."),
    }
    title, body = layer_copy.get(section, layer_copy["Decisión"])
    insight_row(title, body, value=intelligence["suggested_action"], tone="premium", priority="high")
    stat_cluster(intelligence["supporting_evidence"])
    latest = intelligence.get("latest_activity")
    if latest:
        metadata_row([("Ultimo evento", f"{latest.get('date')} / {latest.get('title')}")])


def _render_decision_snapshot(
    risk_report: dict[str, Any],
    negotiation_report: dict[str, Any],
    intelligence: dict[str, Any],
) -> None:
    scores = risk_report.get("scores", {})
    negotiation_signals = negotiation_report.get("signals", [])[:2]
    st.markdown(
        f"""
        <div class="avm-property-panel avm-property-decision-snapshot">
            <div class="avm-property-panel__eyebrow">Primera lectura</div>
            <h3>{html_escape(intelligence["suggested_action"])}</h3>
            <p>{html_escape(intelligence["suggested_action_body"])}</p>
            <div class="avm-property-signal-list">
                {"".join(_signal_html(signal) for signal in negotiation_signals)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    stat_cluster(
        [
            ("Riesgo", f"{risk_report.get('risk_score', scores.get('total', '-'))}/100", str(intelligence["main_risk_tone"])),
            ("Liquidez", f"{scores.get('liquidity', '-')}/100", _score_tone(int(scores.get("liquidity") or 0))),
            ("Mercado", f"{scores.get('market', '-')}/100", _score_tone(int(scores.get("market") or 0))),
        ]
    )


def _render_more_context(market_context: dict[str, Any], comparables: list[dict[str, Any]], property_id: int) -> None:
    st.markdown("#### Más contexto")
    insight_row(
        "Contexto de comuna",
        str(market_context.get("short_market_summary") or "Contexto demo no disponible."),
        value=str(market_context.get("market_temperature", "demo")).title(),
        tone="premium",
        priority="supporting",
    )
    stat_cluster(
        [
            ("Inventario", str(market_context.get("inventory_level", "-")).title(), "neutral"),
            ("Demanda", str(market_context.get("demand_level", "-")).title(), "positive"),
            ("Dias mercado", str(market_context.get("average_days_on_market", "-")), "warning"),
            ("Comparables", str(market_context.get("active_comparables", "-")), "premium"),
        ]
    )
    _render_comparables(comparables, property_id)


def _render_overview(
    listing: dict[str, Any],
    risk_report: dict[str, Any],
    negotiation_report: dict[str, Any],
    market_context: dict[str, Any],
    alerts: list[dict[str, Any]],
    local_alerts: list[dict[str, Any]],
    intelligence: dict[str, Any],
) -> None:
    signals = listing.get("signals", [])[:3]
    workflow_rows = "".join(
        f"""
        <div class="avm-property-flow-row">
            <span>{html_escape(label)}</span>
            <strong>{html_escape(value)}</strong>
            {evidence_chip(value, tone)}
        </div>
        """
        for label, value, tone in intelligence["workflow_steps"]
    )
    st.markdown(
        f"""
        <div class="avm-property-grid">
            <section class="avm-property-panel avm-property-panel--wide">
                <div class="avm-property-panel__eyebrow">Decision flow</div>
                <h3>{html_escape(intelligence["suggested_action"])}</h3>
                <p>{html_escape(risk_report.get("executive_summary"))}</p>
                <div class="avm-property-signal-list">
                    {"".join(_signal_html(signal) for signal in signals)}
                </div>
            </section>
            <aside class="avm-property-panel">
                <div class="avm-property-panel__eyebrow">Decision state</div>
                <h3>{html_escape(str(market_context.get("label", "")).title())}</h3>
                <p>{html_escape(market_context.get("short_market_summary"))}</p>
                <div class="avm-property-flow-stack">{workflow_rows}</div>
            </aside>
        </div>
        """,
        unsafe_allow_html=True,
    )
    insight_row(
        "Evidencia conectada",
        f"{len(alerts) + len(local_alerts)} alertas, estrategia {negotiation_report.get('strategy', 'moderada')} y riesgo {intelligence['main_risk']}",
        value="contextual",
        tone="premium",
    )
    _render_price_story(listing)


def _render_price_story(listing: dict[str, Any]) -> None:
    history = listing.get("price_history", [])
    rows = "".join(
        f"""
        <div class="avm-property-price-row">
            <span>{html_escape(item.get("date"))}</span>
            <strong>{html_escape(format_uf(item.get("price_uf")))}</strong>
            <em>{html_escape(item.get("event"))}</em>
        </div>
        """
        for item in history
    )
    st.markdown(
        f"""
        <div class="avm-property-panel">
            <div class="avm-property-panel__eyebrow">Historia de precio</div>
            <div class="avm-property-price-list">{rows}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_comparables(comparables: list[dict[str, Any]], property_id: int) -> None:
    items = [item for item in comparables if int(item.get("property_id", 0)) != property_id]
    if not items:
        st.caption("Sin comparables demo para esta propiedad.")
        return
    cards = "".join(
        f"""
        <div class="avm-property-comparable">
            <strong>{html_escape(item.get("title") or item.get("label"))}</strong>
            <span>{html_escape(item.get("comuna", "Demo"))} / {html_escape(format_uf(item.get("price_uf")))}</span>
            <p>{html_escape(item.get("fit"))}</p>
        </div>
        """
        for item in items[:6]
    )
    st.markdown(
        f"""
        <div class="avm-property-panel">
            <div class="avm-property-panel__eyebrow">Comparables activos demo</div>
            <div class="avm-property-comparables">{cards}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    selected_ids = st.session_state.setdefault(COMPARE_STATE_KEY, [])
    compare_options = {
        f"{item.get('title') or item.get('label')} / {format_uf(item['price_uf'])}": int(item["property_id"])
        for item in items
    }
    selected = st.multiselect(
        "Comparar contra",
        list(compare_options),
        default=[label for label, item_id in compare_options.items() if item_id in selected_ids],
        key=f"px-compare-{property_id}",
    )
    st.session_state[COMPARE_STATE_KEY] = [compare_options[label] for label in selected]


def _render_alerts(alerts: list[dict[str, Any]], local_alerts: list[dict[str, Any]]) -> None:
    all_alerts = [*local_alerts, *alerts]
    if not all_alerts:
        st.caption("Sin alertas demo para esta propiedad.")
        return
    for alert in all_alerts:
        st.markdown(
            f"""
            <div class="avm-property-alert">
                {_badge(str(alert.get("category", "lab")).title(), str(alert.get("severity", "warning")))}
                <strong>{html_escape(alert.get("title", alert.get("label", "Alerta demo")))}</strong>
                <p>{html_escape(alert.get("body", alert.get("description", "Movimiento simulado del Lab.")))}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _local_alerts(property_id: int) -> list[dict[str, Any]]:
    state = st.session_state.setdefault(ALERT_STATE_KEY, {})
    return list(state.get(str(property_id), []))


def _add_local_alert(property_id: int) -> None:
    state = st.session_state.setdefault(ALERT_STATE_KEY, {})
    alerts = state.setdefault(str(property_id), [])
    alerts.insert(
        0,
        {
            "id": f"local-{property_id}-{len(alerts) + 1}",
            "property_id": property_id,
            "title": "Alerta manual demo",
            "body": "Seguimiento creado desde Property Experience Lab.",
            "severity": "premium",
            "category": "watchlist",
        },
    )


def _discount(listing: dict[str, Any]) -> float:
    published = float(listing.get("price_uf") or 0)
    estimated = float(listing.get("estimated_value_uf") or listing.get("estimated_price_uf") or 0)
    if not published or not estimated:
        return 0.0
    return round(((estimated - published) / estimated) * 100, 1)


def _score_tone(score: int) -> str:
    if score >= 78:
        return "positive"
    if score >= 58:
        return "warning"
    return "negative"


def _fact(label: str, value: str, caption: str) -> str:
    return f"""
    <div class="avm-property-fact">
        <span>{html_escape(label)}</span>
        <strong>{html_escape(value)}</strong>
        <small>{html_escape(caption)}</small>
    </div>
    """


def _mini(label: str, value: str) -> str:
    return f'<div><span>{html_escape(label)}</span><strong>{html_escape(value)}</strong></div>'


def _badge(label: str, tone: str) -> str:
    return f'<span class="avm-badge {tone_class("avm-badge", tone)}">{html_escape(label)}</span>'


def _signal_html(signal: dict[str, Any]) -> str:
    return f"""
    <div class="avm-property-signal">
        {_badge(str(signal.get("label", "Senal")), str(signal.get("tone", "neutral")))}
        <p>{html_escape(signal.get("explanation"))}</p>
    </div>
    """


def _inject_property_experience_styles() -> None:
    st.markdown(
        """
        <style>
        .avm-property-hero {
            border: 1px solid var(--avm-border);
            border-radius: 12px;
            background: var(--avm-hero-bg);
            box-shadow: var(--avm-shadow);
            padding: 1.15rem;
            margin: 0.55rem 0 0.85rem;
        }
        .avm-property-hero.avm-lab-shimmer::after,
        .avm-property-actions.avm-lab-shimmer::after {
            opacity: 0.14;
        }
        .avm-property-hero__top,
        .avm-property-hero__facts,
        .avm-property-grid {
            display: grid;
            gap: 0.85rem;
        }
        .avm-property-hero__top {
            grid-template-columns: minmax(0, 1fr) minmax(180px, 260px);
            align-items: start;
        }
        .avm-property-hero h1 {
            color: var(--avm-text);
            font-size: 1.8rem;
            line-height: 1.12;
            margin: 0.1rem 0 0;
        }
        .avm-property-hero p,
        .avm-property-panel p,
        .avm-property-signal p,
        .avm-property-alert p,
        .avm-property-comparable p {
            color: var(--avm-muted);
            margin: 0.35rem 0 0;
        }
        .avm-property-hero__kicker,
        .avm-property-panel__eyebrow {
            color: var(--avm-premium);
            font-size: 0.72rem;
            font-weight: 800;
            text-transform: uppercase;
        }
        .avm-property-hero__price,
        .avm-property-fact,
        .avm-property-panel,
        .avm-property-alert,
        .avm-property-comparable {
            border: 1px solid var(--avm-border);
            border-radius: 10px;
            background: var(--avm-surface);
            padding: 0.82rem;
        }
        .avm-property-hero__price span,
        .avm-property-fact span,
        .avm-property-mini-stack span,
        .avm-property-price-row span {
            color: var(--avm-muted);
            font-size: 0.78rem;
            font-weight: 650;
        }
        .avm-property-hero__price strong {
            display: block;
            color: var(--avm-text);
            font-size: 1.55rem;
        }
        .avm-property-hero__price small,
        .avm-property-fact small {
            color: var(--avm-positive);
        }
        .avm-property-hero__facts {
            grid-template-columns: repeat(4, minmax(0, 1fr));
            margin-top: 0.9rem;
        }
        .avm-property-fact strong {
            display: block;
            color: var(--avm-text);
            font-size: 1.05rem;
            margin: 0.18rem 0;
        }
        .avm-property-hero__badges {
            display: flex;
            gap: 0.42rem;
            flex-wrap: wrap;
            margin-top: 0.8rem;
        }
        .avm-property-actions {
            border: 1px solid var(--avm-border);
            border-radius: 10px;
            background: var(--avm-surface-alt);
            padding: 0.75rem;
            margin-bottom: 0.85rem;
        }
        .avm-property-intel-rail {
            display: grid;
            grid-template-columns: 1.15fr 1fr 1fr 1.1fr;
            gap: 0.65rem;
            margin: 0.7rem 0 0.75rem;
            padding: 0.75rem;
            border-radius: 14px;
            background:
                radial-gradient(circle at 8% 0%, rgba(82, 113, 255, 0.16), transparent 30%),
                linear-gradient(135deg, rgba(255,255,255,0.065), rgba(255,255,255,0.025));
            border: 1px solid rgba(255,255,255,0.09);
        }
        .avm-property-intel-rail__primary,
        .avm-property-intel-rail__item {
            min-width: 0;
            border-radius: 11px;
            background: rgba(255,255,255,0.04);
            padding: 0.72rem;
        }
        .avm-property-intel-rail__primary span,
        .avm-property-intel-rail__item span,
        .avm-property-step span,
        .avm-property-flow-row span {
            color: var(--avm-muted);
            display: block;
            font-size: 0.74rem;
            font-weight: 800;
            text-transform: uppercase;
        }
        .avm-property-intel-rail__primary strong,
        .avm-property-intel-rail__item strong,
        .avm-property-flow-row strong {
            color: var(--avm-text);
            display: block;
            line-height: 1.2;
            margin: 0.2rem 0 0.35rem;
        }
        .avm-property-intel-rail__primary p {
            color: var(--avm-muted);
            margin: 0;
        }
        .avm-property-workflow-strip {
            grid-column: 1 / -1;
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.45rem;
            padding-top: 0.25rem;
        }
        .avm-property-step,
        .avm-property-flow-row {
            border-top: 1px solid rgba(255,255,255,0.08);
            padding-top: 0.45rem;
        }
        .avm-property-flow-stack {
            display: grid;
            gap: 0.55rem;
            margin-top: 0.75rem;
        }
        .avm-property-grid {
            grid-template-columns: minmax(0, 1.8fr) minmax(260px, 0.8fr);
            margin-top: 0.75rem;
        }
        .avm-property-panel h3,
        .avm-property-alert strong,
        .avm-property-comparable strong {
            color: var(--avm-text);
            margin: 0.2rem 0 0;
        }
        .avm-property-signal-list,
        .avm-property-comparables,
        .avm-property-mini-stack {
            display: grid;
            gap: 0.6rem;
            margin-top: 0.75rem;
        }
        .avm-property-comparables {
            grid-template-columns: repeat(3, minmax(0, 1fr));
        }
        .avm-property-signal {
            border-left: 2px solid var(--avm-premium);
            padding-left: 0.7rem;
        }
        .avm-property-mini-stack div,
        .avm-property-price-row {
            display: flex;
            justify-content: space-between;
            gap: 0.75rem;
            border-top: 1px solid var(--avm-border);
            padding-top: 0.55rem;
        }
        .avm-property-mini-stack strong,
        .avm-property-price-row strong {
            color: var(--avm-text);
        }
        .avm-property-price-list {
            display: grid;
            gap: 0.55rem;
            margin-top: 0.65rem;
        }
        .avm-property-price-row em {
            color: var(--avm-premium);
            font-style: normal;
            font-weight: 700;
        }
        .avm-property-alert {
            margin: 0.55rem 0;
        }
        .avm-property-comparable span {
            display: block;
            color: var(--avm-muted);
            margin-top: 0.25rem;
        }
        @media (max-width: 820px) {
            .avm-property-hero__top,
            .avm-property-grid,
            .avm-property-intel-rail,
            .avm-property-workflow-strip,
            .avm-property-hero__facts,
            .avm-property-comparables {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
