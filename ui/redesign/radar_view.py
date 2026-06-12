"""Neo Premium Dark Radar playground view."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiError
from ui.components.theme import html_escape
from ui.feature_flags import is_demo_mode
from ui.redesign.radar_adapter import (
    DATA_MODE_REAL,
    RADAR_STATUS_EMPTY,
    RADAR_STATUS_ERROR,
    RadarFilterCriteria,
    RadarFiltersViewModel,
    RadarHotZoneViewModel,
    RadarMapViewModel,
    RadarOpportunityViewModel,
    RadarRecentChangeViewModel,
    RadarSavedSearchViewModel,
    RadarScoreFactorViewModel,
    RadarTrendMetricViewModel,
    RadarViewModel,
    build_radar_view_model,
    get_radar_view_model,
)
from ui.redesign.tasar_playground import inject_tasar_playground_styles, render_html
from ui.state import get_token

FILTER_COMUNA_KEY = "tasar_pg_radar_comuna"
FILTER_PRICE_KEY = "tasar_pg_radar_price_range"
FILTER_TYPE_KEY = "tasar_pg_radar_property_type"
FILTER_BEDROOMS_KEY = "tasar_pg_radar_bedrooms"
FILTER_SCORE_KEY = "tasar_pg_radar_score"
FILTER_SORT_KEY = "tasar_pg_radar_sort"


def render(client: object | None = None) -> None:
    """Render the isolated Radar playground."""
    inject_tasar_playground_styles()
    inject_radar_styles()
    initial = _load_view_model(client, _criteria_from_state())
    render_hero(initial)
    criteria = render_filters(initial.filters, initial.criteria)
    view_model = _load_view_model(client, criteria, reload_backend=False, previous=initial)
    render_dashboard(view_model)
    render_score_footer(view_model)


def render_hero(view_model: RadarViewModel) -> None:
    summary = view_model.summary
    render_html(
        f"""
        <section class="avm-radar-hero">
            <div class="avm-radar-hero__copy">
                <div class="avm-radar-kicker">Radar de oportunidades &middot; {html_escape(_mode_label(view_model))}</div>
                <h1>Detectamos propiedades subvaloradas y monitoreamos el mercado por ti.</h1>
                <p>Explora oportunidades, senales de precio y movimientos del mercado inmobiliario en una vista experimental.</p>
                <div class="avm-radar-hero__metrics">
                    {_hero_metric("Oportunidades activas", str(summary.active_opportunities), _source_caption(view_model))}
                    {_hero_metric("Nuevas esta semana", f"+{summary.new_this_week}", _secondary_caption(view_model))}
                    {_hero_metric("Confianza promedio", f"{summary.average_confidence_pct}%", _source_caption(view_model))}
                    {_hero_metric("Precio prom. UF/m2", f"UF {summary.average_price_m2_uf:.1f}".replace(".", ","), _source_caption(view_model))}
                </div>
            </div>
            <div class="avm-radar-hero__visual" aria-hidden="true">
                <span></span><span></span><span></span><span></span>
                <i></i>
            </div>
        </section>
        """,
    )


def render_filters(filters: RadarFiltersViewModel, criteria: RadarFilterCriteria) -> RadarFilterCriteria:
    with st.container(border=True):
        cols = st.columns([1.05, 1.35, 1.05, 0.82, 1.0, 0.92], gap="small")
        with cols[0]:
            comuna = st.selectbox(
                "Comuna",
                filters.comunas,
                index=_option_index(filters.comunas, criteria.comuna),
                key=FILTER_COMUNA_KEY,
            )
        with cols[1]:
            price_range = st.slider(
                "Rango de precio UF",
                min_value=filters.price_min_uf,
                max_value=filters.price_max_uf,
                value=criteria.price_range_uf or filters.default_price_range_uf,
                step=250,
                key=FILTER_PRICE_KEY,
            )
        with cols[2]:
            property_type = st.selectbox(
                "Tipo de propiedad",
                filters.property_types,
                index=_option_index(filters.property_types, criteria.property_type),
                key=FILTER_TYPE_KEY,
                disabled=not filters.property_type_enabled,
            )
            if not filters.property_type_enabled:
                st.caption("Coming soon: no viene en /radar/opportunities.")
        with cols[3]:
            bedrooms_label = st.selectbox(
                "Dormitorios",
                filters.bedroom_options,
                index=_option_index(filters.bedroom_options, _bedrooms_label(criteria.bedrooms_min)),
                key=FILTER_BEDROOMS_KEY,
                disabled=not filters.bedrooms_enabled,
            )
            if not filters.bedrooms_enabled:
                st.caption("Coming soon")
        with cols[4]:
            min_score = st.slider(
                "Score minimo",
                min_value=0,
                max_value=100,
                value=criteria.min_score,
                step=5,
                key=FILTER_SCORE_KEY,
            )
        with cols[5]:
            sort_by = st.selectbox(
                "Ordenar por",
                tuple(key for key, _label in filters.sort_options),
                format_func=lambda key: dict(filters.sort_options).get(key, key),
                index=_sort_index(filters.sort_options, criteria.sort_by),
                key=FILTER_SORT_KEY,
            )

        action_cols = st.columns([1, 1, 4.8], gap="small")
        if action_cols[0].button("Mas filtros", key="tasar_pg_radar_more_filters"):
            st.info("Coming soon: filtros avanzados de liquidez, riesgo y microzona real.")
        action_cols[1].button(
            "Limpiar filtros",
            key="tasar_pg_radar_reset_filters",
            on_click=_reset_filter_state,
            args=(filters,),
        )
        action_cols[2].caption(_filters_caption(filters))

    return RadarFilterCriteria(
        comuna=str(comuna),
        price_range_uf=(int(price_range[0]), int(price_range[1])),
        property_type=str(property_type),
        bedrooms_min=_bedrooms_min(str(bedrooms_label)),
        min_score=int(min_score),
        sort_by=str(sort_by),
    )


def render_dashboard(view_model: RadarViewModel) -> None:
    render_opportunity_list(view_model)
    center, right = st.columns([1.7, 0.9], gap="medium", vertical_alignment="top")
    with center:
        render_map_panel(view_model.map)
    with right:
        render_right_panel(view_model)


def render_opportunity_list(view_model: RadarViewModel) -> None:
    render_html(
        f"""
        <div class="avm-radar-panel-title">
            <strong>{view_model.summary.filtered_count} oportunidades encontradas</strong>
            <span>{html_escape(_mode_label(view_model))}</span>
        </div>
        """,
    )
    if view_model.status == RADAR_STATUS_ERROR:
        render_html(
            f"""
            <div class="avm-radar-empty avm-radar-empty--error">
                <strong>No pudimos cargar oportunidades reales</strong>
                <p>{html_escape(view_model.error_message or "Backend Radar no disponible.")}</p>
            </div>
            """,
        )
        return
    if not view_model.opportunities:
        render_html(
            f"""
            <div class="avm-radar-empty">
                <strong>{html_escape(_empty_title(view_model))}</strong>
                <p>{html_escape(_empty_body(view_model))}</p>
            </div>
            """,
        )
        return
    cards_html = "".join(opportunity_card_html(item) for item in view_model.opportunities)
    render_html(f'<div class="avm-radar-opportunity-grid">{cards_html}</div>')
    if st.button("Ver mas oportunidades", key="tasar_pg_radar_more_opportunities"):
        st.info("Coming soon: paginacion y detalle conectable por bloques.")


def render_opportunity_card(item: RadarOpportunityViewModel) -> None:
    render_html(opportunity_card_html(item))


def opportunity_card_html(item: RadarOpportunityViewModel) -> str:
    return f"""
        <article class="avm-radar-opportunity">
            <div class="avm-radar-opportunity__top">
                <div class="avm-radar-opportunity__rank">{item.rank}</div>
                <div class="avm-radar-score">
                    <strong>{item.score}</strong>
                    <span>Score</span>
                </div>
            </div>
            <div class="avm-radar-opportunity__body">
                <div class="avm-radar-opportunity__head">
                    <div>
                        <strong>{html_escape(item.title)}</strong>
                        <p>{html_escape(item.comuna)} &middot; {html_escape(item.property_type)} &middot; {item.bedrooms}D / {item.bathrooms}B / {_format_m2(item.m2)}</p>
                    </div>
                    <div class="avm-radar-price">
                        <strong>{_format_uf(item.published_price_uf)}</strong>
                        <p>{_format_uf_m2(item.published_price_m2_uf)}</p>
                    </div>
                </div>
                <div class="avm-radar-opportunity__meta">
                    <span class="avm-radar-chip avm-radar-chip--positive">-{_format_pct(item.discount_pct)} bajo mercado</span>
                    <span class="avm-radar-chip avm-radar-chip--{html_escape(item.tone)}">UF {_format_number(item.savings_uf)} ahorro {_saving_caption(item)}</span>
                    <span class="avm-radar-chip">Estado: {html_escape(item.status_label)}</span>
                </div>
                <div class="avm-radar-opportunity__foot">
                    <span>Valor estimado: <b>{_format_uf(item.estimated_value_uf)}</b></span>
                    <span>Confianza: <b>{item.confidence_pct}%</b></span>
                    <span>{html_escape(_third_fact_label(item))}: <b>{html_escape(_third_fact_value(item))}</b></span>
                    {_publication_link(item)}
                    <span class="avm-radar-link">Ver detalle soon</span>
                    <span class="avm-radar-link">Comparar soon</span>
                </div>
            </div>
        </article>
        """


def render_map_panel(map_model: RadarMapViewModel) -> None:
    heat_html = "".join(
        f'<span class="avm-radar-heat" style="left:{zone.x_pct}%;top:{zone.y_pct}%;--intensity:{zone.intensity / 100:.2f}"></span>'
        for zone in map_model.heat_zones
    )
    pins_html = "".join(
        f'<span class="avm-radar-map-pin" style="left:{pin.x_pct}%;top:{pin.y_pct}%"><b>{pin.rank}</b></span>'
        for pin in map_model.pins
    )
    render_html(
        f"""
        <div class="avm-radar-map-card">
            <div class="avm-radar-panel-title">
                <strong>{html_escape(map_model.title)}</strong>
                <span>Mapa demo/lab</span>
            </div>
            <div class="avm-radar-map">
                <i class="avm-radar-map-grid"></i>
                {heat_html}
                {pins_html}
                <em class="avm-radar-map-label avm-radar-map-label--p">Providencia</em>
                <em class="avm-radar-map-label avm-radar-map-label--n">Nunoa</em>
                <em class="avm-radar-map-label avm-radar-map-label--l">Las Condes</em>
                <em class="avm-radar-map-label avm-radar-map-label--r">La Reina</em>
            </div>
            <div class="avm-radar-map-legend">
                <span>Baja</span><i></i><span>Alta</span>
                <strong>{html_escape(map_model.disclaimer)}</strong>
            </div>
        </div>
        """,
    )


def render_right_panel(view_model: RadarViewModel) -> None:
    render_market_summary(view_model.market_summary)
    render_hot_zones(view_model.hot_zones)
    render_recent_changes(view_model.recent_changes)
    render_saved_searches(view_model.saved_searches)


def render_market_summary(items: tuple[RadarTrendMetricViewModel, ...]) -> None:
    rows = "".join(
        f"""
        <div class="avm-radar-side-metric avm-radar-side-metric--{html_escape(item.tone)}">
            <div>
                <span>{html_escape(item.label)}</span>
                <strong>{html_escape(item.value)}</strong>
                <small>{html_escape(item.delta)} &middot; demo/lab</small>
            </div>
            {_sparkline_svg(item.trend)}
        </div>
        """
        for item in items
    )
    render_side_panel("Resumen de mercado", "12 meses / demo-lab", rows)


def render_hot_zones(items: tuple[RadarHotZoneViewModel, ...]) -> None:
    rows = "".join(
        f"""
        <div class="avm-radar-zone">
            <span>{item.rank}</span>
            <strong>{html_escape(item.name)}</strong>
            <b>{item.score}</b>
            {_sparkline_svg(item.trend)}
        </div>
        """
        for item in items
    )
    render_side_panel("Zonas calientes", "Score prom. simulado", rows)


def render_recent_changes(items: tuple[RadarRecentChangeViewModel, ...]) -> None:
    if not items:
        rows = """
        <div class="avm-radar-empty avm-radar-empty--compact">
            <strong>Sin alertas reales recientes</strong>
            <p>Cuando tus propiedades guardadas generen alertas, apareceran aqui.</p>
        </div>
        """
        render_side_panel("Alertas de tus guardados", "Backend real", rows)
        return
    rows = "".join(
        f"""
        <div class="avm-radar-change avm-radar-change--{html_escape(item.tone)}">
            <i></i>
            <div><strong>{html_escape(item.title)}</strong><p>{html_escape(item.detail)} &middot; {html_escape(item.source_state)}</p></div>
            <span>{html_escape(item.time)}</span>
        </div>
        """
        for item in items
    )
    source_state = items[0].source_state if items else "demo/lab"
    title = "Alertas de tus guardados" if source_state == "real" else "Cambios recientes"
    badge = "Backend real" if source_state == "real" else "Feed visual demo"
    render_side_panel(title, badge, rows)


def render_saved_searches(items: tuple[RadarSavedSearchViewModel, ...]) -> None:
    rows = "".join(
        f"""
        <div class="avm-radar-search">
            <i>A</i>
            <div><strong>{html_escape(item.name)}</strong><p>{item.results} resultados &middot; {html_escape(item.source_state)}</p></div>
            <span>{html_escape(item.state)}</span>
        </div>
        """
        for item in items
    )
    render_side_panel("Busquedas guardadas", "Coming soon", rows)


def render_side_panel(title: str, badge: str, body_html: str) -> None:
    render_html(
        f"""
        <section class="avm-radar-side-panel">
            <div class="avm-radar-panel-title">
                <strong>{html_escape(title)}</strong>
                <span>{html_escape(badge)}</span>
            </div>
            {body_html}
        </section>
        """,
    )


def render_score_footer(view_model: RadarViewModel) -> None:
    factors_html = "".join(_score_factor_html(item) for item in view_model.score_breakdown)
    render_html(
        f"""
        <section class="avm-radar-score-footer">
            <div class="avm-radar-score-explainer">
                <div class="avm-radar-panel-title">
                    <strong>Score de oportunidad: &iquest;Que significa?</strong>
                    <span>Demo/lab</span>
                </div>
                <div class="avm-radar-factor-grid">{factors_html}</div>
            </div>
            <div class="avm-radar-cta">
                <i></i>
                <strong>&iquest;Quieres profundizar?</strong>
                <p>Comparables, historial de precios e inteligencia local se conectaran por bloques.</p>
            </div>
        </section>
        """,
    )
    if st.button("Explorar comparables", key="tasar_pg_radar_compare_cta", type="primary"):
        st.info("Coming soon: comparables reales cuando conectemos esta vista al backend.")


def _score_factor_html(item: RadarScoreFactorViewModel) -> str:
    return f"""
    <div class="avm-radar-factor avm-radar-factor--{html_escape(item.tone)}">
        <span>{html_escape(item.state)}</span>
        <strong>{html_escape(item.label)}</strong>
        <b>{html_escape(item.value)}</b>
        <p>{html_escape(item.caption)}</p>
    </div>
    """


def _criteria_from_state() -> RadarFilterCriteria | None:
    if FILTER_COMUNA_KEY not in st.session_state:
        return None
    price_range = st.session_state.get(FILTER_PRICE_KEY)
    return RadarFilterCriteria(
        comuna=str(st.session_state.get(FILTER_COMUNA_KEY) or "Todas"),
        price_range_uf=_price_range_tuple(price_range),
        property_type=str(st.session_state.get(FILTER_TYPE_KEY) or "Todos"),
        bedrooms_min=_bedrooms_min(str(st.session_state.get(FILTER_BEDROOMS_KEY) or "Todos")),
        min_score=int(st.session_state.get(FILTER_SCORE_KEY) or 60),
        sort_by=str(st.session_state.get(FILTER_SORT_KEY) or "score_desc"),
    )


def _load_view_model(
    client: object | None,
    criteria: RadarFilterCriteria | None,
    *,
    reload_backend: bool = True,
    previous: RadarViewModel | None = None,
) -> RadarViewModel:
    if is_demo_mode():
        return build_radar_view_model(criteria)
    if not reload_backend and previous is not None and previous.data_mode == DATA_MODE_REAL:
        return get_radar_view_model(
            criteria,
            data_mode=DATA_MODE_REAL,
            radar_opportunities=_raw_opportunities_from_state(),
            alerts=_raw_alerts_from_state(),
            error_message=previous.error_message,
        )
    token = get_token()
    if token is None:
        return get_radar_view_model(
            criteria,
            data_mode=DATA_MODE_REAL,
            error_message="Inicia sesion para cargar oportunidades reales del Radar.",
        )
    try:
        opportunities = _call_radar_opportunities(client, token)
    except ApiError as exc:
        st.session_state["tasar_pg_radar_real_opportunities"] = []
        st.session_state["tasar_pg_radar_real_alerts"] = []
        return get_radar_view_model(
            criteria,
            data_mode=DATA_MODE_REAL,
            error_message=exc.message,
        )
    alerts = _call_alerts(client, token)
    st.session_state["tasar_pg_radar_real_opportunities"] = opportunities
    st.session_state["tasar_pg_radar_real_alerts"] = alerts
    return get_radar_view_model(
        criteria,
        data_mode=DATA_MODE_REAL,
        radar_opportunities=opportunities,
        alerts=alerts,
    )


def _call_radar_opportunities(client: object | None, token: str) -> list[dict[str, Any]]:
    if client is None or not hasattr(client, "get_radar_opportunities"):
        raise ApiError("Cliente API no disponible para cargar Radar real.")
    result = client.get_radar_opportunities(token=token, limit=100)
    return list(result or [])


def _call_alerts(client: object | None, token: str) -> list[dict[str, Any]]:
    if client is None or not hasattr(client, "get_alerts"):
        return []
    try:
        return list(client.get_alerts(token, limit=20) or [])
    except ApiError as exc:
        st.caption(f"No pudimos cargar alertas reales: {exc.message}")
        return []


def _raw_opportunities_from_state() -> list[dict[str, Any]]:
    value = st.session_state.get("tasar_pg_radar_real_opportunities")
    return list(value) if isinstance(value, list | tuple) else []


def _raw_alerts_from_state() -> list[dict[str, Any]]:
    value = st.session_state.get("tasar_pg_radar_real_alerts")
    return list(value) if isinstance(value, list | tuple) else []


def _reset_filter_state(filters: RadarFiltersViewModel) -> None:
    st.session_state[FILTER_COMUNA_KEY] = "Todas"
    st.session_state[FILTER_PRICE_KEY] = filters.default_price_range_uf
    st.session_state[FILTER_TYPE_KEY] = "Todos"
    st.session_state[FILTER_BEDROOMS_KEY] = "Todos"
    st.session_state[FILTER_SCORE_KEY] = filters.default_min_score
    st.session_state[FILTER_SORT_KEY] = "score_desc"


def _price_range_tuple(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, list | tuple) or len(value) != 2:
        return None
    return int(value[0]), int(value[1])


def _bedrooms_min(label: str) -> int | None:
    if label.endswith("+") and label[:-1].isdigit():
        return int(label[:-1])
    return None


def _bedrooms_label(value: int | None) -> str:
    return f"{value}+" if value else "Todos"


def _option_index(options: tuple[str, ...], value: str) -> int:
    return options.index(value) if value in options else 0


def _sort_index(options: tuple[tuple[str, str], ...], value: str) -> int:
    keys = [key for key, _label in options]
    return keys.index(value) if value in keys else 0


def _hero_metric(label: str, value: str, caption: str) -> str:
    return f"""
    <div>
        <span>{html_escape(label)}</span>
        <strong>{html_escape(value)}</strong>
        <p>{html_escape(caption)}</p>
    </div>
    """


def _mode_label(view_model: RadarViewModel) -> str:
    return "Real" if view_model.data_mode == DATA_MODE_REAL else "Demo/lab"


def _source_caption(view_model: RadarViewModel) -> str:
    return "Backend real" if view_model.data_mode == DATA_MODE_REAL else "Fixture demo/lab"


def _secondary_caption(view_model: RadarViewModel) -> str:
    if view_model.data_mode == DATA_MODE_REAL:
        return "Coming soon"
    return "Simulado"


def _filters_caption(filters: RadarFiltersViewModel) -> str:
    if filters.is_demo:
        return "Filtros aplicados solo sobre fixtures demo/lab; no consultan backend."
    return "Filtros client-side sobre oportunidades reales ya cargadas del backend."


def _empty_title(view_model: RadarViewModel) -> str:
    if view_model.data_mode == DATA_MODE_REAL and view_model.status == RADAR_STATUS_EMPTY:
        return "Sin oportunidades reales por ahora"
    return "Sin oportunidades para estos filtros"


def _empty_body(view_model: RadarViewModel) -> str:
    if view_model.data_mode == DATA_MODE_REAL and view_model.status == RADAR_STATUS_EMPTY:
        return "El backend respondio sin oportunidades. No se muestran fixtures demo en modo real."
    if view_model.data_mode == DATA_MODE_REAL:
        return "Ajusta comuna, rango de precio o score minimo sobre las oportunidades reales cargadas."
    return "Ajusta comuna, rango de precio o score minimo. Estado demo/lab."


def _saving_caption(item: RadarOpportunityViewModel) -> str:
    return "demo" if item.is_demo else "estimado"


def _third_fact_label(item: RadarOpportunityViewModel) -> str:
    return "Tiempo" if item.is_demo else "Comparables"


def _third_fact_value(item: RadarOpportunityViewModel) -> str:
    return f"{item.days_on_market} dias" if item.is_demo else "ver reporte"


def _publication_link(item: RadarOpportunityViewModel) -> str:
    if not item.url:
        return '<span class="avm-radar-link">Sin publicacion</span>'
    return (
        f'<a class="avm-radar-link" href="{html_escape(item.url)}" '
        'target="_blank" rel="noreferrer">Ver publicacion</a>'
    )


def _format_uf(value: float) -> str:
    return f"UF {_format_number(value)}"


def _format_uf_m2(value: float) -> str:
    return f"UF {value:.1f}/m2".replace(".", ",")


def _format_m2(value: float) -> str:
    return f"{value:.0f} m2"


def _format_pct(value: float) -> str:
    return f"{value:.1f}%".replace(".", ",")


def _format_number(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _sparkline_svg(values: tuple[int, ...]) -> str:
    if len(values) < 2:
        return '<svg class="avm-radar-spark" viewBox="0 0 92 34" aria-hidden="true"></svg>'
    min_value = min(values)
    max_value = max(values)
    span = max(max_value - min_value, 1)
    points: list[str] = []
    for index, value in enumerate(values):
        x = index / (len(values) - 1) * 88 + 2
        y = 30 - ((value - min_value) / span * 24)
        points.append(f"{x:.1f},{y:.1f}")
    points_value = " ".join(points)
    return (
        '<svg class="avm-radar-spark" viewBox="0 0 92 34" aria-hidden="true">'
        f'<polyline points="{points_value}" fill="none" stroke="currentColor" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round" />'
        "</svg>"
    )


def inject_radar_styles() -> None:
    render_html(
        """
        <style>
        .avm-radar-hero {
            position: relative;
            overflow: hidden;
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(20rem, 0.58fr);
            gap: 1.1rem;
            min-height: 12.6rem;
            border: 1px solid var(--avm-neo-border-strong);
            border-radius: 8px;
            background:
                radial-gradient(circle at 83% 42%, rgba(139, 53, 255, 0.32), transparent 27%),
                radial-gradient(circle at 70% 38%, rgba(23, 199, 255, 0.22), transparent 30%),
                linear-gradient(92deg, rgba(4, 18, 37, 0.99) 0%, rgba(5, 17, 34, 0.96) 49%, rgba(35, 16, 78, 0.9) 100%);
            box-shadow: var(--avm-neo-shadow), var(--avm-neo-inset);
            padding: 1.28rem 1.5rem;
            margin-bottom: 0.66rem;
        }

        .avm-radar-hero__copy {
            position: relative;
            z-index: 2;
        }

        .avm-radar-kicker {
            color: var(--avm-neo-cyan);
            font-size: 0.7rem;
            font-weight: 850;
            text-transform: uppercase;
        }

        .avm-radar-hero h1 {
            max-width: 48rem;
            color: #ffffff;
            font-size: 1.72rem;
            line-height: 1.08;
            letter-spacing: 0;
            margin: 0.44rem 0 0;
        }

        .avm-radar-hero p {
            max-width: 44rem;
            color: var(--avm-neo-soft);
            font-size: 0.84rem;
            line-height: 1.42;
            margin: 0.58rem 0 0;
        }

        .avm-radar-hero__metrics {
            display: grid;
            grid-template-columns: repeat(4, minmax(7rem, 1fr));
            gap: 0.42rem;
            margin-top: 0.92rem;
            max-width: 52rem;
        }

        .avm-radar-hero__metrics div,
        .avm-radar-side-panel,
        .avm-radar-map-card,
        .avm-radar-score-explainer,
        .avm-radar-cta,
        .avm-radar-empty {
            border: 1px solid rgba(66, 132, 191, 0.2);
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(10, 24, 44, 0.82), rgba(5, 13, 26, 0.86));
            box-shadow: var(--avm-neo-inset);
        }

        .avm-radar-hero__metrics div {
            padding: 0.48rem 0.58rem;
        }

        .avm-radar-hero__metrics span,
        .avm-radar-panel-title span,
        .avm-radar-factor span {
            color: var(--avm-neo-cyan);
            display: block;
            font-size: 0.64rem;
            font-weight: 850;
            text-transform: uppercase;
        }

        .avm-radar-hero__metrics strong {
            color: #ffffff;
            display: block;
            font-size: 1rem;
            margin-top: 0.12rem;
        }

        .avm-radar-hero__metrics p {
            color: var(--avm-neo-muted);
            font-size: 0.66rem;
            margin: 0.08rem 0 0;
        }

        .avm-radar-hero__visual {
            position: absolute;
            inset: 0 0 0 auto;
            width: 52%;
            opacity: 0.92;
        }

        .avm-radar-hero__visual::before,
        .avm-radar-hero__visual::after {
            content: "";
            position: absolute;
            right: 8%;
            top: 50%;
            width: 22rem;
            height: 22rem;
            border: 1px solid rgba(139, 53, 255, 0.38);
            border-radius: 50%;
            transform: translateY(-50%) rotateX(68deg);
            box-shadow: 0 0 42px rgba(139, 53, 255, 0.16), inset 0 0 24px rgba(23, 199, 255, 0.12);
        }

        .avm-radar-hero__visual::after {
            width: 14rem;
            height: 14rem;
            right: 17%;
            border-color: rgba(23, 199, 255, 0.42);
        }

        .avm-radar-hero__visual span {
            position: absolute;
            width: 0.48rem;
            height: 0.48rem;
            border-radius: 999px;
            background: #ffffff;
            box-shadow: 0 0 18px var(--avm-neo-cyan);
        }

        .avm-radar-hero__visual span:nth-child(1) { right: 24%; top: 25%; }
        .avm-radar-hero__visual span:nth-child(2) { right: 9%; top: 47%; }
        .avm-radar-hero__visual span:nth-child(3) { right: 33%; top: 69%; }
        .avm-radar-hero__visual span:nth-child(4) { right: 43%; top: 36%; }

        .avm-radar-hero__visual i {
            position: absolute;
            right: 5%;
            bottom: 0;
            width: 92%;
            height: 44%;
            background:
                linear-gradient(180deg, transparent 0%, rgba(23, 199, 255, 0.12) 100%),
                repeating-linear-gradient(90deg, rgba(94, 165, 255, 0.22) 0 1px, transparent 1px 2rem);
            clip-path: polygon(0 78%, 8% 72%, 8% 48%, 14% 48%, 14% 66%, 22% 60%, 22% 34%, 29% 34%, 29% 62%, 39% 54%, 39% 20%, 47% 20%, 47% 62%, 59% 50%, 59% 31%, 66% 31%, 66% 68%, 77% 58%, 77% 39%, 85% 39%, 85% 72%, 100% 58%, 100% 100%, 0 100%);
        }

        .avm-radar-panel-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.6rem;
            margin: 0.04rem 0 0.52rem;
        }

        .avm-radar-panel-title strong {
            color: var(--avm-neo-text);
            font-size: 0.86rem;
            font-weight: 850;
        }

        .avm-radar-panel-title span {
            border: 1px solid rgba(139, 53, 255, 0.34);
            border-radius: 999px;
            background: rgba(71, 29, 129, 0.22);
            color: #caa9ff;
            padding: 0.18rem 0.46rem;
            white-space: nowrap;
        }

        .avm-radar-opportunity-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.58rem;
            margin-bottom: 0.7rem;
        }

        .avm-radar-opportunity {
            position: relative;
            display: flex;
            flex-direction: column;
            gap: 0.48rem;
            border: 1px solid rgba(66, 132, 191, 0.2);
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(10, 23, 42, 0.92), rgba(5, 13, 26, 0.94));
            box-shadow: var(--avm-neo-inset);
            min-height: 12.1rem;
            min-width: 0;
            padding: 0.62rem;
        }

        .avm-radar-opportunity__top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
        }

        .avm-radar-opportunity__rank {
            width: 1.24rem;
            height: 1.24rem;
            display: grid;
            place-items: center;
            border-radius: 999px;
            color: #ffffff;
            background: linear-gradient(135deg, var(--avm-neo-blue), var(--avm-neo-purple));
            font-size: 0.7rem;
            font-weight: 900;
        }

        .avm-radar-thumb {
            position: relative;
            overflow: hidden;
            height: 4.5rem;
            border: 1px solid rgba(91, 156, 216, 0.24);
            border-radius: 7px;
            background:
                linear-gradient(135deg, rgba(255, 255, 255, 0.2), transparent 32%),
                linear-gradient(160deg, rgba(28, 138, 255, 0.42), rgba(8, 19, 34, 0.9));
        }

        .avm-radar-thumb--purple,
        .avm-radar-thumb--violet {
            background:
                linear-gradient(135deg, rgba(255, 255, 255, 0.18), transparent 32%),
                linear-gradient(160deg, rgba(139, 53, 255, 0.42), rgba(8, 19, 34, 0.9));
        }

        .avm-radar-thumb--teal {
            background:
                linear-gradient(135deg, rgba(255, 255, 255, 0.18), transparent 32%),
                linear-gradient(160deg, rgba(35, 196, 157, 0.38), rgba(8, 19, 34, 0.9));
        }

        .avm-radar-thumb--amber {
            background:
                linear-gradient(135deg, rgba(255, 255, 255, 0.18), transparent 32%),
                linear-gradient(160deg, rgba(247, 169, 40, 0.34), rgba(8, 19, 34, 0.9));
        }

        .avm-radar-thumb span {
            position: absolute;
            bottom: 0.34rem;
            width: 0.72rem;
            border: 1px solid rgba(255, 255, 255, 0.28);
            border-bottom: 0;
            background: rgba(255, 255, 255, 0.12);
        }

        .avm-radar-thumb span:nth-child(1) { left: 1rem; height: 2.7rem; }
        .avm-radar-thumb span:nth-child(2) { left: 2rem; height: 3.5rem; }
        .avm-radar-thumb span:nth-child(3) { left: 3rem; height: 2.25rem; }

        .avm-radar-opportunity__body {
            display: flex;
            flex: 1 1 auto;
            flex-direction: column;
            min-width: 0;
        }

        .avm-radar-opportunity__head,
        .avm-radar-opportunity__foot,
        .avm-radar-opportunity__meta {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.4rem;
            min-width: 0;
        }

        .avm-radar-opportunity__head strong {
            color: #ffffff;
            display: block;
            font-size: 0.82rem;
            line-height: 1.18;
        }

        .avm-radar-opportunity__head p,
        .avm-radar-price p,
        .avm-radar-opportunity__foot span {
            color: var(--avm-neo-muted);
            font-size: 0.68rem;
            line-height: 1.28;
            margin: 0.12rem 0 0;
        }

        .avm-radar-price {
            flex: 0 0 auto;
            min-width: 4.9rem;
            text-align: right;
        }

        .avm-radar-price strong {
            color: #ffffff;
        }

        .avm-radar-opportunity__meta {
            justify-content: flex-start;
            flex-wrap: wrap;
            margin-top: 0.42rem;
        }

        .avm-radar-chip,
        .avm-radar-link {
            border: 1px solid rgba(66, 132, 191, 0.18);
            border-radius: 999px;
            background: rgba(13, 30, 53, 0.72);
            color: var(--avm-neo-soft);
            font-size: 0.63rem;
            font-weight: 800;
            padding: 0.18rem 0.42rem;
            white-space: nowrap;
        }

        .avm-radar-chip--positive {
            color: var(--avm-neo-green);
            background: rgba(56, 217, 145, 0.1);
            border-color: rgba(56, 217, 145, 0.24);
        }

        .avm-radar-chip--warning {
            color: var(--avm-neo-amber);
            background: rgba(247, 169, 40, 0.1);
            border-color: rgba(247, 169, 40, 0.22);
        }

        .avm-radar-opportunity__foot {
            justify-content: flex-start;
            flex-wrap: wrap;
            margin-top: auto;
            padding-top: 0.5rem;
        }

        .avm-radar-opportunity__foot b {
            color: var(--avm-neo-soft);
        }

        .avm-radar-link {
            color: #caa9ff;
            border-color: rgba(139, 53, 255, 0.28);
            background: rgba(71, 29, 129, 0.16);
        }

        .avm-radar-score {
            width: 2.74rem;
            height: 2.74rem;
            display: grid;
            place-items: center;
            align-content: center;
            border-radius: 999px;
            background:
                radial-gradient(circle, rgba(8, 18, 34, 0.98) 0 54%, transparent 55%),
                conic-gradient(var(--avm-neo-green) 0 86%, rgba(48, 76, 111, 0.72) 86% 100%);
            color: #ffffff;
        }

        .avm-radar-score strong {
            font-size: 0.86rem;
            line-height: 1;
        }

        .avm-radar-score span {
            color: var(--avm-neo-green);
            font-size: 0.52rem;
            font-weight: 850;
            text-transform: uppercase;
        }

        .avm-radar-map-card,
        .avm-radar-side-panel,
        .avm-radar-score-explainer,
        .avm-radar-cta,
        .avm-radar-empty {
            padding: 0.72rem;
            margin-bottom: 0.62rem;
        }

        .avm-radar-map {
            position: relative;
            min-height: 29.6rem;
            overflow: hidden;
            border: 1px solid rgba(66, 132, 191, 0.22);
            border-radius: 8px;
            background:
                radial-gradient(circle at 44% 54%, rgba(23, 199, 255, 0.15), transparent 18%),
                linear-gradient(135deg, rgba(11, 25, 46, 0.96), rgba(5, 13, 26, 0.98));
        }

        .avm-radar-map-grid {
            position: absolute;
            inset: -18%;
            background:
                linear-gradient(rgba(105, 153, 204, 0.08) 1px, transparent 1px),
                linear-gradient(90deg, rgba(105, 153, 204, 0.08) 1px, transparent 1px);
            background-size: 26px 26px;
            transform: rotate(-14deg);
        }

        .avm-radar-map-grid::after {
            content: "";
            position: absolute;
            inset: 12% 7%;
            border: 1px solid rgba(97, 170, 255, 0.12);
            border-radius: 42% 58% 50% 50%;
            box-shadow: inset 0 0 0 1.4rem rgba(23, 199, 255, 0.025);
        }

        .avm-radar-heat {
            position: absolute;
            width: calc(7.8rem + 5rem * var(--intensity));
            height: calc(7.8rem + 5rem * var(--intensity));
            transform: translate(-50%, -50%);
            border-radius: 999px;
            background:
                radial-gradient(circle, rgba(255, 78, 96, 0.55) 0 9%, rgba(247, 169, 40, 0.5) 10% 20%, rgba(70, 255, 151, 0.26) 21% 40%, rgba(23, 199, 255, 0.08) 41% 64%, transparent 65%);
            filter: blur(1px);
            mix-blend-mode: screen;
        }

        .avm-radar-map-pin {
            position: absolute;
            width: 1.85rem;
            height: 1.85rem;
            display: grid;
            place-items: center;
            transform: translate(-50%, -50%);
            border-radius: 999px 999px 999px 0;
            background: linear-gradient(135deg, var(--avm-neo-purple), var(--avm-neo-blue));
            border: 1px solid rgba(255, 255, 255, 0.32);
            box-shadow: 0 0 22px rgba(139, 53, 255, 0.46);
            color: #ffffff;
            rotate: -45deg;
            z-index: 2;
        }

        .avm-radar-map-pin b {
            rotate: 45deg;
            font-size: 0.76rem;
        }

        .avm-radar-map-label {
            position: absolute;
            color: rgba(229, 239, 255, 0.82);
            font-size: 0.8rem;
            font-style: normal;
            font-weight: 760;
            text-shadow: 0 2px 10px rgba(0, 0, 0, 0.7);
        }

        .avm-radar-map-label--p { left: 34%; top: 49%; }
        .avm-radar-map-label--n { left: 49%; top: 72%; }
        .avm-radar-map-label--l { left: 62%; top: 35%; }
        .avm-radar-map-label--r { left: 68%; top: 55%; }

        .avm-radar-map-legend {
            display: grid;
            grid-template-columns: auto minmax(8rem, 1fr) auto;
            gap: 0.42rem;
            align-items: center;
            color: var(--avm-neo-muted);
            font-size: 0.68rem;
            margin-top: 0.52rem;
        }

        .avm-radar-map-legend i {
            height: 0.44rem;
            border-radius: 999px;
            background: linear-gradient(90deg, var(--avm-neo-purple), var(--avm-neo-cyan), #71ff69, var(--avm-neo-amber), var(--avm-neo-red));
        }

        .avm-radar-map-legend strong {
            grid-column: 1 / -1;
            color: var(--avm-neo-muted);
            font-weight: 700;
        }

        .avm-radar-side-panel {
            min-width: 0;
        }

        .avm-radar-side-metric,
        .avm-radar-zone,
        .avm-radar-change,
        .avm-radar-search {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 5.2rem;
            gap: 0.5rem;
            align-items: center;
            border-top: 1px solid rgba(66, 132, 191, 0.13);
            padding: 0.48rem 0;
        }

        .avm-radar-side-metric:first-of-type,
        .avm-radar-zone:first-of-type,
        .avm-radar-change:first-of-type,
        .avm-radar-search:first-of-type {
            border-top: 0;
            padding-top: 0;
        }

        .avm-radar-side-metric span,
        .avm-radar-side-metric small,
        .avm-radar-change p,
        .avm-radar-search p {
            color: var(--avm-neo-muted);
            display: block;
            font-size: 0.66rem;
            line-height: 1.24;
            margin: 0.08rem 0 0;
        }

        .avm-radar-side-metric strong,
        .avm-radar-zone strong,
        .avm-radar-change strong,
        .avm-radar-search strong {
            color: #ffffff;
            display: block;
            font-size: 0.78rem;
            line-height: 1.18;
        }

        .avm-radar-side-metric--positive small {
            color: var(--avm-neo-green);
        }

        .avm-radar-side-metric--negative small {
            color: var(--avm-neo-red);
        }

        .avm-radar-spark {
            width: 100%;
            height: 2.2rem;
            color: #9a68ff;
            filter: drop-shadow(0 0 8px rgba(139, 53, 255, 0.45));
        }

        .avm-radar-zone {
            grid-template-columns: 1.2rem minmax(0, 1fr) 2rem 4.6rem;
        }

        .avm-radar-zone span,
        .avm-radar-change i,
        .avm-radar-search i {
            width: 1.1rem;
            height: 1.1rem;
            display: grid;
            place-items: center;
            border-radius: 999px;
            color: var(--avm-neo-soft);
            background: rgba(23, 199, 255, 0.13);
            border: 1px solid rgba(23, 199, 255, 0.24);
            font-size: 0.62rem;
            font-style: normal;
            font-weight: 850;
        }

        .avm-radar-zone b {
            color: #ffffff;
            font-size: 0.74rem;
        }

        .avm-radar-change {
            grid-template-columns: 1.2rem minmax(0, 1fr) auto;
        }

        .avm-radar-change--warning i {
            color: var(--avm-neo-amber);
            background: rgba(247, 169, 40, 0.13);
            border-color: rgba(247, 169, 40, 0.26);
        }

        .avm-radar-change span,
        .avm-radar-search span {
            color: var(--avm-neo-muted);
            font-size: 0.62rem;
            text-align: right;
        }

        .avm-radar-search {
            grid-template-columns: 1.3rem minmax(0, 1fr) auto;
        }

        .avm-radar-score-footer {
            display: grid;
            grid-template-columns: minmax(0, 2.5fr) minmax(16rem, 0.82fr);
            gap: 0.62rem;
            align-items: stretch;
            margin-top: 0.14rem;
        }

        .avm-radar-factor-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.5rem;
        }

        .avm-radar-factor {
            min-height: 6rem;
            border: 1px solid rgba(66, 132, 191, 0.16);
            border-radius: 8px;
            background: rgba(8, 18, 34, 0.68);
            padding: 0.62rem;
        }

        .avm-radar-factor strong {
            color: var(--avm-neo-soft);
            display: block;
            font-size: 0.72rem;
            margin-top: 0.32rem;
        }

        .avm-radar-factor b {
            color: #ffffff;
            display: block;
            font-size: 1rem;
            margin-top: 0.22rem;
        }

        .avm-radar-factor p,
        .avm-radar-cta p,
        .avm-radar-empty p {
            color: var(--avm-neo-muted);
            font-size: 0.68rem;
            line-height: 1.28;
            margin: 0.24rem 0 0;
        }

        .avm-radar-factor--positive b { color: var(--avm-neo-green); }
        .avm-radar-factor--warning b { color: var(--avm-neo-amber); }
        .avm-radar-factor--premium b { color: #caa9ff; }

        .avm-radar-cta {
            display: grid;
            align-content: center;
            justify-items: center;
            text-align: center;
            background:
                radial-gradient(circle at 50% 0%, rgba(139, 53, 255, 0.22), transparent 42%),
                linear-gradient(180deg, rgba(18, 28, 58, 0.94), rgba(8, 17, 36, 0.96));
        }

        .avm-radar-cta i {
            width: 3.2rem;
            height: 3.2rem;
            border-radius: 999px;
            border: 1px solid rgba(139, 53, 255, 0.45);
            background:
                radial-gradient(circle, rgba(23, 199, 255, 0.32) 0 12%, transparent 13%),
                conic-gradient(from 30deg, var(--avm-neo-purple), var(--avm-neo-cyan), var(--avm-neo-purple));
            box-shadow: 0 0 28px rgba(139, 53, 255, 0.25);
            margin-bottom: 0.5rem;
        }

        .avm-radar-cta strong,
        .avm-radar-empty strong {
            color: #ffffff;
            font-size: 0.9rem;
        }

        @media (max-width: 1180px) {
            .avm-radar-hero,
            .avm-radar-score-footer {
                grid-template-columns: 1fr;
            }

            .avm-radar-hero__visual {
                opacity: 0.42;
                width: 88%;
            }

            .avm-radar-hero__metrics,
            .avm-radar-factor-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .avm-radar-opportunity-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .avm-radar-map {
                min-height: 24rem;
            }
        }

        @media (max-width: 780px) {
            .avm-radar-hero__metrics,
            .avm-radar-factor-grid,
            .avm-radar-opportunity-grid {
                grid-template-columns: 1fr;
            }

            .avm-radar-opportunity {
                min-height: 0;
            }

            .avm-radar-opportunity__head,
            .avm-radar-opportunity__foot {
                display: grid;
                grid-template-columns: 1fr;
            }

            .avm-radar-price {
                text-align: left;
            }
        }
        </style>
        """,
    )
