from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

from ui.redesign import alerts_adapter as adapter
from ui.redesign import alerts_view
from ui.redesign.alerts_adapter import (
    ALERTS_REAL_SOURCE,
    ALERTS_STATUS_COMING_SOON,
    ALERTS_STATUS_EMPTY,
    ALERTS_STATUS_ERROR,
    AlertsFilterCriteria,
    DATA_MODE_REAL,
    get_alerts_view_model,
    load_alerts_view_model,
)
from ui.redesign.alerts_data import ALERTS_DEMO_SOURCE

NOW = datetime.now(UTC)
REAL_ALERTS = [
    {
        "id": 1,
        "listing_id": 101,
        "alert_type": "price_drop",
        "message": "La propiedad bajo de precio.",
        "payload": {
            "previous_price_clp": 210000000,
            "new_price_clp": 198000000,
            "drop_pct": 5.7,
        },
        "created_at": NOW.isoformat(),
        "is_read": False,
        "title": "Real Pocuro 1200",
        "comuna": "Providencia",
        "price_clp": 198000000,
    },
    {
        "id": 2,
        "listing_id": 102,
        "alert_type": "new_comparable",
        "message": "Nuevo comparable cercano.",
        "payload": {},
        "created_at": (NOW - timedelta(days=10)).isoformat(),
        "is_read": False,
        "title": "Real Irarrazaval 2400",
        "comuna": "Nunoa",
        "price_clp": 185000000,
    },
]


class FakeAlertsClient:
    def __init__(self, alerts: list[dict] | None = None, error: Exception | None = None) -> None:
        self.alerts = alerts or []
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def get_alerts(self, token: str, *, limit: int = 50) -> list[dict]:
        self.calls.append((token, limit))
        if self.error is not None:
            raise self.error
        return self.alerts


def test_adapter_generates_demo_alerts() -> None:
    view_model = get_alerts_view_model()

    assert view_model.is_demo is True
    assert view_model.source_state == ALERTS_DEMO_SOURCE
    assert view_model.groups
    assert view_model.summary.new_today == 18
    assert {group.source_state for group in view_model.groups} == {ALERTS_DEMO_SOURCE}


def test_all_blocks_are_marked_demo_lab_or_coming_soon() -> None:
    view_model = get_alerts_view_model()
    marked_items = [
        view_model,
        view_model.summary,
        view_model.filters,
        view_model.ai,
        *view_model.groups,
        *view_model.trends,
        *view_model.zones,
        *view_model.settings,
    ]

    assert marked_items
    assert {item.source_state for item in marked_items} == {ALERTS_DEMO_SOURCE}
    assert all(item.is_demo is True for item in marked_items)
    assert view_model.filters.status == ALERTS_STATUS_COMING_SOON
    assert view_model.ai.status == ALERTS_STATUS_COMING_SOON
    assert {item.status for item in view_model.settings} == {ALERTS_STATUS_COMING_SOON}


def test_render_alerts_demo_groups() -> None:
    view_model = get_alerts_view_model()

    html = alerts_view.render_alert_groups(view_model)

    assert 'data-testid="alerts-group"' in html
    assert "Alertas criticas" in html
    assert "Caida de precio significativa" in html
    assert "Bajo precio vs mercado" in html
    assert "demo/lab" in html


def test_render_trends_panel() -> None:
    view_model = get_alerts_view_model()

    html = alerts_view.render_trends_panel(view_model)

    assert 'data-testid="alerts-trends"' in html
    assert "Tendencias de alertas" in html
    assert "Caida de precio" in html
    assert "demo/lab" in html


def test_render_settings_panel() -> None:
    view_model = get_alerts_view_model()

    html = alerts_view.render_settings_panel(view_model)

    assert 'data-testid="alerts-settings"' in html
    assert "Configuracion de notificaciones" in html
    assert "Notificaciones push" in html
    assert "coming soon" in html


def test_render_kpis_in_hero(monkeypatch) -> None:
    view_model = get_alerts_view_model()
    html_calls: list[str] = []
    monkeypatch.setattr(alerts_view, "render_html", lambda markup: html_calls.append(markup))

    alerts_view.render_hero(view_model)

    markup = "\n".join(html_calls)
    assert "Recibe se&ntilde;ales al instante" in markup
    assert "Nuevas alertas hoy" in markup
    assert "Alertas criticas" in markup
    assert "Reglas guardadas" in markup
    assert "Tiempo de respuesta promedio" in markup


def test_empty_state_renders_without_alert_rows() -> None:
    view_model = get_alerts_view_model(state=ALERTS_STATUS_EMPTY)

    html = alerts_view.render_alert_groups(view_model)

    assert view_model.groups == ()
    assert "Sin alertas" in html


def test_error_state_is_available() -> None:
    view_model = get_alerts_view_model(error_message="Futuro backend no disponible")

    assert view_model.status == ALERTS_STATUS_ERROR
    assert view_model.error_message == "Futuro backend no disponible"


def test_ai_card_renders_coming_soon() -> None:
    view_model = get_alerts_view_model()

    html = alerts_view.render_ai_panel(view_model)

    assert 'data-testid="alerts-ai"' in html
    assert "Activar priorizacion IA" in html
    assert "Coming Soon" in html


def test_adapter_does_not_import_backend_or_legacy_alerts() -> None:
    source = inspect.getsource(adapter)
    view_source = inspect.getsource(alerts_view)

    assert "ApiClient" not in source
    assert "ui.pages" not in source
    assert "ui.demo_alerts" not in source
    assert ".get_alerts" not in view_source


def test_real_mode_calls_get_alerts() -> None:
    client = FakeAlertsClient(REAL_ALERTS)

    view_model = load_alerts_view_model(client=client, token="token-123", demo_mode=False)

    assert client.calls == [("token-123", 100)]
    assert view_model.source_state == ALERTS_REAL_SOURCE
    assert view_model.is_demo is False
    assert view_model.groups


def test_real_mode_does_not_use_demo_fixtures_for_main_list() -> None:
    view_model = get_alerts_view_model(data_mode=DATA_MODE_REAL, alerts=REAL_ALERTS)
    titles = {item.title for group in view_model.groups for item in group.items}

    assert "Caida de precio significativa" not in titles
    assert "Real Pocuro 1200" in titles
    assert {group.source_state for group in view_model.groups} == {ALERTS_REAL_SOURCE}


def test_demo_mode_uses_fixtures_without_backend() -> None:
    client = FakeAlertsClient(error=RuntimeError("should not call"))

    view_model = load_alerts_view_model(client=client, token="token-123", demo_mode=True)

    assert client.calls == []
    assert view_model.is_demo is True
    assert view_model.groups


def test_real_empty_alerts_produces_empty_state() -> None:
    view_model = get_alerts_view_model(data_mode=DATA_MODE_REAL, alerts=[])

    assert view_model.status == ALERTS_STATUS_EMPTY
    assert view_model.groups == ()
    assert view_model.is_demo is False


def test_real_backend_error_produces_error_state() -> None:
    view_model = load_alerts_view_model(
        client=FakeAlertsClient(error=RuntimeError("Backend caido")),
        token="token-123",
        demo_mode=False,
    )

    assert view_model.status == ALERTS_STATUS_ERROR
    assert view_model.groups == ()
    assert view_model.error_message == "Backend caido"


def test_real_filter_by_commune_works() -> None:
    view_model = get_alerts_view_model(
        AlertsFilterCriteria(commune="Nunoa", date_range="Todas"),
        data_mode=DATA_MODE_REAL,
        alerts=REAL_ALERTS,
    )

    titles = [item.title for group in view_model.groups for item in group.items]
    assert titles == ["Real Irarrazaval 2400"]


def test_real_filter_by_date_works() -> None:
    view_model = get_alerts_view_model(
        AlertsFilterCriteria(date_range="Hoy"),
        data_mode=DATA_MODE_REAL,
        alerts=REAL_ALERTS,
    )

    titles = [item.title for group in view_model.groups for item in group.items]
    assert titles == ["Real Pocuro 1200"]


def test_real_filter_by_alert_type_works() -> None:
    view_model = get_alerts_view_model(
        AlertsFilterCriteria(alert_type="new_comparable", date_range="Todas"),
        data_mode=DATA_MODE_REAL,
        alerts=REAL_ALERTS,
    )

    titles = [item.title for group in view_model.groups for item in group.items]
    assert titles == ["Real Irarrazaval 2400"]


def test_real_kpis_are_calculated_from_alerts() -> None:
    view_model = get_alerts_view_model(data_mode=DATA_MODE_REAL, alerts=REAL_ALERTS)

    kpis = {item.label: item.value for item in view_model.kpis}
    assert kpis["Alertas cargadas"] == "2"
    assert kpis["Creadas hoy"] == "1"
    assert kpis["Bajas de precio"] == "1"
    assert kpis["Comunas con alertas"] == "2"


def test_real_groups_do_not_invent_severity_labels() -> None:
    view_model = get_alerts_view_model(
        AlertsFilterCriteria(date_range="Todas"),
        data_mode=DATA_MODE_REAL,
        alerts=REAL_ALERTS,
    )
    group_titles = [group.title for group in view_model.groups]

    assert "Alertas criticas" not in group_titles
    assert "Alertas medias" not in group_titles
    assert "Alertas bajas" not in group_titles
    assert group_titles == ["Bajas de precio", "Nuevas publicaciones/comparables"]


def test_real_mode_keeps_non_real_blocks_demo_or_coming_soon() -> None:
    view_model = get_alerts_view_model(data_mode=DATA_MODE_REAL, alerts=REAL_ALERTS)

    assert {item.source_state for item in view_model.trends} == {ALERTS_DEMO_SOURCE}
    assert {item.source_state for item in view_model.zones} == {ALERTS_DEMO_SOURCE}
    assert {item.status for item in view_model.settings} == {ALERTS_STATUS_COMING_SOON}
    assert view_model.ai.status == ALERTS_STATUS_COMING_SOON
