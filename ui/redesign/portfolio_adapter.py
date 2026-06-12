"""Adapter and view models for the Portfolio playground."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ui.redesign.portfolio_data import PORTFOLIO_DEMO_SOURCE, get_portfolio_demo_fixtures

PORTFOLIO_REAL_SOURCE = "real"
DATA_MODE_REAL = "real"
DATA_MODE_DEMO = "demo/lab"
PORTFOLIO_STATUS_READY = "ready"
PORTFOLIO_STATUS_EMPTY = "empty"
PORTFOLIO_STATUS_ERROR = "error"
PORTFOLIO_STATUS_COMING_SOON = "coming_soon"

SORT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("saved_desc", "Mas recientes"),
    ("price_asc", "Menor precio"),
    ("price_desc", "Mayor precio"),
)


@dataclass(frozen=True)
class PortfolioFilterCriteria:
    comuna: str = "Todas"
    status: str = "Todos"
    search: str = ""
    sort_by: str = "saved_desc"


@dataclass(frozen=True)
class PortfolioFiltersViewModel:
    comunas: tuple[str, ...]
    statuses: tuple[str, ...]
    sort_options: tuple[tuple[str, str], ...]
    source_state: str
    is_demo: bool
    property_type_enabled: bool = False


@dataclass(frozen=True)
class PortfolioSummaryViewModel:
    tracked_properties: int
    tracked_delta: str
    average_variation_pct: float
    average_variation_caption: str
    active_alerts: int
    active_alerts_caption: str
    upside_potential_uf: int
    upside_potential_caption: str
    source_state: str
    is_demo: bool
    status: str = PORTFOLIO_STATUS_READY


@dataclass(frozen=True)
class PortfolioTabViewModel:
    label: str
    state: str
    source_state: str
    is_demo: bool


@dataclass(frozen=True)
class PortfolioPropertyViewModel:
    id: str
    title: str
    detail: str
    published_at: str
    comuna: str
    avm_value_uf: int
    avm_value_clp: int
    published_price_uf: int
    published_price_clp: int
    delta_pct: float
    delta_uf: int
    trend: tuple[int, ...]
    trend_label: str
    status_label: str
    status_tone: str
    image_tone: str
    source_state: str
    is_demo: bool
    price_basis: str = "legacy_unknown"
    price_data_quality: str = "legacy_unknown"
    url: str | None = None
    avm_state: str = PORTFOLIO_STATUS_READY
    delta_state: str = PORTFOLIO_STATUS_READY
    trend_state: str = PORTFOLIO_STATUS_READY
    status: str = PORTFOLIO_STATUS_READY


@dataclass(frozen=True)
class PortfolioActivityViewModel:
    kind: str
    detail: str
    time: str
    tone: str
    source_state: str
    is_demo: bool
    status: str = PORTFOLIO_STATUS_READY


@dataclass(frozen=True)
class PortfolioRankingViewModel:
    rank: int
    title: str
    comuna: str
    delta: str
    delta_uf: str
    image_tone: str
    source_state: str
    is_demo: bool
    status: str = PORTFOLIO_STATUS_READY


@dataclass(frozen=True)
class PortfolioRecommendationViewModel:
    title: str
    detail: str
    meta: str
    price: str
    delta: str
    tone: str
    image_tone: str
    source_state: str
    is_demo: bool
    status: str = PORTFOLIO_STATUS_READY


@dataclass(frozen=True)
class PortfolioChartViewModel:
    current_average_uf: int
    variation_pct: float
    points: tuple[int, ...]
    labels: tuple[str, ...]
    source_state: str
    is_demo: bool
    status: str = PORTFOLIO_STATUS_READY


@dataclass(frozen=True)
class PortfolioViewModel:
    criteria: PortfolioFilterCriteria
    filters: PortfolioFiltersViewModel
    summary: PortfolioSummaryViewModel
    tabs: tuple[PortfolioTabViewModel, ...]
    properties: tuple[PortfolioPropertyViewModel, ...]
    activity: tuple[PortfolioActivityViewModel, ...]
    ranking: tuple[PortfolioRankingViewModel, ...]
    recommendations: tuple[PortfolioRecommendationViewModel, ...]
    chart: PortfolioChartViewModel
    source_state: str
    is_demo: bool
    data_mode: str
    status: str
    error_message: str | None = None
    activity_title: str = "Actividad reciente"
    activity_badge: str = "demo/lab"


def get_portfolio_view_model(
    criteria: PortfolioFilterCriteria | None = None,
    *,
    data_mode: str = DATA_MODE_DEMO,
    watchlist: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    alerts: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    state: str = PORTFOLIO_STATUS_READY,
    error_message: str | None = None,
) -> PortfolioViewModel:
    """Build a Portfolio view model for real or demo/lab data."""
    if data_mode == DATA_MODE_REAL:
        return build_real_portfolio_view_model(
            criteria,
            watchlist=watchlist or (),
            alerts=alerts or (),
            error_message=error_message,
        )
    return build_demo_portfolio_view_model(criteria, state=state, error_message=error_message)


def load_portfolio_view_model(
    *,
    client: object | None,
    token: str | None,
    criteria: PortfolioFilterCriteria | None = None,
    demo_mode: bool = False,
) -> PortfolioViewModel:
    """Load Portfolio data through the UI API client and return a clean view model."""
    if demo_mode:
        return build_demo_portfolio_view_model(criteria)
    if token is None:
        return build_real_portfolio_view_model(
            criteria,
            watchlist=(),
            alerts=(),
            error_message="Inicia sesion para cargar tu Portafolio real.",
        )
    if client is None or not hasattr(client, "list_watchlist"):
        return build_real_portfolio_view_model(
            criteria,
            watchlist=(),
            alerts=(),
            error_message="Cliente API no disponible para cargar Portafolio real.",
        )
    try:
        watchlist = list(client.list_watchlist(token) or [])  # type: ignore[attr-defined]
        alerts = _safe_get_alerts(client, token)
    except Exception as exc:  # UI-facing adapter: keep backend failures controlled.
        return build_real_portfolio_view_model(
            criteria,
            watchlist=(),
            alerts=(),
            error_message=_exception_message(exc),
        )
    return build_real_portfolio_view_model(criteria, watchlist=watchlist, alerts=alerts)


def build_demo_portfolio_view_model(
    criteria: PortfolioFilterCriteria | None = None,
    *,
    state: str = PORTFOLIO_STATUS_READY,
    error_message: str | None = None,
) -> PortfolioViewModel:
    """Build a demo/lab Portfolio view model from isolated fixtures."""
    fixtures = get_portfolio_demo_fixtures()
    source_state = PORTFOLIO_DEMO_SOURCE
    is_demo = True
    properties = tuple(_map_property(item, source_state=source_state, is_demo=is_demo) for item in fixtures["properties"])
    filters = _build_filters(properties, source_state=source_state, is_demo=is_demo)
    normalized_criteria = _normalize_criteria(criteria, filters)
    properties = tuple(_sort_properties(_filter_properties(properties, normalized_criteria), normalized_criteria.sort_by))
    if state == PORTFOLIO_STATUS_EMPTY:
        properties = ()
    status = PORTFOLIO_STATUS_ERROR if error_message else state
    return PortfolioViewModel(
        criteria=normalized_criteria,
        filters=filters,
        summary=_map_summary(fixtures["summary"], source_state=source_state, is_demo=is_demo, status=status),
        tabs=tuple(
            PortfolioTabViewModel(
                label=str(label),
                state=PORTFOLIO_STATUS_READY if index == 0 else PORTFOLIO_STATUS_COMING_SOON,
                source_state=source_state,
                is_demo=is_demo,
            )
            for index, label in enumerate(fixtures["tabs"])
        ),
        properties=properties,
        activity=tuple(_map_activity(item, source_state=source_state, is_demo=is_demo) for item in fixtures["activity"]),
        ranking=tuple(_map_ranking(item, source_state=source_state, is_demo=is_demo) for item in fixtures["ranking"]),
        recommendations=tuple(_map_recommendation(item, source_state=source_state, is_demo=is_demo) for item in fixtures["recommendations"]),
        chart=_map_chart(fixtures["chart"], source_state=source_state, is_demo=is_demo),
        source_state=source_state,
        is_demo=is_demo,
        data_mode=DATA_MODE_DEMO,
        status=status,
        error_message=error_message,
        activity_title="Actividad reciente",
        activity_badge="demo/lab",
    )


def build_real_portfolio_view_model(
    criteria: PortfolioFilterCriteria | None = None,
    *,
    watchlist: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    alerts: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    error_message: str | None = None,
) -> PortfolioViewModel:
    """Build a Portfolio model from existing real watchlist and alerts endpoints."""
    fixtures = get_portfolio_demo_fixtures()
    properties = tuple(
        map_watchlist_item_response(item, index=index)
        for index, item in enumerate(watchlist)
    )
    filters = _build_filters(properties, source_state=PORTFOLIO_REAL_SOURCE, is_demo=False)
    normalized_criteria = _normalize_criteria(criteria, filters)
    filtered_properties = tuple(
        _sort_properties(_filter_properties(properties, normalized_criteria), normalized_criteria.sort_by)
    )
    status = _status_for_real(error_message, watchlist)
    return PortfolioViewModel(
        criteria=normalized_criteria,
        filters=filters,
        summary=_real_summary(
            total_properties=len(properties),
            filtered_properties=len(filtered_properties),
            alert_count=len(alerts),
            status=status,
        ),
        tabs=_real_tabs(),
        properties=filtered_properties if status != PORTFOLIO_STATUS_ERROR else (),
        activity=tuple(map_alert_response(item) for item in alerts),
        ranking=tuple(_map_ranking(item, source_state=PORTFOLIO_DEMO_SOURCE, is_demo=True) for item in fixtures["ranking"]),
        recommendations=tuple(
            _map_recommendation(item, source_state=PORTFOLIO_DEMO_SOURCE, is_demo=True)
            for item in fixtures["recommendations"]
        ),
        chart=_map_chart(fixtures["chart"], source_state=PORTFOLIO_DEMO_SOURCE, is_demo=True),
        source_state=PORTFOLIO_REAL_SOURCE,
        is_demo=False,
        data_mode=DATA_MODE_REAL,
        status=status,
        error_message=error_message,
        activity_title="Alertas de tus guardados",
        activity_badge="Backend real",
    )


def map_watchlist_item_response(item: dict[str, Any], *, index: int = 0) -> PortfolioPropertyViewModel:
    """Map an existing /watchlist item into the Portfolio table shape."""
    price_basis = _price_basis(item)
    price_uf = _canonical_or_display_price_uf(item, price_basis)
    price_clp = _safe_int(item.get("price_clp_display") or item.get("price_clp") or item.get("saved_price_clp"))
    saved_at = _format_datetime(item.get("saved_at"))
    status_label = _status_label(item.get("status"), item.get("listing_status"))
    price_quality = str(item.get("price_data_quality") or item.get("price_uf_source") or price_basis)
    return PortfolioPropertyViewModel(
        id=str(item.get("listing_id") or item.get("id") or f"watchlist-{index + 1}"),
        title=str(item.get("title") or "Propiedad en seguimiento"),
        detail=_property_detail(item),
        published_at=saved_at,
        comuna=str(item.get("comuna") or "Sin comuna"),
        avm_value_uf=0,
        avm_value_clp=0,
        published_price_uf=int(price_uf),
        published_price_clp=price_clp,
        delta_pct=0,
        delta_uf=0,
        trend=(),
        trend_label="Coming soon",
        status_label=status_label,
        status_tone=_status_tone(status_label),
        image_tone=_image_tone(index),
        source_state=PORTFOLIO_REAL_SOURCE,
        is_demo=False,
        price_basis=price_basis,
        price_data_quality=price_quality,
        url=str(item.get("url")) if item.get("url") else None,
        avm_state=PORTFOLIO_STATUS_COMING_SOON,
        delta_state=PORTFOLIO_STATUS_COMING_SOON,
        trend_state=PORTFOLIO_STATUS_COMING_SOON,
    )


def map_alert_response(item: dict[str, Any]) -> PortfolioActivityViewModel:
    """Map an existing /alerts item into the recent activity panel."""
    return PortfolioActivityViewModel(
        kind=_alert_kind(item.get("alert_type")),
        detail=_alert_detail(item),
        time=_format_datetime(item.get("created_at")),
        tone=_alert_tone(item.get("alert_type")),
        source_state=PORTFOLIO_REAL_SOURCE,
        is_demo=False,
    )


def _map_summary(data: dict[str, Any], *, source_state: str, is_demo: bool, status: str) -> PortfolioSummaryViewModel:
    return PortfolioSummaryViewModel(
        tracked_properties=int(data["tracked_properties"]),
        tracked_delta=str(data["tracked_delta"]),
        average_variation_pct=float(data["average_variation_pct"]),
        average_variation_caption=str(data["average_variation_caption"]),
        active_alerts=int(data["active_alerts"]),
        active_alerts_caption=str(data["active_alerts_caption"]),
        upside_potential_uf=int(data["upside_potential_uf"]),
        upside_potential_caption=str(data["upside_potential_caption"]),
        source_state=source_state,
        is_demo=is_demo,
        status=status,
    )


def _real_summary(
    *,
    total_properties: int,
    filtered_properties: int,
    alert_count: int,
    status: str,
) -> PortfolioSummaryViewModel:
    tracked_caption = "Watchlist real"
    if filtered_properties != total_properties:
        tracked_caption = f"{filtered_properties} visibles con filtros"
    return PortfolioSummaryViewModel(
        tracked_properties=total_properties,
        tracked_delta=tracked_caption,
        average_variation_pct=0,
        average_variation_caption="Coming soon: requiere historial AVM",
        active_alerts=alert_count,
        active_alerts_caption="Alertas de tus guardados",
        upside_potential_uf=0,
        upside_potential_caption="Coming soon: requiere AVM de portafolio",
        source_state=PORTFOLIO_REAL_SOURCE,
        is_demo=False,
        status=status,
    )


def _map_property(data: dict[str, Any], *, source_state: str, is_demo: bool) -> PortfolioPropertyViewModel:
    return PortfolioPropertyViewModel(
        id=str(data["id"]),
        title=str(data["title"]),
        detail=str(data["detail"]),
        published_at=str(data["published_at"]),
        comuna=str(data["comuna"]),
        avm_value_uf=int(data["avm_value_uf"]),
        avm_value_clp=int(data["avm_value_clp"]),
        published_price_uf=int(data["published_price_uf"]),
        published_price_clp=int(data["published_price_clp"]),
        delta_pct=float(data["delta_pct"]),
        delta_uf=int(data["delta_uf"]),
        trend=tuple(int(point) for point in data["trend"]),
        trend_label=str(data["trend_label"]),
        status_label=str(data["status"]),
        status_tone=str(data["status_tone"]),
        image_tone=str(data["image_tone"]),
        source_state=source_state,
        is_demo=is_demo,
        avm_state=PORTFOLIO_STATUS_READY if is_demo else PORTFOLIO_STATUS_COMING_SOON,
        delta_state=PORTFOLIO_STATUS_READY if is_demo else PORTFOLIO_STATUS_COMING_SOON,
        trend_state=PORTFOLIO_STATUS_READY if is_demo else PORTFOLIO_STATUS_COMING_SOON,
    )


def _map_activity(data: dict[str, Any], *, source_state: str, is_demo: bool) -> PortfolioActivityViewModel:
    return PortfolioActivityViewModel(
        kind=str(data["kind"]),
        detail=str(data["detail"]),
        time=str(data["time"]),
        tone=str(data["tone"]),
        source_state=source_state,
        is_demo=is_demo,
    )


def _map_ranking(data: dict[str, Any], *, source_state: str, is_demo: bool) -> PortfolioRankingViewModel:
    return PortfolioRankingViewModel(
        rank=int(data["rank"]),
        title=str(data["title"]),
        comuna=str(data["comuna"]),
        delta=str(data["delta"]),
        delta_uf=str(data["delta_uf"]),
        image_tone=str(data["image_tone"]),
        source_state=source_state,
        is_demo=is_demo,
    )


def _map_recommendation(data: dict[str, Any], *, source_state: str, is_demo: bool) -> PortfolioRecommendationViewModel:
    return PortfolioRecommendationViewModel(
        title=str(data["title"]),
        detail=str(data["detail"]),
        meta=str(data["meta"]),
        price=str(data["price"]),
        delta=str(data["delta"]),
        tone=str(data["tone"]),
        image_tone=str(data["image_tone"]),
        source_state=source_state,
        is_demo=is_demo,
    )


def _map_chart(data: dict[str, Any], *, source_state: str, is_demo: bool) -> PortfolioChartViewModel:
    return PortfolioChartViewModel(
        current_average_uf=int(data["current_average_uf"]),
        variation_pct=float(data["variation_pct"]),
        points=tuple(int(point) for point in data["points"]),
        labels=tuple(str(label) for label in data["labels"]),
        source_state=source_state,
        is_demo=is_demo,
    )


def _real_tabs() -> tuple[PortfolioTabViewModel, ...]:
    return (
        PortfolioTabViewModel("Watchlist", PORTFOLIO_STATUS_READY, PORTFOLIO_REAL_SOURCE, False),
        PortfolioTabViewModel("Comparados", PORTFOLIO_STATUS_COMING_SOON, PORTFOLIO_DEMO_SOURCE, True),
        PortfolioTabViewModel("Favoritos", PORTFOLIO_STATUS_COMING_SOON, PORTFOLIO_DEMO_SOURCE, True),
    )


def _build_filters(
    properties: tuple[PortfolioPropertyViewModel, ...],
    *,
    source_state: str,
    is_demo: bool,
) -> PortfolioFiltersViewModel:
    comunas = tuple(sorted({item.comuna for item in properties if item.comuna}))
    statuses = tuple(sorted({item.status_label for item in properties if item.status_label}))
    return PortfolioFiltersViewModel(
        comunas=("Todas", *comunas),
        statuses=("Todos", *statuses),
        sort_options=SORT_OPTIONS,
        source_state=source_state,
        is_demo=is_demo,
    )


def _normalize_criteria(
    criteria: PortfolioFilterCriteria | None,
    filters: PortfolioFiltersViewModel,
) -> PortfolioFilterCriteria:
    current = criteria or PortfolioFilterCriteria()
    comuna = current.comuna if current.comuna in filters.comunas else "Todas"
    status = current.status if current.status in filters.statuses else "Todos"
    sort_keys = {key for key, _label in filters.sort_options}
    sort_by = current.sort_by if current.sort_by in sort_keys else "saved_desc"
    return PortfolioFilterCriteria(
        comuna=comuna,
        status=status,
        search=str(current.search or "").strip(),
        sort_by=sort_by,
    )


def _filter_properties(
    properties: tuple[PortfolioPropertyViewModel, ...],
    criteria: PortfolioFilterCriteria,
) -> list[PortfolioPropertyViewModel]:
    search = _norm(criteria.search)
    results: list[PortfolioPropertyViewModel] = []
    for item in properties:
        if criteria.comuna != "Todas" and _norm(item.comuna) != _norm(criteria.comuna):
            continue
        if criteria.status != "Todos" and _norm(item.status_label) != _norm(criteria.status):
            continue
        haystack = _norm(" ".join((item.title, item.comuna, item.detail)))
        if search and search not in haystack:
            continue
        results.append(item)
    return results


def _sort_properties(
    properties: list[PortfolioPropertyViewModel],
    sort_by: str,
) -> list[PortfolioPropertyViewModel]:
    if sort_by == "price_asc":
        return sorted(properties, key=lambda item: (_price_sort_bucket(item), item.published_price_uf, item.published_price_clp))
    if sort_by == "price_desc":
        return sorted(properties, key=lambda item: (_price_sort_bucket(item), -item.published_price_uf, -item.published_price_clp))
    return properties


def _status_for_real(
    error_message: str | None,
    watchlist: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> str:
    if error_message:
        return PORTFOLIO_STATUS_ERROR
    if not watchlist:
        return PORTFOLIO_STATUS_EMPTY
    return PORTFOLIO_STATUS_READY


def _safe_get_alerts(client: object, token: str) -> list[dict[str, Any]]:
    if not hasattr(client, "get_alerts"):
        return []
    try:
        return list(client.get_alerts(token, limit=20) or [])  # type: ignore[attr-defined]
    except Exception:
        return []


def _exception_message(exc: Exception) -> str:
    message = getattr(exc, "message", None) or str(exc)
    return message or "Backend Portafolio no disponible."


def _property_detail(item: dict[str, Any]) -> str:
    parts: list[str] = []
    dormitorios = _safe_int(item.get("dormitorios"))
    banos = _safe_int(item.get("banos"))
    m2 = _safe_float(item.get("m2"))
    estacionamientos = _safe_int(item.get("estacionamientos"))
    if dormitorios:
        parts.append(f"{dormitorios}D")
    if banos:
        parts.append(f"{banos}B")
    if m2:
        parts.append(f"{m2:g} m2")
    if estacionamientos:
        parts.append(f"{estacionamientos} est.")
    return " · ".join(parts) if parts else "Datos base reales"


def _status_label(saved_status: Any, listing_status: Any) -> str:
    if str(saved_status or "").lower() == "active":
        return "En seguimiento"
    if listing_status:
        return str(listing_status)
    return str(saved_status or "En seguimiento")


def _status_tone(status_label: str) -> str:
    normalized = _norm(status_label)
    if "removed" in normalized or "inactivo" in normalized:
        return "warning"
    return "watching"


def _alert_kind(alert_type: Any) -> str:
    if str(alert_type or "") == "price_drop":
        return "Alerta de precio"
    return "Alerta reciente"


def _alert_detail(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "Propiedad guardada")
    comuna = str(item.get("comuna") or "").strip()
    message = str(item.get("message") or "").strip()
    if comuna:
        title = f"{title}, {comuna}"
    if message:
        return f"{title} · {message}"
    return title


def _alert_tone(alert_type: Any) -> str:
    if str(alert_type or "") == "price_drop":
        return "blue"
    return "green"


def _format_datetime(value: Any) -> str:
    if value is None:
        return "Fecha no disponible"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    text = str(value)
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed.strftime("%d/%m/%Y")
    except ValueError:
        return text[:16] if len(text) > 16 else text


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _price_basis(item: dict[str, Any]) -> str:
    return str(
        item.get("price_basis_used")
        or item.get("price_display_basis")
        or item.get("saved_price_basis")
        or "legacy_unknown"
    )


def _canonical_or_display_price_uf(item: dict[str, Any], price_basis: str) -> float:
    if price_basis == "canonical_uf":
        return _safe_float(item.get("price_uf") or item.get("saved_price_uf"))
    return 0.0


def _price_sort_bucket(item: PortfolioPropertyViewModel) -> int:
    if item.price_basis == "canonical_uf" and item.published_price_uf > 0:
        return 0
    if item.published_price_clp > 0:
        return 1
    return 2


def _image_tone(index: int) -> str:
    tones = ("tower", "glass", "city", "house", "corner", "midrise")
    return tones[index % len(tones)]


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()
