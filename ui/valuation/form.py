"""Valuation input form components."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient, ApiError


def render_valuation_form(
    client: ApiClient | None = None,
    *,
    token: str | None = None,
) -> tuple[dict[str, Any], bool]:
    st.subheader("Datos de la propiedad")
    st.caption("Usa la informacion esencial. El precio publicado es opcional.")
    _render_url_lookup(client or ApiClient(), token=token)
    prefill = st.session_state.get("valuation_prefill", {})

    property_type_label = st.selectbox(
        "Tipo propiedad",
        ["Departamento", "Casa", "Oficina"],
        index=_property_type_index(prefill.get("property_type")),
        key="valuation_property_type",
    )
    property_type = property_type_payload_value(property_type_label)

    with st.form("valuation_form"):
        comuna = st.text_input("Comuna", value=str(prefill.get("comuna") or "nunoa"))
        location_query = st.text_input(
            "Ubicación específica opcional",
            value=str(prefill.get("location_query") or ""),
            help=(
                "Puedes ingresar calle, intersección, metro, plaza o sector. "
                "Ej: Mujica, Metro Chile España, Plaza Ñuñoa."
            ),
        )

        if property_type == "house":
            c1, c2 = st.columns(2)
            built_area_m2 = c1.number_input(
                "m2 construidos",
                min_value=1.0,
                value=float(prefill.get("built_area_m2") or 140.0),
                step=1.0,
            )
            land_area_m2 = c2.number_input(
                "m2 terreno",
                min_value=1.0,
                value=float(prefill.get("land_area_m2") or 300.0),
                step=1.0,
            )
        else:
            built_area_m2 = st.number_input(
                "m2 utiles/construidos",
                min_value=1.0,
                value=float(prefill.get("built_area_m2") or prefill.get("m2") or 75.0),
                step=1.0,
            )
            land_area_m2 = None

        c3, c4, c5 = st.columns(3)
        dormitorios = c3.number_input("Dormitorios", min_value=0, value=int(prefill.get("dormitorios") or 3), step=1)
        banos = c4.number_input("Banos", min_value=0, value=int(prefill.get("banos") or 2), step=1)
        estacionamientos = c5.number_input(
            "Estacionamientos",
            min_value=0,
            value=int(prefill.get("estacionamientos") or 1),
            step=1,
        )

        c6, c7 = st.columns(2)
        precio_uf = c6.number_input(
            "Precio publicado UF opcional",
            min_value=0.0,
            value=float(prefill.get("precio_publicado_uf") or 0.0),
        )
        precio_clp = c7.number_input(
            "Precio publicado CLP opcional",
            min_value=0,
            value=int(prefill.get("precio_publicado_clp") or 0),
        )

        submitted = st.form_submit_button("Tasar", type="primary")

    payload = build_valuation_payload(
        comuna=comuna,
        property_type=property_type,
        built_area_m2=built_area_m2,
        land_area_m2=land_area_m2,
        dormitorios=int(dormitorios),
        banos=int(banos),
        estacionamientos=int(estacionamientos),
        precio_uf=precio_uf or None,
        precio_clp=int(precio_clp) or None,
        location_query=location_query,
    )
    return payload, submitted


def _render_url_lookup(client: ApiClient, *, token: str | None) -> None:
    with st.expander("Tasar desde URL de publicacion", expanded=False):
        url = st.text_input("URL Yapo", key="valuation_listing_url")
        if st.button("Buscar publicacion", type="secondary"):
            try:
                result = client.lookup_listing_url(url, token=token)
            except ApiError as exc:
                st.warning(exc.message) if exc.status_code == 400 else st.error(exc.message)
                return

            result_status = result.get("status")
            listing_data = result.get("listing_data") if isinstance(result.get("listing_data"), dict) else {}
            if result_status in {"found_existing", "parsed_new", "partial"}:
                st.session_state["valuation_prefill"] = listing_data
                if result_status == "partial":
                    st.warning("Se extrajeron datos parciales. Completa los campos faltantes antes de tasar.")
                else:
                    st.success("Publicacion cargada. Revisa los datos antes de tasar.")
            elif result_status == "unsupported_source":
                st.warning("Fuente aun no soportada.")
            else:
                st.error("No pudimos cargar esa URL.")


def _property_type_index(value: str | None) -> int:
    if value == "house":
        return 1
    if value == "office":
        return 2
    return 0


def property_type_payload_value(label: str) -> str:
    mapping = {
        "departamento": "apartment",
        "casa": "house",
        "oficina": "office",
        "desconocido": "unknown",
        "unknown": "unknown",
    }
    return mapping.get(label.strip().lower(), "apartment")


def build_valuation_payload(
    *,
    comuna: str,
    property_type: str,
    built_area_m2: float,
    land_area_m2: float | None,
    dormitorios: int,
    banos: int,
    estacionamientos: int,
    precio_uf: float | None,
    precio_clp: int | None,
    location_query: str | None = None,
) -> dict[str, Any]:
    is_apartment = property_type == "apartment"
    payload = {
        "comuna": comuna.strip(),
        "property_type": property_type,
        "m2": built_area_m2,
        "built_area_m2": built_area_m2,
        "land_area_m2": None if is_apartment else land_area_m2,
        "usable_area_m2": built_area_m2 if is_apartment else None,
        "dormitorios": dormitorios,
        "banos": banos,
        "estacionamientos": estacionamientos,
        "precio_publicado_uf": precio_uf,
        "precio_publicado_clp": precio_clp,
    }
    clean_location_query = str(location_query or "").strip()
    if clean_location_query:
        payload["location_query"] = clean_location_query
    return payload


# Backward-compatible private names used by older tests.
_render_valuation_form = render_valuation_form
_property_type_payload_value = property_type_payload_value
_build_valuation_payload = build_valuation_payload
