"""Modern Product Lab home dashboard."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient
from ui.components.feedback import record_lab_event
from ui.components.layout import section_header
from ui.components.theme import html_escape, inject_theme, tone_class
from ui.demo_dashboard import build_demo_dashboard
from ui.demo_data import get_demo_listings, get_demo_portfolio
from ui.demo_portfolio import (
    add_demo_property,
    ensure_demo_portfolio_state,
    get_saved_demo_portfolio,
    remove_demo_property,
)
from ui.lab import LAB_DISCLAIMER


def render(client: ApiClient) -> None:
    _ = client
    inject_theme()
    _inject_dashboard_styles()

    listings = get_demo_listings()
    state = ensure_demo_portfolio_state(st.session_state, get_demo_portfolio())
    saved_items = get_saved_demo_portfolio(state, listings)
    data = build_demo_dashboard(listings, saved_items)
    by_id = {int(item["listing_id"]): item for item in listings}

    section_header("Dashboard Lab", "Centro inmobiliario personal demo para decidir que mirar ahora.")
    st.caption(f"{LAB_DISCLAIMER} {data['disclaimer']}")
    _render_home_hero(data, by_id)
    _render_priority_sections(data, by_id, state)
    _render_progressive_reveal(data, by_id, state)


def _render_home_hero(data: dict[str, Any], by_id: dict[int, dict[str, Any]]) -> None:
    summary = data["summary"]
    best = summary["best_opportunity"]
    best_property = by_id.get(int(best["property_id"]), {})
    market_mood = data["modules"]["market_movers"][0]
    movement = _format_uf_delta(summary["total_variation_uf"])
    movement_tone = "positive" if int(summary["total_variation_uf"]) < 0 else "warning"
    active_opportunities = summary["active_opportunities"]
    recent_alerts = summary["recent_alerts"]
    st.markdown(
        f"""
        <div class="avm-lab-home-hero avm-lab-shimmer">
            <div>
                <div class="avm-lab-home-kicker"><span class="avm-lab-live-dot"></span>Que cambio hoy</div>
                <h1>{html_escape(best["title"])}</h1>
                <p>{html_escape(best["interpretation"])}</p>
                <div class="avm-lab-home-badges">
                    {_badge(best["value"], "premium")}
                    {_badge(f"{active_opportunities} oportunidades activas", "positive")}
                    {_badge(f"{recent_alerts} alertas", "warning")}
                </div>
            </div>
            <div class="avm-lab-home-side">
                <span>Portfolio demo</span>
                <strong>{html_escape(movement)}</strong>
                <small>{html_escape(str(summary["portfolio_saved"]))} guardadas / {html_escape(str(summary["observed_comunas"]))} comunas</small>
            </div>
        </div>
        <div class="avm-lab-home-context">
            {_context_tile("Market mood", market_mood["title"], market_mood["value"], market_mood["tone"])}
            {_context_tile("Oportunidad", str(best_property.get("comuna", "Demo")).title(), best["suggested_action"], "premium")}
            {_context_tile("Portfolio", movement, "Movimiento simulado desde guardado.", movement_tone)}
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns([0.22, 0.22, 0.22, 0.34], gap="small")
    if cols[0].button("Abrir oportunidad", type="primary", key="home-open-best"):
        _open_property(int(best["property_id"]))
    if cols[1].button("Ver alertas", key="home-open-alerts"):
        _open_lab_page("Alertas Lab")
    if cols[2].button("Portafolio", key="home-open-portfolio"):
        _open_lab_page("Portfolio Demo")
    cols[3].caption("Home Lab muestra datos simulados para explorar producto futuro.")


def _render_priority_sections(data: dict[str, Any], by_id: dict[int, dict[str, Any]], state: dict[str, Any]) -> None:
    modules = data["modules"]
    left, right = st.columns([0.62, 0.38], gap="large")
    with left:
        _section_label("Tus oportunidades", "Propiedades con mejor combinacion de descuento, score y accion posible.")
        _render_opportunity_stack(modules["opportunity_feed"][:3], by_id, state)
        _section_label("Actividad reciente", "Movimientos que cambian el orden de prioridad.")
        _render_live_feed(modules["watchlist_movers"][:3], by_id, module_key="watchlist")
    with right:
        _render_portfolio_summary(data["summary"], modules["portfolio_health"])
        _section_label("Alertas importantes", "Solo las alertas que piden accion.")
        _render_live_feed([*modules["alert_feed"][:2], *modules["risk_feed"][:2]], by_id, module_key="alert")
        _section_label("Mercado observado", "Comunas que explican el movimiento.")
        _render_market_mood(modules["market_movers"][:3])


def _render_progressive_reveal(data: dict[str, Any], by_id: dict[int, dict[str, Any]], state: dict[str, Any]) -> None:
    with st.expander("Ver detalle completo del Lab", expanded=False):
        _render_action_bar(state, by_id)
        modules = data["modules"]
        _section_label("Movers completos", "Todas las senales demo que alimentan la home.")
        _render_feed(modules["watchlist_movers"], by_id, state, module_key="watchlist-detail")
        _render_feed(modules["exposure_by_comuna"], by_id, state, allow_property_actions=False, module_key="exposure-detail")


def _render_action_bar(state: dict[str, Any], by_id: dict[int, dict[str, Any]]) -> None:
    saved_ids = {int(item["property_id"]) for item in state["items"].values()}
    available = [item for item_id, item in by_id.items() if item_id not in saved_ids]
    st.caption("Agregar propiedad al portafolio demo")
    if available:
        labels = {f"{item['title']} | UF {item['price_uf']:,.0f}".replace(",", "."): item for item in available}
        selected = st.selectbox("Propiedad demo", list(labels), key="dashboard-add-property")
        if st.button("Agregar al portafolio demo", key="dashboard-add-button"):
            add_demo_property(state, labels[selected])
            record_lab_event(
                "saved_property_demo",
                module="dashboard",
                property_id=int(labels[selected]["listing_id"]),
            )
            st.toast("Propiedad agregada al portafolio demo.")
            st.rerun()
    else:
        st.caption("Todas las propiedades demo ya estan guardadas.")


def _render_feed(
    items: list[dict[str, Any]],
    by_id: dict[int, dict[str, Any]],
    state: dict[str, Any],
    *,
    allow_property_actions: bool = True,
    module_key: str = "module",
) -> None:
    if not items:
        st.caption("Sin datos demo para este modulo.")
        return
    for index, item in enumerate(items):
        _render_feed_card(item, by_id, state, index, allow_property_actions=allow_property_actions, module_key=module_key)


def _render_feed_card(
    item: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
    state: dict[str, Any],
    index: int,
    *,
    allow_property_actions: bool,
    module_key: str,
) -> None:
    _render_signal_card(item, compact=False)
    property_id = item.get("property_id")
    if not allow_property_actions or property_id is None:
        return
    prop = by_id.get(int(property_id))
    if prop is None:
        return
    cols = st.columns([0.48, 0.52], gap="small")
    if cols[0].button("Abrir propiedad", key=f"dashboard-open-{property_id}-{module_key}-{index}"):
        _open_property(int(property_id))
    with cols[1]:
        _render_portfolio_toggle(state, prop, f"{module_key}-{index}")


def _render_opportunity_stack(items: list[dict[str, Any]], by_id: dict[int, dict[str, Any]], state: dict[str, Any]) -> None:
    for index, item in enumerate(items):
        _render_signal_card(item, compact=False)
        property_id = item.get("property_id")
        prop = by_id.get(int(property_id)) if property_id is not None else None
        if prop is None:
            continue
        cols = st.columns([0.42, 0.32, 0.26], gap="small")
        if cols[0].button("Abrir propiedad", key=f"home-opportunity-open-{property_id}-{index}"):
            _open_property(int(property_id))
        if cols[1].button("Guardar", key=f"home-opportunity-save-{property_id}-{index}"):
            add_demo_property(state, prop)
            record_lab_event("saved_property_demo", module="dashboard", property_id=int(property_id))
            st.toast("Propiedad guardada en watchlist demo.")
            st.rerun()
        cols[2].caption(str(prop.get("comuna", "Demo")).title())


def _render_live_feed(items: list[dict[str, Any]], by_id: dict[int, dict[str, Any]], *, module_key: str) -> None:
    for index, item in enumerate(items):
        _render_signal_card(item, compact=True)
        property_id = item.get("property_id")
        if property_id is not None and int(property_id) in by_id and st.button(
            "Abrir",
            key=f"home-feed-open-{module_key}-{property_id}-{index}",
        ):
            _open_property(int(property_id))


def _render_portfolio_summary(summary: dict[str, Any], health: dict[str, Any]) -> None:
    tone = "positive" if int(summary["total_variation_uf"]) < 0 else "warning"
    st.markdown(
        f"""
        <div class="avm-lab-portfolio-pulse">
            <div class="avm-lab-home-kicker">Resumen portfolio</div>
            <strong>{html_escape(str(summary["portfolio_saved"]))} propiedades guardadas</strong>
            <p>{html_escape(health["interpretation"])}</p>
            <div class="avm-lab-pulse-row">
                {_pill("Variacion", _format_uf_delta(summary["total_variation_uf"]), tone)}
                {_pill("Movers", str(summary["recent_movements"]), "premium")}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_market_mood(items: list[dict[str, Any]]) -> None:
    for item in items:
        st.markdown(
            f"""
            <div class="avm-lab-market-row">
                <div>
                    <strong>{html_escape(item["title"])}</strong>
                    <span>{html_escape(item["interpretation"])}</span>
                </div>
                {_badge(item["value"], item.get("tone"))}
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_signal_card(item: dict[str, Any], *, compact: bool) -> None:
    density = "avm-lab-feed-card--compact" if compact else ""
    st.markdown(
        f"""
        <div class="avm-lab-feed-card {density}">
            <div>
                <div class="avm-lab-feed-title">{html_escape(item["title"])}</div>
                <p>{html_escape(item["interpretation"])}</p>
                <small>{html_escape(item["suggested_action"])}</small>
            </div>
            {_badge(item["value"], item.get("tone"))}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _section_label(title: str, caption: str) -> None:
    st.markdown(
        f"""
        <div class="avm-lab-section-label">
            <h2>{html_escape(title)}</h2>
            <p>{html_escape(caption)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_portfolio_toggle(state: dict[str, Any], prop: dict[str, Any], key_suffix: str) -> None:
    property_id = int(prop["listing_id"])
    saved = str(property_id) in state["items"]
    if saved:
        if st.button("Quitar", key=f"dashboard-remove-{property_id}-{key_suffix}"):
            remove_demo_property(state, property_id)
            st.toast("Propiedad quitada del portafolio demo.")
            st.rerun()
    else:
        if st.button("Guardar", key=f"dashboard-save-{property_id}-{key_suffix}"):
            add_demo_property(state, prop)
            record_lab_event("saved_property_demo", module="dashboard", property_id=property_id)
            st.toast("Propiedad agregada al portafolio demo.")
            st.rerun()


def _open_property(property_id: int) -> None:
    st.session_state["property_experience_selected_id"] = property_id
    st.session_state["property_experience_section"] = "Resumen"
    _open_lab_page("Property Experience")


def _open_lab_page(page: str) -> None:
    st.session_state["avm_lab_previous_page"] = "Dashboard Lab"
    st.session_state["avm_lab_nav_page"] = page
    st.session_state["avm_lab_nav_group"] = {
        "Property Experience": "market",
        "Portfolio Demo": "portfolio",
        "Alertas Lab": "alerts",
    }.get(page, "dashboard")
    st.rerun()


def _context_tile(label: str, title: str, value: str, tone: str | None) -> str:
    return f"""
    <div class="avm-lab-context-tile avm-lab-shimmer">
        <span>{html_escape(label)}</span>
        <strong>{html_escape(title)}</strong>
        <small>{html_escape(value)}</small>
        {_badge("Activo", tone)}
    </div>
    """


def _pill(label: str, value: str, tone: str | None) -> str:
    return f"""
    <div class="avm-lab-pulse-pill">
        <span>{html_escape(label)}</span>
        <strong>{html_escape(value)}</strong>
        {_badge("Demo", tone)}
    </div>
    """


def _badge(label: str, tone: str | None) -> str:
    return f'<span class="avm-badge {tone_class("avm-badge", tone)}">{html_escape(label)}</span>'


def _format_uf_delta(value: Any) -> str:
    number = int(value or 0)
    sign = "+" if number > 0 else ""
    return f"{sign}UF {number:,}".replace(",", ".")


def _inject_dashboard_styles() -> None:
    st.markdown(
        """
        <style>
        .avm-lab-home-hero {
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(190px, 280px);
            gap: 1rem;
            border: 1px solid var(--avm-border);
            border-radius: 12px;
            background: var(--avm-hero-bg);
            box-shadow: var(--avm-shadow);
            padding: 1.15rem;
            margin: 0.45rem 0 0.85rem;
        }
        .avm-lab-home-hero.avm-lab-shimmer::after,
        .avm-lab-context-tile.avm-lab-shimmer::after {
            opacity: 0.18;
        }
        .avm-lab-home-kicker {
            color: var(--avm-premium);
            font-size: 0.72rem;
            font-weight: 820;
            text-transform: uppercase;
        }
        .avm-lab-home-hero h1 {
            color: var(--avm-text);
            font-size: 1.65rem;
            line-height: 1.12;
            margin: 0.18rem 0 0;
        }
        .avm-lab-home-hero p,
        .avm-lab-feed-card p,
        .avm-lab-section-label p,
        .avm-lab-portfolio-pulse p {
            color: var(--avm-muted);
            margin: 0.35rem 0 0;
        }
        .avm-lab-home-side,
        .avm-lab-context-tile,
        .avm-lab-feed-card,
        .avm-lab-portfolio-pulse,
        .avm-lab-market-row {
            border: 1px solid var(--avm-border);
            border-radius: 10px;
            background: var(--avm-surface);
            box-shadow: var(--avm-shadow);
        }
        .avm-lab-home-side {
            padding: 0.95rem;
        }
        .avm-lab-home-side span,
        .avm-lab-context-tile span,
        .avm-lab-pulse-pill span {
            color: var(--avm-muted);
            font-size: 0.78rem;
            font-weight: 650;
        }
        .avm-lab-home-side strong {
            display: block;
            color: var(--avm-text);
            font-size: 1.7rem;
            margin-top: 0.2rem;
        }
        .avm-lab-home-side small,
        .avm-lab-context-tile small,
        .avm-lab-feed-card small,
        .avm-lab-market-row span {
            color: var(--avm-muted);
            display: block;
            margin-top: 0.28rem;
        }
        .avm-lab-home-badges,
        .avm-lab-pulse-row {
            display: flex;
            gap: 0.42rem;
            flex-wrap: wrap;
            margin-top: 0.8rem;
        }
        .avm-lab-home-context {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.75rem;
            margin-bottom: 0.75rem;
        }
        .avm-lab-context-tile,
        .avm-lab-feed-card,
        .avm-lab-market-row,
        .avm-lab-portfolio-pulse {
            padding: 0.85rem;
            transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
        }
        .avm-lab-context-tile:hover,
        .avm-lab-feed-card:hover,
        .avm-lab-market-row:hover,
        .avm-lab-portfolio-pulse:hover {
            transform: translateY(-1px);
            border-color: var(--avm-border-strong, var(--avm-border));
            box-shadow: var(--avm-glow, var(--avm-shadow));
        }
        .avm-lab-context-tile strong,
        .avm-lab-feed-title,
        .avm-lab-market-row strong,
        .avm-lab-portfolio-pulse strong,
        .avm-lab-pulse-pill strong {
            color: var(--avm-text);
            display: block;
            font-weight: 800;
        }
        .avm-lab-section-label {
            margin: 1.05rem 0 0.45rem;
        }
        .avm-lab-section-label h2 {
            color: var(--avm-text);
            font-size: 1.05rem;
            margin: 0;
        }
        .avm-lab-feed-card {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.75rem;
            margin: 0.45rem 0;
        }
        .avm-lab-feed-card--compact {
            padding: 0.72rem;
        }
        .avm-lab-portfolio-pulse {
            margin-top: 1.05rem;
        }
        .avm-lab-pulse-pill {
            border: 1px solid var(--avm-border);
            border-radius: 10px;
            background: var(--avm-surface-alt);
            padding: 0.6rem;
            min-width: 9rem;
        }
        .avm-lab-market-row {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.75rem;
            margin: 0.45rem 0;
        }
        @media (max-width: 820px) {
            .avm-lab-home-hero,
            .avm-lab-home-context {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
