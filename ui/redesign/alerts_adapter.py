"""Adapter and view models for the Alerts playground."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ui.redesign.alerts_data import ALERTS_DEMO_SOURCE, get_alerts_demo_fixtures

ALERTS_REAL_SOURCE = "real"
DATA_MODE_REAL = "real"
DATA_MODE_DEMO = "demo/lab"
ALERTS_STATUS_READY = "ready"
ALERTS_STATUS_EMPTY = "empty"
ALERTS_STATUS_ERROR = "error"
ALERTS_STATUS_COMING_SOON = "coming_soon"


@dataclass(frozen=True)
class AlertsFilterCriteria:
    commune: str = "Todas"
    alert_type: str = "Todos"
    date_range: str = "Ultimos 7 dias"


@dataclass(frozen=True)
class AlertsKpiViewModel:
    label: str
    value: str
    caption: str
    icon: str
    source_state: str
    is_demo: bool
    status: str = ALERTS_STATUS_READY


@dataclass(frozen=True)
class AlertsSummaryViewModel:
    new_today: int
    new_today_delta: str
    critical: int
    critical_delta: str
    saved_rules: int
    saved_rules_caption: str
    response_time: str
    response_time_delta: str
    source_state: str
    is_demo: bool
    status: str = ALERTS_STATUS_READY


@dataclass(frozen=True)
class AlertItemViewModel:
    id: str
    listing_id: str
    alert_type: str
    icon: str
    title: str
    description: str
    commune: str
    address: str
    date: str
    metric: str
    metric_delta: str
    tone: str
    source_state: str
    is_demo: bool
    is_read: bool = False
    status: str = ALERTS_STATUS_READY


@dataclass(frozen=True)
class AlertGroupViewModel:
    title: str
    count: int
    tone: str
    items: tuple[AlertItemViewModel, ...]
    source_state: str
    is_demo: bool
    status: str = ALERTS_STATUS_READY


@dataclass(frozen=True)
class AlertTrendViewModel:
    label: str
    count: int
    delta: str
    tone: str
    source_state: str
    is_demo: bool
    status: str = ALERTS_STATUS_READY


@dataclass(frozen=True)
class AlertZoneViewModel:
    name: str
    count: int
    level: str
    delta: str
    tone: str
    source_state: str
    is_demo: bool
    status: str = ALERTS_STATUS_READY


@dataclass(frozen=True)
class AlertSettingViewModel:
    label: str
    value: str
    enabled: bool
    kind: str
    source_state: str
    is_demo: bool
    status: str = ALERTS_STATUS_COMING_SOON


@dataclass(frozen=True)
class AlertsFiltersViewModel:
    severities: tuple[str, ...]
    communes: tuple[str, ...]
    property_types: tuple[str, ...]
    dates: tuple[str, ...]
    alert_types: tuple[str, ...]
    source_state: str
    is_demo: bool
    status: str = ALERTS_STATUS_COMING_SOON
    severity_enabled: bool = False
    property_type_enabled: bool = False


@dataclass(frozen=True)
class AlertsAiViewModel:
    title: str
    description: str
    button_label: str
    source_state: str
    is_demo: bool
    status: str = ALERTS_STATUS_COMING_SOON


@dataclass(frozen=True)
class AlertsViewModel:
    criteria: AlertsFilterCriteria
    kpis: tuple[AlertsKpiViewModel, ...]
    summary: AlertsSummaryViewModel
    filters: AlertsFiltersViewModel
    groups: tuple[AlertGroupViewModel, ...]
    trends: tuple[AlertTrendViewModel, ...]
    zones: tuple[AlertZoneViewModel, ...]
    settings: tuple[AlertSettingViewModel, ...]
    ai: AlertsAiViewModel
    source_state: str
    is_demo: bool
    data_mode: str
    status: str
    error_message: str | None = None


def get_alerts_view_model(
    criteria: AlertsFilterCriteria | None = None,
    *,
    data_mode: str = DATA_MODE_DEMO,
    alerts: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    state: str = ALERTS_STATUS_READY,
    error_message: str | None = None,
    fixtures: dict[str, Any] | None = None,
) -> AlertsViewModel:
    """Build an Alerts playground model for real or demo/lab data."""
    if data_mode == DATA_MODE_REAL:
        return build_real_alerts_view_model(
            criteria,
            alerts=alerts or (),
            error_message=error_message,
        )
    return build_demo_alerts_view_model(
        criteria,
        state=state,
        error_message=error_message,
        fixtures=fixtures,
    )


def load_alerts_view_model(
    *,
    client: object | None,
    token: str | None,
    criteria: AlertsFilterCriteria | None = None,
    demo_mode: bool = False,
    limit: int = 100,
) -> AlertsViewModel:
    """Load Alerts data through the UI API client and return a clean view model."""
    if demo_mode:
        return build_demo_alerts_view_model(criteria)
    if token is None:
        return build_real_alerts_view_model(
            criteria,
            alerts=(),
            error_message="Inicia sesion para cargar alertas reales de tus guardados.",
        )
    if client is None or not hasattr(client, "get_alerts"):
        return build_real_alerts_view_model(
            criteria,
            alerts=(),
            error_message="Cliente API no disponible para cargar Alertas reales.",
        )
    try:
        alerts = list(client.get_alerts(token, limit=limit) or [])  # type: ignore[attr-defined]
    except Exception as exc:
        return build_real_alerts_view_model(
            criteria,
            alerts=(),
            error_message=_exception_message(exc),
        )
    return build_real_alerts_view_model(criteria, alerts=alerts)


def build_demo_alerts_view_model(
    criteria: AlertsFilterCriteria | None = None,
    *,
    state: str = ALERTS_STATUS_READY,
    error_message: str | None = None,
    fixtures: dict[str, Any] | None = None,
) -> AlertsViewModel:
    """Build an Alerts playground model from isolated demo/lab fixtures."""
    data = fixtures or get_alerts_demo_fixtures()
    source_state = ALERTS_DEMO_SOURCE
    is_demo = True
    status = ALERTS_STATUS_ERROR if error_message else state
    groups = tuple(_map_group(item, source_state=source_state, is_demo=is_demo) for item in data.get("alert_groups", ()))
    if status == ALERTS_STATUS_EMPTY:
        groups = ()
    filters = _map_filters(data.get("filters", {}), source_state=source_state, is_demo=is_demo)
    normalized_criteria = _normalize_criteria(criteria, filters)
    return AlertsViewModel(
        criteria=normalized_criteria,
        kpis=_demo_kpis(data.get("summary", {}), source_state=source_state, is_demo=is_demo, status=status),
        summary=_map_summary(data.get("summary", {}), source_state=source_state, is_demo=is_demo, status=status),
        filters=filters,
        groups=groups,
        trends=tuple(_map_trend(item, source_state=source_state, is_demo=is_demo) for item in data.get("trends", ())),
        zones=tuple(_map_zone(item, source_state=source_state, is_demo=is_demo) for item in data.get("zones", ())),
        settings=tuple(_map_setting(item, source_state=source_state, is_demo=is_demo) for item in data.get("settings", ())),
        ai=AlertsAiViewModel(
            title="IA te ayuda a priorizar",
            description="Deja que AVM priorice y muestre las alertas con mayor impacto para ti.",
            button_label="Activar priorizacion IA",
            source_state=source_state,
            is_demo=is_demo,
        ),
        source_state=source_state,
        is_demo=is_demo,
        data_mode=DATA_MODE_DEMO,
        status=status,
        error_message=error_message,
    )


def build_real_alerts_view_model(
    criteria: AlertsFilterCriteria | None = None,
    *,
    alerts: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    error_message: str | None = None,
) -> AlertsViewModel:
    """Build an Alerts playground model from existing /alerts responses."""
    fixture_data = get_alerts_demo_fixtures()
    raw_alerts = list(alerts)
    mapped = tuple(map_alert_response(item) for item in raw_alerts)
    filters = _build_real_filters(mapped)
    normalized_criteria = _normalize_criteria(criteria, filters)
    filtered = tuple(_filter_alerts(mapped, normalized_criteria))
    groups = _group_real_alerts(filtered)
    status = _status_for_real(error_message, raw_alerts)
    return AlertsViewModel(
        criteria=normalized_criteria,
        kpis=_real_kpis(raw_alerts, source_state=ALERTS_REAL_SOURCE, status=status),
        summary=_real_summary(raw_alerts, status=status),
        filters=filters,
        groups=groups if status != ALERTS_STATUS_ERROR else (),
        trends=tuple(_map_trend(item, source_state=ALERTS_DEMO_SOURCE, is_demo=True) for item in fixture_data.get("trends", ())),
        zones=tuple(_map_zone(item, source_state=ALERTS_DEMO_SOURCE, is_demo=True) for item in fixture_data.get("zones", ())),
        settings=tuple(_map_setting(item, source_state=ALERTS_DEMO_SOURCE, is_demo=True) for item in fixture_data.get("settings", ())),
        ai=AlertsAiViewModel(
            title="IA te ayuda a priorizar",
            description="Deja que AVM priorice y muestre las alertas con mayor impacto para ti.",
            button_label="Activar priorizacion IA",
            source_state=ALERTS_DEMO_SOURCE,
            is_demo=True,
        ),
        source_state=ALERTS_REAL_SOURCE,
        is_demo=False,
        data_mode=DATA_MODE_REAL,
        status=status,
        error_message=error_message,
    )


def map_alert_response(item: dict[str, Any]) -> AlertItemViewModel:
    """Map an existing /alerts response into the playground shape."""
    alert_type = str(item.get("alert_type") or "other")
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    title = str(item.get("title") or _alert_type_label(alert_type))
    message = str(item.get("message") or "Nueva alerta de la propiedad.")
    listing_id = str(item.get("listing_id") or "")
    return AlertItemViewModel(
        id=str(item.get("id") or ""),
        listing_id=listing_id,
        alert_type=alert_type,
        icon=_icon_for_alert_type(alert_type),
        title=_alert_type_title(alert_type, title),
        description=message,
        commune=str(item.get("comuna") or "Sin comuna"),
        address=f"Listing #{listing_id}" if listing_id else "Propiedad guardada",
        date=_format_datetime(item.get("created_at")),
        metric=_metric_for_alert(item, payload),
        metric_delta=_metric_delta_for_alert(alert_type, payload),
        tone=_tone_for_alert_type(alert_type),
        source_state=ALERTS_REAL_SOURCE,
        is_demo=False,
        is_read=bool(item.get("is_read")),
    )


def _map_summary(data: dict[str, Any], *, source_state: str, is_demo: bool, status: str) -> AlertsSummaryViewModel:
    return AlertsSummaryViewModel(
        new_today=int(data.get("new_today") or 0),
        new_today_delta=str(data.get("new_today_delta") or "demo/lab"),
        critical=int(data.get("critical") or 0),
        critical_delta=str(data.get("critical_delta") or "demo/lab"),
        saved_rules=int(data.get("saved_rules") or 0),
        saved_rules_caption=str(data.get("saved_rules_caption") or "Demo/lab"),
        response_time=str(data.get("response_time") or "Coming soon"),
        response_time_delta=str(data.get("response_time_delta") or "demo/lab"),
        source_state=source_state,
        is_demo=is_demo,
        status=status,
    )


def _real_summary(raw_alerts: list[dict[str, Any]], *, status: str) -> AlertsSummaryViewModel:
    today_count = _today_count(raw_alerts)
    price_drop_count = _type_count(raw_alerts, "price_drop")
    commune_count = len({str(item.get("comuna") or "").strip() for item in raw_alerts if item.get("comuna")})
    return AlertsSummaryViewModel(
        new_today=len(raw_alerts),
        new_today_delta="Alertas cargadas",
        critical=today_count,
        critical_delta="Creadas hoy",
        saved_rules=price_drop_count,
        saved_rules_caption="Bajas de precio",
        response_time=str(commune_count),
        response_time_delta="Comunas con alertas",
        source_state=ALERTS_REAL_SOURCE,
        is_demo=False,
        status=status,
    )


def _demo_kpis(
    data: dict[str, Any],
    *,
    source_state: str,
    is_demo: bool,
    status: str,
) -> tuple[AlertsKpiViewModel, ...]:
    return (
        AlertsKpiViewModel("Nuevas alertas hoy", str(data.get("new_today") or 0), str(data.get("new_today_delta") or "demo/lab"), "bell", source_state, is_demo, status),
        AlertsKpiViewModel("Alertas criticas", str(data.get("critical") or 0), str(data.get("critical_delta") or "demo/lab"), "critical", source_state, is_demo, status),
        AlertsKpiViewModel("Reglas guardadas", str(data.get("saved_rules") or 0), str(data.get("saved_rules_caption") or "demo/lab"), "shield", source_state, is_demo, status),
        AlertsKpiViewModel("Tiempo de respuesta promedio", str(data.get("response_time") or "Coming soon"), str(data.get("response_time_delta") or "demo/lab"), "clock", source_state, is_demo, status),
    )


def _real_kpis(
    raw_alerts: list[dict[str, Any]],
    *,
    source_state: str,
    status: str,
) -> tuple[AlertsKpiViewModel, ...]:
    today_count = _today_count(raw_alerts)
    price_drop_count = _type_count(raw_alerts, "price_drop")
    communes = {str(item.get("comuna") or "").strip() for item in raw_alerts if item.get("comuna")}
    return (
        AlertsKpiViewModel("Alertas cargadas", str(len(raw_alerts)), "Alertas de tus guardados", "bell", source_state, False, status),
        AlertsKpiViewModel("Creadas hoy", str(today_count), "Segun created_at", "clock", source_state, False, status),
        AlertsKpiViewModel("Bajas de precio", str(price_drop_count), "alert_type price_drop", "critical", source_state, False, status),
        AlertsKpiViewModel("Comunas con alertas", str(len(communes)), "Conteo simple", "shield", source_state, False, status),
    )


def _map_filters(data: dict[str, Any], *, source_state: str, is_demo: bool) -> AlertsFiltersViewModel:
    return AlertsFiltersViewModel(
        severities=tuple(str(item) for item in data.get("severity", ("Todas",))),
        communes=tuple(str(item) for item in data.get("commune", ("Todas",))),
        property_types=tuple(str(item) for item in data.get("property_type", ("Todas",))),
        dates=tuple(str(item) for item in data.get("date", ("Ultimos 7 dias",))),
        alert_types=("Todos",),
        source_state=source_state,
        is_demo=is_demo,
        severity_enabled=is_demo,
        property_type_enabled=False,
    )


def _build_real_filters(alerts: tuple[AlertItemViewModel, ...]) -> AlertsFiltersViewModel:
    communes = tuple(sorted({item.commune for item in alerts if item.commune}))
    alert_types = tuple(sorted({item.alert_type for item in alerts if item.alert_type}))
    return AlertsFiltersViewModel(
        severities=("Coming soon",),
        communes=("Todas", *communes),
        property_types=("Coming soon",),
        dates=("Todas", "Hoy", "Ultimos 7 dias", "Ultimos 30 dias"),
        alert_types=("Todos", *alert_types),
        source_state=ALERTS_REAL_SOURCE,
        is_demo=False,
        status=ALERTS_STATUS_READY,
        severity_enabled=False,
        property_type_enabled=False,
    )


def _map_group(data: dict[str, Any], *, source_state: str, is_demo: bool) -> AlertGroupViewModel:
    return AlertGroupViewModel(
        title=str(data.get("title") or "Alertas demo"),
        count=int(data.get("count") or 0),
        tone=str(data.get("tone") or "low"),
        items=tuple(_map_item(item, source_state=source_state, is_demo=is_demo) for item in data.get("items", ())),
        source_state=source_state,
        is_demo=is_demo,
    )


def _map_item(data: dict[str, Any], *, source_state: str, is_demo: bool) -> AlertItemViewModel:
    return AlertItemViewModel(
        id=str(data.get("id") or data.get("title") or "demo-alert"),
        listing_id=str(data.get("listing_id") or "demo"),
        alert_type=str(data.get("alert_type") or data.get("tone") or "demo"),
        icon=str(data.get("icon") or "alert"),
        title=str(data.get("title") or "Alerta demo"),
        description=str(data.get("description") or "Senal preparada para futuras conexiones."),
        commune=str(data.get("commune") or "Sin comuna"),
        address=str(data.get("address") or "Direccion demo"),
        date=str(data.get("date") or "Hoy"),
        metric=str(data.get("metric") or "Demo"),
        metric_delta=str(data.get("metric_delta") or "demo/lab"),
        tone=str(data.get("tone") or "low"),
        source_state=source_state,
        is_demo=is_demo,
    )


def _map_trend(data: dict[str, Any], *, source_state: str, is_demo: bool) -> AlertTrendViewModel:
    return AlertTrendViewModel(
        label=str(data.get("label") or "Tendencia demo"),
        count=int(data.get("count") or 0),
        delta=str(data.get("delta") or "0%"),
        tone=str(data.get("tone") or "positive"),
        source_state=source_state,
        is_demo=is_demo,
    )


def _map_zone(data: dict[str, Any], *, source_state: str, is_demo: bool) -> AlertZoneViewModel:
    level = str(data.get("level") or "Media")
    return AlertZoneViewModel(
        name=str(data.get("name") or "Zona demo"),
        count=int(data.get("count") or 0),
        level=level,
        delta=str(data.get("delta") or "0%"),
        tone=_zone_tone(level),
        source_state=source_state,
        is_demo=is_demo,
    )


def _map_setting(data: dict[str, Any], *, source_state: str, is_demo: bool) -> AlertSettingViewModel:
    return AlertSettingViewModel(
        label=str(data.get("label") or "Preferencia demo"),
        value=str(data.get("value") or "Coming soon"),
        enabled=bool(data.get("enabled")),
        kind=str(data.get("kind") or "switch"),
        source_state=source_state,
        is_demo=is_demo,
    )


def _zone_tone(level: str) -> str:
    normalized = level.strip().lower()
    if normalized == "alta":
        return "high"
    if normalized == "baja":
        return "low"
    return "medium"


def _normalize_criteria(
    criteria: AlertsFilterCriteria | None,
    filters: AlertsFiltersViewModel,
) -> AlertsFilterCriteria:
    current = criteria or AlertsFilterCriteria()
    commune = current.commune if current.commune in filters.communes else "Todas"
    alert_type = current.alert_type if current.alert_type in filters.alert_types else "Todos"
    date_range = current.date_range if current.date_range in filters.dates else filters.dates[0]
    return AlertsFilterCriteria(
        commune=commune,
        alert_type=alert_type,
        date_range=date_range,
    )


def _filter_alerts(
    alerts: tuple[AlertItemViewModel, ...],
    criteria: AlertsFilterCriteria,
) -> list[AlertItemViewModel]:
    results: list[AlertItemViewModel] = []
    for item in alerts:
        if criteria.commune != "Todas" and _norm(item.commune) != _norm(criteria.commune):
            continue
        if criteria.alert_type != "Todos" and item.alert_type != criteria.alert_type:
            continue
        if not _date_matches(item.date, criteria.date_range):
            continue
        results.append(item)
    return results


def _group_real_alerts(alerts: tuple[AlertItemViewModel, ...]) -> tuple[AlertGroupViewModel, ...]:
    buckets: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
        ("Bajas de precio", "critical", "price_drop", ("price_drop",)),
        ("Nuevas publicaciones/comparables", "medium", "market", ("new_listing", "new_publication", "new_comparable", "comparable")),
        ("Otras alertas", "low", "other", ()),
    )
    groups: list[AlertGroupViewModel] = []
    used_ids: set[str] = set()
    for title, tone, _key, types in buckets:
        if types:
            items = tuple(item for item in alerts if item.alert_type in types)
        else:
            items = tuple(item for item in alerts if item.id not in used_ids)
        used_ids.update(item.id for item in items)
        if not items:
            continue
        groups.append(
            AlertGroupViewModel(
                title=title,
                count=len(items),
                tone=tone,
                items=items,
                source_state=ALERTS_REAL_SOURCE,
                is_demo=False,
            )
        )
    return tuple(groups)


def _status_for_real(
    error_message: str | None,
    raw_alerts: list[dict[str, Any]],
) -> str:
    if error_message:
        return ALERTS_STATUS_ERROR
    if not raw_alerts:
        return ALERTS_STATUS_EMPTY
    return ALERTS_STATUS_READY


def _exception_message(exc: Exception) -> str:
    message = getattr(exc, "message", None) or str(exc)
    return message or "Backend Alertas no disponible."


def _alert_type_label(alert_type: str) -> str:
    if alert_type == "price_drop":
        return "Baja de precio"
    if alert_type in {"new_listing", "new_publication"}:
        return "Nueva publicacion"
    if alert_type in {"new_comparable", "comparable"}:
        return "Nuevo comparable"
    return "Alerta reciente"


def _alert_type_title(alert_type: str, title: str) -> str:
    if title and title != _alert_type_label(alert_type):
        return title
    return _alert_type_label(alert_type)


def _icon_for_alert_type(alert_type: str) -> str:
    if alert_type == "price_drop":
        return "drop"
    if alert_type in {"new_listing", "new_publication", "new_comparable", "comparable"}:
        return "scale"
    return "wave"


def _tone_for_alert_type(alert_type: str) -> str:
    if alert_type == "price_drop":
        return "critical"
    if alert_type in {"new_listing", "new_publication", "new_comparable", "comparable"}:
        return "medium"
    return "low"


def _metric_for_alert(item: dict[str, Any], payload: dict[str, Any]) -> str:
    if item.get("alert_type") == "price_drop":
        drop_pct = _safe_float(payload.get("drop_pct"))
        if drop_pct:
            return f"-{abs(drop_pct):.1f}%".replace(".", ",")
    price_clp = _safe_int(item.get("price_clp"))
    if price_clp:
        return f"$ {price_clp:,}".replace(",", ".")
    return _alert_type_label(str(item.get("alert_type") or "other"))


def _metric_delta_for_alert(alert_type: str, payload: dict[str, Any]) -> str:
    if alert_type == "price_drop":
        if str(payload.get("canonical_price_unit") or payload.get("price_currency") or "").upper() == "UF":
            previous_uf = _safe_float(payload.get("canonical_previous_price") or payload.get("previous_price_uf"))
            new_uf = _safe_float(payload.get("canonical_new_price") or payload.get("new_price_uf"))
            if previous_uf and new_uf:
                return f"UF {_format_uf_number(previous_uf)} -> UF {_format_uf_number(new_uf)}"
        previous_price = _safe_int(payload.get("canonical_previous_price") or payload.get("previous_price_clp_snapshot"))
        new_price = _safe_int(payload.get("canonical_new_price") or payload.get("new_price_clp_snapshot"))
        if previous_price and new_price:
            return f"$ {previous_price:,} -> $ {new_price:,}".replace(",", ".")
        return "Baja de precio"
    return "Alerta real"


def _today_count(raw_alerts: list[dict[str, Any]]) -> int:
    today = datetime.now(UTC).date()
    return sum(1 for item in raw_alerts if _parse_datetime(item.get("created_at")) and _parse_datetime(item.get("created_at")).date() == today)


def _type_count(raw_alerts: list[dict[str, Any]], alert_type: str) -> int:
    return sum(1 for item in raw_alerts if str(item.get("alert_type") or "") == alert_type)


def _date_matches(formatted_date: str, date_range: str) -> bool:
    if date_range == "Todas":
        return True
    parsed = _parse_datetime(formatted_date)
    if parsed is None:
        return True
    now = datetime.now(UTC)
    if date_range == "Hoy":
        return parsed.date() == now.date()
    if date_range == "Ultimos 30 dias":
        return parsed >= now - timedelta(days=30)
    return parsed >= now - timedelta(days=7)


def _format_datetime(value: Any) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return str(value or "Fecha no disponible")
    return parsed.isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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


def _format_uf_number(value: float) -> str:
    if value.is_integer():
        return f"{int(value):,}".replace(",", ".")
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()
