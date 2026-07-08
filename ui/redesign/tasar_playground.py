"""Neo Premium Dark playground for the Tasar propiedad screen."""
from __future__ import annotations

from textwrap import dedent
from typing import Any

import streamlit as st

from config.comunas import COMUNAS, find_comuna
from ui.api_client import ApiClient, ApiError
from ui.components.theme import html_escape
from ui.feature_flags import get_ui_version_label, is_demo_mode
from ui.formatting import format_clp, format_confidence, format_m2, format_uf
from ui.product_usage import track_usage_event
from ui.redesign.tasar_playground_adapter import (
    TasarComparableViewModel,
    TasarLocationIntelligence,
    TasarRiskReportContract,
    TasarValuationViewModel,
    build_tasar_risk_report_contract,
    get_tasar_payload_from_form,
    map_tasar_error,
    map_valuation_response_to_view_model,
    run_valuation_for_tasar,
)
from ui.redesign.tasar_playground_data import get_tasar_playground_panel
from ui.state import clear_session, get_token
from ui.valuation.form import property_type_payload_value
from ui.valuation.result import normalize_confidence

RESULT_KEY = "tasar_playground_result"
PAYLOAD_KEY = "tasar_playground_payload"
ERROR_KEY = "tasar_playground_error"
PREFILL_KEY = "tasar_playground_prefill"
NAV_TARGET_KEY = "tasar_playground_nav_target"
SHOW_ALL_COMPARABLES_KEY = "tasar_playground_show_all_comparables"
UNKNOWN_PREFILL_COMUNA_KEY = "tasar_playground_unknown_prefill_comuna"

COMUNA_OPTION_SLUGS = tuple(comuna.slug for comuna in COMUNAS)
COMUNA_LABELS_BY_SLUG = {comuna.slug: comuna.name for comuna in COMUNAS}
DEFAULT_COMUNA_SLUG = "providencia" if "providencia" in COMUNA_OPTION_SLUGS else COMUNA_OPTION_SLUGS[0]

NAV_ITEMS = [
    ("tasar", "Tasar propiedad", "Tasar propiedad"),
    ("radar", "Radar premium", "Radar"),
    ("portafolio", "Portafolio", "Portafolio"),
    ("alertas", "Alertas", "Alertas Lab"),
]


def render_html(markup: str, *, container: Any = st) -> None:
    cleaned = "\n".join(line.strip() for line in dedent(markup).strip().splitlines())
    container.markdown(cleaned, unsafe_allow_html=True)


def render_sidebar_shell(base_url: str) -> None:
    inject_tasar_playground_styles()
    current_user = st.session_state.get("current_user")
    email = current_user.get("email") if isinstance(current_user, dict) else "andreasplarno10@gmail.com"
    mode_label = "Modo demo/lab activo" if is_demo_mode() else "Tasacion real disponible"
    api_label = "API conectada" if base_url else "API por configurar"
    docs_url = f"{base_url.rstrip('/')}/docs" if base_url else ""
    docs_action = (
        f'<a class="avm-neo-side-button" href="{html_escape(docs_url)}">'
        "Ver documentacion</a>"
        if docs_url
        else '<span class="avm-neo-side-button avm-neo-side-button--disabled">Sin URL API</span>'
    )
    render_html(
        """
        <div class="avm-neo-side-brand">
            <div class="avm-neo-logo-mark"><span></span></div>
            <div>
                <strong>AVM Chile</strong>
                <p>Tu centro inmobiliario</p>
            </div>
        </div>
        """,
        container=st.sidebar,
    )
    _render_sidebar_nav()
    render_html(
        f"""
        <div class="avm-neo-sidebar">

            <div class="avm-neo-side-card">
                <div class="avm-neo-side-label">Apariencia</div>
                <div class="avm-neo-side-toggle">
                    <span>Modo oscuro</span><i></i>
                </div>
                <p>Tema oficial AVM Chile activo.</p>
            </div>

            <div class="avm-neo-side-link">
                <span>Modo demo</span><b>{html_escape("Activo" if is_demo_mode() else "Inactivo")}</b>
            </div>

            <div class="avm-neo-side-card avm-neo-side-card--ok">
                <div class="avm-neo-side-label">Conectividad</div>
                <strong>{html_escape(api_label)}</strong>
                <p>API: FastAPI<br>Entorno: Produccion<br>{html_escape(base_url)}</p>
                {docs_action}
            </div>

            <div class="avm-neo-side-card">
                <div class="avm-neo-side-label">Cuenta</div>
                <div class="avm-neo-account-row">
                    <em>AP</em><span>{html_escape(email)}</span>
                </div>
                <div class="avm-neo-side-toggle avm-neo-side-toggle--compact">
                    <span>Modo oscuro</span><i></i>
                </div>
            </div>

            <div class="avm-neo-side-card avm-neo-side-card--help">
                <strong>Problemas de conexion?</strong>
                <p>Verifica que FastAPI este corriendo en tu entorno.<br>{html_escape(base_url)}</p>
                {docs_action}
            </div>

            <div class="avm-neo-side-card avm-neo-side-card--premium">
                <strong>Usuarios beta</strong>
                <p>{html_escape(mode_label)}. Variante {html_escape(get_ui_version_label("tasar_playground"))}.</p>
                <span class="avm-neo-side-button avm-neo-side-button--disabled">Ver estado del sistema</span>
            </div>

            <div class="avm-neo-side-footer">AVM Chile &copy; 2024<br>Todos los derechos reservados.</div>
        </div>
        """,
        container=st.sidebar,
    )
    if get_token():
        if st.sidebar.button("Cerrar sesion", key="tasar_pg_logout_button"):
            clear_session()
            st.rerun()
        _render_sidebar_admin_tools(base_url, current_user)


def _render_sidebar_nav() -> None:
    current_page = _current_nav_target()
    render_html('<div class="avm-neo-side-label avm-neo-side-label--menu">Menu</div>', container=st.sidebar)
    for slug, label, page in NAV_ITEMS:
        if st.sidebar.button(
            label,
            key=f"tasar_pg_side_nav_{slug}",
            type="primary" if page == current_page else "secondary",
        ):
            _set_nav_target(page)
            st.rerun()


def _render_sidebar_admin_tools(base_url: str, current_user: Any) -> None:
    if not isinstance(current_user, dict) or current_user.get("role") != "admin":
        return
    token = get_token()
    if token is None:
        return

    client = ApiClient(base_url=base_url)
    with st.sidebar.expander("Usuarios beta", expanded=False):
        with st.form("tasar_pg_create_beta_user_form"):
            email = st.text_input("Email beta", key="tasar_pg_create_beta_email")
            password = st.text_input("Password inicial", type="password", key="tasar_pg_create_beta_password")
            submitted = st.form_submit_button("Crear beta_user")
        if not submitted:
            return
        if not email or not password:
            st.warning("Ingresa email y password.")
            return
        try:
            client.create_user(token, email, password, "beta_user")
        except ApiError as exc:
            st.error(exc.message)
            return
        st.success("Usuario beta_user creado.")


def _current_nav_target() -> str:
    _sync_nav_target_from_query()
    page = st.session_state.get(NAV_TARGET_KEY)
    valid_pages = {target for _slug, _label, target in NAV_ITEMS}
    if isinstance(page, str) and page in valid_pages:
        return page
    st.session_state[NAV_TARGET_KEY] = "Tasar propiedad"
    return "Tasar propiedad"


def _set_nav_target(page: str) -> None:
    valid_pages = {target for _slug, _label, target in NAV_ITEMS}
    target = page if page in valid_pages else "Tasar propiedad"
    st.session_state[NAV_TARGET_KEY] = target


def _sync_nav_target_from_query() -> None:
    try:
        slug = st.query_params.get("neo")
    except Exception:
        return
    if isinstance(slug, list):
        slug = slug[0] if slug else None
    if not slug:
        return
    for item_slug, _label, target in NAV_ITEMS:
        if str(slug) == item_slug:
            st.session_state[NAV_TARGET_KEY] = target
            return


def _nav_label_for_page(page: str) -> str:
    for _slug, label, target in NAV_ITEMS:
        if target == page:
            return label
    return "Tasar"


def render_top_nav(current_user: dict[str, Any] | None) -> str:
    inject_tasar_playground_styles()
    email = (
        current_user.get("email")
        if isinstance(current_user, dict) and current_user.get("email")
        else "andreasplarno10@gmail.com"
    )
    current_page = _current_nav_target()
    current_label = _nav_label_for_page(current_page)
    render_html(
        f"""
        <div class="avm-neo-topbar">
            <div class="avm-neo-topbar__nav">
                <span class="avm-neo-topbar-title">AVM Chile</span>
                <span class="avm-neo-topbar-subtitle">Futuro UI / {html_escape(current_label)}</span>
            </div>
            <div class="avm-neo-topbar__tools">
                <span class="avm-neo-tool-dot">1</span>
                <span class="avm-neo-tool">?</span>
                <span class="avm-neo-tool">o</span>
                <span class="avm-neo-avatar">AP</span>
                <span class="avm-neo-email">{html_escape(email)}</span>
            </div>
        </div>
        """,
    )
    nav_cols = st.columns([1.08, 1.0, 0.86, 0.76, 2.9], gap="small", vertical_alignment="center")
    for index, (slug, label, page) in enumerate(NAV_ITEMS):
        with nav_cols[index]:
            if st.button(
                label,
                key=f"tasar_pg_nav_{slug}",
                type="primary" if page == current_page else "secondary",
            ):
                _set_nav_target(page)
                st.rerun()
    return _current_nav_target()


def render(client: ApiClient) -> None:
    inject_tasar_playground_styles()
    demo_mode = is_demo_mode()
    panel = get_tasar_playground_panel() if demo_mode else {}
    render_hero_banner(panel=panel, demo_mode=demo_mode)
    view_model = _render_main_dashboard(client, panel=panel, demo_mode=demo_mode)
    render_market_footer(panel=panel, demo_mode=demo_mode, view_model=view_model)


def render_hero_banner(*, panel: dict[str, Any], demo_mode: bool) -> None:
    location = panel.get("location", {}) if demo_mode else {}
    chips = ["Datos actualizados", "Modelos avanzados", "Senales de mercado", "Cobertura nacional"]
    chips_html = "".join(f"<span>{html_escape(chip)}</span>" for chip in chips)
    location_html = ""
    if demo_mode:
        location_html = f"""
            <div class="avm-neo-location-pill">
                <i></i>
                <div>
                    <span>{html_escape(location.get("label", "Ubicacion actual"))}</span>
                    <strong>{html_escape(location.get("value", "Providencia, RM"))}</strong>
                </div>
            </div>
        """
    render_html(
        f"""
        <section class="avm-neo-hero">
            <div class="avm-neo-hero__copy">
                <div class="avm-neo-kicker">Fintech inmobiliaria para Chile</div>
                <h1>Tasaci&oacute;n instant&aacute;nea con datos reales.<br>Decide mejor, invierte con confianza.</h1>
                <p>Usamos datos actualizados, modelos avanzados y comparables de mercado para entregarte la mejor estimaci&oacute;n en segundos.</p>
                <div class="avm-neo-chip-row">{chips_html}</div>
            </div>
            <div class="avm-neo-hero-city" aria-hidden="true">
                <i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i>
            </div>
            {location_html}
        </section>
        """,
    )


def _render_main_dashboard(
    client: ApiClient,
    *,
    panel: dict[str, Any],
    demo_mode: bool,
) -> TasarValuationViewModel | None:
    form_col, center_col, right_col = st.columns(
        [1.12, 1.78, 1.1],
        gap="medium",
        vertical_alignment="top",
    )
    with form_col:
        payload, submitted = render_tasar_form(client, demo_mode=demo_mode)

    if submitted:
        _submit_valuation(client, payload, demo_mode=demo_mode)

    result = _current_result()
    saved_payload = st.session_state.get(PAYLOAD_KEY)
    error = st.session_state.get(ERROR_KEY)
    active_payload = saved_payload if isinstance(saved_payload, dict) else payload
    view_model = map_valuation_response_to_view_model(
        result,
        payload=active_payload,
        source="demo" if demo_mode else "real",
    )

    with center_col:
        render_result_panel(
            view_model,
            active_payload,
            error if isinstance(error, dict) else None,
            demo_mode=demo_mode,
        )
        render_location_intelligence(panel=panel, demo_mode=demo_mode, view_model=view_model)
        render_featured_comparables(view_model, demo_mode=demo_mode)

    with right_col:
        render_right_panel(client, view_model, payload=active_payload, panel=panel, demo_mode=demo_mode)

    return view_model


def render_tasar_form(client: ApiClient, *, demo_mode: bool) -> tuple[dict[str, Any], bool]:
    prefill = _form_prefill(demo_mode=demo_mode)
    with st.container(border=True):
        render_section_header("1", "Datos de la propiedad", "Completa los datos para obtener una tasacion precisa.")
        render_tasar_url_lookup(client)
        property_type_label = st.selectbox(
            "Tipo de propiedad",
            ["Departamento", "Casa", "Oficina", "Desconocido"],
            index=_property_type_index(prefill.get("property_type")),
            key="tasar_pg_property_type",
        )
        property_type = property_type_payload_value(property_type_label)

        _prepare_comuna_selector_state(prefill.get("comuna"))
        unknown_comuna = st.session_state.get(UNKNOWN_PREFILL_COMUNA_KEY)
        if unknown_comuna:
            st.warning(
                f'La comuna detectada desde URL ("{unknown_comuna}") no esta en el catalogo. '
                "Selecciona una comuna valida antes de tasar."
            )

        with st.form("tasar_playground_form"):
            comuna = st.selectbox(
                "Comuna",
                COMUNA_OPTION_SLUGS,
                index=_comuna_index(prefill.get("comuna")),
                format_func=_comuna_option_label,
                key="tasar_pg_comuna",
            )
            st.text_input(
                "Direccion o referencia (opcional)",
                value=str(prefill.get("address_label") or prefill.get("url") or ""),
                key="tasar_pg_address_or_url",
            )
            built_area_m2, land_area_m2 = _render_area_inputs(property_type, prefill)

            dormitorios = st.number_input(
                "Dormitorios",
                min_value=0,
                value=int(prefill.get("dormitorios") or prefill.get("bedrooms") or 3),
                step=1,
                key="tasar_pg_dormitorios",
            )
            banos = st.number_input(
                "Banos",
                min_value=0,
                value=int(prefill.get("banos") or prefill.get("bathrooms") or 2),
                step=1,
                key="tasar_pg_banos",
            )
            estacionamientos = st.number_input(
                "Estacionamientos",
                min_value=0,
                value=int(prefill.get("estacionamientos") or prefill.get("parking_spaces") or 1),
                step=1,
                key="tasar_pg_estacionamientos",
            )

            precio_uf = st.number_input(
                "Precio publicado UF (opcional)",
                min_value=0.0,
                value=float(_first_present(prefill, "precio_publicado_uf", "price_uf", default=0.0)),
                step=10.0,
                key="tasar_pg_precio_uf",
            )
            precio_clp = st.number_input(
                "Precio publicado CLP (opcional)",
                min_value=0,
                value=int(_first_present(prefill, "precio_publicado_clp", "price_clp", default=0)),
                step=1_000_000,
                key="tasar_pg_precio_clp",
            )
            st.checkbox("Incluir bodegas", value=False, key="tasar_pg_storage")
            submitted = st.form_submit_button("Tasar propiedad", type="primary")

        render_html('<div class="avm-neo-button-caption">Tasacion en ~15 segundos</div>')

    payload = get_tasar_payload_from_form(
        comuna=_comuna_for_payload(comuna),
        property_type=property_type,
        built_area_m2=float(built_area_m2),
        land_area_m2=float(land_area_m2) if land_area_m2 else None,
        dormitorios=int(dormitorios),
        banos=int(banos),
        estacionamientos=int(estacionamientos),
        precio_uf=float(precio_uf) if precio_uf else None,
        precio_clp=int(precio_clp) if precio_clp else None,
    )
    return payload, submitted


def render_tasar_url_lookup(client: ApiClient) -> None:
    with st.expander("Tasar desde URL de publicacion", expanded=False):
        url = st.text_input("URL Yapo", key="tasar_pg_listing_url")
        if not st.button("Buscar publicacion", type="secondary", key="tasar_pg_lookup_listing_url"):
            return
        try:
            result = client.lookup_listing_url(url, token=get_token())
        except ApiError as exc:
            render_error_state("No pudimos cargar esa URL.", "El flujo real de URL respondio con error.", exc.message)
            return

        result_status = result.get("status")
        listing_data = result.get("listing_data") if isinstance(result.get("listing_data"), dict) else {}
        result_url = str(result.get("url") or url)
        if result_status in {"found_existing", "parsed_new", "partial"}:
            st.session_state[PREFILL_KEY] = listing_data
            _apply_url_prefill_to_tasar_state(listing_data, fallback_url=result_url)
            if result_status == "partial":
                st.warning("Se extrajeron datos parciales. Completa los campos faltantes antes de tasar.")
            else:
                st.success("Publicacion cargada. Revisa los datos antes de tasar.")
            return
        if result_status == "unsupported_source":
            st.warning("Fuente aun no soportada.")
            return
        warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
        detail = ", ".join(str(item) for item in warnings) if warnings else str(result_status)
        render_error_state("No pudimos cargar esa URL.", "El flujo real de URL respondio con error.", detail)


def _apply_url_prefill_to_tasar_state(data: dict[str, Any], *, fallback_url: str) -> None:
    property_type = data.get("property_type")
    if property_type:
        st.session_state["tasar_pg_property_type"] = _property_type_label(property_type)
    if data.get("comuna"):
        _set_comuna_state_from_prefill(data.get("comuna"))
    if data.get("built_area_m2") or data.get("m2"):
        st.session_state["tasar_pg_built_area_m2"] = float(data.get("built_area_m2") or data.get("m2"))
    if data.get("land_area_m2"):
        st.session_state["tasar_pg_land_area_m2"] = float(data.get("land_area_m2"))
    for source_key, widget_key in [
        ("dormitorios", "tasar_pg_dormitorios"),
        ("banos", "tasar_pg_banos"),
        ("estacionamientos", "tasar_pg_estacionamientos"),
    ]:
        value = _safe_int(data.get(source_key))
        if value is not None:
            st.session_state[widget_key] = value
    price_uf = _safe_float(_first_present(data, "precio_publicado_uf", "price_uf"))
    if price_uf is not None:
        st.session_state["tasar_pg_precio_uf"] = price_uf
    price_clp = _safe_int(_first_present(data, "precio_publicado_clp", "price_clp"))
    if price_clp is not None:
        st.session_state["tasar_pg_precio_clp"] = price_clp
    st.session_state["tasar_pg_address_or_url"] = str(data.get("url") or data.get("address_label") or fallback_url)


def _prepare_comuna_selector_state(prefill_value: Any) -> None:
    current = st.session_state.get("tasar_pg_comuna")
    current_slug = _resolve_comuna_slug(current)
    if current_slug:
        st.session_state["tasar_pg_comuna"] = current_slug
        return

    prefill_slug = _resolve_comuna_slug(prefill_value)
    if prefill_slug:
        st.session_state["tasar_pg_comuna"] = prefill_slug
        st.session_state.pop(UNKNOWN_PREFILL_COMUNA_KEY, None)
        return

    if prefill_value:
        st.session_state[UNKNOWN_PREFILL_COMUNA_KEY] = str(prefill_value)
    st.session_state["tasar_pg_comuna"] = DEFAULT_COMUNA_SLUG


def _set_comuna_state_from_prefill(value: Any) -> None:
    slug = _resolve_comuna_slug(value)
    if slug:
        st.session_state["tasar_pg_comuna"] = slug
        st.session_state.pop(UNKNOWN_PREFILL_COMUNA_KEY, None)
        return

    st.session_state[UNKNOWN_PREFILL_COMUNA_KEY] = str(value)
    current_slug = _resolve_comuna_slug(st.session_state.get("tasar_pg_comuna"))
    st.session_state["tasar_pg_comuna"] = current_slug or DEFAULT_COMUNA_SLUG


def _render_area_inputs(property_type: str, prefill: dict[str, Any]) -> tuple[float, float | None]:
    if property_type == "house":
        area_col, land_col = st.columns(2, gap="small")
        built_area_m2 = area_col.number_input(
            "Superficie construida (m2)",
            min_value=1.0,
            value=float(prefill.get("built_area_m2") or prefill.get("m2") or 75.0),
            step=1.0,
            key="tasar_pg_built_area_m2",
        )
        land_area_m2 = land_col.number_input(
            "Superficie terreno (m2)",
            min_value=1.0,
            value=float(prefill.get("land_area_m2") or 180.0),
            step=1.0,
            key="tasar_pg_land_area_m2",
        )
        return float(built_area_m2), float(land_area_m2)

    built_area_m2 = st.number_input(
        "Superficie util (m2)",
        min_value=1.0,
        value=float(prefill.get("built_area_m2") or prefill.get("m2") or 75.0),
        step=1.0,
        key="tasar_pg_built_area_m2",
    )
    return float(built_area_m2), None


def render_result_panel(
    view_model: TasarValuationViewModel | None,
    payload: dict[str, Any],
    error: dict[str, Any] | None,
    *,
    demo_mode: bool,
) -> None:
    with st.container(border=True):
        render_result_header(view_model=view_model, demo_mode=demo_mode)
        if error:
            render_error_state(
                "No se pudo obtener la tasacion.",
                "La API devolvio un error real para esta solicitud.",
                str(error.get("message") or ""),
            )
            return
        if view_model is None:
            render_empty_state("Ingresa los datos de la propiedad para obtener una estimacion.")
            return
        if not view_model.has_result:
            render_empty_state("La tasacion respondio, pero no incluyo un valor estimado para mostrar.")
            _render_view_model_warnings(view_model)
            return

        confidence = view_model.confidence_key
        confidence_text = format_confidence(view_model.confidence_label or view_model.confidence)
        score = _confidence_score_from_view_model(view_model)
        estimate_uf_label = format_uf(view_model.estimated_value_uf).replace(",00", "")
        model_caption = "Datos simulados demo/lab" if view_model.is_demo else "Respuesta real de API"
        render_html(
            f"""
            <div class="avm-neo-value-grid">
                <div class="avm-neo-estimate-main">
                    <span>Valor estimado</span>
                    <strong>{html_escape(estimate_uf_label)}</strong>
                    <p>{html_escape(format_clp(view_model.estimated_value_clp))}</p>
                </div>
                <div class="avm-neo-confidence-box">
                    <span>Confianza del modelo</span>
                    <div class="avm-neo-confidence-ring avm-neo-confidence-ring--{html_escape(confidence)}">
                        <strong>{html_escape(score)}</strong>
                    </div>
                    <b>{html_escape(confidence_text)}</b>
                    <small>{html_escape(model_caption)}</small>
                </div>
                <div class="avm-neo-distribution">
                    <span>Distribucion de valor (UF)</span>
                    {build_value_distribution_html(_view_model_result_dict(view_model))}
                </div>
            </div>
            """,
        )
        metrics = [
            ("Rango estimado", _range_label_from_view_model(view_model), _range_clp_label_from_view_model(view_model)),
            ("Precio UF/m2", _price_m2_label_from_view_model(view_model), _price_m2_clp_label_from_view_model(view_model)),
        ]
        render_html(build_metric_strip_html(metrics))
        render_confidence_bar(view_model)
        _render_view_model_warnings(view_model)


def render_result_header(*, view_model: TasarValuationViewModel | None, demo_mode: bool) -> None:
    badge = "Demo/lab" if view_model and view_model.is_demo else "Modelo AVM"
    timestamp = "Resultado demo simulado" if view_model and view_model.is_demo else "Respuesta real al tasar"
    if view_model is None:
        timestamp = "Sin resultado aun"
        badge = "Demo/lab" if demo_mode else "Modelo AVM"
    render_html(
        f"""
        <div class="avm-neo-result-head">
            <div class="avm-neo-section-head avm-neo-section-head--inline">
                <span>2</span>
                <div>
                    <strong>Valor estimado</strong>
                    <p>{html_escape(timestamp)}</p>
                </div>
            </div>
            <div class="avm-neo-premium-badge">{html_escape(badge)}</div>
        </div>
        """,
    )


def render_location_intelligence(
    *,
    panel: dict[str, Any],
    demo_mode: bool,
    view_model: TasarValuationViewModel | None,
) -> None:
    with st.container(border=True):
        render_section_header("3", "Ubicacion e inteligencia", "Analisis de entorno y conectividad.")
        if view_model is None:
            render_empty_state("Ejecuta una tasacion para cargar inteligencia local disponible.")
            return
        if not view_model.is_demo:
            render_location_intelligence_contract(view_model.location_intelligence)
            return
        location = panel.get("location", {})
        render_html(
            f"""
            <div class="avm-neo-map">
                <div class="avm-neo-map-grid"></div>
                <div class="avm-neo-map-radius"></div>
                <div class="avm-neo-map-pin"></div>
                <span>{html_escape(location.get("radius", "R 400m"))}</span>
            </div>
            <div class="avm-neo-map-stats">
                <div><span>Entorno</span><strong>{html_escape(location.get("environment"))}</strong></div>
                <div><span>Conectividad</span><strong>{html_escape(location.get("connectivity"))}</strong></div>
                <div><span>Servicios</span><strong>{html_escape(location.get("services"))}</strong></div>
            </div>
            """,
        )


def render_location_intelligence_contract(location: TasarLocationIntelligence) -> None:
    badge = {
        "available": "Backend real",
        "partial": "Datos parciales",
        "not_available": "No disponible",
    }.get(location.status, "No disponible")
    tone = {
        "available": "positive",
        "partial": "warning",
        "not_available": "neutral",
    }.get(location.status, "neutral")
    warning_labels = tuple(detail.human_label for detail in location.location_warnings)
    signals = location.geo_signals[:3]
    missing = tuple(_location_reason_label(reason) for reason in location.reasons[:3])
    metrics = [
        ("Comuna analizada", _display_value(_comuna_label(location.comuna)), "Backend real"),
        ("Calidad ubicacion", _display_value(location.comparable_location_quality), _display_value(location.geocoding_precision)),
        ("Microzona", _microzone_status_label(location.microzone_status), "Estado disponible"),
        ("Comparables usados", str(location.comparable_count) if location.comparable_count is not None else "N/D", "Respuesta API"),
    ]
    rows = "".join(
        f"""
        <div class="avm-neo-location-metric">
            <span>{html_escape(label)}</span>
            <strong>{html_escape(value)}</strong>
            <p>{html_escape(caption)}</p>
        </div>
        """
        for label, value, caption in metrics
    )
    details = []
    if location.address_label:
        details.append(("Referencia", location.address_label))
    if location.coordinates is not None:
        details.append(("Coordenadas", f"{location.coordinates[0]:.5f}, {location.coordinates[1]:.5f}"))
    if signals:
        details.append(("Senales detectadas", ", ".join(signals)))
    if warning_labels:
        details.append(("Advertencias de ubicacion", "; ".join(warning_labels[:3])))
    if missing:
        details.append(("Datos faltantes", "; ".join(missing)))
    detail_rows = "".join(
        f"""
        <div class="avm-neo-location-row">
            <span>{html_escape(label)}</span>
            <strong>{html_escape(value)}</strong>
        </div>
        """
        for label, value in details
    )
    if not detail_rows:
        detail_rows = """
        <div class="avm-neo-location-row">
            <span>Estado</span>
            <strong>Sin datos territoriales suficientes en esta respuesta.</strong>
        </div>
        """
    render_html(
        f"""
        <div class="avm-neo-location-card avm-neo-location-card--{html_escape(tone)}">
            <div class="avm-neo-location-card__head">
                <div>
                    <span>{html_escape(badge)}</span>
                    <strong>{html_escape(location.summary)}</strong>
                </div>
                <em>{html_escape(location.status)}</em>
            </div>
            <div class="avm-neo-location-grid">{rows}</div>
            <div class="avm-neo-location-detail">{detail_rows}</div>
        </div>
        """,
    )


def render_featured_comparables(view_model: TasarValuationViewModel | None, *, demo_mode: bool) -> None:
    comparables = list(view_model.comparables) if view_model else []
    count = view_model.comparable_count if view_model and view_model.comparable_count is not None else len(comparables)
    source_label = "Demo/lab" if view_model and view_model.is_demo else "Respuesta API"
    with st.container(border=True):
        render_html(
            f"""
            <div class="avm-neo-comparable-head">
                <div class="avm-neo-section-head avm-neo-section-head--inline">
                    <span>4</span>
                    <div>
                        <strong>Comparables destacados</strong>
                        <p>Basado en propiedades similares.</p>
                    </div>
                </div>
                <span>{html_escape(source_label)}</span>
            </div>
            """,
        )
        if not comparables:
            render_empty_state("No hay comparables disponibles para esta busqueda.")
            return
        show_all = bool(st.session_state.get(SHOW_ALL_COMPARABLES_KEY))
        total_label = count if count is not None else len(comparables)
        button_label = "Ocultar comparables" if show_all else f"Ver todas ({total_label})"
        if st.button(button_label, key="tasar_pg_toggle_comparables"):
            st.session_state[SHOW_ALL_COMPARABLES_KEY] = not show_all
            st.rerun()
        if show_all and len(comparables) <= 4:
            st.caption("Mostrando todos los comparables disponibles en la respuesta.")
        visible_count = len(comparables) if st.session_state.get(SHOW_ALL_COMPARABLES_KEY) else 4
        for index, item in enumerate(comparables[:visible_count], start=1):
            render_comparable_card(item, index=index, compact=False)


def render_right_panel(
    client: ApiClient,
    view_model: TasarValuationViewModel | None,
    *,
    payload: dict[str, Any],
    panel: dict[str, Any],
    demo_mode: bool,
) -> None:
    if view_model is None:
        with st.container(border=True):
            render_section_title("Panel contextual")
            render_status_badge("Estado inicial", "empty", "Ejecuta una tasacion para poblar indicadores conectados.")
            render_status_badge("Tendencia de precio", "coming_soon", "Modulo futuro, sin datos fabricados.")
            render_status_badge("Risk Report", "coming_soon", "Disponible cuando la ruta quede conectada.")
        return

    if not view_model.is_demo:
        risk_report = build_tasar_risk_report_contract(
            view_model,
            payload=payload,
            lookup_result=_risk_report_lookup_context(),
        )
        render_price_trend(_load_price_m2_trend(client, payload))
        render_confidence_summary(view_model)
        render_response_signals(view_model)
        render_recent_activity(_load_recent_user_activity(client))
        render_risk_opportunity(risk_report)
        return

    render_price_trend(panel.get("price_trend", {}), demo_mode=True)
    render_confidence_summary(view_model, panel=panel)
    render_market_signals(panel.get("market_signals", []))
    render_recent_activity(panel.get("recent_activity", []))
    render_risk_opportunity(panel.get("risk", {}))


def _load_price_m2_trend(client: ApiClient, payload: dict[str, Any]) -> dict[str, Any]:
    comuna = str(payload.get("comuna") or "").strip()
    property_type = str(payload.get("property_type") or "").strip()
    if not comuna or not property_type:
        return {
            "status": "not_available",
            "period_months": 12,
            "reasons": ["missing_trend_inputs"],
        }
    try:
        return client.get_price_m2_trend(
            comuna=comuna,
            property_type=property_type,
            period_months=12,
            token=get_token(),
        )
    except ApiError as exc:
        return {
            "status": "not_available",
            "period_months": 12,
            "reasons": [str(exc.message or "trend_api_unavailable")],
        }


def render_price_trend(trend: dict[str, Any], *, demo_mode: bool = False) -> None:
    with st.container(border=True):
        trend = _normalize_price_trend_for_chart(trend)
        period = str(trend.get("period", "12 meses"))
        action = f"Demo/lab - {period}" if demo_mode and trend.get("values") else period
        render_panel_header(str(trend.get("title", "Tendencia de precio (UF/m2)")), action)
        if not trend.get("values"):
            status = str(trend.get("status") or "not_available")
            reason = _trend_reason_label(trend)
            render_status_badge(
                "Tendencia de precio",
                status,
                f"Tendencia no disponible con datos suficientes para esta comuna/tipo. {reason}",
            )
            return
        render_html(build_trend_chart_html(trend))
        render_html(_price_trend_meta_html(trend))


def render_confidence_summary(view_model: TasarValuationViewModel, *, panel: dict[str, Any] | None = None) -> None:
    data = (panel or {}).get("confidence", {})
    score = data.get("score") or _confidence_score_from_view_model(view_model)
    label = data.get("value") or format_confidence(view_model.confidence_label or view_model.confidence)
    detail = data.get("detail") or ("Datos simulados demo/lab" if view_model.is_demo else "Respuesta real de API")
    ring_class = view_model.confidence_key
    with st.container(border=True):
        render_html(
            f"""
            <div class="avm-neo-confidence-summary">
                <div>
                    <span>Nivel de confianza</span>
                    <strong>{html_escape(label)}</strong>
                    <p>{html_escape(detail)}</p>
                    <span class="avm-neo-disabled-link">Detalle proximamente</span>
                </div>
                <div class="avm-neo-confidence-ring avm-neo-confidence-ring--{html_escape(ring_class)}">
                    <strong>{html_escape(score)}</strong>
                </div>
            </div>
            """,
        )


def render_market_signals(signals: list[dict[str, Any]]) -> None:
    with st.container(border=True):
        render_section_title("Senales de mercado")
        if not signals:
            render_empty_state("No hay senales de mercado disponibles para esta tasacion.")
            return
        rows = "".join(
            f"""
            <div class="avm-neo-signal-row avm-neo-signal-row--{html_escape(str(item.get("tone", "neutral")))}">
                <span>{html_escape(item.get("label"))}</span>
                <strong>{html_escape(item.get("value"))}</strong>
                <small>{html_escape(item.get("delta"))}</small>
            </div>
            """
            for item in signals
        )
        render_html(f'<div class="avm-neo-signal-stack">{rows}</div>')


def render_response_signals(view_model: TasarValuationViewModel) -> None:
    with st.container(border=True):
        render_section_title("Senales de la respuesta")
        items = [
            {
                "tone": "positive" if view_model.comparables else "neutral",
                "label": "Comparables recibidos",
                "value": str(view_model.comparable_count if view_model.comparable_count is not None else len(view_model.comparables)),
                "delta": "Backend/API",
            },
            {
                "tone": "neutral",
                "label": "Precio UF/m2",
                "value": _price_m2_label_from_view_model(view_model),
                "delta": "Campo price_m2_uf",
            },
            {
                "tone": "negative" if view_model.warnings else "positive",
                "label": "Detalles tecnicos",
                "value": str(len(view_model.warnings)),
                "delta": "Backend/API",
            },
        ]
        rows = "".join(
            f"""
            <div class="avm-neo-signal-row avm-neo-signal-row--{html_escape(str(item.get("tone", "neutral")))}">
                <span>{html_escape(item.get("label"))}</span>
                <strong>{html_escape(item.get("value"))}</strong>
                <small>{html_escape(item.get("delta"))}</small>
            </div>
            """
            for item in items
        )
        render_html(f'<div class="avm-neo-signal-stack">{rows}</div>')


def render_recent_activity(activity: list[dict[str, Any]] | dict[str, Any]) -> None:
    with st.container(border=True):
        normalized = _normalize_recent_activity(activity)
        events = normalized.get("events", [])
        source_label = "Demo/lab" if normalized.get("is_demo") else _activity_status_label(normalized)
        render_panel_header("Actividad reciente", source_label)
        if normalized.get("status") == "not_available":
            render_status_badge(
                "Actividad reciente",
                "not_available",
                "No pudimos cargar tu actividad reciente. La tasacion sigue disponible.",
            )
            return
        if not events:
            render_status_badge(
                "Actividad reciente",
                "empty",
                "No hay actividad reciente registrada todavia. Realiza una tasacion para empezar a ver tu historial.",
            )
            return
        rows = "".join(
            f"""
            <div class="avm-neo-activity-row">
                <i></i><span>{html_escape(item.get("title") or item.get("label"))}<br><small>{html_escape(item.get("description") or "")}</small></span><small>{html_escape(_activity_time_label(item))}</small>
            </div>
            """
            for item in events[:3]
        )
        render_html(f'<div class="avm-neo-activity-stack">{rows}</div>')


def _load_recent_user_activity(client: ApiClient) -> dict[str, Any]:
    token = get_token()
    if token is None:
        return {
            "status": "not_available",
            "events": [],
            "reasons": ["missing_auth_token"],
        }
    try:
        return client.get_tasar_recent_activity(token=token, limit=3)
    except ApiError as exc:
        return {
            "status": "not_available",
            "events": [],
            "reasons": [str(exc.message or "activity_api_unavailable")],
        }


def _normalize_recent_activity(activity: list[dict[str, Any]] | dict[str, Any]) -> dict[str, Any]:
    if isinstance(activity, dict):
        events = activity.get("events")
        return {
            **activity,
            "events": list(events) if isinstance(events, list) else [],
        }
    return {
        "status": "available" if activity else "empty",
        "events": list(activity),
        "is_demo": bool(activity),
    }


def _activity_status_label(activity: dict[str, Any]) -> str:
    status = str(activity.get("status") or "empty")
    if status == "available":
        return "Historial real"
    if status == "partial":
        return "Historial parcial"
    if status == "empty":
        return "Sin actividad"
    return "No disponible"


def _activity_time_label(item: dict[str, Any]) -> str:
    explicit = item.get("time")
    if explicit:
        return str(explicit)
    occurred_at = str(item.get("occurred_at") or "")
    if not occurred_at:
        return ""
    return occurred_at.replace("T", " ")[:16]


def render_risk_opportunity(risk: dict[str, Any] | TasarRiskReportContract) -> None:
    with st.container(border=True):
        render_section_title("Oportunidad / Riesgo")
        if isinstance(risk, TasarRiskReportContract):
            if not risk.risk_report_available or not risk.risk_report_html:
                render_status_badge("Risk Report", risk.risk_report_status, _risk_report_status_body(risk))
                return
            render_html(
                f"""
                <div class="avm-neo-risk-box">
                    <i>!</i>
                    <div>
                        <strong>Reportes HTML</strong>
                        <p>Reportes reales generados con la tasacion actual.<br>{html_escape(risk.generated_at or "Generado en esta sesion")}</p>
                    </div>
                    <span>&gt;</span>
                </div>
                """,
            )
            if risk.investment_report_html:
                st.download_button(
                    "Descargar Investment Intelligence Report",
                    data=risk.investment_report_html,
                    file_name=risk.investment_file_name or f"investment_intelligence_report_{_risk_report_file_suffix()}.html",
                    mime="text/html",
                    key="tasar-playground-investment-report-download",
                )
            if risk.listing_report_html:
                st.download_button(
                    "Descargar Listing Risk Report",
                    data=risk.listing_report_html,
                    file_name=risk.listing_file_name or f"listing_risk_report_{_risk_report_file_suffix()}.html",
                    mime="text/html",
                    key="tasar-playground-listing-risk-report-download",
                )
            return
        if not risk:
            render_status_badge("Risk Report", "coming_soon", "No hay reporte de riesgo conectado a la ruta Tasar.")
            return
        render_html(
            f"""
            <div class="avm-neo-risk-box">
                <i>!</i>
                <div>
                    <strong>{html_escape(risk.get("label"))}</strong>
                    <p>{html_escape(risk.get("body"))}<br>{html_escape(risk.get("detail"))}</p>
                </div>
                <span>&gt;</span>
            </div>
            """,
        )


def render_market_footer(
    *,
    panel: dict[str, Any],
    demo_mode: bool,
    view_model: TasarValuationViewModel | None,
) -> None:
    if view_model is None:
        render_html(
            """
            <div class="avm-neo-market-footer avm-neo-market-footer--empty">
                <span>Resumen de tasacion</span>
                <strong>Sin resultado aun</strong>
                <p>El resumen se completa despues de ejecutar Tasar propiedad.</p>
            </div>
            """,
        )
        return

    if view_model.is_demo:
        footer = panel.get("market_footer", {})
        items = footer.get("items", [])
        footer_label = f"Demo/lab - {footer.get('label', 'Resumen simulado')}"
        metrics = "".join(
            f"""
            <div class="avm-neo-footer-kpi avm-neo-footer-kpi--{html_escape(str(item.get("tone", "neutral")))}">
                <span>{html_escape(item.get("label"))}</span>
                <strong>{html_escape(item.get("value"))}</strong>
                <p>{html_escape(item.get("delta"))}</p>
            </div>
            """
            for item in items
        )
    else:
        footer_label = f"Resumen real - {_comuna_label(view_model.payload.get('comuna'))}"
        items = _footer_items_from_view_model(view_model)
        metrics = "".join(
            f"""
            <div class="avm-neo-footer-kpi avm-neo-footer-kpi--{html_escape(str(item.get("tone", "neutral")))}">
                <span>{html_escape(item.get("label"))}</span>
                <strong>{html_escape(item.get("value"))}</strong>
                <p>{html_escape(item.get("delta"))}</p>
            </div>
            """
            for item in items
        )
    footer_col, action_col = st.columns([0.84, 0.16], gap="small", vertical_alignment="center")
    with footer_col:
        render_html(
            f"""
            <div class="avm-neo-market-footer">
                <div class="avm-neo-footer-title">{html_escape(footer_label)}</div>
                {metrics}
            </div>
            """,
        )
    with action_col:
        render_html('<div class="avm-neo-market-action-kicker">Radar conectado</div>')
        if st.button("Explorar en Radar", key="tasar_pg_explore_radar"):
            _set_nav_target("Radar")
            st.rerun()


def render_section_header(step: str, title: str, subtitle: str) -> None:
    render_html(
        f"""
        <div class="avm-neo-section-head">
            <span>{html_escape(step)}</span>
            <div>
                <strong>{html_escape(title)}</strong>
                <p>{html_escape(subtitle)}</p>
            </div>
        </div>
        """,
    )


def render_section_title(title: str) -> None:
    render_html(f'<div class="avm-neo-panel-title">{html_escape(title)}</div>')


def render_panel_header(title: str, action: str) -> None:
    render_html(
        f"""
        <div class="avm-neo-panel-header">
            <strong>{html_escape(title)}</strong>
            <span>{html_escape(action)}</span>
        </div>
        """,
    )


def render_status_badge(title: str, state: str, body: str) -> None:
    render_html(
        f"""
        <div class="avm-neo-status avm-neo-status--{html_escape(state)}">
            <span>{html_escape(state)}</span>
            <strong>{html_escape(title)}</strong>
            <p>{html_escape(body)}</p>
        </div>
        """,
    )


def render_empty_state(message: str) -> None:
    render_html(
        f"""
        <div class="avm-neo-empty">
            <strong>{html_escape(message)}</strong>
            <p>El panel se actualizara cuando existan datos reales o demo/lab para esta sesion.</p>
        </div>
        """,
    )


def render_error_state(title: str, body: str, detail: str) -> None:
    detail_html = f"<p>{html_escape(detail)}</p>" if detail else ""
    render_html(
        f"""
        <div class="avm-neo-error">
            <strong>{html_escape(title)}</strong>
            <span>{html_escape(body)}</span>
            {detail_html}
        </div>
        """,
    )


def _display_value(value: Any) -> str:
    text = str(value or "").strip()
    return text if text and text.lower() not in {"none", "n/a"} else "N/D"


def _microzone_status_label(status: str) -> str:
    labels = {
        "available": "Disponible",
        "limited": "Limitada",
        "not_available": "No disponible",
    }
    return labels.get(str(status or ""), str(status or "No disponible"))


def _location_reason_label(reason: str) -> str:
    labels = {
        "no_geocoding_data": "sin geocoding en respuesta",
        "no_microzone_data": "sin microzona",
        "no_geo_signals": "sin senales geograficas",
        "insufficient_location_coverage": "cobertura territorial insuficiente",
        "no_location_data": "sin datos de ubicacion",
        "demo_data_not_used_as_real_location_intelligence": "demo/lab no usado como dato real",
    }
    return labels.get(reason, reason)


def _normalize_price_trend_for_chart(trend: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(trend, dict):
        return {}
    if trend.get("values"):
        return trend
    points = trend.get("points") if isinstance(trend.get("points"), list) else []
    values = [
        _safe_float(point.get("median_price_m2_uf"))
        for point in points
        if isinstance(point, dict) and _safe_float(point.get("median_price_m2_uf")) is not None
    ]
    if not values:
        return dict(trend)
    labels = [
        str(point.get("month"))
        for point in points
        if isinstance(point, dict) and _safe_float(point.get("median_price_m2_uf")) is not None
    ]
    status = str(trend.get("status") or "partial")
    period_months = int(_safe_float(trend.get("period_months")) or 12)
    return {
        **trend,
        "title": "Tendencia de precio (UF/m2)",
        "period": f"{period_months} meses",
        "values": values,
        "labels": labels,
        "status": status,
    }


def _price_trend_meta_html(trend: dict[str, Any]) -> str:
    latest = _safe_float(trend.get("latest_value"))
    change = _safe_float(trend.get("change_pct"))
    latest_label = f"UF {latest:.2f}/m2" if latest is not None else "N/D"
    change_label = f"{change:+.2f}%" if change is not None else "Sin variacion"
    coverage = str(trend.get("coverage_count") or 0)
    source = str(trend.get("source") or "not_available")
    status = str(trend.get("status") or "partial")
    return f"""
        <div class="avm-neo-trend-meta">
            <div><span>Ultimo valor</span><strong>{html_escape(latest_label)}</strong></div>
            <div><span>Variacion</span><strong>{html_escape(change_label)}</strong></div>
            <div><span>Muestras</span><strong>{html_escape(coverage)}</strong></div>
            <div><span>Fuente</span><strong>{html_escape(source)} - {html_escape(status)}</strong></div>
        </div>
    """


def _trend_reason_label(trend: dict[str, Any]) -> str:
    reasons = trend.get("reasons") if isinstance(trend.get("reasons"), list) else []
    if not reasons:
        return ""
    labels = {
        "insufficient_price_history": "Historial de precios insuficiente.",
        "insufficient_monthly_points": "Faltan puntos mensuales reales.",
        "insufficient_sample_count": "Muestras mensuales insuficientes.",
        "missing_canonical_price": "Faltan precios UF canonicos.",
        "missing_surface": "Falta superficie para calcular UF/m2.",
        "only_artifact_history": "El historial disponible es artifact.",
        "unsupported_property_type": "Tipo de propiedad no soportado.",
        "unsupported_comuna": "Comuna no soportada.",
        "missing_trend_inputs": "Faltan comuna o tipo de propiedad.",
    }
    return labels.get(str(reasons[0]), str(reasons[0]))


def render_confidence_bar(view_model: TasarValuationViewModel) -> None:
    confidence = view_model.confidence_key
    label = format_confidence(view_model.confidence_label or view_model.confidence)
    pct = _confidence_pct_from_view_model(view_model, confidence)
    caption = (
        "Resultado simulado para explorar la experiencia demo/lab."
        if view_model.is_demo
        else "Resultado generado por el backend para los datos ingresados."
    )
    render_html(
        f"""
        <div class="avm-neo-confidence-bar">
            <div>
                <strong>Nivel de confianza del modelo</strong>
                <span>{html_escape(label)}</span>
            </div>
            <div class="avm-neo-confidence-track">
                <span style="width:{pct}%"></span>
            </div>
            <p>{html_escape(caption)}</p>
        </div>
        """,
    )


def _render_view_model_warnings(view_model: TasarValuationViewModel) -> None:
    if view_model.errors:
        rows = "".join(f"<p>{html_escape(message)}</p>" for message in view_model.errors[:4])
        render_html(
            f"""
            <div class="avm-neo-status">
                <span>{html_escape("demo/lab" if view_model.is_demo else "backend")}</span>
                <strong>Errores de la respuesta</strong>
                {rows}
            </div>
            """,
        )
        return

    summary = view_model.warning_summary
    if summary.count <= 0:
        return

    render_html(
        f"""
        <div class="avm-neo-status avm-neo-warning-summary">
            <span>{html_escape("demo/lab" if view_model.is_demo else "backend")}</span>
            <strong>{html_escape(summary.headline)}</strong>
            <p>Los codigos tecnicos quedan disponibles para auditoria sin dominar la lectura principal.</p>
        </div>
        """,
    )
    with st.expander(summary.details_label, expanded=False):
        rows = "".join(
            f"""
            <div class="avm-neo-warning-detail">
                <div>
                    <strong>{html_escape(detail.human_label)}</strong>
                    <p>{html_escape(detail.short_description)}</p>
                </div>
                <span>{html_escape(detail.severity)} - {html_escape(detail.category)}</span>
                <code>{html_escape(detail.code)}</code>
            </div>
            """
            for detail in summary.details
        )
        render_html(f'<div class="avm-neo-warning-detail-stack">{rows}</div>')


def render_comparable_card(item: TasarComparableViewModel | dict[str, Any], *, index: int, compact: bool) -> None:
    data = _comparable_to_dict(item)
    title = str(data.get("title") or data.get("address_label") or "Comparable activo")
    comuna = _comuna_label(data.get("comuna"))
    price = format_uf(data.get("price_uf") or data.get("precio_uf"))
    surface = format_m2(data.get("m2") or data.get("built_area_m2"))
    program = _program_label(data)
    date = str(data.get("date") or data.get("detected_at") or "")
    distance = str(data.get("distance") or "")
    compact_class = " avm-neo-comparable--compact" if compact else ""
    render_html(
        f"""
        <div class="avm-neo-comparable{compact_class}">
            <div class="avm-neo-comparable-thumb avm-neo-comparable-thumb--{index % 4}"></div>
            <div>
                <strong>{html_escape(title)}</strong>
                <span>{html_escape(comuna)}</span>
                <p>{html_escape(surface)} - {html_escape(program)}</p>
            </div>
            <div>
                <strong>{html_escape(price)}</strong>
                <span>{html_escape(date)}</span>
                <p>{html_escape(distance)}</p>
            </div>
        </div>
        """,
    )


def build_metric_strip_html(metrics: list[tuple[str, str, str]]) -> str:
    rows = "".join(
        f"""
        <div class="avm-neo-result-metric">
            <span>{html_escape(label)}</span>
            <strong>{html_escape(value)}</strong>
            <p>{html_escape(caption)}</p>
        </div>
        """
        for label, value, caption in metrics
    )
    return f'<div class="avm-neo-result-metrics">{rows}</div>'


def build_value_distribution_html(result: dict[str, Any]) -> str:
    low = _safe_float(result.get("price_range_low_uf"))
    estimate = _safe_float(result.get("estimated_price_uf") or result.get("estimated_value_uf"))
    high = _safe_float(result.get("price_range_high_uf"))
    if low is None or estimate is None or high is None or high <= low:
        return '<div class="avm-neo-dist-empty">Distribucion no disponible.</div>'
    position = max(0.0, min(100.0, ((estimate - low) / (high - low)) * 100))
    labels = [
        format_uf(low).replace("UF ", ""),
        format_uf(estimate).replace("UF ", ""),
        format_uf(high).replace("UF ", ""),
    ]
    return f"""
        <div class="avm-neo-bell">
            <svg viewBox="0 0 220 98" role="img" aria-label="Distribucion de valor">
                <defs>
                    <linearGradient id="neoBellGradient" x1="0" x2="1" y1="0" y2="0">
                        <stop offset="0%" stop-color="#7437ff" stop-opacity="0.25" />
                        <stop offset="52%" stop-color="#7b3cff" stop-opacity="0.82" />
                        <stop offset="100%" stop-color="#16b7ff" stop-opacity="0.28" />
                    </linearGradient>
                </defs>
                <path d="M15 88 C42 88 54 72 72 45 C88 20 99 12 110 12 C124 12 136 25 151 52 C166 78 181 88 205 88 L15 88 Z" fill="url(#neoBellGradient)" />
                <path d="M15 88 C42 88 54 72 72 45 C88 20 99 12 110 12 C124 12 136 25 151 52 C166 78 181 88 205 88" fill="none" stroke="#24baff" stroke-width="2" />
                <line x1="{position * 2.0 + 10:.1f}" y1="16" x2="{position * 2.0 + 10:.1f}" y2="90" stroke="#9fb8ff" stroke-opacity="0.52" />
                <circle cx="{position * 2.0 + 10:.1f}" cy="18" r="7" fill="#2d8cff" stroke="#eff6ff" stroke-width="2" />
            </svg>
            <div class="avm-neo-bell-labels">
                <span>{html_escape(labels[0])}</span><span>{html_escape(labels[1])}</span><span>{html_escape(labels[2])}</span>
            </div>
        </div>
    """


def build_trend_chart_html(trend: dict[str, Any]) -> str:
    values = [_safe_float(value) or 0 for value in trend.get("values", [])]
    labels = [str(label) for label in trend.get("labels", [])]
    if not values:
        return '<div class="avm-neo-trend-empty">Sin tendencia disponible.</div>'
    minimum = min(values)
    maximum = max(values)
    spread = maximum - minimum or 1
    points: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        x = 12 + index * (196 / max(1, len(values) - 1))
        y = 92 - ((value - minimum) / spread) * 58
        points.append((x, y))
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    circles = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" />' for x, y in points)
    label_step = max(1, len(labels) // 6)
    label_html = "".join(f"<span>{html_escape(label)}</span>" for index, label in enumerate(labels) if index % label_step == 0)
    return f"""
        <div class="avm-neo-trend-chart">
            <svg viewBox="0 0 220 112" role="img" aria-label="Tendencia de precio">
                <path d="M10 92 H212" stroke="#1b3554" />
                <path d="M10 70 H212" stroke="#102945" />
                <path d="M10 48 H212" stroke="#102945" />
                <path d="M10 26 H212" stroke="#102945" />
                <polyline points="{polyline}" fill="none" stroke="#8748ff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
                <polygon points="12,94 {polyline} 208,94" fill="rgba(101, 61, 255, 0.16)" />
                <g fill="#9157ff" stroke="#cbd7ff" stroke-width="1.3">{circles}</g>
            </svg>
            <div class="avm-neo-trend-labels">{label_html}</div>
        </div>
    """


def _submit_valuation(client: ApiClient, payload: dict[str, Any], *, demo_mode: bool) -> None:
    st.session_state.pop(ERROR_KEY, None)
    st.session_state.pop(RESULT_KEY, None)
    if not str(payload.get("comuna") or "").strip():
        st.session_state[ERROR_KEY] = {"message": "Completa la comuna antes de tasar.", "status_code": None}
        return
    if _safe_float(payload.get("built_area_m2") or payload.get("m2")) is None:
        st.session_state[ERROR_KEY] = {"message": "Completa la superficie antes de tasar.", "status_code": None}
        return
    mode = "demo" if demo_mode else "real"
    properties = {**_valuation_usage_properties(payload), "ui_version": "tasar_playground", "mode": mode}
    track_usage_event("valuation_submitted", properties)
    with st.spinner("Tasando propiedad..."):
        try:
            result = run_valuation_for_tasar(client, payload, token=get_token(), demo_mode=demo_mode)
        except ApiError as exc:
            track_usage_event(
                "valuation_failed",
                {**properties, "error_status_code": exc.status_code},
            )
            st.session_state[ERROR_KEY] = map_tasar_error(exc)
            return
    st.session_state[PAYLOAD_KEY] = payload
    st.session_state[RESULT_KEY] = result
    view_model = map_valuation_response_to_view_model(result, payload=payload, source=mode)
    track_usage_event(
        "valuation_completed",
        {
            **properties,
            "comparable_count": view_model.comparable_count if view_model else None,
            "confidence": view_model.confidence if view_model else None,
            "estimated_value_uf": view_model.estimated_value_uf if view_model else None,
        },
    )


def _current_result() -> dict[str, Any] | None:
    result = st.session_state.get(RESULT_KEY)
    if isinstance(result, dict):
        return result
    return None


def _risk_report_lookup_context() -> dict[str, Any]:
    prefill = st.session_state.get(PREFILL_KEY)
    if isinstance(prefill, dict) and prefill:
        return {"status": "prefilled", "listing_data": dict(prefill)}
    return {}


def _risk_report_status_body(contract: TasarRiskReportContract) -> str:
    if contract.risk_report_status == "requires_valuation":
        return "Ejecuta una tasacion real antes de generar el reporte."
    if contract.risk_report_status == "requires_comparables":
        return "La tasacion real no entrego comparables suficientes para el reporte."
    if contract.risk_report_status == "requires_risk_inputs":
        return "Faltan campos base de la propiedad para generar el reporte."
    if contract.risk_report_status == "not_available":
        return "No se genera Risk Report real desde datos demo/lab."
    return "Risk Report no disponible para esta tasacion."


def _risk_report_file_suffix() -> str:
    payload = st.session_state.get(PAYLOAD_KEY)
    if not isinstance(payload, dict):
        return "sin_resultado"
    comuna = str(payload.get("comuna") or "tasacion").strip().lower().replace(" ", "_")
    suffix = "".join(ch for ch in comuna if ch.isalnum() or ch in {"_", "-"})
    return suffix or "tasacion"


def _form_prefill(*, demo_mode: bool) -> dict[str, Any]:
    prefill = st.session_state.get(PREFILL_KEY)
    if isinstance(prefill, dict):
        return prefill
    if demo_mode:
        return {
            "property_type": "apartment",
            "comuna": "providencia",
            "built_area_m2": 75,
            "m2": 75,
            "dormitorios": 3,
            "banos": 2,
            "estacionamientos": 1,
            "price_uf": 6400,
            "price_clp": 252_000_000,
            "address_label": "Suecia 123, Providencia",
        }
    return {}


def _property_type_index(value: Any) -> int:
    label = _property_type_label(value)
    return ["Departamento", "Casa", "Oficina", "Desconocido"].index(label)


def _property_type_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"house", "casa"}:
        return "Casa"
    if text in {"office", "oficina"}:
        return "Oficina"
    if text in {"unknown", "desconocido"}:
        return "Desconocido"
    return "Departamento"


def _comuna_index(value: Any) -> int:
    slug = _resolve_comuna_slug(value) or DEFAULT_COMUNA_SLUG
    return COMUNA_OPTION_SLUGS.index(slug)


def _resolve_comuna_slug(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    comuna = find_comuna(text)
    return comuna.slug if comuna else None


def _comuna_option_label(slug: str) -> str:
    return COMUNA_LABELS_BY_SLUG.get(slug, slug)


def _comuna_for_payload(value: Any) -> str:
    return str(value or "").strip()


def _first_present(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return default


def _view_model_result_dict(view_model: TasarValuationViewModel) -> dict[str, Any]:
    return {
        "estimated_price_uf": view_model.estimated_value_uf,
        "estimated_price_clp": view_model.estimated_value_clp,
        "estimated_value_uf": view_model.estimated_value_uf,
        "estimated_value_clp": view_model.estimated_value_clp,
        "price_range_low_uf": view_model.price_range_low_uf,
        "price_range_high_uf": view_model.price_range_high_uf,
        "price_range_low_clp": view_model.price_range_low_clp,
        "price_range_high_clp": view_model.price_range_high_clp,
        "price_m2_uf": view_model.price_m2_uf,
        "confidence": view_model.confidence,
        "confidence_label": view_model.confidence_label,
        "confidence_score": view_model.confidence_score,
    }


def _comparable_to_dict(item: TasarComparableViewModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    return {
        "title": item.title,
        "comuna": item.comuna,
        "price_uf": item.price_uf,
        "price_clp": item.price_clp,
        "m2": item.m2,
        "bedrooms": item.bedrooms,
        "bathrooms": item.bathrooms,
        "parking_spaces": item.parking_spaces,
        "similarity": item.similarity,
        "date": item.date,
        "distance": item.distance,
        "url": item.url,
        **item.raw,
    }


def _range_label_from_view_model(view_model: TasarValuationViewModel) -> str:
    low = view_model.price_range_low_uf
    high = view_model.price_range_high_uf
    if low is None or high is None:
        return "No disponible"
    return f"{format_uf(low).replace(',00', '')} - {format_uf(high).replace(',00', '')}"


def _range_clp_label_from_view_model(view_model: TasarValuationViewModel) -> str:
    low_clp = view_model.price_range_low_clp
    high_clp = view_model.price_range_high_clp
    if low_clp is not None and high_clp is not None:
        return f"{format_clp(low_clp)} - {format_clp(high_clp)}"

    low = view_model.price_range_low_uf
    high = view_model.price_range_high_uf
    estimate = view_model.estimated_value_uf
    estimate_clp = view_model.estimated_value_clp
    if low is None or high is None or estimate is None or estimate_clp is None or estimate == 0:
        return "CLP no disponible"
    clp_per_uf = estimate_clp / estimate
    return f"{format_clp(low * clp_per_uf)} - {format_clp(high * clp_per_uf)}"


def _price_m2_label_from_view_model(view_model: TasarValuationViewModel) -> str:
    if view_model.price_m2_uf is None:
        return "No disponible"
    return format_uf(view_model.price_m2_uf)


def _price_m2_clp_label_from_view_model(view_model: TasarValuationViewModel) -> str:
    price_m2 = view_model.price_m2_uf
    estimate = view_model.estimated_value_uf
    estimate_clp = view_model.estimated_value_clp
    if price_m2 is None or estimate is None or estimate_clp is None or estimate == 0:
        return "CLP/m2 no disponible"
    return f"{format_clp(price_m2 * (estimate_clp / estimate))}/m2"


def _confidence_score_from_view_model(view_model: TasarValuationViewModel) -> str:
    score = view_model.confidence_score
    if score is not None:
        if score <= 1:
            return f"{score * 100:.0f}%"
        return f"{score:.0f}%"
    if view_model.is_demo:
        fallback = {"high": "87%", "medium": "62%", "low": "38%", "insufficient_data": "12%"}
        return fallback.get(view_model.confidence_key, "--")
    return "--"


def _confidence_pct_from_view_model(view_model: TasarValuationViewModel, confidence: str) -> int:
    score = view_model.confidence_score
    if score is not None:
        return int(max(0, min(100, score * 100 if score <= 1 else score)))
    if view_model.is_demo:
        return {"high": 87, "medium": 62, "low": 38, "insufficient_data": 12}.get(confidence, 45)
    return 0


def _footer_items_from_view_model(view_model: TasarValuationViewModel) -> list[dict[str, str]]:
    return [
        {
            "label": "Valor estimado UF",
            "value": format_uf(view_model.estimated_value_uf).replace(",00", ""),
            "delta": "Backend/API",
            "tone": "neutral",
        },
        {
            "label": "Valor estimado CLP",
            "value": format_clp(view_model.estimated_value_clp),
            "delta": "Backend/API",
            "tone": "neutral",
        },
        {
            "label": "Confianza",
            "value": format_confidence(view_model.confidence_label or view_model.confidence),
            "delta": _confidence_score_from_view_model(view_model),
            "tone": "positive" if view_model.confidence_key == "high" else "neutral",
        },
        {
            "label": "Comparables",
            "value": str(view_model.comparable_count if view_model.comparable_count is not None else len(view_model.comparables)),
            "delta": "Respuesta real",
            "tone": "positive" if view_model.comparables else "neutral",
        },
        {
            "label": "Precio UF/m2",
            "value": _price_m2_label_from_view_model(view_model),
            "delta": "Campo price_m2_uf",
            "tone": "neutral",
        },
    ]


def _range_label(result: dict[str, Any]) -> str:
    low = result.get("price_range_low_uf")
    high = result.get("price_range_high_uf")
    if low is None or high is None:
        return "No disponible"
    return f"{format_uf(low).replace(',00', '')} - {format_uf(high).replace(',00', '')}"


def _range_clp_label(result: dict[str, Any]) -> str:
    low = _safe_float(result.get("price_range_low_uf"))
    high = _safe_float(result.get("price_range_high_uf"))
    estimate = _safe_float(result.get("estimated_price_uf") or result.get("estimated_value_uf"))
    estimate_clp = _safe_float(result.get("estimated_price_clp") or result.get("estimated_value_clp"))
    if low is None or high is None or estimate is None or estimate_clp is None or estimate == 0:
        return "CLP no disponible"
    clp_per_uf = estimate_clp / estimate
    return f"{format_clp(low * clp_per_uf)} - {format_clp(high * clp_per_uf)}"


def _price_m2_label(result: dict[str, Any]) -> str:
    value = result.get("price_m2_uf")
    if value is None:
        return "No disponible"
    return format_uf(value)


def _price_m2_clp_label(result: dict[str, Any]) -> str:
    price_m2 = _safe_float(result.get("price_m2_uf"))
    estimate = _safe_float(result.get("estimated_price_uf") or result.get("estimated_value_uf"))
    estimate_clp = _safe_float(result.get("estimated_price_clp") or result.get("estimated_value_clp"))
    if price_m2 is None or estimate is None or estimate_clp is None or estimate == 0:
        return "CLP/m2 no disponible"
    return f"{format_clp(price_m2 * (estimate_clp / estimate))}/m2"


def _confidence_score(result: dict[str, Any]) -> str:
    score = _safe_float(result.get("confidence_score") or result.get("confidence"))
    if score is not None:
        if score <= 1:
            return f"{score * 100:.0f}%"
        return f"{score:.0f}%"
    confidence = normalize_confidence(result.get("confidence_label") or result.get("confidence"))
    fallback = {"high": "87%", "medium": "62%", "low": "38%", "insufficient_data": "12%"}
    return fallback.get(confidence, "--")


def _confidence_pct(result: dict[str, Any], confidence: str) -> int:
    score = _safe_float(result.get("confidence_score") or result.get("confidence"))
    if score is not None:
        return int(max(0, min(100, score * 100 if score <= 1 else score)))
    return {"high": 87, "medium": 62, "low": 38, "insufficient_data": 12}.get(confidence, 45)


def _program_label(item: dict[str, Any]) -> str:
    bedrooms = _safe_int(item.get("bedrooms") or item.get("dormitorios"))
    bathrooms = _safe_int(item.get("bathrooms") or item.get("banos"))
    parking = _safe_int(item.get("parking_spaces") or item.get("estacionamientos"))
    parts = []
    if bedrooms is not None:
        parts.append(f"{bedrooms}D")
    if bathrooms is not None:
        parts.append(f"{bathrooms}B")
    if parking is not None:
        parts.append(f"{parking}E")
    return " - ".join(parts) if parts else "Programa no disponible"


def _comuna_label(value: Any) -> str:
    text = str(value or "Comuna no disponible").replace("_", " ").strip()
    return text.title()


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _valuation_usage_properties(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "comuna": payload.get("comuna"),
        "property_type": payload.get("property_type"),
        "m2": payload.get("m2"),
        "built_area_m2": payload.get("built_area_m2"),
        "land_area_m2": payload.get("land_area_m2"),
        "bedrooms": payload.get("dormitorios"),
        "bathrooms": payload.get("banos"),
        "parking": payload.get("estacionamientos"),
        "precio_publicado_uf": payload.get("precio_publicado_uf"),
        "precio_publicado_clp": payload.get("precio_publicado_clp"),
    }


def inject_tasar_playground_styles() -> None:
    render_html(
        """
        <style>
        :root {
            --avm-neo-bg: #030812;
            --avm-neo-page: #071121;
            --avm-neo-panel: rgba(9, 20, 37, 0.94);
            --avm-neo-panel-2: rgba(10, 24, 44, 0.92);
            --avm-neo-panel-3: rgba(12, 29, 53, 0.86);
            --avm-neo-border: rgba(64, 130, 190, 0.24);
            --avm-neo-border-strong: rgba(27, 153, 255, 0.58);
            --avm-neo-text: #f6f9ff;
            --avm-neo-muted: #91a0b8;
            --avm-neo-soft: #c5d4ec;
            --avm-neo-cyan: #17c7ff;
            --avm-neo-blue: #2778ff;
            --avm-neo-purple: #8b35ff;
            --avm-neo-green: #38d991;
            --avm-neo-amber: #f7a928;
            --avm-neo-red: #ff5b6e;
            --avm-neo-shadow: 0 18px 46px rgba(0, 0, 0, 0.42);
            --avm-neo-inset: inset 0 1px 0 rgba(255, 255, 255, 0.045);
        }

        html,
        body,
        .stApp,
        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at 74% 8%, rgba(115, 45, 255, 0.14), transparent 28%),
                radial-gradient(circle at 24% 0%, rgba(20, 166, 255, 0.12), transparent 25%),
                linear-gradient(135deg, #02060f 0%, #061225 58%, #050917 100%);
            color: var(--avm-neo-text);
        }

        .block-container {
            max-width: 1680px !important;
            padding: 0.46rem 0.68rem 0.72rem !important;
        }

        [data-testid="stHeader"] {
            background: transparent;
            height: 0;
        }

        section[data-testid="stSidebar"] {
            width: 292px !important;
            background:
                linear-gradient(180deg, rgba(7, 20, 38, 0.98) 0%, rgba(5, 16, 30, 0.99) 100%);
            border-right: 1px solid rgba(40, 113, 176, 0.32);
            box-shadow: inset -1px 0 0 rgba(84, 159, 255, 0.08), 18px 0 42px rgba(0, 0, 0, 0.24);
        }

        section[data-testid="stSidebar"] > div {
            padding-top: 0.7rem;
        }

        .avm-neo-sidebar {
            padding: 0.28rem 0.18rem 0.45rem;
        }

        .avm-neo-side-brand {
            display: flex;
            align-items: center;
            gap: 0.72rem;
            padding: 0.18rem 0.08rem 0.72rem;
        }

        .avm-neo-logo-mark,
        .avm-neo-avatar,
        .avm-neo-account-row em {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            color: #ffffff;
            background: linear-gradient(135deg, var(--avm-neo-cyan), var(--avm-neo-purple));
            box-shadow: 0 0 22px rgba(38, 137, 255, 0.34);
        }

        .avm-neo-logo-mark {
            width: 2.42rem;
            height: 2.42rem;
            border-radius: 10px;
        }

        .avm-neo-logo-mark span {
            width: 1.05rem;
            height: 1.05rem;
            border: 1px solid rgba(255, 255, 255, 0.78);
            transform: rotate(45deg);
        }

        .avm-neo-side-brand strong {
            color: var(--avm-neo-text);
            display: block;
            font-size: 1rem;
            font-weight: 800;
            line-height: 1.15;
        }

        .avm-neo-side-brand p {
            color: var(--avm-neo-muted);
            font-size: 0.72rem;
            margin: 0.13rem 0 0;
        }

        .avm-neo-side-card,
        .avm-neo-side-link {
            border: 1px solid rgba(70, 130, 190, 0.2);
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(12, 25, 46, 0.85), rgba(7, 17, 32, 0.88));
            box-shadow: var(--avm-neo-inset);
            padding: 0.72rem;
            margin: 0 0 0.58rem;
        }

        .avm-neo-side-label {
            color: var(--avm-neo-muted);
            font-size: 0.68rem;
            font-weight: 800;
            letter-spacing: 0;
            margin-bottom: 0.44rem;
            text-transform: uppercase;
        }

        .avm-neo-side-label--menu {
            border-top: 1px solid rgba(70, 130, 190, 0.18);
            margin: 0.16rem 0 0.28rem;
            padding-top: 0.62rem;
        }

        .avm-neo-side-card strong {
            color: var(--avm-neo-text);
            display: block;
            font-size: 0.9rem;
            font-weight: 800;
        }

        .avm-neo-side-card p {
            color: var(--avm-neo-muted);
            font-size: 0.73rem;
            line-height: 1.38;
            margin: 0.36rem 0 0;
        }

        .avm-neo-side-button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            border: 1px solid rgba(94, 161, 222, 0.25);
            border-radius: 8px;
            background: rgba(21, 42, 69, 0.72);
            color: var(--avm-neo-soft);
            font-size: 0.78rem;
            font-weight: 800;
            margin-top: 0.58rem;
            padding: 0.5rem 0.62rem;
            text-align: center;
            text-decoration: none;
        }

        .avm-neo-side-button--disabled {
            color: rgba(197, 212, 236, 0.48);
            cursor: not-allowed;
            opacity: 0.68;
        }

        .avm-neo-side-card--ok {
            border-color: rgba(56, 217, 145, 0.24);
            background: linear-gradient(180deg, rgba(15, 65, 45, 0.45), rgba(8, 34, 31, 0.65));
        }

        .avm-neo-side-card--ok strong {
            color: #72f0ac;
        }

        .avm-neo-side-card--help {
            border-color: rgba(95, 161, 255, 0.24);
            background: linear-gradient(145deg, rgba(16, 27, 58, 0.84), rgba(8, 24, 43, 0.88));
        }

        .avm-neo-side-card--premium {
            border-color: rgba(139, 53, 255, 0.34);
            background:
                radial-gradient(circle at 20% 8%, rgba(23, 199, 255, 0.24), transparent 20%),
                linear-gradient(145deg, rgba(30, 26, 79, 0.88), rgba(9, 21, 40, 0.88));
        }

        .avm-neo-side-card--premium strong {
            color: #67caff;
            font-size: 1rem;
        }

        .avm-neo-side-link,
        .avm-neo-side-toggle,
        .avm-neo-account-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.55rem;
        }

        .avm-neo-side-link span,
        .avm-neo-side-toggle span {
            color: var(--avm-neo-soft);
            font-size: 0.8rem;
            font-weight: 760;
        }

        .avm-neo-side-link b {
            color: var(--avm-neo-muted);
            font-size: 0.72rem;
        }

        .avm-neo-side-toggle i {
            position: relative;
            display: inline-block;
            width: 2rem;
            height: 1.05rem;
            border-radius: 999px;
            background: linear-gradient(90deg, var(--avm-neo-blue), var(--avm-neo-purple));
        }

        .avm-neo-side-toggle i::after {
            content: "";
            position: absolute;
            top: 0.2rem;
            right: 0.2rem;
            width: 0.65rem;
            height: 0.65rem;
            border-radius: 50%;
            background: #ffffff;
        }

        .avm-neo-side-toggle--compact {
            border-top: 1px solid rgba(70, 130, 190, 0.16);
            margin-top: 0.68rem;
            padding-top: 0.58rem;
        }

        .avm-neo-account-row {
            justify-content: flex-start;
            min-width: 0;
        }

        .avm-neo-account-row em {
            width: 1.85rem;
            height: 1.85rem;
            flex: 0 0 auto;
            font-size: 0.72rem;
            font-style: normal;
            font-weight: 800;
        }

        .avm-neo-account-row span {
            color: var(--avm-neo-soft);
            font-size: 0.72rem;
            overflow-wrap: anywhere;
        }

        .avm-neo-side-footer {
            color: rgba(151, 169, 194, 0.76);
            font-size: 0.72rem;
            line-height: 1.35;
            padding: 1.45rem 0.1rem 0;
        }

        .avm-neo-topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            min-height: 3.34rem;
            border: 1px solid rgba(60, 127, 190, 0.28);
            border-radius: 8px;
            background:
                linear-gradient(90deg, rgba(4, 13, 25, 0.98), rgba(7, 17, 32, 0.98));
            box-shadow: 0 18px 42px rgba(0, 0, 0, 0.34), var(--avm-neo-inset);
            padding: 0.42rem 0.62rem;
            margin-bottom: 0.6rem;
        }

        .avm-neo-topbar__nav,
        .avm-neo-topbar__tools {
            display: flex;
            align-items: center;
            gap: 0.34rem;
            min-width: 0;
            flex-wrap: wrap;
        }

        .avm-neo-topbar-title {
            color: #ffffff;
            font-size: 0.94rem;
            font-weight: 860;
        }

        .avm-neo-topbar-subtitle {
            border-left: 1px solid rgba(64, 130, 190, 0.22);
            color: var(--avm-neo-muted);
            font-size: 0.74rem;
            font-weight: 760;
            padding-left: 0.58rem;
        }

        .avm-neo-nav-item {
            position: relative;
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            min-height: 2.26rem;
            border: 1px solid transparent;
            color: var(--avm-neo-muted);
            font-size: 0.82rem;
            font-weight: 780;
            padding: 0.48rem 0.86rem;
            text-decoration: none;
            transition: background 140ms ease, border-color 140ms ease, color 140ms ease;
        }

        .avm-neo-nav-item i {
            width: 0.76rem;
            height: 0.76rem;
            border: 1px solid currentColor;
            border-radius: 3px;
            transform: rotate(45deg);
        }

        .avm-neo-nav-item:hover {
            color: var(--avm-neo-soft);
            border-color: rgba(75, 138, 205, 0.24);
            border-radius: 8px;
            background: rgba(12, 29, 53, 0.56);
        }

        .avm-neo-nav-item--active {
            color: #ffffff;
            border: 1px solid rgba(23, 199, 255, 0.36);
            border-radius: 8px;
            background:
                linear-gradient(180deg, rgba(23, 199, 255, 0.13), rgba(139, 53, 255, 0.11)),
                rgba(22, 78, 132, 0.2);
            box-shadow: inset 3px 0 0 rgba(23, 199, 255, 0.72), 0 0 24px rgba(23, 199, 255, 0.08);
        }

        .avm-neo-nav-item--active::after {
            content: "";
            position: absolute;
            left: 2.4rem;
            right: 0.8rem;
            bottom: 0.28rem;
            height: 2px;
            border-radius: 999px;
            background: linear-gradient(90deg, var(--avm-neo-cyan), var(--avm-neo-purple));
        }

        .avm-neo-tool,
        .avm-neo-tool-dot,
        .avm-neo-avatar {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 1.9rem;
            height: 1.9rem;
            border: 1px solid rgba(80, 143, 203, 0.24);
            border-radius: 999px;
            color: var(--avm-neo-soft);
            background: rgba(10, 22, 40, 0.7);
            font-size: 0.78rem;
            font-weight: 800;
            flex: 0 0 auto;
        }

        .avm-neo-tool-dot {
            color: #ffffff;
            border-color: transparent;
            background: linear-gradient(135deg, rgba(38, 84, 255, 0.88), rgba(139, 53, 255, 0.9));
        }

        .avm-neo-avatar {
            width: 2rem;
            height: 2rem;
        }

        .avm-neo-email {
            max-width: 18rem;
            color: var(--avm-neo-muted);
            font-size: 0.74rem;
            overflow-wrap: anywhere;
        }

        .avm-neo-hero {
            position: relative;
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(25rem, 0.56fr);
            min-height: 9.7rem;
            overflow: hidden;
            border: 1px solid rgba(24, 150, 255, 0.62);
            border-radius: 8px;
            background:
                linear-gradient(90deg, rgba(4, 18, 37, 0.99) 0%, rgba(7, 23, 54, 0.96) 42%, rgba(44, 17, 86, 0.92) 100%);
            box-shadow: var(--avm-neo-shadow), inset 0 1px 0 rgba(255, 255, 255, 0.04);
            padding: 0.98rem 1.38rem;
            margin-bottom: 0.5rem;
        }

        .avm-neo-hero__copy {
            position: relative;
            z-index: 2;
        }

        .avm-neo-kicker,
        .avm-neo-section-head span,
        .avm-neo-estimate-main span,
        .avm-neo-confidence-box span,
        .avm-neo-distribution span,
        .avm-neo-result-metric span,
        .avm-neo-map-stats span,
        .avm-neo-footer-kpi span {
            color: var(--avm-neo-cyan);
            font-size: 0.68rem;
            font-weight: 850;
            letter-spacing: 0;
            text-transform: uppercase;
        }

        .avm-neo-hero h1 {
            color: #ffffff;
            font-size: 1.56rem;
            line-height: 1.06;
            letter-spacing: 0;
            margin: 0.28rem 0 0;
            max-width: 820px;
        }

        .avm-neo-hero p {
            color: var(--avm-neo-muted);
            font-size: 0.78rem;
            line-height: 1.42;
            margin: 0.42rem 0 0;
            max-width: 690px;
        }

        .avm-neo-chip-row {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
            margin-top: 0.56rem;
        }

        .avm-neo-chip-row span {
            border: 1px solid rgba(88, 149, 211, 0.23);
            border-radius: 999px;
            background: rgba(13, 30, 53, 0.82);
            color: var(--avm-neo-muted);
            font-size: 0.7rem;
            font-weight: 740;
            padding: 0.32rem 0.72rem;
            cursor: default;
        }

        .avm-neo-hero-city {
            position: absolute;
            right: 0;
            bottom: 0;
            width: 50%;
            height: 100%;
            display: flex;
            align-items: flex-end;
            justify-content: flex-end;
            gap: 0.46rem;
            padding: 0 1.2rem 0.9rem 0;
            opacity: 0.95;
            background:
                linear-gradient(180deg, rgba(23, 199, 255, 0.06), transparent 62%);
        }

        .avm-neo-hero-city i {
            display: block;
            width: 1.58rem;
            border: 1px solid rgba(34, 173, 255, 0.28);
            border-bottom: 0;
            background:
                repeating-linear-gradient(180deg, rgba(255, 255, 255, 0.16) 0 2px, transparent 2px 14px),
                linear-gradient(180deg, rgba(34, 173, 255, 0.34), rgba(20, 38, 75, 0.42));
            box-shadow: 0 0 24px rgba(23, 199, 255, 0.12);
        }

        .avm-neo-hero-city i:nth-child(1) { height: 42%; }
        .avm-neo-hero-city i:nth-child(2) { height: 58%; }
        .avm-neo-hero-city i:nth-child(3) { height: 48%; }
        .avm-neo-hero-city i:nth-child(4) { height: 76%; background-color: rgba(139, 53, 255, 0.18); }
        .avm-neo-hero-city i:nth-child(5) { height: 62%; }
        .avm-neo-hero-city i:nth-child(6) { height: 88%; background-color: rgba(139, 53, 255, 0.24); }
        .avm-neo-hero-city i:nth-child(7) { height: 54%; }
        .avm-neo-hero-city i:nth-child(8) { height: 68%; }
        .avm-neo-hero-city i:nth-child(9) { height: 46%; }

        .avm-neo-location-pill {
            position: absolute;
            right: 1.42rem;
            bottom: 1.08rem;
            z-index: 3;
            display: inline-grid;
            grid-template-columns: auto minmax(0, 1fr);
            align-items: center;
            gap: 0.5rem;
            border: 1px solid rgba(111, 156, 233, 0.28);
            border-radius: 8px;
            background: rgba(18, 24, 54, 0.86);
            padding: 0.54rem 0.74rem;
            box-shadow: 0 14px 34px rgba(0, 0, 0, 0.28);
        }

        .avm-neo-location-pill i {
            width: 0.74rem;
            height: 0.74rem;
            border-radius: 999px;
            background: #ffffff;
            box-shadow: 0 0 0 0.26rem rgba(23, 199, 255, 0.16), 0 0 16px rgba(23, 199, 255, 0.36);
        }

        .avm-neo-location-pill span {
            color: var(--avm-neo-muted);
            display: block;
            font-size: 0.68rem;
        }

        .avm-neo-location-pill strong {
            color: #ffffff;
            display: block;
            font-size: 0.78rem;
            margin-top: 0.1rem;
        }

        div[data-testid="stVerticalBlock"] {
            gap: 0.46rem;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: rgba(66, 132, 191, 0.24);
            border-radius: 8px;
            background:
                linear-gradient(180deg, rgba(10, 23, 42, 0.94), rgba(5, 13, 26, 0.96));
            box-shadow: 0 16px 42px rgba(0, 0, 0, 0.34), var(--avm-neo-inset);
        }

        div[data-testid="stVerticalBlockBorderWrapper"] > div {
            padding: 0.78rem 0.86rem;
        }

        .avm-neo-section-head {
            display: grid;
            grid-template-columns: auto minmax(0, 1fr);
            gap: 0.58rem;
            align-items: start;
            margin-bottom: 0.6rem;
        }

        .avm-neo-section-head--inline {
            margin-bottom: 0;
        }

        .avm-neo-section-head > span {
            width: 1.28rem;
            height: 1.28rem;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border: 1px solid rgba(23, 199, 255, 0.46);
            border-radius: 6px;
            background: rgba(39, 120, 255, 0.18);
            box-shadow: 0 0 18px rgba(23, 199, 255, 0.18);
        }

        .avm-neo-section-head strong,
        .avm-neo-panel-title,
        .avm-neo-panel-header strong,
        .avm-neo-comparable-head strong {
            color: var(--avm-neo-text);
            display: block;
            font-size: 0.9rem;
            font-weight: 850;
            line-height: 1.1;
        }

        .avm-neo-section-head p {
            color: var(--avm-neo-muted);
            font-size: 0.7rem;
            line-height: 1.25;
            margin: 0.14rem 0 0;
        }

        .avm-neo-result-head,
        .avm-neo-comparable-head,
        .avm-neo-panel-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.8rem;
            margin-bottom: 0.62rem;
        }

        .avm-neo-premium-badge,
        .avm-neo-comparable-head span,
        .avm-neo-panel-header span {
            border: 1px solid rgba(139, 53, 255, 0.36);
            border-radius: 999px;
            color: #c597ff;
            background: rgba(71, 29, 129, 0.22);
            font-size: 0.66rem;
            font-weight: 800;
            padding: 0.2rem 0.52rem;
            white-space: nowrap;
        }

        .avm-neo-value-grid {
            display: grid;
            grid-template-columns: minmax(8.6rem, 0.8fr) minmax(7rem, 0.52fr) minmax(10.8rem, 0.84fr);
            gap: 0.78rem;
            align-items: center;
            border-bottom: 1px solid rgba(66, 132, 191, 0.18);
            padding-bottom: 0.82rem;
        }

        .avm-neo-estimate-main strong {
            color: #ffffff;
            display: block;
            font-size: 2.35rem;
            font-weight: 860;
            letter-spacing: 0;
            line-height: 1.02;
            margin-top: 0.16rem;
            overflow-wrap: normal !important;
            white-space: nowrap !important;
            word-break: keep-all !important;
        }

        .avm-neo-estimate-main p,
        .avm-neo-confidence-box small,
        .avm-neo-result-metric p,
        .avm-neo-confidence-bar p {
            color: var(--avm-neo-muted);
            font-size: 0.76rem;
            line-height: 1.3;
            margin: 0.2rem 0 0;
        }

        .avm-neo-confidence-box {
            border-left: 1px solid rgba(66, 132, 191, 0.18);
            border-right: 1px solid rgba(66, 132, 191, 0.18);
            min-height: 6.4rem;
            padding: 0 0.78rem;
            text-align: center;
        }

        .avm-neo-confidence-box b {
            color: var(--avm-neo-green);
            display: block;
            font-size: 0.82rem;
            margin-top: 0.24rem;
        }

        .avm-neo-confidence-ring {
            width: 4.05rem;
            height: 4.05rem;
            margin: 0.34rem auto 0;
            display: grid;
            place-content: center;
            border-radius: 999px;
            border: 0.32rem solid var(--avm-neo-cyan);
            background:
                radial-gradient(circle, rgba(16, 31, 54, 0.94) 0 57%, transparent 58%),
                conic-gradient(var(--avm-neo-green) 0 87%, rgba(48, 76, 111, 0.78) 87% 100%);
        }

        .avm-neo-confidence-ring strong {
            color: #ffffff;
            font-size: 1rem;
            font-weight: 850;
        }

        .avm-neo-confidence-ring--medium {
            background:
                radial-gradient(circle, rgba(16, 31, 54, 0.94) 0 57%, transparent 58%),
                conic-gradient(var(--avm-neo-amber) 0 62%, rgba(48, 76, 111, 0.78) 62% 100%);
        }

        .avm-neo-confidence-ring--low,
        .avm-neo-confidence-ring--insufficient_data {
            background:
                radial-gradient(circle, rgba(16, 31, 54, 0.94) 0 57%, transparent 58%),
                conic-gradient(var(--avm-neo-red) 0 38%, rgba(48, 76, 111, 0.78) 38% 100%);
        }

        .avm-neo-distribution svg,
        .avm-neo-trend-chart svg {
            width: 100%;
            height: auto;
            display: block;
        }

        .avm-neo-bell,
        .avm-neo-trend-chart {
            border: 1px solid rgba(66, 132, 191, 0.14);
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(8, 19, 36, 0.62), rgba(5, 13, 26, 0.48));
            padding: 0.22rem 0.32rem 0.34rem;
        }

        .avm-neo-bell-labels,
        .avm-neo-trend-labels {
            display: flex;
            justify-content: space-between;
            gap: 0.3rem;
            color: var(--avm-neo-muted);
            font-size: 0.68rem;
            margin-top: -0.16rem;
        }

        .avm-neo-result-metrics {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            border-bottom: 1px solid rgba(66, 132, 191, 0.18);
            gap: 0.72rem;
            padding: 0.78rem 0;
        }

        .avm-neo-result-metric {
            border-right: 1px solid rgba(66, 132, 191, 0.16);
            padding-right: 0.8rem;
        }

        .avm-neo-result-metric:last-child {
            border-right: 0;
        }

        .avm-neo-result-metric strong {
            color: #ffffff;
            display: block;
            font-size: 1.14rem;
            margin-top: 0.18rem;
        }

        .avm-neo-confidence-bar {
            padding-top: 0.72rem;
        }

        .avm-neo-confidence-bar > div:first-child {
            display: flex;
            justify-content: space-between;
            gap: 0.7rem;
            align-items: center;
        }

        .avm-neo-confidence-bar strong {
            color: var(--avm-neo-soft);
            font-size: 0.82rem;
        }

        .avm-neo-confidence-bar span {
            color: var(--avm-neo-green);
            font-size: 0.78rem;
            font-weight: 850;
        }

        .avm-neo-confidence-track {
            height: 0.44rem;
            border-radius: 999px;
            background: rgba(38, 79, 118, 0.62);
            overflow: hidden;
            margin-top: 0.55rem;
        }

        .avm-neo-confidence-track span {
            display: block;
            height: 100%;
            background: linear-gradient(90deg, var(--avm-neo-cyan), var(--avm-neo-blue), var(--avm-neo-purple));
        }

        .avm-neo-map {
            position: relative;
            min-height: 11.2rem;
            overflow: hidden;
            border: 1px solid rgba(66, 132, 191, 0.22);
            border-radius: 8px;
            background:
                radial-gradient(circle at 52% 54%, rgba(33, 136, 255, 0.2), transparent 32%),
                linear-gradient(135deg, rgba(16, 35, 62, 0.78), rgba(6, 17, 32, 0.88));
        }

        .avm-neo-map-grid {
            position: absolute;
            inset: -30%;
            background:
                linear-gradient(rgba(105, 153, 204, 0.08) 1px, transparent 1px),
                linear-gradient(90deg, rgba(105, 153, 204, 0.08) 1px, transparent 1px);
            background-size: 24px 24px;
            transform: rotate(-13deg);
        }

        .avm-neo-map-radius {
            position: absolute;
            left: 50%;
            top: 50%;
            width: 8rem;
            height: 8rem;
            transform: translate(-50%, -50%);
            border: 1px solid rgba(97, 170, 255, 0.52);
            border-radius: 50%;
            box-shadow: 0 0 0 2.3rem rgba(42, 122, 255, 0.08);
        }

        .avm-neo-map-pin {
            position: absolute;
            left: 50%;
            top: 50%;
            width: 1rem;
            height: 1rem;
            transform: translate(-50%, -50%) rotate(45deg);
            border-radius: 50% 50% 50% 0;
            background: #ffffff;
            box-shadow: 0 0 16px rgba(23, 199, 255, 0.44);
        }

        .avm-neo-map > span {
            position: absolute;
            right: 0.55rem;
            bottom: 0.55rem;
            border: 1px solid rgba(97, 170, 255, 0.34);
            border-radius: 999px;
            color: var(--avm-neo-soft);
            background: rgba(8, 18, 34, 0.78);
            font-size: 0.66rem;
            padding: 0.2rem 0.48rem;
        }

        .avm-neo-map-stats {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.45rem;
            margin-top: 0.52rem;
        }

        .avm-neo-map-stats div {
            min-width: 0;
        }

        .avm-neo-map-stats strong {
            color: var(--avm-neo-green);
            display: block;
            font-size: 0.7rem;
            margin-top: 0.12rem;
        }

        .avm-neo-location-card {
            border: 1px solid rgba(66, 132, 191, 0.2);
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(8, 18, 34, 0.72), rgba(5, 13, 26, 0.68));
            padding: 0.72rem;
        }

        .avm-neo-location-card--positive {
            border-color: rgba(49, 211, 111, 0.28);
        }

        .avm-neo-location-card--warning {
            border-color: rgba(247, 169, 40, 0.34);
        }

        .avm-neo-location-card__head {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.7rem;
            align-items: start;
            margin-bottom: 0.58rem;
        }

        .avm-neo-location-card__head span {
            color: var(--avm-neo-amber);
            display: block;
            font-size: 0.66rem;
            font-weight: 850;
            text-transform: uppercase;
        }

        .avm-neo-location-card__head strong {
            color: #ffffff;
            display: block;
            font-size: 0.86rem;
            line-height: 1.25;
            margin-top: 0.12rem;
        }

        .avm-neo-location-card__head em {
            border: 1px solid rgba(66, 132, 191, 0.22);
            border-radius: 999px;
            color: var(--avm-neo-soft);
            font-size: 0.64rem;
            font-style: normal;
            font-weight: 850;
            padding: 0.18rem 0.44rem;
            text-transform: uppercase;
        }

        .avm-neo-location-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.48rem;
        }

        .avm-neo-location-metric {
            border: 1px solid rgba(66, 132, 191, 0.14);
            border-radius: 8px;
            background: rgba(9, 22, 39, 0.62);
            min-width: 0;
            padding: 0.48rem;
        }

        .avm-neo-location-metric span,
        .avm-neo-location-row span {
            color: var(--avm-neo-muted);
            display: block;
            font-size: 0.66rem;
            font-weight: 820;
            text-transform: uppercase;
        }

        .avm-neo-location-metric strong,
        .avm-neo-location-row strong {
            color: #ffffff;
            display: block;
            font-size: 0.78rem;
            line-height: 1.25;
            margin-top: 0.12rem;
        }

        .avm-neo-location-metric p {
            color: var(--avm-neo-muted);
            font-size: 0.66rem;
            margin: 0.1rem 0 0;
        }

        .avm-neo-location-detail {
            border-top: 1px solid rgba(66, 132, 191, 0.14);
            display: grid;
            gap: 0.38rem;
            margin-top: 0.58rem;
            padding-top: 0.54rem;
        }

        .avm-neo-location-row {
            display: grid;
            grid-template-columns: minmax(7.2rem, 0.42fr) minmax(0, 1fr);
            gap: 0.5rem;
            align-items: start;
        }

        .avm-neo-comparable {
            display: grid;
            grid-template-columns: 3rem minmax(0, 1fr) auto;
            gap: 0.55rem;
            align-items: center;
            border: 1px solid rgba(66, 132, 191, 0.16);
            border-radius: 8px;
            background: rgba(9, 22, 39, 0.72);
            padding: 0.44rem;
            margin: 0.36rem 0;
        }

        .avm-neo-comparable-thumb {
            width: 3rem;
            height: 3rem;
            border-radius: 7px;
            border: 1px solid rgba(91, 156, 216, 0.22);
            background:
                linear-gradient(135deg, rgba(255, 255, 255, 0.22), transparent 34%),
                linear-gradient(145deg, rgba(42, 137, 255, 0.35), rgba(35, 24, 78, 0.72));
        }

        .avm-neo-comparable-thumb--1 { background-color: rgba(67, 142, 255, 0.2); }
        .avm-neo-comparable-thumb--2 { background-color: rgba(35, 196, 157, 0.18); }
        .avm-neo-comparable-thumb--3 { background-color: rgba(139, 53, 255, 0.18); }

        .avm-neo-comparable strong {
            color: #ffffff;
            display: block;
            font-size: 0.78rem;
            line-height: 1.16;
        }

        .avm-neo-comparable span,
        .avm-neo-comparable p {
            color: var(--avm-neo-muted);
            display: block;
            font-size: 0.68rem;
            line-height: 1.24;
            margin: 0.1rem 0 0;
        }

        .avm-neo-comparable div:last-child {
            min-width: 5.9rem;
            text-align: right;
        }

        .avm-neo-comparable div:last-child strong {
            color: #75f18f;
        }

        .avm-neo-panel-title {
            margin-bottom: 0.54rem;
            text-transform: uppercase;
            font-size: 0.76rem;
        }

        .avm-neo-trend-chart {
            min-height: 8.65rem;
        }

        .avm-neo-trend-meta {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.34rem;
            margin-top: 0.46rem;
        }

        .avm-neo-trend-meta div {
            border: 1px solid rgba(66, 132, 191, 0.14);
            border-radius: 8px;
            background: rgba(9, 22, 39, 0.58);
            min-width: 0;
            padding: 0.38rem 0.42rem;
        }

        .avm-neo-trend-meta span {
            color: var(--avm-neo-muted);
            display: block;
            font-size: 0.58rem;
            font-weight: 820;
            text-transform: uppercase;
        }

        .avm-neo-trend-meta strong {
            color: #ffffff;
            display: block;
            font-size: 0.68rem;
            line-height: 1.2;
            margin-top: 0.1rem;
        }

        .avm-neo-confidence-summary {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.7rem;
            align-items: center;
            min-height: 4.95rem;
        }

        .avm-neo-confidence-summary span,
        .avm-neo-panel-header strong {
            color: var(--avm-neo-muted);
            font-size: 0.72rem;
            font-weight: 820;
            text-transform: uppercase;
        }

        .avm-neo-confidence-summary strong {
            color: #ffffff;
            display: block;
            font-size: 1rem;
            margin-top: 0.18rem;
        }

        .avm-neo-confidence-summary p,
        .avm-neo-disabled-link {
            color: var(--avm-neo-muted);
            display: block;
            font-size: 0.74rem;
            margin: 0.16rem 0 0;
        }

        .avm-neo-disabled-link {
            color: rgba(145, 160, 184, 0.74);
            font-weight: 800;
            cursor: not-allowed;
        }

        .avm-neo-signal-row,
        .avm-neo-activity-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.5rem;
            align-items: center;
            border-top: 1px solid rgba(66, 132, 191, 0.13);
            padding: 0.46rem 0;
        }

        .avm-neo-signal-row:first-child,
        .avm-neo-activity-row:first-child {
            border-top: 0;
            padding-top: 0;
        }

        .avm-neo-signal-row span,
        .avm-neo-activity-row span {
            color: var(--avm-neo-soft);
            font-size: 0.77rem;
        }

        .avm-neo-signal-row strong {
            color: var(--avm-neo-soft);
            font-size: 0.78rem;
        }

        .avm-neo-signal-row small,
        .avm-neo-activity-row small {
            grid-column: 2;
            color: var(--avm-neo-muted);
            font-size: 0.64rem;
        }

        .avm-neo-signal-row--positive strong {
            color: var(--avm-neo-green);
        }

        .avm-neo-signal-row--negative strong {
            color: var(--avm-neo-red);
        }

        .avm-neo-activity-row {
            grid-template-columns: auto minmax(0, 1fr) auto;
        }

        .avm-neo-activity-row i {
            width: 1rem;
            height: 1rem;
            border-radius: 4px;
            background: rgba(23, 199, 255, 0.16);
            border: 1px solid rgba(23, 199, 255, 0.35);
        }

        .avm-neo-activity-row small {
            grid-column: auto;
        }

        .avm-neo-risk-box {
            display: grid;
            grid-template-columns: auto minmax(0, 1fr) auto;
            gap: 0.66rem;
            align-items: center;
            border: 1px solid rgba(247, 169, 40, 0.42);
            border-radius: 8px;
            background: rgba(111, 71, 11, 0.24);
            padding: 0.66rem;
        }

        .avm-neo-risk-box i {
            width: 2rem;
            height: 2rem;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            border: 1px solid var(--avm-neo-amber);
            color: var(--avm-neo-amber);
            font-style: normal;
            font-weight: 900;
        }

        .avm-neo-risk-box strong {
            color: var(--avm-neo-amber);
            display: block;
            font-size: 0.82rem;
        }

        .avm-neo-risk-box p {
            color: var(--avm-neo-soft);
            font-size: 0.72rem;
            line-height: 1.28;
            margin: 0.12rem 0 0;
        }

        .avm-neo-risk-box span {
            color: var(--avm-neo-soft);
        }

        .avm-neo-market-footer {
            display: grid;
            grid-template-columns: minmax(8.8rem, 1.12fr) repeat(5, minmax(6.4rem, 1fr));
            gap: 0.62rem;
            align-items: center;
            border: 1px solid rgba(66, 132, 191, 0.24);
            border-radius: 8px;
            background:
                linear-gradient(180deg, rgba(10, 23, 42, 0.94), rgba(5, 13, 26, 0.96));
            box-shadow: 0 16px 42px rgba(0, 0, 0, 0.34), var(--avm-neo-inset);
            margin-top: 0.62rem;
            min-height: 4.55rem;
            padding: 0.72rem 0.88rem;
        }

        .avm-neo-market-footer--empty {
            grid-template-columns: 1fr;
        }

        .avm-neo-footer-title {
            color: var(--avm-neo-muted);
            font-size: 0.68rem;
            font-weight: 850;
            line-height: 1.3;
            text-transform: uppercase;
        }

        .avm-neo-footer-kpi {
            border-left: 1px solid rgba(66, 132, 191, 0.18);
            padding-left: 0.68rem;
        }

        .avm-neo-footer-kpi strong {
            color: #ffffff;
            display: block;
            font-size: 0.98rem;
            margin-top: 0.1rem;
        }

        .avm-neo-footer-kpi p {
            color: var(--avm-neo-green);
            font-size: 0.68rem;
            margin: 0.12rem 0 0;
        }

        .avm-neo-footer-kpi--negative p {
            color: var(--avm-neo-red);
        }

        .avm-neo-market-action-kicker {
            color: var(--avm-neo-muted);
            font-size: 0.68rem;
            font-weight: 820;
            margin: 0.62rem 0 0.32rem;
            text-align: center;
            text-transform: uppercase;
        }

        .avm-neo-empty,
        .avm-neo-error,
        .avm-neo-status {
            border: 1px dashed rgba(66, 132, 191, 0.24);
            border-radius: 8px;
            background: rgba(8, 18, 34, 0.64);
            padding: 0.78rem;
        }

        .avm-neo-error {
            border-style: solid;
            border-color: rgba(255, 91, 110, 0.38);
            background: rgba(92, 18, 30, 0.26);
        }

        .avm-neo-empty strong,
        .avm-neo-error strong,
        .avm-neo-status strong {
            color: #ffffff;
            display: block;
            font-size: 0.86rem;
        }

        .avm-neo-empty p,
        .avm-neo-error span,
        .avm-neo-error p,
        .avm-neo-status p {
            color: var(--avm-neo-muted);
            font-size: 0.76rem;
            line-height: 1.32;
            margin: 0.26rem 0 0;
        }

        .avm-neo-status span {
            color: var(--avm-neo-amber);
            font-size: 0.68rem;
            font-weight: 850;
            text-transform: uppercase;
        }

        .avm-neo-warning-summary {
            border-style: solid;
            border-color: rgba(247, 169, 40, 0.26);
            background: rgba(111, 71, 11, 0.14);
            margin-top: 0.68rem;
        }

        .avm-neo-warning-detail-stack {
            display: grid;
            gap: 0.46rem;
        }

        .avm-neo-warning-detail {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.38rem 0.72rem;
            align-items: start;
            border: 1px solid rgba(66, 132, 191, 0.16);
            border-radius: 8px;
            background: rgba(8, 18, 34, 0.58);
            padding: 0.58rem 0.66rem;
        }

        .avm-neo-warning-detail strong {
            color: #ffffff;
            display: block;
            font-size: 0.78rem;
        }

        .avm-neo-warning-detail p {
            color: var(--avm-neo-muted);
            font-size: 0.72rem;
            line-height: 1.3;
            margin: 0.12rem 0 0;
        }

        .avm-neo-warning-detail span {
            color: var(--avm-neo-amber);
            font-size: 0.66rem;
            font-weight: 820;
            text-align: right;
            text-transform: uppercase;
        }

        .avm-neo-warning-detail code {
            grid-column: 1 / -1;
            color: rgba(197, 212, 236, 0.88);
            background: rgba(3, 10, 20, 0.76);
            border: 1px solid rgba(66, 132, 191, 0.14);
            border-radius: 6px;
            display: block;
            font-size: 0.68rem;
            overflow-wrap: anywhere;
            padding: 0.28rem 0.38rem;
        }

        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-baseweb="select"] > div {
            min-height: 2.24rem;
            border-radius: 8px;
            border-color: rgba(74, 139, 199, 0.28);
            background: rgba(4, 12, 24, 0.86);
            color: var(--avm-neo-text);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
        }

        div[data-testid="stTextInput"] input:focus,
        div[data-testid="stNumberInput"] input:focus,
        div[data-baseweb="select"] > div:focus-within {
            border-color: rgba(23, 199, 255, 0.48);
            box-shadow: 0 0 0 1px rgba(23, 199, 255, 0.08);
        }

        div[data-testid="stTextInput"],
        div[data-testid="stNumberInput"],
        div[data-testid="stSelectbox"],
        div[data-testid="stCheckbox"] {
            margin-bottom: 0.12rem;
        }

        label,
        [data-testid="stWidgetLabel"] p {
            color: var(--avm-neo-soft) !important;
            font-size: 0.7rem !important;
            font-weight: 700 !important;
            overflow-wrap: normal !important;
            word-break: normal !important;
        }

        div[data-testid="stNumberInput"] label p {
            font-size: 0.64rem !important;
            line-height: 1.08 !important;
        }

        div[data-testid="stCheckbox"] label {
            border: 0;
            background: transparent;
            padding: 0;
        }

        .stFormSubmitButton button {
            width: 100%;
            min-height: 2.98rem;
            border: 1px solid rgba(23, 199, 255, 0.42);
            border-radius: 8px;
            background:
                linear-gradient(100deg, rgba(29, 162, 255, 0.98), rgba(135, 54, 255, 0.98));
            color: #ffffff;
            font-weight: 850;
            box-shadow: 0 14px 28px rgba(62, 80, 255, 0.22);
        }

        .stFormSubmitButton button:hover,
        .stButton button:hover {
            border-color: rgba(23, 199, 255, 0.5);
            color: #ffffff;
            filter: brightness(1.08);
        }

        .avm-neo-button-caption {
            color: rgba(197, 212, 236, 0.72);
            font-size: 0.68rem;
            margin-top: -1.12rem;
            padding-bottom: 0.28rem;
            text-align: center;
        }

        .stButton button {
            border-radius: 8px;
            border: 1px solid rgba(66, 132, 191, 0.24);
            background:
                linear-gradient(180deg, rgba(14, 34, 62, 0.92), rgba(8, 20, 38, 0.92));
            color: var(--avm-neo-text);
            font-size: 0.76rem;
            font-weight: 820;
            min-height: 2.42rem;
            width: 100%;
        }

        .stButton button p {
            white-space: nowrap;
        }

        .stButton button[kind="primary"] {
            border-color: rgba(23, 199, 255, 0.5);
            background:
                linear-gradient(110deg, rgba(23, 199, 255, 0.95), rgba(139, 53, 255, 0.94));
            box-shadow: 0 12px 28px rgba(62, 80, 255, 0.2);
        }

        section[data-testid="stSidebar"] .stButton button {
            justify-content: flex-start;
            min-height: 2.34rem;
            margin-top: 0.16rem;
            padding-left: 0.72rem;
        }

        section[data-testid="stSidebar"] .stButton button[kind="primary"] {
            border-color: rgba(23, 199, 255, 0.46);
            background:
                linear-gradient(90deg, rgba(23, 199, 255, 0.22), rgba(42, 114, 255, 0.13)),
                rgba(13, 42, 76, 0.78);
            box-shadow: inset 3px 0 0 rgba(23, 199, 255, 0.82), 0 0 22px rgba(23, 199, 255, 0.08);
        }

        section[data-testid="stSidebar"] .stButton button p {
            text-align: left;
        }

        section[data-testid="stSidebar"] div[data-testid="stExpander"] {
            border-color: rgba(70, 130, 190, 0.22);
            border-radius: 8px;
            background: rgba(7, 17, 32, 0.74);
        }

        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] p,
        span,
        p,
        h1,
        h2,
        h3,
        strong,
        small {
            letter-spacing: 0;
            overflow-wrap: break-word;
        }

        @media (max-width: 1180px) {
            .avm-neo-value-grid {
                grid-template-columns: 1fr;
            }

            .avm-neo-confidence-box {
                border: 1px solid rgba(66, 132, 191, 0.18);
                border-radius: 8px;
                padding: 0.65rem;
            }

            .avm-neo-market-footer {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .avm-neo-trend-meta {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }

        @media (max-width: 820px) {
            .avm-neo-topbar,
            .avm-neo-result-head,
            .avm-neo-comparable-head,
            .avm-neo-panel-header,
            .avm-neo-confidence-summary {
                align-items: flex-start;
                display: grid;
                grid-template-columns: 1fr;
            }

            .avm-neo-hero {
                grid-template-columns: 1fr;
                min-height: 12rem;
            }

            .avm-neo-hero-city {
                opacity: 0.28;
                width: 82%;
            }

            .avm-neo-location-pill {
                position: static;
                margin-top: 0.8rem;
                width: fit-content;
            }

            .avm-neo-result-metrics,
            .avm-neo-map-stats,
            .avm-neo-location-grid,
            .avm-neo-location-row,
            .avm-neo-trend-meta,
            .avm-neo-market-footer {
                grid-template-columns: 1fr;
            }

            .avm-neo-comparable {
                grid-template-columns: 3.2rem minmax(0, 1fr);
            }

            .avm-neo-comparable div:last-child {
                grid-column: 2;
                text-align: left;
            }
        }
        </style>
        """,
    )


render_tasar_playground = render
render_app_shell = render_top_nav
render_sidebar = render_sidebar_shell
