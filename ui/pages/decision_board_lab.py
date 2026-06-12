"""Decision Board Lab page."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient
from ui.components.checklist import render_demo_due_diligence_checklist
from ui.components.evidence import evidence_chip, insight_row, stat_cluster
from ui.components.feedback import record_lab_event, render_lab_feedback_widget
from ui.components.layout import render_focus_property_bar, section_header
from ui.components.negotiation import render_demo_negotiation_signals
from ui.components.offer_simulator import render_demo_offer_simulator
from ui.components.risk_report import render_demo_risk_report
from ui.components.theme import html_escape, inject_theme
from ui.demo_alerts import build_demo_alerts
from ui.demo_data import get_demo_listings, get_demo_portfolio
from ui.demo_decision_board import (
    DEMO_DECISION_BOARD_DISCLAIMER,
    DEMO_DECISION_BOARD_STATUSES,
    ensure_demo_decision_board_state,
    get_demo_decision_board_cards,
    move_demo_decision_property,
    summarize_demo_decision_board,
    sync_decision_status_to_portfolio,
)
from ui.demo_market import get_demo_market_context
from ui.demo_portfolio import (
    add_demo_property,
    ensure_demo_portfolio_state,
    set_demo_property_note,
)
from ui.demo_providers import (
    get_demo_autofact_report,
    get_demo_negotiation_report,
    get_demo_property_activity,
    get_demo_property_comparison,
    get_demo_risk_report,
)
from ui.formatting import format_uf
from ui.lab import LAB_DISCLAIMER
from ui.lab_focus import get_focused_demo_listing, set_focus_property
from ui.state import is_demo_mode

FOCUS_KEY = "decision_board_focus_property_id"
PANEL_KEY = "decision_board_context_panel"
STRATEGY_KEY = "decision_board_strategy"
PROFILE_KEY = "decision_board_buyer_profile"

PANEL_OPTIONS = [
    "Resumen",
    "Riesgo",
    "Negociar",
    "Checklist",
    "Notas",
]
PANEL_ALIASES = {
    "alertas": "Resumen",
    "timeline": "Resumen",
    "mercado": "Resumen",
    "comparar": "Resumen",
    "risk": "Riesgo",
    "riesgo": "Riesgo",
    "autofact": "Riesgo",
    "resumen": "Resumen",
    "negociar": "Negociar",
    "checklist": "Checklist",
    "notas": "Notas",
}


def render(client: ApiClient) -> None:
    _ = client
    if not is_demo_mode():
        st.info("Activa Product Lab para abrir Decision Board Lab. En modo real esta experiencia sigue oculta.")
        return

    inject_theme()
    _inject_decision_cockpit_styles()

    listings = get_demo_listings()
    portfolio_state = ensure_demo_portfolio_state(st.session_state, get_demo_portfolio())
    board_state = ensure_demo_decision_board_state(st.session_state, listings, portfolio_state)
    cards = get_demo_decision_board_cards(listings, board_state)
    focus_card = _get_focus_card(cards)
    queues = _build_operating_queues(cards)
    summary = summarize_demo_decision_board(cards)

    section_header(
        "Decision Board Lab",
        "Cockpit demo para decidir, desbloquear riesgos y mover oportunidades sin saltar entre pantallas.",
    )
    st.info(LAB_DISCLAIMER)
    st.caption(DEMO_DECISION_BOARD_DISCLAIMER)
    render_focus_property_bar(get_focused_demo_listing())

    _render_operating_hero(focus_card, queues, summary)
    _render_quick_command_bar(focus_card)

    left, right = st.columns([0.38, 0.62], gap="large")
    with left:
        _render_operating_queues(queues)
        _render_state_map(cards, board_state, portfolio_state)
    with right:
        _render_contextual_panel(focus_card, cards, listings, board_state, portfolio_state)


def _get_focus_card(cards: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {int(card["property_id"]): card for card in cards}
    focus_id = st.session_state.get("avm_global_focus_property_id") or st.session_state.get(FOCUS_KEY)
    if isinstance(focus_id, int) and focus_id in by_id:
        st.session_state[FOCUS_KEY] = int(focus_id)
        return by_id[focus_id]
    try:
        focus_id = int(focus_id)
    except (TypeError, ValueError):
        focus_id = None
    if focus_id in by_id:
        st.session_state[FOCUS_KEY] = int(focus_id)
        return by_id[focus_id]
    queues = _build_operating_queues(cards)
    default = queues["next_best_action"] or (cards[0] if cards else None)
    if default is None:
        raise ValueError("Decision Board Lab requires demo listings.")
    st.session_state[FOCUS_KEY] = int(default["property_id"])
    set_focus_property(int(default["property_id"]), source="Decision Board")
    return default


def _build_operating_queues(cards: list[dict[str, Any]]) -> dict[str, Any]:
    active_cards = [card for card in cards if card["status"] != "descartada"]
    blocked = [
        card
        for card in active_cards
        if card["risk"] == "alto" or (card["status"] in {"contactar", "negociar"} and card["risk"] == "medio")
    ]
    negotiations = [card for card in active_cards if card["status"] == "negociar"]
    opportunities = sorted(active_cards, key=lambda card: (card["score"], -_risk_weight(card["risk"])), reverse=True)
    next_best = (blocked or negotiations or opportunities)[0] if active_cards else None
    return {
        "next_best_action": next_best,
        "blocked_decisions": blocked[:4],
        "active_negotiations": negotiations[:4],
        "opportunities_queue": opportunities[:5],
    }


def _render_operating_hero(
    focus_card: dict[str, Any],
    queues: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    counts = summary["counts_by_status"]
    next_card = queues["next_best_action"] or focus_card
    st.markdown(
        f"""
        <div class="avm-decision-hero avm-lab-motion-reveal">
            <div>
                <div class="avm-decision-kicker">Decision cockpit</div>
                <h2>{html_escape(next_card["title"])}</h2>
                <p>{html_escape(next_card["next_action"])}</p>
                <div class="avm-evidence-chip-row">
                    {evidence_chip(next_card["status_label"], "premium")}
                    {evidence_chip(f"Score {next_card['score']:.1f}", "positive")}
                    {evidence_chip(f"Riesgo {next_card['risk']}", next_card["risk_tone"])}
                    {evidence_chip(next_card["comuna"], "neutral")}
                </div>
            </div>
            <div class="avm-decision-hero__side">
                <span>Foco activo</span>
                <strong>{format_uf(next_card["price_uf"])}</strong>
                <small>{html_escape(next_card["main_signal"])}</small>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    stat_cluster(
        [
            ("Pendientes", summary["pending_decisions"], "warning"),
            ("Bloqueadas", len(queues["blocked_decisions"]), "negative" if queues["blocked_decisions"] else "positive"),
            ("Negociaciones", counts["negociar"], "premium"),
            ("Favoritas", counts["favorita"], "positive"),
        ]
    )


def _render_quick_command_bar(focus_card: dict[str, Any]) -> None:
    property_id = int(focus_card["property_id"])
    st.markdown('<div class="avm-decision-command-label">Acciones rapidas sobre el foco activo</div>', unsafe_allow_html=True)
    cols = st.columns(5, gap="small")
    actions = [
        ("Propiedad", "Resumen"),
        ("Riesgo", "Riesgo"),
        ("Negociar", "Negociar"),
        ("Checklist", "Checklist"),
        ("Notas", "Notas"),
    ]
    for col, (label, panel) in zip(cols, actions, strict=False):
        if col.button(label, key=f"decision-command-{property_id}-{panel}", use_container_width=True):
            if panel == "Resumen":
                _open_property_experience(property_id)
            else:
                _set_focus(property_id, panel)


def _render_operating_queues(queues: dict[str, Any]) -> None:
    st.markdown("### Mesa operativa")
    _render_queue(
        "Next best action",
        [queues["next_best_action"]] if queues["next_best_action"] else [],
        "Sin accion principal pendiente.",
        default_panel="Resumen",
    )
    _render_queue(
        "Decisiones bloqueadas",
        queues["blocked_decisions"],
        "No hay bloqueos criticos en este momento.",
        default_panel="Riesgo",
    )
    _render_queue(
        "Negociaciones activas",
        queues["active_negotiations"],
        "Aun no hay propiedades en negociacion.",
        default_panel="Negociar",
    )
    _render_queue(
        "Oportunidades en cola",
        queues["opportunities_queue"],
        "Sin oportunidades demo disponibles.",
        default_panel="Resumen",
    )


def _render_queue(title: str, cards: list[dict[str, Any]], empty: str, *, default_panel: str) -> None:
    st.markdown(f'<div class="avm-decision-queue-title">{html_escape(title)}</div>', unsafe_allow_html=True)
    if not cards:
        st.caption(empty)
        return
    for card in cards:
        property_id = int(card["property_id"])
        st.markdown(
            f"""
            <div class="avm-decision-row">
                <div>
                    <strong>{html_escape(card["title"])}</strong>
                    <p>{html_escape(card["next_action"])}</p>
                    <small>{html_escape(card["comuna"])} / {format_uf(card["price_uf"])}</small>
                </div>
                <div>
                    {evidence_chip(f"{card['score']:.1f}", "positive")}
                    {evidence_chip(card["risk"], card["risk_tone"])}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        cols = st.columns([1, 1, 1], gap="small")
        if cols[0].button("Foco", key=f"decision-focus-{title}-{property_id}", use_container_width=True):
            _set_focus(property_id, default_panel)
        if cols[1].button("Riesgo", key=f"decision-risk-{title}-{property_id}", use_container_width=True):
            _set_focus(property_id, "Riesgo")
        if cols[2].button("Negociar", key=f"decision-offer-{title}-{property_id}", use_container_width=True):
            _set_focus(property_id, "Negociar")


def _render_state_map(
    cards: list[dict[str, Any]],
    board_state: dict[str, Any],
    portfolio_state: dict[str, Any],
) -> None:
    st.markdown("### Estado de decision")
    for status, label in DEMO_DECISION_BOARD_STATUSES.items():
        stage_cards = [card for card in cards if card["status"] == status]
        chips = "".join(evidence_chip(card["title"][:24], _status_tone(status)) for card in stage_cards[:4])
        st.markdown(
            f"""
            <div class="avm-decision-stage-row">
                <div><strong>{html_escape(label)}</strong><small>{len(stage_cards)} propiedades</small></div>
                <div class="avm-evidence-chip-row">{chips or evidence_chip("vacio", "neutral")}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    focus_id = int(st.session_state.get(FOCUS_KEY, cards[0]["property_id"]))
    focus_card = next(card for card in cards if int(card["property_id"]) == focus_id)
    _render_status_control(focus_card, board_state, portfolio_state, key_prefix="decision-map")


def _render_contextual_panel(
    focus_card: dict[str, Any],
    cards: list[dict[str, Any]],
    listings: list[dict[str, Any]],
    board_state: dict[str, Any],
    portfolio_state: dict[str, Any],
) -> None:
    property_id = int(focus_card["property_id"])
    current_panel = _normalize_panel(st.session_state.get(PANEL_KEY, "Resumen"))
    panel = st.segmented_control(
        "Panel contextual",
        PANEL_OPTIONS,
        default=current_panel,
        key=f"decision-panel-{property_id}",
        label_visibility="collapsed",
    ) or "Resumen"
    st.session_state[PANEL_KEY] = panel

    st.markdown(
        f"""
        <div class="avm-decision-context-title">
            <span>Foco activo</span>
            <strong>{html_escape(focus_card["title"])}</strong>
            <small>{html_escape(focus_card["status_label"])} / {html_escape(focus_card["comuna"])} / {format_uf(focus_card["price_uf"])}</small>
        </div>
        """,
        unsafe_allow_html=True,
    )

    risk_report = get_demo_risk_report(property_id, demo_mode=True)
    autofact_report = get_demo_autofact_report(property_id, demo_mode=True)

    if panel == "Resumen":
        _render_overview_panel(focus_card, board_state, portfolio_state, cards, listings)
    elif panel == "Riesgo":
        render_demo_risk_report(risk_report, expanded=False, key_suffix=f"decision-risk-{property_id}", use_expander=False)
    elif panel == "Negociar":
        _render_negotiation_panel(focus_card, risk_report)
    elif panel == "Checklist":
        render_demo_due_diligence_checklist(
            focus_card["listing"],
            risk_report=risk_report,
            autofact_report=autofact_report,
            expanded=False,
            key_prefix=f"decision-checklist-{property_id}",
            use_expander=False,
        )
    elif panel == "Notas":
        _render_notes_panel(focus_card, portfolio_state)

    render_lab_feedback_widget("decision_board", property_id=property_id, key_prefix=f"decision-context-feedback-{property_id}")


def _normalize_panel(value: Any) -> str:
    panel = str(value or "Resumen").strip()
    normalized = panel.casefold().replace("_", " ")
    mapped = PANEL_ALIASES.get(normalized, PANEL_ALIASES.get(panel, panel))
    return mapped if mapped in PANEL_OPTIONS else "Resumen"


def _render_overview_panel(
    focus_card: dict[str, Any],
    board_state: dict[str, Any],
    portfolio_state: dict[str, Any],
    cards: list[dict[str, Any]],
    listings: list[dict[str, Any]],
) -> None:
    listing = focus_card["listing"]
    property_id = int(focus_card["property_id"])
    insight_row(
        "Decision actual",
        focus_card["next_action"],
        value=focus_card["status_label"],
        tone="premium",
        priority="high",
    )
    stat_cluster(
        [
            ("Precio", format_uf(focus_card["price_uf"]), "neutral"),
            ("Score", f"{focus_card['score']:.1f}/100", "positive"),
            ("Riesgo", focus_card["risk"], focus_card["risk_tone"]),
            ("Dias mercado", listing.get("days_on_market", "-"), "warning"),
        ]
    )
    insight_row("Senal dominante", focus_card["main_signal"], value="accionable", tone="positive")
    _render_summary_mini_feeds(property_id, listings)
    _render_status_control(focus_card, board_state, portfolio_state, key_prefix="decision-overview")
    cols = st.columns(4, gap="small")
    panel_actions = [("Riesgo", "Riesgo"), ("Checklist", "Checklist"), ("Negociar", "Negociar"), ("Notas", "Notas")]
    for col, (label, panel) in zip(cols, panel_actions, strict=False):
        if col.button(label, key=f"decision-overview-action-{property_id}-{panel}", use_container_width=True):
            _set_focus(property_id, panel)
    _render_more_context_panel(focus_card, cards)


def _render_summary_mini_feeds(property_id: int, listings: list[dict[str, Any]]) -> None:
    alerts = [
        alert
        for alert in build_demo_alerts(listings, demo_mode=True)
        if alert.get("property_id") in {None, property_id}
    ][:2]
    activity = get_demo_property_activity(property_id, demo_mode=True)[:2]
    st.markdown("#### Movimientos recientes")
    if not alerts and not activity:
        st.caption("Sin movimientos demo recientes para esta propiedad.")
        return
    for alert in alerts:
        insight_row(
            alert["title"],
            alert["body"],
            value=alert["category"],
            tone=alert["severity"],
            priority="supporting",
        )
    for event in activity:
        insight_row(
            event["title"],
            event["description"],
            value=event["date"],
            tone=event.get("tone", "neutral"),
            priority="supporting",
        )


def _render_more_context_panel(focus_card: dict[str, Any], cards: list[dict[str, Any]]) -> None:
    property_id = int(focus_card["property_id"])
    market_context = get_demo_market_context(focus_card["comuna"], demo_mode=True)
    st.markdown("#### Más contexto")
    insight_row(
        "Mercado observado",
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
            ("Liquidez", f"{market_context.get('liquidity_score', '-')}/100", "premium"),
        ]
    )
    _render_compare_panel(property_id, cards)


def _render_status_control(
    focus_card: dict[str, Any],
    board_state: dict[str, Any],
    portfolio_state: dict[str, Any],
    *,
    key_prefix: str,
) -> None:
    property_id = int(focus_card["property_id"])
    current = str(focus_card["status"])
    labels = {label: status for status, label in DEMO_DECISION_BOARD_STATUSES.items()}
    current_label = DEMO_DECISION_BOARD_STATUSES.get(current, "Descubierta")
    selected = st.segmented_control(
        "Cambiar estado de decision",
        list(labels),
        default=current_label,
        key=f"{key_prefix}-status-{property_id}",
    )
    status = labels.get(str(selected), current)
    if status != current:
        move_demo_decision_property(board_state, property_id, status)
        record_lab_event(
            "moved_decision_card_demo",
            module="decision_board",
            property_id=property_id,
            metadata={"from": current, "to": status},
        )
        sync_decision_status_to_portfolio(status, portfolio_state, focus_card["listing"])
        st.success("Decision actualizada en el cockpit.")
        st.rerun()


def _render_alerts_panel(property_id: int, listings: list[dict[str, Any]]) -> None:
    alerts = [
        alert
        for alert in build_demo_alerts(listings, demo_mode=True)
        if alert.get("property_id") in {None, property_id}
    ][:8]
    if not alerts:
        st.caption("Sin alertas demo para esta propiedad.")
        return
    for alert in alerts:
        insight_row(
            alert["title"],
            alert["body"],
            value=alert["category"],
            tone=alert["severity"],
            priority="high" if alert["severity"] in {"negative", "warning"} else "supporting",
        )
        if st.button(alert["action_label"], key=f"decision-alert-action-{property_id}-{alert['id']}"):
            target = str(alert.get("action_target") or "")
            if "risk" in target or "autofact" in target:
                _set_focus(property_id, "Riesgo")
            else:
                _open_property_experience(property_id)


def _render_negotiation_panel(focus_card: dict[str, Any], risk_report: dict[str, Any]) -> None:
    property_id = int(focus_card["property_id"])
    negotiation_report = get_demo_negotiation_report(property_id, demo_mode=True)
    render_demo_negotiation_signals(negotiation_report, expanded=False, use_expander=False)
    strategies = ["conservadora", "moderada", "agresiva"]
    key = f"{STRATEGY_KEY}-{property_id}"
    selected = st.segmented_control(
        "Estrategia demo",
        strategies,
        default=st.session_state.get(key, negotiation_report.get("strategy", "moderada")),
        key=f"{key}-control",
    )
    st.session_state[key] = selected or "moderada"
    profile = st.selectbox(
        "Perfil comprador demo",
        ["primer_comprador", "inversionista_inicial", "familia_upgrade"],
        index=0,
        key=f"{PROFILE_KEY}-{property_id}",
    )
    render_demo_offer_simulator(
        focus_card["listing"],
        buyer_profile=profile,
        strategy=st.session_state[key],
        risk_report=risk_report,
        expanded=False,
        key_prefix=f"decision-offer-{property_id}",
        use_expander=False,
    )


def _render_compare_panel(property_id: int, cards: list[dict[str, Any]]) -> None:
    focus_ids = {int(card["property_id"]) for card in cards}
    for row in get_demo_property_comparison(property_id):
        compared_id = int(row["property_id"])
        insight_row(
            row["label"],
            f"Liquidez {row['liquidity_score']}/100, legal {row['legal_score']}/100, mercado {row['market_score']}/100.",
            value=row["fit"],
            tone="premium" if compared_id == property_id else "neutral",
        )
        cols = st.columns([1, 1], gap="small")
        if compared_id in focus_ids and cols[0].button("Usar como foco", key=f"decision-compare-focus-{property_id}-{compared_id}"):
            _set_focus(compared_id, "Resumen")
        if compared_id in focus_ids and cols[1].button("Abrir Riesgo", key=f"decision-compare-risk-{property_id}-{compared_id}"):
            _set_focus(compared_id, "Riesgo")


def _render_notes_panel(focus_card: dict[str, Any], portfolio_state: dict[str, Any]) -> None:
    property_id = int(focus_card["property_id"])
    items = portfolio_state.setdefault("items", {})
    if str(property_id) not in items:
        st.caption("Guarda la propiedad en el portafolio demo para asociar una nota local.")
        if st.button("Guardar y anotar", key=f"decision-save-for-note-{property_id}"):
            add_demo_property(portfolio_state, focus_card["listing"])
            st.rerun()
        return
    current_note = str(items[str(property_id)].get("note") or "")
    note = st.text_area(
        "Tesis de decision demo",
        value=current_note,
        placeholder="Ej: buena liquidez, pedir rebaja moderada y validar permisos antes de ofertar.",
        key=f"decision-note-{property_id}",
        height=140,
    )
    if st.button("Guardar nota demo", key=f"decision-note-save-{property_id}"):
        set_demo_property_note(portfolio_state, property_id, note)
        st.success("Nota demo guardada.")
        st.rerun()


def _set_focus(property_id: int, panel: str = "Resumen") -> None:
    st.session_state[FOCUS_KEY] = int(property_id)
    set_focus_property(property_id, source="Decision Board")
    st.session_state[PANEL_KEY] = _normalize_panel(panel)
    st.rerun()


def _open_property_experience(property_id: int) -> None:
    set_focus_property(property_id, source="Decision Board")
    st.session_state["property_experience_selected_id"] = int(property_id)
    st.session_state["property_experience_section"] = "Decisión"
    st.session_state["avm_lab_previous_page"] = "Decision Board Lab"
    st.session_state["avm_lab_nav_page"] = "Property Experience"
    st.session_state["avm_lab_nav_group"] = "market"
    st.rerun()


def _status_tone(status: str) -> str:
    if status == "descartada":
        return "neutral"
    if status == "favorita":
        return "positive"
    if status == "negociar":
        return "premium"
    if status == "contactar":
        return "warning"
    return "neutral"


def _risk_weight(risk: str) -> int:
    if risk == "alto":
        return 3
    if risk == "medio":
        return 2
    return 1


def _inject_decision_cockpit_styles() -> None:
    st.markdown(
        """
        <style>
        .avm-decision-hero {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 15rem;
            gap: 1rem;
            align-items: stretch;
            padding: 1.1rem;
            border-radius: 18px;
            background:
                radial-gradient(circle at 12% 0%, rgba(82, 113, 255, 0.18), transparent 32%),
                linear-gradient(135deg, rgba(255,255,255,0.08), rgba(255,255,255,0.025));
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: 0 22px 60px rgba(0,0,0,0.18);
            margin: 0.4rem 0 0.8rem;
        }
        .avm-decision-hero h2 {
            margin: 0.15rem 0 0.35rem;
            color: var(--avm-text);
            font-size: 1.55rem;
            line-height: 1.15;
        }
        .avm-decision-hero p {
            margin: 0 0 0.75rem;
            color: var(--avm-muted);
            max-width: 46rem;
        }
        .avm-decision-kicker,
        .avm-decision-command-label,
        .avm-decision-queue-title {
            color: var(--avm-muted);
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .avm-decision-command-label { margin: 0.9rem 0 0.35rem; }
        .avm-decision-queue-title { margin: 1rem 0 0.35rem; }
        .avm-decision-hero__side {
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 0.25rem;
            padding: 0.9rem;
            border-radius: 14px;
            background: rgba(255,255,255,0.055);
        }
        .avm-decision-hero__side span,
        .avm-decision-hero__side small {
            color: var(--avm-muted);
        }
        .avm-decision-hero__side strong {
            color: var(--avm-text);
            font-size: 1.45rem;
        }
        .avm-decision-row,
        .avm-decision-stage-row,
        .avm-decision-context-title {
            border-radius: 14px;
            background: rgba(255,255,255,0.045);
            border: 1px solid rgba(255,255,255,0.08);
            padding: 0.75rem;
            margin: 0.45rem 0;
        }
        .avm-decision-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.7rem;
            align-items: center;
        }
        .avm-decision-row strong,
        .avm-decision-stage-row strong,
        .avm-decision-context-title strong {
            color: var(--avm-text);
        }
        .avm-decision-row p {
            color: var(--avm-muted);
            margin: 0.18rem 0;
            font-size: 0.9rem;
        }
        .avm-decision-row small,
        .avm-decision-stage-row small,
        .avm-decision-context-title span,
        .avm-decision-context-title small {
            color: var(--avm-muted);
            display: block;
        }
        .avm-decision-stage-row {
            display: grid;
            grid-template-columns: 9rem minmax(0, 1fr);
            gap: 0.65rem;
            align-items: center;
        }
        .avm-decision-context-title {
            margin-top: 0.7rem;
        }
        @media (max-width: 760px) {
            .avm-decision-hero,
            .avm-decision-row,
            .avm-decision-stage-row {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
