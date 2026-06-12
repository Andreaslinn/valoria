"""Neo Premium Dark Alerts playground view."""
from __future__ import annotations

import streamlit as st

from ui.components.theme import html_escape
from ui.feature_flags import is_demo_mode
from ui.redesign.alerts_adapter import (
    ALERTS_STATUS_COMING_SOON,
    ALERTS_STATUS_EMPTY,
    ALERTS_STATUS_ERROR,
    AlertsFilterCriteria,
    AlertsFiltersViewModel,
    AlertGroupViewModel,
    AlertSettingViewModel,
    AlertsViewModel,
    load_alerts_view_model,
)
from ui.redesign.tasar_playground import inject_tasar_playground_styles, render_html
from ui.state import get_token

FILTER_COMMUNE_KEY = "tasar_pg_alerts_commune"
FILTER_TYPE_KEY = "tasar_pg_alerts_type"
FILTER_DATE_KEY = "tasar_pg_alerts_date"


def render(client: object | None = None) -> None:
    """Render the isolated Alerts playground."""
    inject_tasar_playground_styles()
    inject_alerts_styles()
    view_model = _load_view_model(client, _criteria_from_state())
    render_hero(view_model)
    criteria = render_filters(view_model.filters, view_model.criteria)
    if criteria != view_model.criteria:
        view_model = _load_view_model(client, criteria)
    render_dashboard(view_model)


def render_hero(view_model: AlertsViewModel) -> None:
    render_html(
        f"""
        <section class="avm-alerts-hero" data-source="{html_escape(view_model.source_state)}">
            <div class="avm-alerts-hero__copy">
                <div class="avm-alerts-kicker">Alertas inteligentes en tiempo real &middot; {html_escape(view_model.source_state)}</div>
                <h1>Recibe se&ntilde;ales al instante.</h1>
                <p>No te pierdas ning&uacute;n cambio relevante del mercado.</p>
                <div class="avm-alerts-actions">
                    <button type="button">Ver mis reglas</button>
                    <button type="button" class="primary">+ Nueva regla de alerta</button>
                </div>
            </div>
            <div class="avm-alerts-hero__coverage">
                <span>Cobertura actual</span>
                <strong>Nacional</strong>
            </div>
            <div class="avm-alerts-hero__skyline" aria-hidden="true">
                <i></i><i></i><i></i><i></i><i></i><i></i><i></i>
            </div>
        </section>
        <section class="avm-alerts-kpis">
            {"".join(_kpi_card(item.label, item.value, item.caption, item.icon) for item in view_model.kpis)}
        </section>
        """,
    )


def render_dashboard(view_model: AlertsViewModel) -> None:
    if view_model.status == ALERTS_STATUS_ERROR:
        render_state_panel("No pudimos cargar Alertas", view_model.error_message or "Error demo/lab.")
        return
    render_html(
        f"""
        <section class="avm-alerts-layout">
            <main class="avm-alerts-main">
                {render_alert_groups(view_model)}
            </main>
            <aside class="avm-alerts-side">
                {render_trends_panel(view_model)}
                {render_zones_panel(view_model)}
                {render_settings_panel(view_model)}
                {render_ai_panel(view_model)}
            </aside>
        </section>
        """,
    )


def render_filters(filters: AlertsFiltersViewModel, criteria: AlertsFilterCriteria) -> AlertsFilterCriteria:
    with st.container(border=True):
        cols = st.columns([1.05, 1.05, 1.0, 1.0, 0.8], gap="small")
        with cols[0]:
            alert_type = st.selectbox(
                "Tipo de alerta",
                filters.alert_types,
                index=_option_index(filters.alert_types, criteria.alert_type),
                key=FILTER_TYPE_KEY,
            )
        with cols[1]:
            commune = st.selectbox(
                "Comuna",
                filters.communes,
                index=_option_index(filters.communes, criteria.commune),
                key=FILTER_COMMUNE_KEY,
            )
        with cols[2]:
            date_range = st.selectbox(
                "Fecha",
                filters.dates,
                index=_option_index(filters.dates, criteria.date_range),
                key=FILTER_DATE_KEY,
            )
        with cols[3]:
            st.selectbox(
                "Tipo de propiedad",
                filters.property_types,
                index=0,
                key="tasar_pg_alerts_property_type",
                disabled=not filters.property_type_enabled,
            )
            st.caption("Coming soon")
        with cols[4]:
            st.selectbox(
                "Severidad",
                filters.severities,
                index=0,
                key="tasar_pg_alerts_severity",
                disabled=not filters.severity_enabled,
            )
            if not filters.severity_enabled:
                st.caption("Sin severity real")
        st.caption(_filters_caption(filters))
    return AlertsFilterCriteria(
        commune=str(commune),
        alert_type=str(alert_type),
        date_range=str(date_range),
    )


def render_alert_groups(view_model: AlertsViewModel) -> str:
    if view_model.status == ALERTS_STATUS_EMPTY or not view_model.groups:
        message = (
            "No hay alertas reales no leidas para tus propiedades guardadas."
            if not view_model.is_demo
            else "Estado empty preparado para futuras alertas reales."
        )
        return f"""
        <div class="avm-alerts-state">
            <strong>Sin alertas</strong>
            <p>{html_escape(message)}</p>
        </div>
        """
    title = "Alertas de tus guardados" if not view_model.is_demo else "Alertas demo/lab"
    badge = view_model.source_state
    load_badge = "demo/lab" if view_model.is_demo else "real"
    return f"""
    <div class="avm-alerts-list-title">
        <strong>{html_escape(title)}</strong>
        <span>{html_escape(badge)}</span>
    </div>
    """ + "".join(render_alert_group(group) for group in view_model.groups) + """
    <div class="avm-alerts-load-more"><button type="button">Cargar mas alertas <small>""" + html_escape(load_badge) + """</small></button></div>
    """


def render_alert_group(group: AlertGroupViewModel) -> str:
    rows = "".join(
        f"""
        <article class="avm-alert-card avm-alert-card--{html_escape(item.tone)}">
            <div class="avm-alert-icon avm-alert-icon--{html_escape(item.icon)}"></div>
            <div class="avm-alert-copy">
                <strong>{html_escape(item.title)}</strong>
                <p>{html_escape(item.description)}</p>
            </div>
            <div class="avm-alert-place">
                <span>{html_escape(item.commune)}</span>
                <small>{html_escape(item.address)}</small>
            </div>
            <div class="avm-alert-metric">
                <strong>{html_escape(item.metric)}</strong>
                <small>{html_escape(item.metric_delta)}</small>
            </div>
            <time>{html_escape(item.date)}<small>{html_escape(item.source_state)}</small></time>
            <div class="avm-alert-card-actions"><i></i><b></b></div>
        </article>
        """
        for item in group.items
    )
    return f"""
    <section class="avm-alert-group avm-alert-group--{html_escape(group.tone)}" data-testid="alerts-group">
        <header><span>{html_escape(group.title)} ({group.count})</span><b>{html_escape(group.source_state)}</b></header>
        {rows}
    </section>
    """


def render_trends_panel(view_model: AlertsViewModel) -> str:
    rows = "".join(
        f"""
        <div class="avm-alert-trend">
            <span>{html_escape(item.label)}</span>
            <strong>{item.count}</strong>
            <em class="avm-alert-tone--{html_escape(item.tone)}">{html_escape(item.delta)}</em>
        </div>
        """
        for item in view_model.trends
    )
    return f"""
    <section class="avm-alert-panel" data-testid="alerts-trends">
        <header><span>Tendencias de alertas</span><b>demo/lab</b></header>
        {rows}
    </section>
    """


def render_zones_panel(view_model: AlertsViewModel) -> str:
    rows = "".join(
        f"""
        <div class="avm-alert-zone">
            <span>{html_escape(item.name)}</span>
            <b class="avm-alert-zone__level avm-alert-zone__level--{html_escape(item.tone)}">{html_escape(item.level)}</b>
            <strong>{item.count}</strong>
            <em>{html_escape(item.delta)}</em>
        </div>
        """
        for item in view_model.zones
    )
    return f"""
    <section class="avm-alert-panel" data-testid="alerts-zones">
        <header><span>Zonas mas activas</span><b>demo/lab</b></header>
        {rows}
        <small>Basado en volumen de alertas demo.</small>
    </section>
    """


def render_settings_panel(view_model: AlertsViewModel) -> str:
    rows = "".join(render_setting_row(item) for item in view_model.settings)
    return f"""
    <section class="avm-alert-panel" data-testid="alerts-settings">
        <header><span>Configuracion de notificaciones</span><b>coming soon</b></header>
        {rows}
        <button type="button" class="avm-alert-panel-button">Administrar notificaciones</button>
    </section>
    """


def render_setting_row(item: AlertSettingViewModel) -> str:
    control = '<i class="avm-alert-switch avm-alert-switch--on"></i>' if item.enabled else '<i class="avm-alert-chevron"></i>'
    return f"""
    <div class="avm-alert-setting" data-state="{html_escape(item.status)}">
        <span>{html_escape(item.label)}</span>
        <strong>{html_escape(item.value)}</strong>
        {control}
    </div>
    """


def render_ai_panel(view_model: AlertsViewModel) -> str:
    ai = view_model.ai
    state = "Coming Soon" if ai.status == ALERTS_STATUS_COMING_SOON else ai.source_state
    return f"""
    <section class="avm-alert-ai" data-testid="alerts-ai">
        <div class="avm-alert-ai__icon"></div>
        <div>
            <strong>{html_escape(ai.title)}</strong>
            <p>{html_escape(ai.description)}</p>
            <button type="button">{html_escape(ai.button_label)} <small>{html_escape(state)}</small></button>
        </div>
    </section>
    """


def render_state_panel(title: str, message: str) -> None:
    render_html(
        f"""
        <div class="avm-alerts-state avm-alerts-state--error">
            <strong>{html_escape(title)}</strong>
            <p>{html_escape(message)}</p>
        </div>
        """,
    )


def _kpi_card(label: str, value: str, caption: str, icon: str) -> str:
    return f"""
    <article class="avm-alert-kpi avm-alert-kpi--{html_escape(icon)}">
        <span>{html_escape(label)}</span>
        <strong>{html_escape(value)}</strong>
        <small>{html_escape(caption)}</small>
        <i></i>
    </article>
    """


def _load_view_model(client: object | None, criteria: AlertsFilterCriteria | None) -> AlertsViewModel:
    return load_alerts_view_model(
        client=client,
        token=get_token(),
        criteria=criteria,
        demo_mode=is_demo_mode(),
    )


def _criteria_from_state() -> AlertsFilterCriteria:
    return AlertsFilterCriteria(
        commune=str(st.session_state.get(FILTER_COMMUNE_KEY) or "Todas"),
        alert_type=str(st.session_state.get(FILTER_TYPE_KEY) or "Todos"),
        date_range=str(st.session_state.get(FILTER_DATE_KEY) or "Ultimos 7 dias"),
    )


def _option_index(options: tuple[str, ...], value: str) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


def _filters_caption(filters: AlertsFiltersViewModel) -> str:
    if filters.is_demo:
        return "Filtros visuales demo/lab sobre fixtures."
    return "Filtros client-side sobre alertas reales cargadas. Severidad y tipo de propiedad quedan coming soon."


def _filter_chip(label: str, value: str) -> str:
    return f"""
    <label>
        <span>{html_escape(label)}</span>
        <b>{html_escape(value)}</b>
    </label>
    """


def inject_alerts_styles() -> None:
    st.markdown(
        """
        <style>
        .avm-alerts-hero {
            position: relative;
            overflow: hidden;
            min-height: 206px;
            border: 1px solid rgba(14, 165, 233, 0.38);
            border-radius: 10px;
            padding: 28px 34px;
            background:
                radial-gradient(circle at 82% 18%, rgba(124, 58, 237, 0.58), transparent 34%),
                radial-gradient(circle at 56% 76%, rgba(14, 165, 233, 0.23), transparent 42%),
                linear-gradient(101deg, rgba(2, 8, 23, 0.98) 0%, rgba(7, 18, 44, 0.94) 44%, rgba(49, 12, 98, 0.9) 100%);
            box-shadow: 0 24px 72px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.08);
        }
        .avm-alerts-hero__copy { position: relative; z-index: 3; max-width: 720px; }
        .avm-alerts-kicker {
            color:#22d3ee; font-size:.72rem; font-weight:900; text-transform:uppercase; margin-bottom:10px;
        }
        .avm-alerts-hero h1 { margin:0; color:#fff; font-size:2rem; line-height:1.07; letter-spacing:0; }
        .avm-alerts-hero p { margin:10px 0 0; color:#b8c7dc; max-width:620px; font-size:1rem; }
        .avm-alerts-actions { display:flex; gap:10px; margin-top:22px; }
        .avm-alerts-actions button {
            min-height:42px; padding:0 22px; border-radius:8px; border:1px solid rgba(148,163,184,.25);
            background:rgba(15,23,42,.82); color:#eef2ff; font-weight:900;
        }
        .avm-alerts-actions .primary { border-color:rgba(125,92,246,.72); background:linear-gradient(135deg,#2563eb,#7c3aed); }
        .avm-alerts-hero__coverage {
            position:absolute; right:22px; bottom:24px; z-index:4; min-width:150px; padding:11px 14px;
            border-radius:8px; border:1px solid rgba(148,163,184,.22); background:rgba(2,6,23,.72); color:#e5edf8;
        }
        .avm-alerts-hero__coverage span { display:block; color:#94a3b8; font-size:.72rem; }
        .avm-alerts-hero__skyline {
            position:absolute; right:0; bottom:0; width:58%; height:100%; opacity:.82;
            background:linear-gradient(to top, rgba(6,182,212,.2), transparent 38%), repeating-linear-gradient(90deg, transparent 0 28px, rgba(125,92,246,.28) 30px 32px);
            mask-image:linear-gradient(90deg, transparent, #000 22%);
        }
        .avm-alerts-hero__skyline i {
            position:absolute; bottom:0; width:34px; border-radius:5px 5px 0 0;
            background:linear-gradient(180deg, rgba(56,189,248,.75), rgba(91,33,182,.42));
            box-shadow:0 0 30px rgba(56,189,248,.28);
        }
        .avm-alerts-hero__skyline i:nth-child(1){right:66%;height:65px}
        .avm-alerts-hero__skyline i:nth-child(2){right:55%;height:96px}
        .avm-alerts-hero__skyline i:nth-child(3){right:45%;height:54px}
        .avm-alerts-hero__skyline i:nth-child(4){right:33%;height:126px}
        .avm-alerts-hero__skyline i:nth-child(5){right:23%;height:76px}
        .avm-alerts-hero__skyline i:nth-child(6){right:13%;height:105px}
        .avm-alerts-hero__skyline i:nth-child(7){right:4%;height:70px}

        .avm-alerts-kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:14px 0; }
        .avm-alert-kpi {
            position:relative; min-height:104px; padding:18px; border:1px solid rgba(51,65,85,.82); border-radius:8px;
            background:linear-gradient(145deg, rgba(15,23,42,.96), rgba(8,17,36,.88)); box-shadow:inset 0 1px 0 rgba(255,255,255,.06);
        }
        .avm-alert-kpi span { color:#9fb0c7; font-size:.72rem; text-transform:uppercase; display:block; }
        .avm-alert-kpi strong { color:#f8fafc; font-size:1.55rem; display:block; margin-top:10px; }
        .avm-alert-kpi small { color:#6ee7b7; font-weight:800; }
        .avm-alert-kpi--critical small { color:#fb7185; }
        .avm-alert-kpi i { position:absolute; right:18px; top:26px; width:42px; height:42px; border-radius:999px; border:1px solid rgba(96,165,250,.35); background:rgba(37,99,235,.18); }
        .avm-alert-kpi--critical i { border-color:rgba(248,113,113,.45); background:rgba(127,29,29,.26); }
        .avm-alert-kpi--shield i { border-color:rgba(45,212,191,.4); background:rgba(13,148,136,.18); }
        .avm-alert-kpi--clock i { border-color:rgba(216,180,254,.45); background:rgba(88,28,135,.25); }

        .avm-alerts-layout { display:grid; grid-template-columns:minmax(0,1fr) 318px; gap:14px; align-items:start; }
        .avm-alerts-main, .avm-alerts-side { min-width:0; }
        .avm-alerts-side { display:flex; flex-direction:column; gap:12px; }
        .avm-alerts-filterbar {
            display:grid; grid-template-columns:repeat(4,minmax(0,1fr)) auto; gap:10px; margin-bottom:12px;
            border:1px solid rgba(51,65,85,.82); border-radius:8px; padding:10px; background:rgba(8,17,36,.76);
        }
        .avm-alerts-filterbar label, .avm-alerts-filterbar button {
            min-height:42px; border:1px solid rgba(51,65,85,.82); border-radius:7px; background:rgba(15,23,42,.72);
            color:#e2e8f0; padding:7px 12px; font-size:.8rem;
        }
        .avm-alerts-filterbar label span { display:block; color:#64748b; font-size:.65rem; }
        .avm-alerts-filterbar b { color:#f8fafc; }
        .avm-alerts-filterbar button { font-weight:900; color:#dbeafe; }
        .avm-alert-group {
            overflow:hidden; border:1px solid rgba(51,65,85,.82); border-radius:8px; margin-bottom:10px;
            background:linear-gradient(145deg, rgba(15,23,42,.9), rgba(5,12,27,.86));
        }
        .avm-alert-group header {
            display:flex; justify-content:space-between; align-items:center; padding:12px 14px; color:#f8fafc; font-weight:900;
            border-bottom:1px solid rgba(51,65,85,.62);
        }
        .avm-alert-group header b { color:#22d3ee; font-size:.68rem; text-transform:uppercase; }
        .avm-alert-group--critical header { background:linear-gradient(90deg, rgba(127,29,29,.24), transparent); }
        .avm-alert-group--medium header { background:linear-gradient(90deg, rgba(146,64,14,.22), transparent); }
        .avm-alert-group--low header { background:linear-gradient(90deg, rgba(13,148,136,.2), transparent); }
        .avm-alert-card {
            display:grid; grid-template-columns:54px minmax(0,1.8fr) 1fr .8fr .74fr 54px; gap:12px; align-items:center;
            min-height:82px; padding:12px 14px; border-bottom:1px solid rgba(30,41,59,.78); color:#cbd5e1;
        }
        .avm-alert-card:last-child { border-bottom:0; }
        .avm-alert-icon {
            width:46px; height:46px; border-radius:999px; border:1px solid rgba(248,113,113,.6);
            background:radial-gradient(circle, rgba(248,113,113,.28), rgba(127,29,29,.12)); position:relative;
        }
        .avm-alert-card--medium .avm-alert-icon { border-color:rgba(251,191,36,.6); background:radial-gradient(circle, rgba(251,191,36,.25), rgba(146,64,14,.1)); }
        .avm-alert-card--low .avm-alert-icon { border-color:rgba(45,212,191,.55); background:radial-gradient(circle, rgba(45,212,191,.24), rgba(13,148,136,.1)); }
        .avm-alert-icon:after { content:""; position:absolute; inset:13px; border:2px solid currentColor; color:#fb7185; border-radius:4px; transform:rotate(45deg); }
        .avm-alert-card--medium .avm-alert-icon:after { color:#fbbf24; }
        .avm-alert-card--low .avm-alert-icon:after { color:#2dd4bf; }
        .avm-alert-copy strong, .avm-alert-metric strong, .avm-alert-place span { display:block; color:#f8fafc; font-weight:900; }
        .avm-alert-copy p, .avm-alert-place small, .avm-alert-metric small, .avm-alert-card time small {
            color:#8fa1b8; font-size:.75rem; margin:3px 0 0; display:block;
        }
        .avm-alert-metric small { color:#fb7185; font-weight:900; }
        .avm-alert-card--medium .avm-alert-metric small { color:#fbbf24; }
        .avm-alert-card--low .avm-alert-metric small { color:#2dd4bf; }
        .avm-alert-card time { color:#cbd5e1; font-size:.78rem; }
        .avm-alert-card-actions { display:flex; gap:8px; justify-content:flex-end; }
        .avm-alert-card-actions i, .avm-alert-card-actions b {
            width:26px; height:26px; border-radius:7px; border:1px solid rgba(51,65,85,.82); background:rgba(15,23,42,.72);
        }
        .avm-alerts-load-more {
            display:grid; place-items:center; min-height:54px; border:1px solid rgba(51,65,85,.82); border-radius:8px; background:rgba(8,17,36,.72);
        }
        .avm-alerts-load-more button { border:0; background:transparent; color:#cbd5e1; font-weight:900; }
        .avm-alerts-load-more small { color:#22d3ee; }

        .avm-alert-panel, .avm-alert-ai, .avm-alerts-state {
            border:1px solid rgba(51,65,85,.82); border-radius:8px; background:linear-gradient(145deg, rgba(15,23,42,.92), rgba(5,12,27,.88));
            box-shadow:inset 0 1px 0 rgba(255,255,255,.05);
        }
        .avm-alert-panel { padding:14px; }
        .avm-alert-panel header {
            display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; color:#cbd5e1; font-weight:900; text-transform:uppercase; font-size:.72rem;
        }
        .avm-alert-panel header b { color:#22d3ee; font-size:.66rem; }
        .avm-alert-trend, .avm-alert-zone, .avm-alert-setting {
            display:grid; grid-template-columns:1fr auto auto; gap:10px; align-items:center; padding:8px 0; border-bottom:1px solid rgba(30,41,59,.72);
        }
        .avm-alert-trend:last-child, .avm-alert-zone:last-child, .avm-alert-setting:last-child { border-bottom:0; }
        .avm-alert-trend span, .avm-alert-zone span, .avm-alert-setting span { color:#dbeafe; font-size:.8rem; }
        .avm-alert-trend strong, .avm-alert-zone strong, .avm-alert-setting strong { color:#f8fafc; font-size:.8rem; }
        .avm-alert-trend em, .avm-alert-zone em { color:#4ade80; font-style:normal; font-size:.78rem; font-weight:900; }
        .avm-alert-tone--negative { color:#fb7185 !important; }
        .avm-alert-zone { grid-template-columns:1fr auto auto auto; }
        .avm-alert-zone__level { border-radius:999px; padding:3px 7px; font-size:.66rem !important; }
        .avm-alert-zone__level--high { color:#86efac !important; background:rgba(22,101,52,.35); }
        .avm-alert-zone__level--medium { color:#fbbf24 !important; background:rgba(146,64,14,.34); }
        .avm-alert-zone__level--low { color:#2dd4bf !important; background:rgba(13,148,136,.26); }
        .avm-alert-panel > small { color:#64748b; display:block; margin-top:8px; }
        .avm-alert-setting { grid-template-columns:1fr auto 28px; }
        .avm-alert-switch { width:28px; height:16px; border-radius:999px; background:#4f46e5; position:relative; }
        .avm-alert-switch:after { content:""; position:absolute; width:12px; height:12px; right:2px; top:2px; border-radius:999px; background:#fff; }
        .avm-alert-chevron { width:22px; height:22px; border-radius:6px; border:1px solid rgba(51,65,85,.82); }
        .avm-alert-panel-button {
            width:100%; min-height:38px; margin-top:10px; border-radius:7px; border:1px solid rgba(51,65,85,.82);
            background:rgba(15,23,42,.72); color:#dbeafe; font-weight:900;
        }
        .avm-alert-ai {
            padding:18px; display:grid; grid-template-columns:50px 1fr; gap:14px; background:radial-gradient(circle at 15% 15%, rgba(124,58,237,.7), transparent 35%), linear-gradient(145deg, rgba(88,28,135,.9), rgba(30,41,59,.86));
            border-color:rgba(168,85,247,.72);
        }
        .avm-alert-ai__icon { width:48px; height:48px; border-radius:10px; background:rgba(167,139,250,.22); border:1px solid rgba(216,180,254,.28); }
        .avm-alert-ai strong { color:#fff; }
        .avm-alert-ai p { color:#c4b5fd; margin:6px 0 12px; font-size:.8rem; }
        .avm-alert-ai button {
            width:100%; min-height:42px; border:0; border-radius:7px; background:#7c3aed; color:#fff; font-weight:900;
        }
        .avm-alert-ai small { color:#ddd6fe; }
        .avm-alerts-state { padding:24px; color:#cbd5e1; }
        .avm-alerts-state strong { color:#fff; }
        .avm-alerts-state p { color:#94a3b8; }

        @media (max-width:1180px) {
            .avm-alerts-layout { grid-template-columns:1fr; }
            .avm-alerts-side { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); }
            .avm-alert-ai { grid-column:1 / -1; }
        }
        @media (max-width:920px) {
            .avm-alerts-kpis { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .avm-alerts-filterbar { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .avm-alerts-filterbar button { grid-column:1 / -1; }
            .avm-alert-group { overflow-x:auto; }
            .avm-alert-card { min-width:860px; }
        }
        @media (max-width:640px) {
            .avm-alerts-hero { padding:22px 18px; min-height:250px; }
            .avm-alerts-hero h1 { font-size:1.55rem; }
            .avm-alerts-actions { flex-direction:column; align-items:flex-start; }
            .avm-alerts-hero__coverage { position:relative; right:auto; bottom:auto; margin-top:18px; width:fit-content; }
            .avm-alerts-kpis, .avm-alerts-side, .avm-alerts-filterbar { grid-template-columns:1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
