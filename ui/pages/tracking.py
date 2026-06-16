"""Portfolio/watchlist page backed by listing endpoints."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import streamlit as st

from ui.api_client import ApiClient, ApiError
from ui.components.layout import (
    empty_state,
    metric_card,
    premium_feature_card,
    section_header,
)
from ui.components.theme import html_escape, inject_theme, tone_class
from ui.formatting import format_clp, format_uf
from ui.state import get_token


def render(client: ApiClient) -> None:
    section_header(
        "Exploracion / Portafolio",
        "Listings reales del mercado y, cuando exista, tu watchlist persistente.",
    )

    controls_col, premium_col = st.columns([1.45, 1], gap="large")
    with controls_col:
        limit = st.slider("MÃ¡ximo de propiedades observadas", min_value=25, max_value=500, value=100, step=25)
    with premium_col:
        _render_premium_teasers()

    market_listings, watchlist_items = _load_real_portfolio(client, limit)
    if market_listings is None:
        return

    source_options = []
    if market_listings:
        source_options.append("Mercado real")
    if watchlist_items:
        source_options.append("Watchlist")
    if not source_options:
        _render_empty_portfolio()
        return

    selected_source = st.radio(
        "Fuente de exploracion",
        source_options,
        horizontal=True,
        key="portfolio_data_source",
    )
    using_watchlist = selected_source == "Watchlist"
    listings = watchlist_items if using_watchlist else market_listings

    _render_summary(listings)
    filters = _render_filters(listings)
    filtered = _filter_listings(listings, **filters)

    if not filtered:
        empty_state(
            "Sin propiedades para estos filtros",
            "Ajusta comuna, fuente, estado, precio o superficie para ampliar el mercado observado.",
        )
        return

    _render_portfolio_items(filtered, using_watchlist=using_watchlist)


def _load_real_portfolio(
    client: ApiClient,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | tuple[None, list[dict[str, Any]]]:
    token = get_token()
    watchlist_items: list[dict[str, Any]] = []
    if token is not None:
        try:
            watchlist_items = client.list_watchlist(token)
        except ApiError as e:
            st.warning(f"No pudimos cargar tu watchlist real: {e.message}")
    else:
        st.info("Inicia sesión para ver y guardar una watchlist persistente.")

    if token is None:
        st.info("Inicia sesión para ver el portafolio.")
        return None, []

    try:
        market_listings = client.list_listings(token=token, limit=limit)
    except ApiError as e:
        if not watchlist_items:
            _render_api_error(e)
            return None, []
        st.warning(f"No pudimos cargar el mercado completo: {e.message}")
        market_listings = []

    if watchlist_items:
        st.success("Watchlist persistente disponible como vista alternativa.")
    else:
        st.info("Aún no hay watchlist guardada. La exploración usa listings reales del mercado.")
    return market_listings, watchlist_items


def _render_summary(listings: list[dict[str, Any]]) -> None:
    comunas = {str(item.get("comuna")).strip() for item in listings if item.get("comuna")}
    prices = [_to_float(item.get("price_clp")) for item in listings]
    m2_values = [_listing_surface_m2(item) for item in listings]
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
            caption=f"Fuente principal: {source or 'No disponible'}",
            delta=_recent_delta(recent_count),
            tone="positive" if recent_count else "neutral",
        )


def _render_filters(listings: list[dict[str, Any]]) -> dict[str, Any]:
    st.subheader("Explorar mercado observado")
    st.caption("Filtros locales sobre las propiedades cargadas.")

    property_type_options = ["Todos", *_unique_property_types(listings)]
    source_options = ["Todas", *_unique_options(listings, "source")]
    status_options = ["Todos", *_unique_status_options(listings)]

    c1, c2, c3, c4 = st.columns(4)
    comuna = c1.text_input("Comuna")
    property_type = c2.selectbox(
        "Tipo de propiedad",
        property_type_options,
        format_func=_property_type_label,
    )
    source = c3.selectbox("Fuente", source_options)
    status = c4.selectbox("Estado", status_options)

    c5, c6, c7, c8 = st.columns(4)
    min_price = c5.number_input("Precio mínimo CLP", min_value=0, value=0, step=10_000_000)
    max_price = c6.number_input("Precio máximo CLP", min_value=0, value=0, step=10_000_000)
    min_m2 = c7.number_input("m² mínimo", min_value=0.0, value=0.0, step=5.0)
    max_m2 = c8.number_input("m² máximo", min_value=0.0, value=0.0, step=5.0)
    view = st.radio("Vista", ["Cards", "Tabla"], horizontal=True, key="portfolio_view")

    return {
        "comuna": comuna,
        "property_type": None if property_type == "Todos" else property_type,
        "source": None if source == "Todas" else source,
        "status": None if status == "Todos" else status,
        "min_price": min_price or None,
        "max_price": max_price or None,
        "min_m2": min_m2 or None,
        "max_m2": max_m2 or None,
        "view": view,
    }


def _render_portfolio_items(
    listings: list[dict[str, Any]],
    *,
    using_watchlist: bool,
) -> None:
    st.subheader("Propiedades en seguimiento")
    st.caption("Vista temporal basada en publicaciones disponibles. El guardado persistente llegarÃ¡ en una etapa premium.")

    if st.session_state.get("portfolio_view", "Cards") == "Tabla":
        _render_table(listings)
        return

    for index, item in enumerate(listings):
        _render_portfolio_card(item, index, using_watchlist)


def _render_portfolio_card(
    listing: dict[str, Any],
    index: int,
    using_watchlist: bool,
) -> None:
    inject_theme()
    status = str(_listing_status(listing) or "").lower()
    status_label, status_tone = _status_signal(status)
    date_label = _date_label(listing)
    facts_html = f"""
                {_fact_html("Precio UF", _format_uf(listing.get("price_uf")), "Valor publicado")}
                {_fact_html("Precio CLP", _format_clp(listing.get("price_clp")), "Referencia local")}
                {_fact_html("Superficie", _format_m2(_listing_surface_m2(listing)), "TamaÃ±o activo")}
                {_fact_html("Detectada", date_label, "Fecha de captura")}
        """

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
                        {html_escape(_format_m2(_listing_surface_m2(listing)))} |
                        {html_escape(_rooms_label(listing))}
                    </div>
                </div>
                <div style="display:flex; gap:0.35rem; flex-wrap:wrap; justify-content:flex-end;">
                    {_badge_html(status_label, status_tone)}
                    {_badge_html(_text(listing.get("source")), "neutral")}
                </div>
            </div>
            <div style="display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:0.9rem; margin-top:1rem;">
                {facts_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _render_alerts(listing.get("alerts", []))

    action_col, alert_col, compare_col = st.columns([1, 1, 1], gap="small")
    if listing.get("url"):
        action_col.link_button("Abrir publicaciÃ³n", listing["url"])
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


def _render_table(listings: list[dict[str, Any]]) -> None:
    rows = [
        {
            "ID": _listing_id(item),
            "Título": item.get("title"),
            "Comuna": item.get("comuna"),
            "Tipo": _property_type_label(_listing_property_type(item)),
            "Precio UF": _format_uf(item.get("price_uf")),
            "Precio CLP": _format_clp(item.get("price_clp")),
            "m²": _format_m2(_listing_surface_m2(item)),
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


def _render_premium_teasers() -> None:
    premium_feature_card(
        "Watchlist persistente",
        "Guarda propiedades y vuelve a ellas como activos observados.",
        status="soon",
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


def _render_api_error(error: ApiError) -> None:
    empty_state(
        "No pudimos cargar el portafolio",
        "Verifica que la API esté disponible y vuelve a intentarlo.",
        action_label=error.message,
    )


def _filter_listings(
    listings: list[dict[str, Any]],
    *,
    comuna: str,
    property_type: str | None,
    source: str | None,
    status: str | None,
    min_price: int | None,
    max_price: int | None,
    min_m2: float | None,
    max_m2: float | None,
    view: str,
) -> list[dict[str, Any]]:
    _ = view
    comuna_norm = comuna.strip().lower()
    result: list[dict[str, Any]] = []
    for item in listings:
        if comuna_norm and comuna_norm not in str(item.get("comuna", "")).lower():
            continue
        if property_type and _listing_property_type(item) != property_type:
            continue
        if source and item.get("source") != source:
            continue
        if status and _visible_status(item) != status:
            continue
        price = _to_float(item.get("price_clp"))
        if min_price is not None and (price is None or price < min_price):
            continue
        if max_price is not None and (price is None or price > max_price):
            continue
        m2 = _listing_surface_m2(item)
        if min_m2 is not None and (m2 is None or m2 < min_m2):
            continue
        if max_m2 is not None and (m2 is None or m2 > max_m2):
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


def _listing_property_type(listing: dict[str, Any]) -> str:
    return str(listing.get("property_type") or "unknown").strip().lower()


def _listing_surface_m2(listing: dict[str, Any]) -> float | None:
    for key in ("m2", "built_area_m2", "usable_area_m2", "surface_m2"):
        value = _to_float(listing.get(key))
        if value is not None:
            return value
    return None


def _property_type_label(value: Any) -> str:
    labels = {
        "Todos": "Todos",
        "apartment": "Departamento",
        "house": "Casa",
        "office": "Oficina",
        "unknown": "No disponible",
    }
    text = str(value or "unknown").strip()
    return labels.get(text, text.replace("_", " ").title())


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
        return "No disponible"
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


def _unique_property_types(listings: list[dict[str, Any]]) -> list[str]:
    return sorted({_listing_property_type(item) for item in listings})


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
        return "No disponible"
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
    return "No disponible" if value in {"\u00e2\u20ac\u201d", "—"} else value


def _text(value: Any) -> str:
    if value is None or value == "":
        return "No disponible"
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
