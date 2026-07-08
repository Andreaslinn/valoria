"""Neo Premium Dark Portfolio playground view."""
from __future__ import annotations

import streamlit as st

from ui.components.theme import html_escape
from ui.feature_flags import is_demo_mode
from ui.redesign.portfolio_adapter import (
    PORTFOLIO_COMPARE_MAX_ITEMS,
    PORTFOLIO_STATUS_COMING_SOON,
    PORTFOLIO_STATUS_EMPTY,
    PORTFOLIO_STATUS_ERROR,
    PORTFOLIO_TAB_COMPARED,
    PORTFOLIO_TAB_FAVORITES,
    PORTFOLIO_TAB_WATCHLIST,
    PortfolioActivityViewModel,
    PortfolioChartViewModel,
    PortfolioCompareViewModel,
    PortfolioFilterCriteria,
    PortfolioFiltersViewModel,
    PortfolioPropertyViewModel,
    PortfolioRankingViewModel,
    PortfolioRecommendationViewModel,
    PortfolioViewModel,
    build_compare_view_model,
    load_portfolio_view_model,
    toggle_compare_selection,
)
from ui.redesign.tasar_playground import inject_tasar_playground_styles, render_html
from ui.state import get_token

FILTER_COMUNA_KEY = "tasar_pg_portfolio_comuna"
FILTER_STATUS_KEY = "tasar_pg_portfolio_status"
FILTER_PROPERTY_TYPE_KEY = "tasar_pg_portfolio_property_type"
FILTER_SEARCH_KEY = "tasar_pg_portfolio_search"
FILTER_SORT_KEY = "tasar_pg_portfolio_sort"
COMPARE_SELECTION_KEY = "tasar_pg_portfolio_compare_selection"
COMPARE_NOTICE_KEY = "tasar_pg_portfolio_compare_notice"
ACTIVE_TAB_KEY = "tasar_pg_portfolio_active_tab"
COMPARE_ID_KEY = "tasar_pg_portfolio_compare_id"


def render(client: object | None = None) -> None:
    """Render the isolated Portfolio playground."""
    inject_tasar_playground_styles()
    inject_portfolio_styles()
    view_model = _load_view_model(client, _criteria_from_state())
    render_portfolio_hero(view_model)
    render_dashboard(view_model, client=client, token=get_token())


def render_portfolio_hero(view_model: PortfolioViewModel) -> None:
    render_html(
        f"""
        <section class="avm-portfolio-hero" data-source="{html_escape(view_model.source_state)}">
            <div class="avm-portfolio-hero__copy">
                <div class="avm-portfolio-kicker">Portafolio inteligente &middot; {html_escape(view_model.source_state)}</div>
                <h1>Sigue tus propiedades, mueve tu estrategia.</h1>
                <p>Monitorea precios, oportunidades y senales relevantes desde un unico lugar.</p>
                <div class="avm-portfolio-location">
                    <span>Ubicacion actual</span>
                    <strong>Providencia, RM</strong>
                </div>
            </div>
            <div class="avm-portfolio-hero__skyline" aria-hidden="true">
                <i></i><i></i><i></i><i></i><i></i><i></i><i></i>
            </div>
        </section>
        """,
    )


def render_hero(view_model: PortfolioViewModel) -> None:
    render_portfolio_hero(view_model)
    render_portfolio_metrics(view_model)


def render_portfolio_metrics(view_model: PortfolioViewModel) -> None:
    summary = view_model.summary
    render_html(
        f"""
        <section class="avm-portfolio-kpis">
            {_kpi_card("Propiedades en seguimiento", str(summary.tracked_properties), summary.tracked_delta, "building")}
            {_kpi_card("Variacion promedio AVM", _optional_pct(summary.average_variation_pct), summary.average_variation_caption, "spark")}
            {_kpi_card("Alertas disparadas", str(summary.active_alerts), summary.active_alerts_caption, "bell")}
            {_kpi_card("Upside potencial total", _optional_uf(summary.upside_potential_uf), summary.upside_potential_caption, "upside")}
        </section>
        """,
    )


def render_portfolio_filters(
    filters: PortfolioFiltersViewModel,
    criteria: PortfolioFilterCriteria,
) -> PortfolioFilterCriteria:
    return render_filters(filters, criteria)


def render_dashboard(view_model: PortfolioViewModel, *, client: object | None = None, token: str | None = None) -> None:
    if view_model.status == PORTFOLIO_STATUS_ERROR:
        render_state_panel("No pudimos cargar Portafolio", view_model.error_message or "Error demo/lab.")
        return
    comparison = _load_active_comparison(client, token)
    selected_ids = _comparison_selected_listing_ids(comparison) or _selected_compare_ids()
    compare_vm = build_compare_view_model(view_model, selected_ids)
    active_tab = _active_tab()
    if active_tab == PORTFOLIO_TAB_COMPARED and not compare_vm.can_compare:
        active_tab = PORTFOLIO_TAB_WATCHLIST
        st.session_state[ACTIVE_TAB_KEY] = PORTFOLIO_TAB_WATCHLIST

    tab_cols = st.columns([1, 1, 1, 3], gap="small")
    with tab_cols[0]:
        if st.button(PORTFOLIO_TAB_WATCHLIST, key="portfolio_tab_watchlist", use_container_width=True):
            st.session_state[ACTIVE_TAB_KEY] = PORTFOLIO_TAB_WATCHLIST
            st.rerun()
    with tab_cols[1]:
        if st.button(
            PORTFOLIO_TAB_COMPARED,
            key="portfolio_tab_compared",
            disabled=not compare_vm.can_compare,
            use_container_width=True,
        ):
            _open_compare_tab(compare_vm)
            st.rerun()
    with tab_cols[2]:
        st.button(PORTFOLIO_TAB_FAVORITES, key="portfolio_tab_favorites", disabled=True, use_container_width=True)

    render_html(render_tabs(view_model, active_tab=active_tab))
    if active_tab == PORTFOLIO_TAB_WATCHLIST:
        render_portfolio_metrics(view_model)
        criteria = render_portfolio_filters(view_model.filters, view_model.criteria)
        if criteria != view_model.criteria:
            view_model = _load_view_model(client, criteria)
            selected_ids = _comparison_selected_listing_ids(comparison) or _selected_compare_ids()
            compare_vm = build_compare_view_model(view_model, selected_ids)

    main_col, side_col = st.columns([0.74, 0.26], gap="medium")
    with main_col:
        if active_tab == PORTFOLIO_TAB_COMPARED:
            render_html(render_compare_table(compare_vm))
            _render_compared_actions(compare_vm, client=client, token=token, comparison=comparison)
        else:
            _render_watchlist_functional_table(
                view_model,
                compare_vm,
                client=client,
                token=token,
                comparison=comparison,
            )
            render_html(render_chart(view_model.chart))
    with side_col:
        render_html(
            f"""
            <aside class="avm-portfolio-side">
                {render_activity_panel(view_model.activity, title=view_model.activity_title, badge=view_model.activity_badge)}
                {render_ranking_panel(view_model.ranking)}
                {render_recommendations_panel(view_model.recommendations)}
                {render_compare_cta(compare_vm)}
            </aside>
            """,
        )
        _render_compare_cta_action(compare_vm)


def render_tabs(view_model: PortfolioViewModel, *, active_tab: str = PORTFOLIO_TAB_WATCHLIST) -> str:
    tabs = []
    for tab in view_model.tabs:
        if tab.label == active_tab and tab.state != PORTFOLIO_STATUS_COMING_SOON:
            state = "active"
        elif tab.state == PORTFOLIO_STATUS_COMING_SOON:
            state = "soon"
        else:
            state = "ready"
        badge = _item_badge(tab.source_state, tab.is_demo, tab.state)
        tabs.append(
            f"""
            <span class="avm-portfolio-tab avm-portfolio-tab--{state}">
                {html_escape(tab.label)}<small>{html_escape(badge)}</small>
            </span>
            """
        )
    return f'<div class="avm-portfolio-tabs">{"".join(tabs)}</div>'


def render_filters(filters: PortfolioFiltersViewModel, criteria: PortfolioFilterCriteria) -> PortfolioFilterCriteria:
    with st.container(border=True):
        cols = st.columns([1.05, 0.95, 1.0, 1.6, 1.0], gap="small")
        with cols[0]:
            comuna = st.selectbox(
                "Comuna",
                filters.comunas,
                index=_option_index(filters.comunas, criteria.comuna),
                key=FILTER_COMUNA_KEY,
            )
        with cols[1]:
            status = st.selectbox(
                "Estado",
                filters.statuses,
                index=_option_index(filters.statuses, criteria.status),
                key=FILTER_STATUS_KEY,
            )
        with cols[2]:
            property_type = st.selectbox(
                "Tipo de propiedad",
                filters.property_types,
                format_func=_property_type_label,
                index=_option_index(filters.property_types, criteria.property_type),
                key=FILTER_PROPERTY_TYPE_KEY,
                disabled=not filters.property_type_enabled,
            )
        with cols[3]:
            search = st.text_input(
                "Buscar",
                value=criteria.search,
                placeholder="Titulo, comuna o direccion",
                key=FILTER_SEARCH_KEY,
            )
        with cols[4]:
            sort_by = st.selectbox(
                "Ordenar",
                tuple(key for key, _label in filters.sort_options),
                format_func=lambda key: dict(filters.sort_options).get(key, key),
                index=_sort_index(filters.sort_options, criteria.sort_by),
                key=FILTER_SORT_KEY,
            )
        st.caption(_filters_caption(filters))
    return PortfolioFilterCriteria(
        comuna=str(comuna),
        status=str(status),
        property_type=str(property_type),
        search=str(search),
        sort_by=str(sort_by),
    )


def render_property_table(view_model: PortfolioViewModel, *, selected_ids: tuple[str, ...] = ()) -> str:
    if view_model.status == PORTFOLIO_STATUS_EMPTY or not view_model.properties:
        return """
        <div class="avm-portfolio-state">
            <strong>Sin propiedades en seguimiento</strong>
            <p>No hay propiedades reales en tu watchlist para los filtros actuales.</p>
        </div>
        """
    rows = "".join(render_property_row(item, selected=item.id in selected_ids) for item in view_model.properties)
    return f"""
    <div class="avm-portfolio-table" data-testid="portfolio-watchlist">
        <div class="avm-portfolio-table__head">
            <span>Propiedad</span><span>Comuna</span><span>Valor AVM</span><span>Precio publicado</span>
            <span>Delta vs AVM</span><span>Tendencia</span><span>Estado</span><span>Acciones</span>
        </div>
        {rows}
        <div class="avm-portfolio-table__footer">
            <span>Mostrando {len(view_model.properties)} de {view_model.summary.tracked_properties} propiedades</span>
            <div><button>&lsaquo;</button><b>1</b><button>2</button><button>3</button><button>4</button><button>&rsaquo;</button></div>
            <span>Mostrar <b>6</b> por pagina</span>
        </div>
    </div>
    """


def render_property_row(item: PortfolioPropertyViewModel, *, selected: bool = False) -> str:
    delta_class = "positive" if item.delta_pct >= 0 else "negative"
    delta_sign = "+" if item.delta_uf > 0 else ""
    avm_cell = _coming_soon_cell("AVM") if item.avm_state == PORTFOLIO_STATUS_COMING_SOON else f"<strong>UF {_thousands(item.avm_value_uf)}</strong><small>$ {_thousands(item.avm_value_clp)}</small>"
    delta_cell = (
        _coming_soon_cell("Delta AVM")
        if item.delta_state == PORTFOLIO_STATUS_COMING_SOON
        else f'<span class="avm-portfolio-delta avm-portfolio-delta--{delta_class}">{_signed_pct(item.delta_pct)}<small>{delta_sign}UF {_thousands(item.delta_uf)}</small></span>'
    )
    trend_cell = (
        _coming_soon_cell("Tendencia AVM")
        if item.trend_state == PORTFOLIO_STATUS_COMING_SOON
        else f"{_sparkline(item.trend, tone=delta_class)}<small>{html_escape(item.trend_label)}</small>"
    )
    price_cell = _published_price_cell(item)
    return f"""
    <div class="avm-portfolio-row">
        <div class="avm-portfolio-property">
            <span class="avm-portfolio-thumb avm-portfolio-thumb--{html_escape(item.image_tone)}"></span>
            <div>
                <strong>{html_escape(item.title)}</strong>
                <small>{html_escape(item.detail)}</small>
                <em>Publicado: {html_escape(item.published_at)}</em>
            </div>
        </div>
        <span>{html_escape(item.comuna)}</span>
        <span>{avm_cell}</span>
        <span>{price_cell}</span>
        <span>{delta_cell}</span>
        <span>{trend_cell}</span>
        <span><b class="avm-portfolio-status avm-portfolio-status--{html_escape(item.status_tone)}">{html_escape(item.status_label)}</b></span>
        <span class="avm-portfolio-actions">{_property_actions(item, selected=selected)}</span>
    </div>
    """


def _published_price_cell(item: PortfolioPropertyViewModel) -> str:
    if item.price_basis == "canonical_uf" and item.published_price_uf > 0:
        return (
            f"<strong>UF {_thousands(item.published_price_uf)}</strong>"
            f"<small>$ {_thousands(item.published_price_clp)}</small>"
        )
    label = "CLP snapshot" if item.published_price_clp > 0 else "Precio no confiable"
    return (
        f"<strong>$ {_thousands(item.published_price_clp)}</strong>"
        f"<small>{html_escape(label)} - {html_escape(item.price_data_quality)}</small>"
    )


def render_activity_panel(
    items: tuple[PortfolioActivityViewModel, ...],
    *,
    title: str = "Actividad reciente",
    badge: str = "demo/lab",
) -> str:
    if not items:
        return f"""
        <section class="avm-portfolio-panel" data-testid="portfolio-activity">
            <header><span>{html_escape(title)}</span><b>{html_escape(badge)}</b></header>
            <div class="avm-portfolio-state avm-portfolio-state--compact">
                <strong>Sin alertas recientes</strong>
                <p>No hay alertas reales no leidas para tus guardados.</p>
            </div>
        </section>
        """
    rows = "".join(
        f"""
        <div class="avm-portfolio-feed-item">
            <i class="avm-portfolio-feed-dot avm-portfolio-feed-dot--{html_escape(item.tone)}"></i>
            <div><strong>{html_escape(item.kind)}</strong><span>{html_escape(item.detail)}</span></div>
            <time>{html_escape(item.time)}</time>
        </div>
        """
        for item in items
    )
    return f"""
    <section class="avm-portfolio-panel" data-testid="portfolio-activity">
        <header><span>{html_escape(title)}</span><b>{html_escape(badge)}</b></header>
        {rows}
    </section>
    """


def render_ranking_panel(items: tuple[PortfolioRankingViewModel, ...]) -> str:
    rows = "".join(
        f"""
        <div class="avm-portfolio-ranking-item">
            <b>{item.rank}</b>
            <span class="avm-portfolio-mini-thumb avm-portfolio-thumb--{html_escape(item.image_tone)}"></span>
            <div><strong>{html_escape(item.title)}</strong><small>{html_escape(item.comuna)}</small></div>
            <em>{html_escape(item.delta)}<small>{html_escape(item.delta_uf)}</small></em>
        </div>
        """
        for item in items
    )
    return f"""
    <section class="avm-portfolio-panel" data-testid="portfolio-ranking">
        <header><span>Mayores alzas (30 dias)</span><b>demo/lab</b></header>
        {rows}
    </section>
    """


def render_recommendations_panel(items: tuple[PortfolioRecommendationViewModel, ...]) -> str:
    rows = "".join(
        f"""
        <div class="avm-portfolio-rec avm-portfolio-rec--{html_escape(item.tone)}">
            <span class="avm-portfolio-mini-thumb avm-portfolio-thumb--{html_escape(item.image_tone)}"></span>
            <div><strong>{html_escape(item.title)}</strong><span>{html_escape(item.detail)}</span><small>{html_escape(item.meta)}</small></div>
            <em>{html_escape(item.price)}<small>{html_escape(item.delta)}</small></em>
        </div>
        """
        for item in items
    )
    return f"""
    <section class="avm-portfolio-panel" data-testid="portfolio-recommendations">
        <header><span>Recomendaciones para ti</span><b>demo/lab</b></header>
        {rows}
    </section>
    """


def render_compare_cta(compare_vm: PortfolioCompareViewModel | None = None) -> str:
    if compare_vm is None:
        compare_vm = PortfolioCompareViewModel((), (), False, "Selecciona entre 2 y 4 propiedades reales para comparar.")
    state = "ready" if compare_vm.can_compare else "selecting"
    action = "Ir a comparar" if compare_vm.can_compare else "Seleccion insuficiente"
    selected_count = len(compare_vm.selected_properties)
    hint = compare_vm.message if selected_count else "Selecciona propiedades con el boton Cmp."
    return f"""
    <section class="avm-portfolio-compare" data-state="{html_escape(state)}">
        <button type="button" aria-label="Cerrar">x</button>
        <div class="avm-portfolio-compare-icon"></div>
        <div>
            <strong>Quieres comparar esta propiedad?</strong>
            <p>{html_escape(hint)}</p>
            <span class="avm-portfolio-compare-count">{html_escape(action)} <small>{selected_count}/{compare_vm.max_items}</small></span>
        </div>
    </section>
    """


def render_compare_table(compare_vm: PortfolioCompareViewModel) -> str:
    if not compare_vm.can_compare:
        return f"""
        <div class="avm-portfolio-state">
            <strong>Comparados necesita al menos {compare_vm.min_items} propiedades</strong>
            <p>{html_escape(compare_vm.message)}</p>
        </div>
        """
    rows = "".join(_render_compare_row(item) for item in compare_vm.selected_properties)
    return f"""
    <div class="avm-portfolio-table avm-portfolio-table--compare" data-testid="portfolio-compared">
        <div class="avm-portfolio-table__head avm-portfolio-table__head--compare">
            <span>Propiedad</span><span>Comuna</span><span>Tipo</span><span>m2</span>
            <span>D/B</span><span>Publicado</span><span>UF/m2</span><span>AVM</span>
            <span>Delta</span><span>Upside</span><span>Alertas</span><span>Ver</span>
        </div>
        {rows}
    </div>
    """


def _render_compare_row(item: PortfolioPropertyViewModel) -> str:
    avm = (
        f"UF {_thousands(item.avm_value_uf)}"
        if item.avm_state != PORTFOLIO_STATUS_COMING_SOON
        else f"No disponible <small>{html_escape(item.avm_reason or 'needs_snapshot')}</small>"
    )
    delta = (
        f"{_signed_pct(item.delta_pct)} <small>{_signed_uf(item.delta_uf)}</small>"
        if item.delta_state != PORTFOLIO_STATUS_COMING_SOON
        else f"No disponible <small>{html_escape(item.delta_reason or 'needs_canonical_price')}</small>"
    )
    upside = (
        f"UF {_thousands(item.delta_uf)}"
        if item.delta_state != PORTFOLIO_STATUS_COMING_SOON and item.delta_uf > 0
        else "No disponible"
    )
    view = (
        f'<a href="{html_escape(item.url)}" target="_blank" rel="noopener noreferrer">Ver</a>'
        if item.url
        else "No disponible"
    )
    return f"""
    <div class="avm-portfolio-row avm-portfolio-row--compare">
        <span><strong>{html_escape(item.title)}</strong><small>{html_escape(item.detail)}</small></span>
        <span>{html_escape(item.comuna)}</span>
        <span>{html_escape(_property_type_label(item.property_type))}</span>
        <span>{_optional_m2(item.m2)}</span>
        <span>{_optional_rooms(item)}</span>
        <span>{_compare_price(item)}</span>
        <span>{_compare_price_m2(item)}</span>
        <span>{avm}</span>
        <span>{delta}</span>
        <span>{upside}</span>
        <span>{_optional_alerts(item.alert_count)}</span>
        <span>{view}</span>
    </div>
    """


def render_chart(chart: PortfolioChartViewModel) -> str:
    if chart.status == PORTFOLIO_STATUS_COMING_SOON or not chart.points:
        return """
        <section class="avm-portfolio-chart" data-testid="portfolio-chart" data-state="coming-soon">
            <header><span>Evolucion del valor promedio del portafolio (UF)</span><b>coming soon</b></header>
            <div class="avm-portfolio-state avm-portfolio-state--compact">
                <strong>Historial AVM no disponible</strong>
                <p>Requiere snapshots AVM repetidos de portafolio.</p>
            </div>
        </section>
        """
    points = _chart_points(chart.points)
    labels = "".join(f"<span>{html_escape(label)}</span>" for label in chart.labels)
    return f"""
    <section class="avm-portfolio-chart" data-testid="portfolio-chart">
        <header><span>Evolucion del valor promedio del portafolio (UF)</span><b>demo/lab</b></header>
        <div class="avm-portfolio-chart__body">
            <aside>
                <strong>{_optional_uf(chart.current_average_uf)}</strong>
                <span>Promedio actual</span>
                <em>{_optional_pct(chart.variation_pct)}</em>
                <small>Ultimos 30 dias</small>
            </aside>
            <div class="avm-portfolio-line">
                <svg viewBox="0 0 600 170" role="img" aria-label="Grafico demo del portafolio">
                    <defs>
                        <linearGradient id="portfolioArea" x1="0" x2="0" y1="0" y2="1">
                            <stop offset="0%" stop-color="#8b5cf6" stop-opacity="0.62"/>
                            <stop offset="100%" stop-color="#0ea5e9" stop-opacity="0.04"/>
                        </linearGradient>
                    </defs>
                    <path class="area" d="M 0 145 L {points} L 600 145 Z"></path>
                    <polyline points="{points}" fill="none"></polyline>
                    {_chart_dots(points)}
                </svg>
                <div class="avm-portfolio-chart-labels">{labels}</div>
            </div>
        </div>
    </section>
    """


def render_state_panel(title: str, message: str) -> None:
    render_html(
        f"""
        <div class="avm-portfolio-state avm-portfolio-state--error">
            <strong>{html_escape(title)}</strong>
            <p>{html_escape(message)}</p>
        </div>
        """,
    )


def _kpi_card(label: str, value: str, caption: str, icon: str) -> str:
    return f"""
    <article class="avm-portfolio-kpi avm-portfolio-kpi--{html_escape(icon)}">
        <span>{html_escape(label)}</span>
        <strong>{html_escape(value)}</strong>
        <small>{html_escape(caption)}</small>
        <i></i>
    </article>
    """


def _load_view_model(client: object | None, criteria: PortfolioFilterCriteria | None) -> PortfolioViewModel:
    return load_portfolio_view_model(
        client=client,
        token=get_token(),
        criteria=criteria,
        demo_mode=is_demo_mode(),
    )


def _criteria_from_state() -> PortfolioFilterCriteria:
    return PortfolioFilterCriteria(
        comuna=str(st.session_state.get(FILTER_COMUNA_KEY) or "Todas"),
        status=str(st.session_state.get(FILTER_STATUS_KEY) or "Todos"),
        property_type=str(st.session_state.get(FILTER_PROPERTY_TYPE_KEY) or "Todos"),
        search=str(st.session_state.get(FILTER_SEARCH_KEY) or ""),
        sort_by=str(st.session_state.get(FILTER_SORT_KEY) or "saved_desc"),
    )


def _option_index(options: tuple[str, ...], value: str) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


def _sort_index(options: tuple[tuple[str, str], ...], value: str) -> int:
    keys = tuple(key for key, _label in options)
    return _option_index(keys, value)


def _filters_caption(filters: PortfolioFiltersViewModel) -> str:
    if filters.is_demo:
        return "Filtros demo/lab sobre fixtures visuales."
    return "Filtros client-side sobre watchlist real."


def _property_type_label(value: str) -> str:
    labels = {
        "Todos": "Todos",
        "apartment": "Departamento",
        "house": "Casa",
        "unknown": "Sin tipo",
    }
    return labels.get(value, "Otro")


def _item_badge(source_state: str, is_demo: bool, status: str) -> str:
    if status == PORTFOLIO_STATUS_COMING_SOON:
        return "coming soon"
    if is_demo:
        return "demo/lab"
    return source_state


def _coming_soon_cell(label: str) -> str:
    return f'<b class="avm-portfolio-soon">{html_escape(label)}</b><small>Coming soon</small>'


def _property_actions(item: PortfolioPropertyViewModel, *, selected: bool = False) -> str:
    if item.url:
        view = f'<a href="{html_escape(item.url)}" target="_blank" rel="noopener noreferrer" title="Ver publicacion">Ver</a>'
    else:
        view = '<i title="Sin URL">Ver</i>'
    compare_class = "avm-portfolio-action--selected" if selected else ""
    compare_title = "Quitar de Comparados" if selected else "Agregar a Comparados"
    compare_label = "Cmp*" if selected else "Cmp"
    return (
        f'{view} <i class="{compare_class}" title="{html_escape(compare_title)}">'
        f'{html_escape(compare_label)}</i> <i title="Alertas coming soon">Alr</i>'
    )


def _render_watchlist_functional_table(
    view_model: PortfolioViewModel,
    compare_vm: PortfolioCompareViewModel,
    *,
    client: object | None,
    token: str | None,
    comparison: dict | None,
) -> None:
    if view_model.status == PORTFOLIO_STATUS_EMPTY or not view_model.properties:
        render_html(render_property_table(view_model))
        return
    render_html(_watchlist_header_html())
    notice = st.session_state.get(COMPARE_NOTICE_KEY)
    if notice:
        st.warning(str(notice), icon=None)
    for item in view_model.properties:
        selected = item.id in compare_vm.selected_ids
        row_cols = st.columns([0.86, 0.14], gap="small")
        with row_cols[0]:
            st.markdown(_watchlist_row_html(item, selected=selected), unsafe_allow_html=True)
        with row_cols[1]:
            _render_watchlist_row_actions(item, selected=selected, client=client, token=token, comparison=comparison)
    render_html(
        f"""
        <div class="avm-portfolio-table__footer avm-portfolio-table__footer--standalone">
            <span>Mostrando {len(view_model.properties)} de {view_model.summary.tracked_properties} propiedades</span>
            <div><button>&lsaquo;</button><b>1</b><button>2</button><button>3</button><button>4</button><button>&rsaquo;</button></div>
            <span>Mostrar <b>6</b> por pagina</span>
        </div>
        """,
    )


def _watchlist_header_html() -> str:
    return """
    <div class="avm-portfolio-watchlist-shell" data-testid="portfolio-watchlist">
        <div class="avm-portfolio-watchlist-head">
            <span>Propiedad</span><span>Comuna</span><span>Valor AVM</span><span>Precio publicado</span>
            <span>Delta vs AVM</span><span>Tendencia</span><span>Estado</span>
        </div>
    </div>
    """


def _watchlist_row_html(item: PortfolioPropertyViewModel, *, selected: bool = False) -> str:
    return f"""
    <div class="avm-portfolio-watchlist-row" data-selected="{str(selected).lower()}">
        <div class="avm-portfolio-watchlist-row__grid">
            <div>{_property_summary_markdown(item)}</div>
            {_watchlist_cell(item.comuna)}
            {_watchlist_cell(_avm_label(item))}
            {_watchlist_cell(_published_price_label(item))}
            {_watchlist_cell(_delta_label_for_item(item))}
            {_watchlist_cell(_trend_label_for_item(item))}
            <span><b class="avm-portfolio-status avm-portfolio-status--{html_escape(item.status_tone)}">{html_escape(item.status_label)}</b></span>
        </div>
    </div>
    """


def _watchlist_cell(value: str) -> str:
    return f'<span class="avm-portfolio-watchlist-cell">{html_escape(value)}</span>'


def _render_watchlist_row_actions(
    item: PortfolioPropertyViewModel,
    *,
    selected: bool,
    client: object | None,
    token: str | None,
    comparison: dict | None,
) -> None:
    action_cols = st.columns(3, gap="small")
    with action_cols[0]:
        st.markdown(_view_action_link(item), unsafe_allow_html=True)
    with action_cols[1]:
        if st.button(
            "Cmp*" if selected else "Cmp",
            key=f"portfolio_cmp_row_{_safe_key(item.id)}",
            type="primary" if selected else "secondary",
            use_container_width=True,
        ):
            _toggle_compare_item(item, client=client, token=token, comparison=comparison)
            st.rerun()
    with action_cols[2]:
        st.button("Alr", key=f"portfolio_alert_row_{_safe_key(item.id)}", disabled=True, use_container_width=True)


def _render_compare_cta_action(compare_vm: PortfolioCompareViewModel) -> None:
    if st.button(
        "Ir a comparar",
        key="portfolio_compare_open",
        disabled=not compare_vm.can_compare,
        use_container_width=True,
    ):
        _open_compare_tab(compare_vm)
        st.rerun()


def _render_compared_actions(
    compare_vm: PortfolioCompareViewModel,
    *,
    client: object | None,
    token: str | None,
    comparison: dict | None,
) -> None:
    if compare_vm.can_compare:
        html = _comparison_report_html(client, token, comparison)
        if html:
            st.download_button(
                "Descargar HTML",
                data=html,
                file_name="comparados_valoria.html",
                mime="text/html",
                key="portfolio_compare_download_html",
                use_container_width=True,
            )


def _view_action_link(item: PortfolioPropertyViewModel) -> str:
    if item.url:
        return (
            f'<a class="avm-portfolio-action-link" href="{html_escape(item.url)}" '
            f'target="_blank" rel="noopener noreferrer" title="Ver publicacion">Ver</a>'
        )
    return '<span class="avm-portfolio-action-link avm-portfolio-action-link--disabled">Ver</span>'


def _toggle_compare_item(
    item: PortfolioPropertyViewModel,
    *,
    client: object | None,
    token: str | None,
    comparison: dict | None,
) -> None:
    selected_ids = _comparison_selected_listing_ids(comparison) or _selected_compare_ids()
    is_selected = item.id in selected_ids
    if not is_selected and len(selected_ids) >= PORTFOLIO_COMPARE_MAX_ITEMS:
        st.session_state[COMPARE_NOTICE_KEY] = f"Maximo {PORTFOLIO_COMPARE_MAX_ITEMS} propiedades para comparar."
        return
    if client is None or token is None or not _has_comparison_client(client):
        selected_ids, message = toggle_compare_selection(_selected_compare_ids(), item.id)
        st.session_state[COMPARE_SELECTION_KEY] = list(selected_ids)
        st.session_state[COMPARE_NOTICE_KEY] = message or (
            "Removida de comparacion." if is_selected else "Agregada a comparacion."
        )
        return
    try:
        comparison = comparison or client.create_portfolio_comparison(token, title="Comparacion de Portafolio")  # type: ignore[attr-defined]
        comparison_id = int(comparison["comparison"]["id"])
        st.session_state[COMPARE_ID_KEY] = comparison_id
        comparison_item_id = _comparison_item_id_for_listing(comparison, item.id)
        if comparison_item_id is not None:
            updated = client.remove_portfolio_comparison_item(token, comparison_id, comparison_item_id)  # type: ignore[attr-defined]
            notice = "Removida de comparacion."
        else:
            updated = client.add_portfolio_comparison_item(  # type: ignore[attr-defined]
                token,
                comparison_id,
                listing_id=int(item.id),
            )
            notice = "Agregada a comparacion."
        st.session_state[COMPARE_SELECTION_KEY] = list(_comparison_selected_listing_ids(updated))
        st.session_state[COMPARE_NOTICE_KEY] = notice
    except Exception as exc:
        st.session_state[COMPARE_NOTICE_KEY] = str(exc)


def _load_active_comparison(client: object | None, token: str | None) -> dict | None:
    if client is None or token is None or not _has_comparison_client(client):
        return None
    comparison_id = st.session_state.get(COMPARE_ID_KEY)
    try:
        if comparison_id:
            return client.get_portfolio_comparison(token, int(comparison_id))  # type: ignore[attr-defined]
        comparisons = client.list_portfolio_comparisons(token).get("comparisons", [])  # type: ignore[attr-defined]
        if not comparisons:
            return None
        latest = comparisons[0]
        st.session_state[COMPARE_ID_KEY] = int(latest["id"])
        return client.get_portfolio_comparison(token, int(latest["id"]))  # type: ignore[attr-defined]
    except Exception as exc:
        st.session_state[COMPARE_NOTICE_KEY] = str(exc)
        return None


def _comparison_report_html(client: object | None, token: str | None, comparison: dict | None) -> str | None:
    if client is None or token is None or comparison is None or not hasattr(client, "get_portfolio_comparison_report_html"):
        return None
    try:
        comparison_id = int(comparison["comparison"]["id"])
        return str(client.get_portfolio_comparison_report_html(token, comparison_id))  # type: ignore[attr-defined]
    except Exception as exc:
        st.session_state[COMPARE_NOTICE_KEY] = str(exc)
        return None


def _comparison_selected_listing_ids(comparison: dict | None) -> tuple[str, ...]:
    if not isinstance(comparison, dict):
        return ()
    items = comparison.get("items")
    if not isinstance(items, list):
        return ()
    return tuple(str(item.get("listing_id")) for item in items if isinstance(item, dict) and item.get("listing_id"))


def _comparison_item_id_for_listing(comparison: dict, listing_id: str) -> int | None:
    for item in comparison.get("items", []):
        if isinstance(item, dict) and str(item.get("listing_id")) == str(listing_id):
            return int(item["id"])
    return None


def _has_comparison_client(client: object) -> bool:
    return all(
        hasattr(client, name)
        for name in (
            "create_portfolio_comparison",
            "list_portfolio_comparisons",
            "get_portfolio_comparison",
            "add_portfolio_comparison_item",
            "remove_portfolio_comparison_item",
        )
    )


def _property_summary_markdown(item: PortfolioPropertyViewModel) -> str:
    return (
        f'<div class="avm-portfolio-property avm-portfolio-property--streamlit">'
        f'<span class="avm-portfolio-thumb avm-portfolio-thumb--{html_escape(item.image_tone)}"></span>'
        f"<div><strong>{html_escape(item.title)}</strong>"
        f"<small>{html_escape(item.detail)}</small>"
        f"<em>Publicado: {html_escape(item.published_at)}</em></div></div>"
    )


def _cell_text(value: str) -> str:
    return value.replace("\n", "<br>")


def _avm_label(item: PortfolioPropertyViewModel) -> str:
    if item.avm_state == PORTFOLIO_STATUS_COMING_SOON:
        return "No disponible"
    return f"UF {_thousands(item.avm_value_uf)}"


def _published_price_label(item: PortfolioPropertyViewModel) -> str:
    if item.price_basis == "canonical_uf" and item.published_price_uf > 0:
        return f"UF {_thousands(item.published_price_uf)}"
    if item.published_price_clp > 0:
        return f"$ {_thousands(item.published_price_clp)}"
    return "No disponible"


def _delta_label_for_item(item: PortfolioPropertyViewModel) -> str:
    if item.delta_state == PORTFOLIO_STATUS_COMING_SOON:
        return "No disponible"
    return f"{_signed_pct(item.delta_pct)} / {_signed_uf(item.delta_uf)}"


def _trend_label_for_item(item: PortfolioPropertyViewModel) -> str:
    if item.trend_state == PORTFOLIO_STATUS_COMING_SOON:
        return "No disponible"
    return item.trend_label


def _selected_compare_ids() -> tuple[str, ...]:
    raw = st.session_state.get(COMPARE_SELECTION_KEY) or []
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(item_id) for item_id in raw if str(item_id).strip())


def _active_tab() -> str:
    active = str(st.session_state.get(ACTIVE_TAB_KEY) or PORTFOLIO_TAB_WATCHLIST)
    if active not in {PORTFOLIO_TAB_WATCHLIST, PORTFOLIO_TAB_COMPARED}:
        return PORTFOLIO_TAB_WATCHLIST
    return active


def _open_compare_tab(compare_vm: PortfolioCompareViewModel) -> None:
    if compare_vm.can_compare:
        st.session_state[ACTIVE_TAB_KEY] = PORTFOLIO_TAB_COMPARED
        st.session_state[COMPARE_NOTICE_KEY] = ""
        return
    st.session_state[COMPARE_NOTICE_KEY] = compare_vm.message


def _optional_m2(value: float | None) -> str:
    if not value:
        return "No disponible"
    return f"{value:g} m2"


def _optional_rooms(item: PortfolioPropertyViewModel) -> str:
    parts: list[str] = []
    if item.bedrooms:
        parts.append(f"{item.bedrooms}D")
    if item.bathrooms:
        parts.append(f"{item.bathrooms}B")
    return " / ".join(parts) if parts else "No disponible"


def _compare_price(item: PortfolioPropertyViewModel) -> str:
    if item.price_basis == "canonical_uf" and item.published_price_uf > 0:
        return f"UF {_thousands(item.published_price_uf)}"
    if item.published_price_clp > 0:
        return f"$ {_thousands(item.published_price_clp)}"
    return "No disponible"


def _compare_price_m2(item: PortfolioPropertyViewModel) -> str:
    if item.price_basis != "canonical_uf" or item.published_price_uf <= 0 or not item.m2:
        return "No disponible"
    return f"UF {_thousands(item.published_price_uf / item.m2)}/m2"


def _optional_alerts(value: int) -> str:
    if value <= 0:
        return "No disponible"
    return str(value)


def _signed_uf(value: int | float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}UF {_thousands(value)}"


def _safe_key(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)


def _sparkline(points: tuple[int, ...], *, tone: str) -> str:
    svg_points = _spark_points(points)
    return f"""
    <svg class="avm-portfolio-spark avm-portfolio-spark--{tone}" viewBox="0 0 80 30" aria-hidden="true">
        <polyline points="{svg_points}" fill="none"></polyline>
    </svg>
    """


def _spark_points(points: tuple[int, ...]) -> str:
    if not points:
        return ""
    low, high = min(points), max(points)
    spread = max(high - low, 1)
    step = 80 / max(len(points) - 1, 1)
    return " ".join(f"{index * step:.1f},{26 - ((point - low) / spread) * 22:.1f}" for index, point in enumerate(points))


def _chart_points(points: tuple[int, ...]) -> str:
    if not points:
        return ""
    low, high = min(points), max(points)
    spread = max(high - low, 1)
    step = 600 / max(len(points) - 1, 1)
    return " ".join(f"{index * step:.1f},{140 - ((point - low) / spread) * 105:.1f}" for index, point in enumerate(points))


def _chart_dots(points: str) -> str:
    dots = []
    for index, pair in enumerate(points.split()):
        if index % 3 != 0:
            continue
        x, y = pair.split(",")
        dots.append(f'<circle cx="{x}" cy="{y}" r="3"></circle>')
    return "".join(dots)


def _signed_pct(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%".replace(".", ",")


def _optional_pct(value: float | None) -> str:
    if value is None:
        return "Coming soon"
    return _signed_pct(value)


def _optional_uf(value: int | float | None) -> str:
    if value is None:
        return "Coming soon"
    return f"UF {_thousands(value)}"


def _thousands(value: int | float) -> str:
    return f"{int(value):,}".replace(",", ".")


def inject_portfolio_styles() -> None:
    st.markdown(
        """
        <style>
        .avm-portfolio-hero {
            position: relative;
            overflow: hidden;
            min-height: 176px;
            border: 1px solid rgba(14, 165, 233, 0.34);
            border-radius: 10px;
            padding: 26px 30px;
            background:
                radial-gradient(circle at 83% 16%, rgba(124, 58, 237, 0.55), transparent 34%),
                radial-gradient(circle at 58% 72%, rgba(14, 165, 233, 0.22), transparent 42%),
                linear-gradient(100deg, rgba(2, 8, 23, 0.98) 0%, rgba(7, 18, 44, 0.92) 45%, rgba(49, 12, 98, 0.88) 100%);
            box-shadow: 0 24px 72px rgba(0, 0, 0, 0.34), inset 0 1px 0 rgba(255,255,255,0.08);
        }
        .avm-portfolio-hero__copy { position: relative; z-index: 2; max-width: 760px; }
        .avm-portfolio-kicker {
            color: #22d3ee;
            font-size: 0.72rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0;
            margin-bottom: 10px;
        }
        .avm-portfolio-hero h1 {
            margin: 0;
            color: #f8fafc;
            font-size: 1.9rem;
            line-height: 1.08;
            letter-spacing: 0;
            max-width: 650px;
        }
        .avm-portfolio-hero p {
            margin: 12px 0 0;
            color: #b8c7dc;
            max-width: 610px;
            font-size: 0.98rem;
        }
        .avm-portfolio-location {
            position: absolute;
            right: 18px;
            bottom: 18px;
            z-index: 3;
            padding: 10px 14px;
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 8px;
            background: rgba(2, 6, 23, 0.72);
            color: #e5edf8;
            min-width: 164px;
        }
        .avm-portfolio-location span { display:block; color:#94a3b8; font-size:0.74rem; }
        .avm-portfolio-location strong { font-size:0.86rem; }
        .avm-portfolio-hero__skyline {
            position: absolute;
            right: 0;
            bottom: 0;
            width: 54%;
            height: 100%;
            opacity: 0.8;
            background:
                linear-gradient(to top, rgba(6, 182, 212, 0.22), transparent 38%),
                repeating-linear-gradient(90deg, transparent 0 28px, rgba(125, 92, 246, 0.28) 30px 32px);
            mask-image: linear-gradient(90deg, transparent, #000 24%);
        }
        .avm-portfolio-hero__skyline i {
            position: absolute;
            bottom: 0;
            width: 32px;
            border-radius: 5px 5px 0 0;
            background: linear-gradient(180deg, rgba(56,189,248,0.75), rgba(91,33,182,0.42));
            box-shadow: 0 0 28px rgba(56, 189, 248, 0.26);
        }
        .avm-portfolio-hero__skyline i:nth-child(1){right:64%;height:62px}
        .avm-portfolio-hero__skyline i:nth-child(2){right:54%;height:94px}
        .avm-portfolio-hero__skyline i:nth-child(3){right:43%;height:52px}
        .avm-portfolio-hero__skyline i:nth-child(4){right:32%;height:118px}
        .avm-portfolio-hero__skyline i:nth-child(5){right:22%;height:76px}
        .avm-portfolio-hero__skyline i:nth-child(6){right:12%;height:103px}
        .avm-portfolio-hero__skyline i:nth-child(7){right:4%;height:68px}

        .avm-portfolio-kpis {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin: 14px 0;
        }
        .avm-portfolio-kpi {
            position: relative;
            min-height: 104px;
            padding: 18px;
            border: 1px solid rgba(51, 65, 85, 0.82);
            border-radius: 8px;
            background: linear-gradient(145deg, rgba(15, 23, 42, 0.96), rgba(8, 17, 36, 0.88));
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
        }
        .avm-portfolio-kpi span { color:#9fb0c7; font-size:0.72rem; text-transform:uppercase; display:block; }
        .avm-portfolio-kpi strong { color:#f8fafc; font-size:1.55rem; display:block; margin-top:10px; }
        .avm-portfolio-kpi small { color:#6ee7b7; font-weight:700; }
        .avm-portfolio-kpi i {
            position:absolute; right:18px; top:28px; width:38px; height:38px;
            border-radius:8px; background:rgba(99,102,241,.16); border:1px solid rgba(129,140,248,.3);
        }
        .avm-portfolio-grid {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 318px;
            gap: 14px;
            align-items: start;
        }
        .avm-portfolio-tabs {
            display:flex;
            gap:0;
            border:1px solid rgba(51,65,85,.82);
            border-radius:8px 8px 0 0;
            overflow:hidden;
            background:rgba(2,8,23,.48);
        }
        .avm-portfolio-tab {
            padding: 13px 24px;
            min-width: 152px;
            border-right: 1px solid rgba(51,65,85,.72);
            color:#a8b5c8;
            font-weight:800;
        }
        .avm-portfolio-tab small { display:block; margin-top:2px; color:#64748b; font-size:.65rem; text-transform:uppercase; }
        .avm-portfolio-tab--active {
            color:#f8fafc;
            background:linear-gradient(180deg, rgba(37,99,235,.22), rgba(2,8,23,.04));
            box-shadow: inset 0 -2px 0 #7c3aed;
        }
        .avm-portfolio-tab--ready { color:#dbeafe; }
        .avm-portfolio-toolbar {
            display:grid;
            grid-template-columns: 1fr .75fr 1fr minmax(180px, 1.7fr) auto;
            gap:8px;
            padding:10px;
            border:1px solid rgba(51,65,85,.82);
            border-top:0;
            background:rgba(8,17,36,.76);
        }
        .avm-portfolio-toolbar label,
        .avm-portfolio-search,
        .avm-portfolio-toolbar button {
            min-height:42px;
            border:1px solid rgba(51,65,85,.82);
            border-radius:7px;
            background:rgba(15,23,42,.72);
            color:#e2e8f0;
            padding:7px 12px;
            font-size:.8rem;
        }
        .avm-portfolio-toolbar label span { display:block; color:#64748b; font-size:.65rem; }
        .avm-portfolio-toolbar label b { font-weight:700; }
        .avm-portfolio-search { color:#64748b; display:flex; align-items:center; }
        .avm-portfolio-toolbar button { color:#dbeafe; font-weight:800; }
        .avm-portfolio-toolbar button small { background:#4f46e5; border-radius:999px; padding:2px 6px; }
        .avm-portfolio-table {
            border:1px solid rgba(51,65,85,.82);
            border-top:0;
            border-radius:0 0 8px 8px;
            overflow:hidden;
            background:rgba(5,12,27,.78);
        }
        .avm-portfolio-table__head,
        .avm-portfolio-row {
            display:grid;
            grid-template-columns: 2.15fr .8fr 1fr 1fr .9fr .9fr .95fr .72fr;
            gap:10px;
            align-items:center;
        }
        .avm-portfolio-table__head {
            padding:12px 14px;
            color:#8fa1b8;
            text-transform:uppercase;
            font-size:.66rem;
            font-weight:800;
            border-bottom:1px solid rgba(51,65,85,.62);
        }
        .avm-portfolio-row {
            min-height:78px;
            padding:10px 14px;
            border-bottom:1px solid rgba(30,41,59,.78);
            color:#cbd5e1;
            font-size:.8rem;
        }
        .avm-portfolio-row strong { color:#f8fafc; display:block; }
        .avm-portfolio-row small,
        .avm-portfolio-property em { display:block; color:#7e8da2; font-style:normal; font-size:.72rem; }
        .avm-portfolio-property { display:flex; gap:10px; align-items:center; min-width:0; }
        .avm-portfolio-property div { min-width:0; }
        .avm-portfolio-property strong,
        .avm-portfolio-property small,
        .avm-portfolio-property em { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .avm-portfolio-thumb,
        .avm-portfolio-mini-thumb {
            flex: 0 0 auto;
            display:inline-block;
            border-radius:7px;
            background:
                linear-gradient(135deg, rgba(255,255,255,.25), transparent 26%),
                linear-gradient(145deg, rgba(14,165,233,.6), rgba(124,58,237,.6)),
                repeating-linear-gradient(90deg, rgba(15,23,42,.6) 0 7px, rgba(255,255,255,.1) 8px 10px);
            border:1px solid rgba(148,163,184,.22);
        }
        .avm-portfolio-thumb { width:58px; height:58px; }
        .avm-portfolio-mini-thumb { width:42px; height:42px; }
        .avm-portfolio-delta { font-weight:900; }
        .avm-portfolio-delta small { font-weight:800; }
        .avm-portfolio-delta--positive, .avm-portfolio-delta--positive small { color:#4ade80; }
        .avm-portfolio-delta--negative, .avm-portfolio-delta--negative small { color:#fb7185; }
        .avm-portfolio-spark { width:72px; height:26px; display:block; }
        .avm-portfolio-spark polyline { stroke:#8b5cf6; stroke-width:3; stroke-linecap:round; stroke-linejoin:round; }
        .avm-portfolio-spark--negative polyline { stroke:#f472b6; }
        .avm-portfolio-status {
            display:inline-flex;
            justify-content:center;
            min-width:96px;
            padding:7px 10px;
            border-radius:7px;
            font-size:.72rem;
            border:1px solid rgba(59,130,246,.3);
            background:rgba(30,64,175,.22);
            color:#60a5fa;
        }
        .avm-portfolio-status--opportunity { color:#86efac; background:rgba(22,101,52,.28); border-color:rgba(34,197,94,.3); }
        .avm-portfolio-status--warning { color:#fbbf24; background:rgba(146,64,14,.28); border-color:rgba(245,158,11,.3); }
        .avm-portfolio-actions { display:flex; gap:7px; }
        .avm-portfolio-actions i,
        .avm-portfolio-actions a {
            width:28px; height:28px; border:1px solid rgba(51,65,85,.82); border-radius:7px;
            display:grid; place-items:center; color:#94a3b8; font-style:normal; background:rgba(15,23,42,.72);
            text-decoration:none; font-size:.68rem; font-weight:800;
        }
        .avm-portfolio-actions a { color:#67e8f9; border-color:rgba(34,211,238,.35); }
        .avm-portfolio-actions .avm-portfolio-action--selected {
            color:#fff;
            background:#7c3aed;
            border-color:rgba(216,180,254,.66);
        }
        .avm-portfolio-action-link {
            width:28px;
            height:28px;
            border:1px solid rgba(34,211,238,.35);
            border-radius:7px;
            display:grid;
            place-items:center;
            color:#67e8f9;
            background:rgba(15,23,42,.72);
            text-decoration:none;
            font-size:.68rem;
            font-weight:800;
        }
        .avm-portfolio-action-link--disabled { color:#94a3b8; border-color:rgba(51,65,85,.82); }
        div[data-testid="stHorizontalBlock"]:has(.avm-portfolio-action-link) button {
            min-height:28px;
            height:28px;
            padding:0;
            border-radius:7px;
            font-size:.68rem;
            font-weight:800;
        }
        .avm-portfolio-watchlist-shell {
            border:1px solid rgba(51,65,85,.82);
            border-bottom:0;
            border-radius:8px 8px 0 0;
            overflow-x:auto;
            background:rgba(5,12,27,.78);
        }
        .avm-portfolio-watchlist-head,
        .avm-portfolio-watchlist-row__grid {
            display:grid;
            grid-template-columns:
                minmax(260px, 2.05fr)
                minmax(86px, .72fr)
                minmax(104px, .86fr)
                minmax(116px, .95fr)
                minmax(104px, .9fr)
                minmax(94px, .78fr)
                minmax(110px, .86fr);
            gap:10px;
            align-items:center;
            min-width: 910px;
        }
        .avm-portfolio-watchlist-head {
            padding:12px 14px;
            color:#8fa1b8;
            text-transform:uppercase;
            font-size:.66rem;
            font-weight:800;
        }
        .avm-portfolio-watchlist-row {
            min-height:78px;
            margin:0;
            padding:10px 14px;
            border:1px solid rgba(30,41,59,.86);
            border-top:0;
            background:rgba(5,12,27,.74);
            color:#cbd5e1;
            font-size:.8rem;
            overflow-x:auto;
        }
        .avm-portfolio-watchlist-row[data-selected="true"] {
            background:linear-gradient(90deg, rgba(124,58,237,.18), rgba(5,12,27,.74));
            border-left-color:rgba(168,85,247,.86);
        }
        .avm-portfolio-watchlist-cell {
            display:block;
            min-width:0;
            overflow:hidden;
            text-overflow:ellipsis;
            white-space:nowrap;
        }
        .avm-portfolio-action-cluster {
            min-height:78px;
            display:flex;
            align-items:center;
        }
        div[data-testid="stHorizontalBlock"]:has(.avm-portfolio-action-cluster),
        div[data-testid="stHorizontalBlock"]:has(.avm-portfolio-watchlist-row) {
            align-items:center;
        }
        div[data-testid="stHorizontalBlock"]:has(.avm-portfolio-watchlist-row) {
            border-bottom:1px solid rgba(30,41,59,.78);
        }
        .avm-portfolio-soon { color:#94a3b8 !important; font-size:.78rem; }
        .avm-portfolio-table__footer {
            display:flex;
            justify-content:space-between;
            gap:12px;
            padding:12px 14px;
            color:#94a3b8;
            font-size:.8rem;
        }
        .avm-portfolio-table__footer button,
        .avm-portfolio-table__footer b {
            min-width:28px;
            height:28px;
            display:inline-grid;
            place-items:center;
            border-radius:7px;
            border:1px solid rgba(51,65,85,.82);
            background:rgba(15,23,42,.72);
            color:#cbd5e1;
            margin:0 2px;
        }
        .avm-portfolio-table__footer b { border-color:#6d5dfc; color:#fff; }
        .avm-portfolio-side { display:flex; flex-direction:column; gap:12px; }
        .avm-portfolio-panel,
        .avm-portfolio-chart,
        .avm-portfolio-compare,
        .avm-portfolio-state {
            border:1px solid rgba(51,65,85,.82);
            border-radius:8px;
            background:linear-gradient(145deg, rgba(15,23,42,.92), rgba(5,12,27,.88));
            box-shadow: inset 0 1px 0 rgba(255,255,255,.05);
        }
        .avm-portfolio-panel { padding:14px; }
        .avm-portfolio-panel header,
        .avm-portfolio-chart header {
            display:flex;
            justify-content:space-between;
            align-items:center;
            margin-bottom:12px;
            color:#cbd5e1;
            font-weight:900;
            text-transform:uppercase;
            font-size:.72rem;
        }
        .avm-portfolio-panel header b,
        .avm-portfolio-chart header b {
            color:#22d3ee;
            font-size:.66rem;
        }
        .avm-portfolio-feed-item,
        .avm-portfolio-ranking-item,
        .avm-portfolio-rec {
            display:grid;
            grid-template-columns:auto 1fr auto;
            gap:10px;
            align-items:center;
            padding:9px 0;
            border-bottom:1px solid rgba(30,41,59,.72);
        }
        .avm-portfolio-feed-item:last-child,
        .avm-portfolio-ranking-item:last-child,
        .avm-portfolio-rec:last-child { border-bottom:0; }
        .avm-portfolio-feed-dot {
            width:28px;
            height:28px;
            border-radius:8px;
            background:#2563eb;
            box-shadow:0 0 18px rgba(37,99,235,.3);
        }
        .avm-portfolio-feed-dot--pink { background:#be185d; }
        .avm-portfolio-feed-dot--green { background:#15803d; }
        .avm-portfolio-feed-dot--amber { background:#d97706; }
        .avm-portfolio-feed-dot--red { background:#e11d48; }
        .avm-portfolio-feed-item strong,
        .avm-portfolio-ranking-item strong,
        .avm-portfolio-rec strong { color:#f8fafc; font-size:.82rem; display:block; }
        .avm-portfolio-feed-item span,
        .avm-portfolio-ranking-item small,
        .avm-portfolio-rec span,
        .avm-portfolio-rec small { color:#94a3b8; font-size:.74rem; display:block; }
        .avm-portfolio-feed-item time,
        .avm-portfolio-ranking-item em,
        .avm-portfolio-rec em { color:#cbd5e1; font-size:.76rem; font-style:normal; text-align:right; }
        .avm-portfolio-ranking-item { grid-template-columns:20px auto 1fr auto; }
        .avm-portfolio-ranking-item b { color:#94a3b8; }
        .avm-portfolio-ranking-item em,
        .avm-portfolio-rec--opportunity em,
        .avm-portfolio-rec--info em { color:#4ade80; font-weight:900; }
        .avm-portfolio-rec--danger em { color:#fb7185; }
        .avm-portfolio-compare {
            position:relative;
            padding:18px;
            display:grid;
            grid-template-columns:58px 1fr;
            gap:14px;
            background:
                radial-gradient(circle at 15% 15%, rgba(124,58,237,.7), transparent 35%),
                linear-gradient(145deg, rgba(88,28,135,.9), rgba(30,41,59,.86));
            border-color:rgba(168,85,247,.72);
        }
        .avm-portfolio-compare button {
            position:absolute; right:10px; top:8px; border:0; background:transparent; color:#c4b5fd;
        }
        .avm-portfolio-compare-icon {
            width:58px; height:58px; border-radius:10px; background:rgba(167,139,250,.22);
            border:1px solid rgba(216,180,254,.28);
        }
        .avm-portfolio-compare strong { color:#fff; }
        .avm-portfolio-compare p { color:#c4b5fd; margin:6px 0 12px; font-size:.8rem; }
        .avm-portfolio-compare-count {
            display:inline-flex;
            gap:8px;
            align-items:center;
            padding:10px 14px;
            border-radius:7px;
            background:#7c3aed;
            color:#fff;
            font-weight:900;
        }
        .avm-portfolio-compare-count small { color:#ddd6fe; }
        .avm-portfolio-table--compare { overflow-x:auto; }
        .avm-portfolio-table__head--compare,
        .avm-portfolio-row--compare {
            grid-template-columns: 1.7fr .75fr .75fr .55fr .55fr .8fr .65fr .75fr .75fr .7fr .55fr .5fr;
            min-width: 1180px;
        }
        .avm-portfolio-row--compare a { color:#67e8f9; font-weight:800; text-decoration:none; }
        .avm-portfolio-chart { margin-top:12px; padding:14px; }
        .avm-portfolio-chart__body {
            display:grid;
            grid-template-columns:150px 1fr;
            gap:16px;
            align-items:stretch;
        }
        .avm-portfolio-chart aside {
            border-right:1px solid rgba(51,65,85,.72);
            padding-right:16px;
        }
        .avm-portfolio-chart aside strong { display:block; color:#fff; font-size:1.5rem; }
        .avm-portfolio-chart aside span,
        .avm-portfolio-chart aside small { display:block; color:#94a3b8; }
        .avm-portfolio-chart aside em { display:block; color:#4ade80; font-style:normal; font-size:1.25rem; font-weight:900; margin-top:18px; }
        .avm-portfolio-line { min-width:0; }
        .avm-portfolio-line svg { width:100%; height:180px; display:block; }
        .avm-portfolio-line .area { fill:url(#portfolioArea); stroke:none; }
        .avm-portfolio-line polyline { stroke:#8b5cf6; stroke-width:4; stroke-linecap:round; stroke-linejoin:round; filter:drop-shadow(0 0 8px rgba(139,92,246,.8)); }
        .avm-portfolio-line circle { fill:#a78bfa; stroke:#1e1b4b; stroke-width:2; }
        .avm-portfolio-chart-labels { display:flex; justify-content:space-between; color:#94a3b8; font-size:.78rem; padding:0 4px; }
        .avm-portfolio-state { padding:24px; color:#cbd5e1; }
        .avm-portfolio-state--compact { padding:12px; }
        .avm-portfolio-state strong { color:#fff; }
        .avm-portfolio-state p { color:#94a3b8; }

        @media (max-width: 1180px) {
            .avm-portfolio-grid { grid-template-columns: 1fr; }
            .avm-portfolio-side { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .avm-portfolio-compare { grid-column:1 / -1; }
        }
        @media (max-width: 920px) {
            .avm-portfolio-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .avm-portfolio-toolbar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .avm-portfolio-search { grid-column:1 / -1; }
            .avm-portfolio-table { overflow-x:auto; }
            .avm-portfolio-table__head,
            .avm-portfolio-row { min-width: 900px; }
            .avm-portfolio-watchlist-head,
            .avm-portfolio-watchlist-row__grid { min-width: 860px; }
            .avm-portfolio-chart__body { grid-template-columns:1fr; }
            .avm-portfolio-chart aside { border-right:0; border-bottom:1px solid rgba(51,65,85,.72); padding:0 0 12px; }
        }
        @media (max-width: 640px) {
            .avm-portfolio-hero { padding:22px 18px; min-height:220px; }
            .avm-portfolio-hero h1 { font-size:1.55rem; }
            .avm-portfolio-location { position:relative; right:auto; bottom:auto; margin-top:18px; width:fit-content; }
            .avm-portfolio-kpis,
            .avm-portfolio-side,
            .avm-portfolio-toolbar { grid-template-columns:1fr; }
            .avm-portfolio-tab { min-width:0; flex:1; padding:12px 10px; }
            .avm-portfolio-table__footer { flex-direction:column; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
