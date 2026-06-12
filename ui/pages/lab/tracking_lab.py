# Product Lab only. No real data.
"""Portfolio/watchlist page backed by listing endpoints."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import streamlit as st

from ui.api_client import ApiClient
from ui.components.activity import render_demo_property_activity
from ui.components.alerts import render_demo_alert_list, render_demo_alert_summary
from ui.components.autofact import render_demo_autofact_report
from ui.components.decision_board import (
    render_demo_decision_property_control,
    render_demo_decision_summary,
)
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
from ui.demo_alerts import build_demo_alerts, ensure_demo_alert_state, with_demo_alert_read_state
from ui.demo_data import get_demo_listings, get_demo_portfolio
from ui.demo_decision_board import ensure_demo_decision_board_state, get_demo_decision_board_cards
from ui.demo_market import get_demo_market_context
from ui.demo_portfolio import (
    DEMO_PORTFOLIO_STATE_KEY,
    DEMO_PORTFOLIO_STATUSES,
    add_demo_property,
    add_demo_property_tag,
    calculate_demo_portfolio_metrics,
    ensure_demo_portfolio_state,
    get_saved_demo_portfolio,
    remove_demo_property,
    set_demo_property_favorite,
    set_demo_property_note,
    set_demo_property_status,
)
from ui.demo_providers import (
    get_demo_autofact_report,
    get_demo_negotiation_report,
    get_demo_owner_recommendations,
    get_demo_portal_presence,
    get_demo_price_history,
    get_demo_property_activity,
    get_demo_property_comparison,
    get_demo_risk_report,
)
from ui.feature_flags import (
    DEMO_ALERTS,
    DEMO_OWNER_RECOMMENDATIONS,
    DEMO_PORTAL_PRESENCE,
    DEMO_PRICE_HISTORY,
    DEMO_PROPERTY_COMPARISON,
    is_feature_enabled,
)
from ui.formatting import format_clp, format_uf
from ui.lab import LAB_DISCLAIMER
from ui.lab_focus import get_focused_demo_listing, set_focus_property


def render(client: ApiClient) -> None:
    section_header(
        "Portfolio Demo",
        "Watchlist simulada para guardar, comparar y decidir sobre propiedades demo.",
    )
    st.info(LAB_DISCLAIMER)
    render_focus_property_bar(get_focused_demo_listing())

    controls_col, premium_col = st.columns([1.45, 1], gap="large")
    with controls_col:
        st.slider("MÃ¡ximo de propiedades observadas", min_value=25, max_value=500, value=100, step=25)
    with premium_col:
        _render_premium_teasers(True)

    demo_catalog = get_demo_listings()
    demo_state = ensure_demo_portfolio_state(st.session_state, get_demo_portfolio())
    _render_demo_watchlist_controls(demo_state, demo_catalog)
    listings = get_saved_demo_portfolio(demo_state, demo_catalog)
    using_watchlist = True
    _render_demo_dashboard(listings)
    _render_demo_decision_board_preview(demo_catalog, demo_state)
    _render_demo_portfolio_alerts(demo_catalog, listings)
    st.success("Mostrando watchlist demo editable. Los cambios viven solo en esta sesion.")

    if not listings:
        _render_empty_portfolio()
        return

    _render_summary(listings)
    filters = _render_filters(listings)
    filtered = _filter_listings(listings, **filters)

    if not filtered:
        empty_state(
            "Sin propiedades para estos filtros",
            "Ajusta comuna, fuente, estado, precio o superficie para ampliar el mercado observado.",
        )
        return

    _render_portfolio_items(filtered, using_watchlist=using_watchlist, demo_mode=True)
    if is_feature_enabled(DEMO_OWNER_RECOMMENDATIONS):
        _render_demo_recommendations()
    if is_feature_enabled(DEMO_PROPERTY_COMPARISON):
        _render_demo_comparison()

def _render_summary(listings: list[dict[str, Any]]) -> None:
    comunas = {str(item.get("comuna")).strip() for item in listings if item.get("comuna")}
    prices = [_to_float(item.get("price_clp")) for item in listings]
    m2_values = [_to_float(item.get("m2")) for item in listings]
    source = _most_common(listings, "source")
    recent_count = _recent_count(listings)

    c1, c2, c3, c4 = st.columns(4, gap="medium")
    with c1:
        metric_card("Observadas", len(listings), caption="Propiedades disponibles", tone="premium")
    with c2:
        metric_card("Comunas", len(comunas), caption="Cobertura del mercado", tone="neutral")
    with c3:
        metric_card("Precio promedio", _format_clp(_average(prices)), caption="CLP sobre observadas", tone="neutral")
    with c4:
        metric_card(
            "Superficie promedio",
            _format_m2(_average(m2_values)),
            caption=f"Fuente principal: {source or '—'}",
            delta=_recent_delta(recent_count),
            tone="positive" if recent_count else "neutral",
        )


def _render_demo_watchlist_controls(state: dict[str, Any], catalog: list[dict[str, Any]]) -> None:
    saved_ids = {int(value["property_id"]) for value in state["items"].values()}
    available = [item for item in catalog if int(item["listing_id"]) not in saved_ids]
    with st.expander("Agregar propiedades demo", expanded=False):
        if not available:
            st.caption("Todas las propiedades demo estan guardadas en la watchlist.")
            return
        labels = {f"{item['title']} | UF {item['price_uf']:,.0f}".replace(",", "."): item for item in available}
        selected_label = st.selectbox("Propiedad demo", list(labels), key="demo_add_property_select")
        if st.button("Guardar en watchlist", type="primary", key="demo_add_property"):
            add_demo_property(state, labels[selected_label])
            set_focus_property(int(labels[selected_label]["listing_id"]), source="Portfolio Demo")
            record_lab_event(
                "saved_property_demo",
                module="decision_board",
                property_id=int(labels[selected_label]["listing_id"]),
            )
            st.success("Propiedad demo guardada en watchlist.")
            st.rerun()


def _render_demo_dashboard(listings: list[dict[str, Any]]) -> None:
    metrics = calculate_demo_portfolio_metrics(listings)
    st.subheader("Dashboard demo de portafolio")
    c1, c2, c3 = st.columns(3, gap="medium")
    with c1:
        metric_card("Guardadas", metrics["saved_count"], caption="Watchlist demo", tone="premium")
    with c2:
        metric_card(
            "Variacion total",
            _format_change_uf(metrics["total_change_uf"]),
            caption="Desde precio guardado",
            tone="positive" if metrics["total_change_uf"] < 0 else "warning" if metrics["total_change_uf"] > 0 else "neutral",
        )
    with c3:
        metric_card("Con rebaja", metrics["price_drop_count"], caption="Bajaron desde guardado", tone="positive")
    c4, c5, c6 = st.columns(3, gap="medium")
    with c4:
        metric_card("Alertas activas", metrics["active_alert_count"], caption="Simuladas", tone="warning")
    with c5:
        metric_card("Mayor exposicion", metrics["top_comuna"], caption="Comuna dominante", tone="neutral")
    with c6:
        metric_card("Mejor oportunidad", metrics["best_opportunity"], caption="Por score demo", tone="premium")


def _render_demo_portfolio_alerts(catalog: list[dict[str, Any]], listings: list[dict[str, Any]]) -> None:
    saved_ids = {int(item["listing_id"]) for item in listings}
    alerts = [
        alert
        for alert in build_demo_alerts(catalog, demo_mode=True)
        if alert.get("property_id") is None or int(alert["property_id"]) in saved_ids
    ]
    state = ensure_demo_alert_state(st.session_state, alerts)
    hydrated = with_demo_alert_read_state(alerts, state)
    by_id = {int(item["listing_id"]): item for item in catalog}
    with st.expander("Alertas Lab del portafolio", expanded=False):
        render_demo_alert_summary(hydrated)
        render_demo_alert_list(hydrated, state, by_id, key_prefix="portfolio-alerts", limit=4)


def _render_demo_decision_board_preview(catalog: list[dict[str, Any]], portfolio_state: dict[str, Any]) -> None:
    board_state = ensure_demo_decision_board_state(st.session_state, catalog, portfolio_state)
    cards = get_demo_decision_board_cards(catalog, board_state)
    with st.expander("Decision Board Lab", expanded=False):
        render_demo_decision_summary(cards)


def _render_filters(listings: list[dict[str, Any]]) -> dict[str, Any]:
    st.subheader("Explorar mercado observado")
    st.caption("Filtros locales sobre las propiedades cargadas.")

    source_options = ["Todas", *_unique_options(listings, "source")]
    status_options = ["Todos", *_unique_status_options(listings)]

    c1, c2, c3 = st.columns(3)
    comuna = c1.text_input("Comuna")
    source = c2.selectbox("Fuente", source_options)
    status = c3.selectbox("Estado", status_options)

    c4, c5, c6 = st.columns(3)
    max_price = c4.number_input("Precio máximo CLP", min_value=0, value=0, step=10_000_000)
    min_m2 = c5.number_input("m² mínimo", min_value=0.0, value=0.0, step=5.0)
    view = c6.radio("Vista", ["Cards", "Tabla"], horizontal=True, key="portfolio_view")

    return {
        "comuna": comuna,
        "source": None if source == "Todas" else source,
        "status": None if status == "Todos" else status,
        "max_price": max_price or None,
        "min_m2": min_m2 or None,
        "view": view,
    }


def _render_portfolio_items(
    listings: list[dict[str, Any]],
    *,
    using_watchlist: bool,
    demo_mode: bool,
) -> None:
    st.subheader("Propiedades en seguimiento")
    caption = (
        "Vista demo con alertas y movimientos simulados."
        if demo_mode
        else "Vista temporal basada en publicaciones disponibles. El guardado persistente llegará en una etapa premium."
    )
    st.caption(caption)

    if st.session_state.get("portfolio_view", "Cards") == "Tabla":
        _render_table(listings)
        return

    for index, item in enumerate(listings):
        _render_portfolio_card(item, index, using_watchlist, demo_mode)


def _render_portfolio_card(
    listing: dict[str, Any],
    index: int,
    using_watchlist: bool,
    demo_mode: bool,
) -> None:
    inject_theme()
    status = str(listing.get("demo_status") if demo_mode else _listing_status(listing) or "").lower()
    status_label, status_tone = _status_signal(status)
    date_label = _date_label(listing)
    movement = _movement_html(listing) if demo_mode and is_feature_enabled(DEMO_PRICE_HISTORY) else ""
    favorite = _badge_html("Favorita", "positive") if demo_mode and listing.get("favorite") else ""
    local_tags = "".join(_badge_html(str(tag), "premium") for tag in listing.get("local_tags", [])) if demo_mode else ""
    facts_html = (
        f"""
                {_fact_html("Precio al guardar", _format_uf(listing.get("saved_price_uf")), "Base demo")}
                {_fact_html("Precio actual", _format_uf(listing.get("price_uf")), "Valor publicado")}
                {_fact_html("Cambio UF", _format_change_uf(listing.get("change_uf")), _format_pct(listing.get("movement_pct")), str(listing.get("movement_tone") or "neutral"))}
                {_fact_html("Dias guardada", str(listing.get("days_since_saved", 0)), "Desde guardado demo")}
        """
        if demo_mode
        else f"""
                {_fact_html("Precio UF", _format_uf(listing.get("price_uf")), "Valor publicado")}
                {_fact_html("Precio CLP", _format_clp(listing.get("price_clp")), "Referencia local")}
                {_fact_html("Superficie", _format_m2(listing.get("m2")), "Tamaño activo")}
                {_fact_html("Detectada", date_label, "Fecha de captura")}
        """
    )

    st.markdown(
        f"""
        <div class="avm-card">
            <div style="display:flex; gap:0.75rem; justify-content:space-between; align-items:flex-start;">
                <div>
                    <div style="font-size:1.08rem; font-weight:750; color:var(--avm-text);">
                        {html_escape(_text(listing.get("title")))}
                    </div>
                    <div style="margin-top:0.25rem; color:var(--avm-muted); font-size:0.9rem;">
                        {html_escape(_text(listing.get("comuna")))} |
                        {html_escape(_format_m2(listing.get("m2")))} |
                        {html_escape(_rooms_label(listing))}
                    </div>
                </div>
                <div style="display:flex; gap:0.35rem; flex-wrap:wrap; justify-content:flex-end;">
                    {_badge_html(status_label, status_tone)}
                    {_badge_html(_text(listing.get("source")), "neutral")}
                    {movement}
                    {favorite}
                    {local_tags}
                </div>
            </div>
            <div style="display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:0.9rem; margin-top:1rem;">
                {facts_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if demo_mode and listing.get("note"):
        st.caption(f"Nota demo: {listing['note']}")
    if not demo_mode or is_feature_enabled(DEMO_ALERTS):
        _render_alerts(listing.get("alerts", []))
    if demo_mode and is_feature_enabled(DEMO_PORTAL_PRESENCE):
        _render_portal_presence_hint(_listing_id(listing))
    if demo_mode and is_feature_enabled(DEMO_PRICE_HISTORY):
        _render_price_history_hint(_listing_id(listing))
    if demo_mode:
        listing_id = _listing_id(listing)
        render_demo_market_context(
            get_demo_market_context(str(listing.get("comuna")), demo_mode=True),
            expanded=False,
        )
        render_demo_autofact_report(
            get_demo_autofact_report(_safe_int(listing_id), demo_mode=True),
            expanded=False,
            key_suffix=f"portfolio-card-{listing_id}-{index}",
        )
        render_demo_negotiation_signals(
            get_demo_negotiation_report(_safe_int(listing_id), demo_mode=True),
            expanded=False,
        )
        _render_brief_timeline(_safe_int(listing_id))
        render_demo_property_activity(
            get_demo_property_activity(_safe_int(listing_id), demo_mode=demo_mode),
            key=f"portfolio-activity-{listing_id}-{index}",
        )
        render_demo_risk_report(
            get_demo_risk_report(_safe_int(listing_id), demo_mode=True),
            expanded=False,
            key_suffix=f"portfolio-card-{listing_id}-{index}",
        )
        board_state = ensure_demo_decision_board_state(st.session_state, get_demo_listings(), st.session_state.get(DEMO_PORTFOLIO_STATE_KEY))
        render_demo_decision_property_control(
            listing,
            board_state,
            portfolio_state=st.session_state.get(DEMO_PORTFOLIO_STATE_KEY),
            key_prefix=f"portfolio-board-{listing_id}-{index}",
        )
        _render_demo_card_controls(listing, index)
        return

    action_col, alert_col, compare_col = st.columns([1, 1, 1], gap="small")
    if listing.get("url"):
        action_col.link_button("Abrir publicación", listing["url"])
    else:
        action_col.button("Sin enlace", disabled=True, key=f"no-url-track-{index}")
    alert_col.button("Alerta de precio", disabled=True, key=f"price-alert-{_listing_id(listing)}-{index}")
    compare_col.button(
        "Guardado" if using_watchlist else "Guardar en watchlist",
        disabled=True,
        key=f"save-watchlist-{_listing_id(listing)}-{index}",
    )


def _render_alerts(alerts: list[str]) -> None:
    if not alerts:
        return
    chips = " ".join(_badge_html(alert, "warning") for alert in alerts)
    st.markdown(f"<div style='margin:0.15rem 0 0.75rem 0;'>{chips}</div>", unsafe_allow_html=True)


def _render_brief_timeline(listing_id: int | None) -> None:
    events = get_demo_property_activity(listing_id, demo_mode=True)[:3]
    if not events:
        return
    st.caption("Timeline breve: " + " | ".join(f"{event['date']}: {event['title']}" for event in events))


def _render_demo_card_controls(listing: dict[str, Any], index: int) -> None:
    state = st.session_state.get(DEMO_PORTFOLIO_STATE_KEY)
    if not isinstance(state, dict):
        return
    property_id = int(_listing_id(listing))
    c1, c2, c3, c4 = st.columns([1, 1, 1.25, 1], gap="small")
    if c1.button("Quitar", key=f"demo-remove-{property_id}-{index}"):
        remove_demo_property(state, property_id)
        st.warning("Propiedad quitada de la watchlist demo.")
        st.rerun()
    favorite_label = "Quitar favorita" if listing.get("favorite") else "Marcar como favorita"
    if c2.button(favorite_label, key=f"demo-favorite-{property_id}-{index}"):
        set_demo_property_favorite(state, property_id, not bool(listing.get("favorite")))
        st.success("Favorito demo actualizado.")
        st.rerun()
    status_options = sorted(DEMO_PORTFOLIO_STATUSES)
    current_status = str(listing.get("demo_status") or "mirando")
    selected_status = c3.selectbox(
        "Cambiar estado",
        status_options,
        index=status_options.index(current_status) if current_status in status_options else 0,
        key=f"demo-status-select-{property_id}-{index}",
    )
    if c3.button("Aplicar estado", key=f"demo-status-apply-{property_id}-{index}"):
        set_demo_property_status(state, property_id, selected_status)
        set_focus_property(property_id, source="Portfolio Demo")
        st.success("Estado demo actualizado.")
        st.rerun()
    if c4.button("Fijar foco", key=f"demo-focus-{property_id}-{index}"):
        set_focus_property(property_id, source="Portfolio Demo")
        st.success("Propiedad fijada como foco del Lab.")
        st.rerun()

    with st.expander("Nota y tags demo", expanded=False):
        note = st.text_area("Nota local/demo", value=str(listing.get("note") or ""), key=f"demo-note-{property_id}-{index}")
        if st.button("Agregar nota", key=f"demo-note-save-{property_id}-{index}"):
            set_demo_property_note(state, property_id, note)
            st.success("Nota demo guardada.")
            st.rerun()
        tag_col, tag_action_col = st.columns([2, 1], gap="small")
        tag = tag_col.text_input("Tag local/demo", key=f"demo-tag-{property_id}-{index}")
        if tag_action_col.button("Agregar tag", key=f"demo-tag-save-{property_id}-{index}"):
            add_demo_property_tag(state, property_id, tag)
            st.success("Tag demo agregado.")
            st.rerun()


def _render_demo_recommendations() -> None:
    recs = get_demo_owner_recommendations()
    st.subheader("Recomendaciones demo")
    st.caption("Simulación de estrategias futuras. No es recomendación financiera real.")
    cols = st.columns(3, gap="medium")
    for col, item in zip(cols, recs, strict=False):
        with col:
            premium_feature_card(
                item["recommendation"].replace("_", " ").title(),
                item["rationale"],
                status=item["confidence"],
            )


def _render_portal_presence_hint(listing_id: Any) -> None:
    presence = get_demo_portal_presence(_safe_int(listing_id))
    active = sum(1 for item in presence if item["is_active"])
    st.caption(f"Demo portales: {active}/{len(presence)} activos en presencia simulada.")


def _render_price_history_hint(listing_id: Any) -> None:
    history = get_demo_price_history(_safe_int(listing_id))
    if history:
        st.caption(
            "Historial demo: "
            + " -> ".join(
                f"{item['date']}: UF {item['price_uf']:,.0f} ({item['event']})".replace(",", ".")
                for item in history
            )
        )


def _render_demo_comparison() -> None:
    st.subheader("Comparación demo")
    st.caption("Comparador simulado para preparar decisiones de portafolio.")
    rows = [
        {
            "Propiedad": item["label"],
            "Precio UF": _format_uf(item["price_uf"]),
            "Liquidez": item["liquidity_score"],
            "Legal": item["legal_score"],
            "Mercado": item["market_score"],
            "Fit": item["fit"],
        }
        for item in get_demo_property_comparison()
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    render_lab_feedback_widget("comparison", key_prefix="portfolio-comparison-feedback")


def _render_table(listings: list[dict[str, Any]]) -> None:
    rows = [
        {
            "ID": _listing_id(item),
            "Título": item.get("title"),
            "Comuna": item.get("comuna"),
            "Precio UF": _format_uf(item.get("price_uf")),
            "Precio CLP": _format_clp(item.get("price_clp")),
            "m²": _format_m2(item.get("m2")),
            "Dorm.": item.get("dormitorios"),
            "Baños": item.get("banos"),
            "Est.": item.get("estacionamientos"),
            "Fuente": item.get("source"),
            "Estado": _visible_status(item),
            "Detectada": _date_label(item),
            "URL": item.get("url"),
        }
        for item in listings
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_premium_teasers(demo_mode: bool) -> None:
    premium_feature_card(
        "Watchlist persistente",
        "Guarda propiedades y vuelve a ellas como activos observados.",
        status="demo" if demo_mode else "soon",
    )
    premium_feature_card(
        "Alertas de precio",
        "Recibe señales cuando una propiedad cambie de precio o vuelva a estar activa.",
        status="premium",
    )


def _render_empty_portfolio() -> None:
    empty_state(
        "Todavía no hay propiedades observadas",
        "Ejecuta los scrapers o carga datos para activar este portafolio temporal.",
        action_label="Cuando existan publicaciones, aparecerán como mercado observado.",
    )


def _filter_listings(
    listings: list[dict[str, Any]],
    *,
    comuna: str,
    source: str | None,
    status: str | None,
    max_price: int | None,
    min_m2: float | None,
    view: str,
) -> list[dict[str, Any]]:
    _ = view
    comuna_norm = comuna.strip().lower()
    result: list[dict[str, Any]] = []
    for item in listings:
        if comuna_norm and comuna_norm not in str(item.get("comuna", "")).lower():
            continue
        if source and item.get("source") != source:
            continue
        if status and _visible_status(item) != status:
            continue
        price = item.get("price_clp")
        if max_price is not None and isinstance(price, int | float) and price > max_price:
            continue
        m2 = item.get("m2")
        if min_m2 is not None and isinstance(m2, int | float) and m2 < min_m2:
            continue
        result.append(item)
    return result


def _status_signal(status: str) -> tuple[str, str]:
    if status == "mirando":
        return "Mirando", "neutral"
    if status == "contactar":
        return "Contactar", "warning"
    if status == "negociar":
        return "Negociar", "positive"
    if status == "descartada":
        return "Descartada", "negative"
    if status == "favorita":
        return "Favorita", "positive"
    if status == "active":
        return "Activa", "positive"
    if status in {"inactive", "closed", "sold"}:
        return "No activa", "warning"
    if status:
        return status.title(), "neutral"
    return "Estado por revisar", "neutral"


def _listing_id(listing: dict[str, Any]) -> Any:
    return listing.get("listing_id") or listing.get("id")


def _listing_status(listing: dict[str, Any]) -> Any:
    return listing.get("listing_status") or listing.get("status")


def _visible_status(listing: dict[str, Any]) -> Any:
    return listing.get("demo_status") or _listing_status(listing)


def _rooms_label(listing: dict[str, Any]) -> str:
    bedrooms = listing.get("dormitorios")
    bathrooms = listing.get("banos")
    parts = []
    if bedrooms is not None:
        parts.append(f"{bedrooms} dorm.")
    if bathrooms is not None:
        parts.append(f"{bathrooms} baños")
    return " | ".join(parts) if parts else "Programa no disponible"


def _date_label(listing: dict[str, Any]) -> str:
    raw = listing.get("captured_at") or listing.get("created_at")
    parsed = _parse_datetime(raw)
    if parsed is None:
        return "—"
    return parsed.strftime("%d-%m-%Y")


def _recent_count(listings: list[dict[str, Any]]) -> int:
    now = datetime.now()
    count = 0
    for item in listings:
        parsed = _parse_datetime(item.get("captured_at") or item.get("created_at"))
        if parsed is not None and (now - parsed.replace(tzinfo=None)).days <= 7:
            count += 1
    return count


def _recent_delta(count: int) -> str | None:
    if count <= 0:
        return None
    return f"{count} recientes"


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _unique_options(listings: list[dict[str, Any]], key: str) -> list[str]:
    return sorted({str(item.get(key)) for item in listings if item.get(key)})


def _unique_status_options(listings: list[dict[str, Any]]) -> list[str]:
    return sorted({str(_visible_status(item)) for item in listings if _visible_status(item)})


def _most_common(listings: list[dict[str, Any]], key: str) -> str | None:
    values = [str(item.get(key)) for item in listings if item.get(key)]
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def _average(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


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


def _movement_html(listing: dict[str, Any]) -> str:
    label = listing.get("movement_label")
    if not label:
        return ""
    return _badge_html(str(label), str(listing.get("movement_tone") or "neutral"))


def _format_uf(value: Any) -> str:
    return _clean_empty(format_uf(value))


def _format_clp(value: Any) -> str:
    return _clean_empty(format_clp(value))


def _format_m2(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "—"
    return f"{number:.1f} m²".replace(".", ",")


def _format_change_uf(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "UF 0"
    sign = "+" if number > 0 else ""
    return f"{sign}UF {number:,.0f}".replace(",", ".")


def _format_pct(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "0,0%"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.1f}%".replace(".", ",")


def _clean_empty(value: str) -> str:
    return "—" if value in {"\u00e2\u20ac\u201d", "—"} else value


def _text(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


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
