"""Valuation page orchestration."""
from __future__ import annotations

from typing import Any

from ui.api_client import ApiClient, ApiError
from ui.components.layout import empty_state, section_header
from ui.components.risk_report_html import build_risk_report_html, build_valuation_risk_report_data
from ui.demo_data import get_demo_valuation_result
from ui.feature_flags import is_tasar_playground_mode
from ui.product_usage import track_usage_event
from ui.redesign.tasar_playground import render_tasar_playground
from ui.state import get_token, is_demo_mode
from ui.valuation import form as valuation_form
from ui.valuation import landing as valuation_landing
from ui.valuation import result as valuation_result


def render(client: ApiClient) -> None:
    if is_tasar_playground_mode():
        render_tasar_playground(client)
        return

    valuation_landing.render_home_hero()
    valuation_landing.render_quick_access()
    demo_mode = is_demo_mode()
    if demo_mode:
        valuation_landing.render_demo_notice()
    section_header(
        "Tasar propiedad",
        "Calcula un valor estimado con comparables activos y señales simples de mercado.",
    )

    import streamlit as st

    form_col, context_col = st.columns([1.45, 1], gap="large")
    with form_col:
        payload, submitted = valuation_form.render_valuation_form(client, token=get_token())

    with context_col:
        valuation_landing.render_context_panel(client, demo_mode=demo_mode)

    demo_submitted = False
    if demo_mode:
        demo_submitted = st.button("Cargar ejemplo demo", type="secondary")

    st.divider()
    _render_property_analysis(client)

    if not submitted and not demo_submitted:
        empty_state(
            "Lista para tasar",
            "Ingresa los atributos principales de la propiedad para ver valor estimado, confianza y comparables.",
        )
        if demo_mode:
            valuation_landing.render_demo_future_sections()
        return

    if demo_submitted:
        result = get_demo_valuation_result()
        payload = {
            "precio_publicado_uf": 4550,
            "m2": 65,
            "comuna": "nunoa",
        }
        track_usage_event("valuation_submitted", _valuation_usage_properties(payload))
    else:
        track_usage_event("valuation_submitted", _valuation_usage_properties(payload))
        token = get_token()
        if token is None:
            empty_state(
                "Inicia sesión para tasar",
                "La beta privada requiere una sesión activa para acceder a datos de valoración.",
            )
            return
        try:
            result = client.create_valuation(payload, token=token)
        except ApiError as e:
            track_usage_event(
                "valuation_failed",
                {
                    **_valuation_usage_properties(payload),
                    "error_status_code": e.status_code,
                },
            )
            _render_api_error(e)
            return

    track_usage_event(
        "valuation_completed",
        {
            **_valuation_usage_properties(payload),
            "comparables_used": result.get("comparables_used"),
            "confidence_score": result.get("confidence_score"),
            "low_data_mode": result.get("low_data_mode"),
            "geocode_precision": result.get("geocode_precision"),
        },
    )
    st.divider()
    valuation_result.render_valuation_result(result, payload, api_client=client)
    if demo_mode:
        valuation_landing.render_demo_future_sections()


def _render_property_analysis(client: ApiClient) -> None:
    import streamlit as st

    st.subheader("Analizar propiedad")
    st.caption(
        "Pega una URL, extrae datos, revisalos, ejecuta la tasacion y descarga un Risk Report HTML."
    )

    with st.container(border=True):
        url = st.text_input(
            "URL de publicacion",
            key="property_analysis_url",
            placeholder="https://www.yapo.cl/...",
        )
        action_col, reset_col = st.columns([1, 0.35], gap="small")
        if action_col.button("Extraer datos", type="secondary", disabled=not bool(url.strip())):
            _extract_property_analysis_url(client, url.strip(), token=get_token())
        if reset_col.button("Limpiar", type="secondary"):
            _reset_property_analysis_state(clear_url=False)
            st.rerun()

        lookup = _current_property_analysis_lookup(url)
        if lookup is None:
            if url.strip():
                st.info("Pulsa Extraer datos para analizar esta URL.")
            else:
                st.info("Ingresa una URL y pulsa Extraer datos para comenzar.")
            return

        _render_property_analysis_lookup_status(lookup)
        if lookup.get("status") not in {"found_existing", "parsed_new", "partial"}:
            return

        payload = _render_property_analysis_review()
        if st.button("Ejecutar tasacion", type="primary", key="property_analysis_run_valuation"):
            _run_property_analysis_valuation(client, payload, lookup)

        result = st.session_state.get("property_analysis_result")
        saved_payload = st.session_state.get("property_analysis_payload")
        if isinstance(result, dict) and isinstance(saved_payload, dict) and saved_payload != payload:
            st.warning("Los datos editados cambiaron. Ejecuta la tasacion nuevamente para actualizar el resultado y el reporte.")
        elif isinstance(result, dict) and isinstance(saved_payload, dict):
            st.divider()
            st.subheader("Resultado del analisis")
            valuation_result.render_valuation_result(result, saved_payload, api_client=client)
            _render_property_analysis_actions(client, lookup, result, saved_payload)


def _extract_property_analysis_url(client: ApiClient, url: str, *, token: str | None) -> None:
    import streamlit as st

    _reset_property_analysis_state(clear_url=False)
    with st.spinner("Extrayendo datos de la publicacion..."):
        try:
            lookup = client.lookup_listing_url(url, token=token)
        except ApiError as e:
            st.session_state["property_analysis_lookup"] = {
                "status": "error",
                "listing_data": {},
                "warnings": [e.message],
                "source": None,
                "url": url,
            }
            return
    st.session_state["property_analysis_lookup"] = lookup
    listing_data = lookup.get("listing_data") if isinstance(lookup.get("listing_data"), dict) else {}
    st.session_state["property_analysis_form_data"] = dict(listing_data)
    if lookup.get("status") in {"found_existing", "parsed_new", "partial"}:
        _populate_property_analysis_widgets(listing_data)


def _current_property_analysis_lookup(url: str) -> dict[str, Any] | None:
    import streamlit as st

    lookup = st.session_state.get("property_analysis_lookup")
    if not isinstance(lookup, dict):
        return None
    if lookup.get("url") != url.strip():
        return None
    return lookup


def _reset_property_analysis_state(*, clear_url: bool) -> None:
    import streamlit as st

    keys = [
        "property_analysis_lookup",
        "property_analysis_form_data",
        "property_analysis_payload",
        "property_analysis_result",
        "property_analysis_watchlist_saved",
        "property_analysis_error",
    ]
    widget_keys = [
        "property_analysis_comuna",
        "property_analysis_location_query",
        "property_analysis_property_type",
        "property_analysis_built_area_m2",
        "property_analysis_land_area_m2",
        "property_analysis_dormitorios",
        "property_analysis_banos",
        "property_analysis_estacionamientos",
        "property_analysis_precio_uf",
        "property_analysis_precio_clp",
    ]
    for key in keys + widget_keys:
        st.session_state.pop(key, None)
    if clear_url:
        st.session_state.pop("property_analysis_url", None)


def _populate_property_analysis_widgets(data: dict[str, Any]) -> None:
    import streamlit as st

    property_type = _property_type_label(data.get("property_type"))
    built_area = _to_positive_float(data.get("built_area_m2") or data.get("m2"), default=0.0)
    st.session_state["property_analysis_comuna"] = str(data.get("comuna") or "")
    st.session_state["property_analysis_location_query"] = str(data.get("location_query") or _location_hint_from_listing_data(data) or "")
    st.session_state["property_analysis_property_type"] = property_type
    st.session_state["property_analysis_built_area_m2"] = built_area
    st.session_state["property_analysis_land_area_m2"] = _to_positive_float(data.get("land_area_m2"), default=0.0)
    st.session_state["property_analysis_dormitorios"] = int(_to_non_negative_int(data.get("dormitorios"), default=0))
    st.session_state["property_analysis_banos"] = int(_to_non_negative_int(data.get("banos"), default=0))
    st.session_state["property_analysis_estacionamientos"] = int(
        _to_non_negative_int(data.get("estacionamientos"), default=0)
    )
    st.session_state["property_analysis_precio_uf"] = float(_to_positive_float(data.get("precio_publicado_uf"), default=0.0))
    st.session_state["property_analysis_precio_clp"] = int(_to_non_negative_int(data.get("precio_publicado_clp"), default=0))


def _render_property_analysis_lookup_status(lookup: dict[str, Any]) -> None:
    import streamlit as st

    status = lookup.get("status")
    warnings = lookup.get("warnings") or []
    listing_data = lookup.get("listing_data") if isinstance(lookup.get("listing_data"), dict) else {}
    listing_id = listing_data.get("listing_id")

    if status == "found_existing":
        st.success(f"Publicacion encontrada en la base AVM. Listing ID: {listing_id or 'N/A'}.")
    elif status == "parsed_new":
        st.success("Datos extraidos desde la URL. Revisa antes de tasar.")
    elif status == "partial":
        st.warning("Se extrajeron datos parciales. Completa los campos faltantes antes de tasar.")
    elif status == "unsupported_source":
        st.warning("Fuente aun no soportada para extraccion automatica.")
    elif status == "invalid_url":
        st.error("URL invalida o privada. Usa una URL publica de una publicacion.")
    else:
        st.error("No pudimos extraer datos desde esa URL.")

    if warnings:
        st.caption("Advertencias: " + ", ".join(str(item) for item in warnings))


def _render_property_analysis_review() -> dict[str, Any]:
    import streamlit as st

    st.markdown("#### Revision editable")
    st.caption("Ajusta cualquier dato extraido antes de ejecutar la tasacion.")

    type_col, comuna_col = st.columns([0.7, 1], gap="medium")
    with type_col:
        property_type_label = st.selectbox(
            "Tipo propiedad",
            ["Departamento", "Casa", "Oficina", "Desconocido"],
            key="property_analysis_property_type",
        )
    with comuna_col:
        comuna = st.text_input("Comuna", key="property_analysis_comuna")
    location_query = st.text_input(
        "Ubicación específica opcional",
        key="property_analysis_location_query",
        help=(
            "Puedes ingresar calle, intersección, metro, plaza o sector. "
            "Ej: Mujica, Metro Chile España, Plaza Ñuñoa."
        ),
    )

    property_type = valuation_form.property_type_payload_value(property_type_label)

    if property_type == "house":
        area_col, land_col = st.columns(2, gap="medium")
        built_area_m2 = area_col.number_input(
            "m2 construidos",
            min_value=0.0,
            step=1.0,
            key="property_analysis_built_area_m2",
        )
        land_area_m2 = land_col.number_input(
            "m2 terreno",
            min_value=0.0,
            step=1.0,
            key="property_analysis_land_area_m2",
        )
    else:
        built_area_m2 = st.number_input(
            "m2 utiles/construidos",
            min_value=0.0,
            step=1.0,
            key="property_analysis_built_area_m2",
        )
        land_area_m2 = None

    d_col, b_col, p_col = st.columns(3, gap="medium")
    dormitorios = d_col.number_input("Dormitorios", min_value=0, step=1, key="property_analysis_dormitorios")
    banos = b_col.number_input("Banos", min_value=0, step=1, key="property_analysis_banos")
    estacionamientos = p_col.number_input(
        "Estacionamientos",
        min_value=0,
        step=1,
        key="property_analysis_estacionamientos",
    )

    price_uf_col, price_clp_col = st.columns(2, gap="medium")
    precio_uf = price_uf_col.number_input(
        "Precio publicado UF opcional",
        min_value=0.0,
        step=10.0,
        key="property_analysis_precio_uf",
    )
    precio_clp = price_clp_col.number_input(
        "Precio publicado CLP opcional",
        min_value=0,
        step=1_000_000,
        key="property_analysis_precio_clp",
    )

    return valuation_form.build_valuation_payload(
        comuna=comuna,
        property_type=property_type,
        built_area_m2=float(built_area_m2),
        land_area_m2=float(land_area_m2) if land_area_m2 else None,
        dormitorios=int(dormitorios),
        banos=int(banos),
        estacionamientos=int(estacionamientos),
        precio_uf=float(precio_uf) if precio_uf else None,
        precio_clp=int(precio_clp) if precio_clp else None,
        location_query=location_query,
    )


def _run_property_analysis_valuation(client: ApiClient, payload: dict[str, Any], lookup: dict[str, Any]) -> None:
    import streamlit as st

    if not str(payload.get("comuna") or "").strip():
        st.error("Completa la comuna antes de tasar.")
        return
    if float(payload.get("built_area_m2") or payload.get("m2") or 0) <= 0:
        st.error("Completa la superficie antes de tasar.")
        return

    token = get_token()
    if token is None:
        empty_state(
            "Inicia sesion para analizar",
            "La tasacion real requiere una sesion activa.",
        )
        return

    track_usage_event("property_analysis_submitted", _valuation_usage_properties(payload))
    with st.spinner("Ejecutando tasacion..."):
        try:
            result = client.create_valuation(payload, token=token)
        except ApiError as e:
            track_usage_event(
                "property_analysis_failed",
                {
                    **_valuation_usage_properties(payload),
                    "error_status_code": e.status_code,
                },
            )
            _render_api_error(e)
            return

    st.session_state["property_analysis_payload"] = payload
    st.session_state["property_analysis_result"] = result
    st.session_state["property_analysis_lookup"] = lookup
    st.session_state.pop("property_analysis_watchlist_saved", None)
    track_usage_event(
        "property_analysis_completed",
        {
            **_valuation_usage_properties(payload),
            "comparable_count": result.get("comparable_count"),
            "confidence": result.get("confidence"),
        },
    )
    st.success("Tasacion lista. Ya puedes descargar el Risk Report HTML.")


def _render_property_analysis_actions(
    client: ApiClient,
    lookup: dict[str, Any],
    result: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    import streamlit as st

    listing_data = lookup.get("listing_data") if isinstance(lookup.get("listing_data"), dict) else {}
    listing_id = _safe_int(listing_data.get("listing_id"))
    report_data = build_valuation_risk_report_data(result, payload, lookup)
    report_html = build_risk_report_html(report_data)
    file_suffix = listing_id or "analisis_url"

    report_col, watch_col, link_col = st.columns([1, 1, 1], gap="small")
    report_col.download_button(
        "Descargar Risk Report HTML",
        data=report_html,
        file_name=f"risk_report_{file_suffix}.html",
        mime="text/html",
        key=f"property-analysis-risk-report-{file_suffix}",
    )

    token = get_token()
    if listing_id is None:
        watch_col.button("Agregar a Watchlist", disabled=True, key="property-analysis-watchlist-missing")
        st.info("Esta propiedad no tiene listing_id guardado en AVM; por ahora no se puede agregar al Watchlist real.")
    elif token is None:
        watch_col.button("Agregar a Watchlist", disabled=True, key=f"property-analysis-watchlist-login-{listing_id}")
        st.info("Inicia sesion para agregar esta propiedad al Watchlist.")
    elif st.session_state.get("property_analysis_watchlist_saved"):
        watch_col.button("Guardado", disabled=True, key=f"property-analysis-watchlist-saved-{listing_id}")
    elif watch_col.button("Agregar a Watchlist", key=f"property-analysis-watchlist-save-{listing_id}"):
        try:
            client.save_to_watchlist(listing_id, token)
            st.session_state["property_analysis_watchlist_saved"] = True
            st.success("Propiedad agregada al Watchlist.")
        except ApiError as e:
            st.error(f"No se pudo agregar al Watchlist: {e.message}")

    url = lookup.get("url") or listing_data.get("url")
    if url:
        link_col.link_button("Abrir publicacion", str(url))
    else:
        link_col.button("Sin enlace", disabled=True, key="property-analysis-no-url")


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _property_type_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"house", "casa"}:
        return "Casa"
    if text in {"office", "oficina"}:
        return "Oficina"
    if text in {"unknown", "desconocido", ""}:
        return "Desconocido"
    return "Departamento"


def _to_positive_float(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _to_non_negative_int(value: Any, *, default: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def _location_hint_from_listing_data(data: dict[str, Any]) -> str | None:
    for key in ("address_label", "street_hint", "location_query"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raw_metadata = data.get("raw_metadata")
    if isinstance(raw_metadata, dict):
        for key in ("address_label", "street_hint"):
            value = raw_metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _render_api_error(error: ApiError) -> None:
    if error.status_code == 400:
        empty_state(
            "Datos insuficientes para una tasación confiable",
            "No hay comparables suficientes para estimar esta propiedad con seguridad.",
            action_label=error.message,
        )
        return
    empty_state(
        "No pudimos conectar con la tasación",
        "Verifica que la API esté corriendo y vuelve a intentarlo.",
        action_label=error.message,
    )


def _valuation_usage_properties(payload: dict) -> dict:
    return {
        "comuna": payload.get("comuna"),
        "property_type": payload.get("property_type"),
        "m2": payload.get("m2"),
        "built_area_m2": payload.get("built_area_m2"),
        "land_area_m2": payload.get("land_area_m2"),
        "bedrooms": payload.get("dormitorios"),
        "bathrooms": payload.get("banos"),
        "parking": payload.get("estacionamientos"),
    }


_render_valuation_form = valuation_form.render_valuation_form
_build_valuation_payload = valuation_form.build_valuation_payload
_property_type_payload_value = valuation_form.property_type_payload_value
_quick_card = valuation_landing.quick_card
_render_context_panel = valuation_landing.render_context_panel
_render_demo_future_sections = valuation_landing.render_demo_future_sections
_render_demo_notice = valuation_landing.render_demo_notice
_render_home_hero = valuation_landing.render_home_hero
_render_quick_access = valuation_landing.render_quick_access
_comparable_count_sentence = valuation_result.comparable_count_sentence
_comparable_count_value = valuation_result.comparable_count_value
_confidence_explanation = valuation_result.confidence_explanation_text
_confidence_score_text = valuation_result.confidence_score_text
_confidence_signal = valuation_result.confidence_signal
_data_signal = valuation_result.data_signal
_format_m2 = valuation_result.format_m2
_format_rooms = valuation_result.format_rooms
_has_approx_geocoding = valuation_result.has_approx_geocoding
_has_unknown_property_type = valuation_result.has_unknown_property_type
_is_low_data_mode = valuation_result.is_low_data_mode
_market_signal = valuation_result.market_signal
_normalize_confidence = valuation_result.normalize_confidence
_property_type_display = valuation_result.property_type_display
_range_band_position = valuation_result.range_band_position
_render_comparables = valuation_result.render_comparables
_render_comparables_compact = valuation_result.render_comparables_compact
_render_valuation_result = valuation_result.render_valuation_result
_to_float = valuation_result.to_float
_valuation_quality_state = valuation_result.valuation_quality_state
_valuation_risk_messages = valuation_result.valuation_risk_messages
_warning_codes = valuation_result.warning_codes
