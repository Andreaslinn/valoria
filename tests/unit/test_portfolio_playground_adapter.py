from __future__ import annotations

import inspect

from ui.redesign import portfolio_adapter as adapter
from ui.redesign import portfolio_view
from ui.redesign.portfolio_adapter import (
    DATA_MODE_REAL,
    PORTFOLIO_REAL_SOURCE,
    PORTFOLIO_STATUS_COMING_SOON,
    PORTFOLIO_STATUS_EMPTY,
    PORTFOLIO_STATUS_ERROR,
    PortfolioFilterCriteria,
    get_portfolio_view_model,
    load_portfolio_view_model,
)
from ui.redesign.portfolio_data import PORTFOLIO_DEMO_SOURCE

REAL_WATCHLIST = [
    {
        "id": 11,
        "listing_id": 101,
        "saved_at": "2026-06-01T10:00:00",
        "saved_price_clp": 250000000,
        "saved_price_uf": 6400.0,
        "status": "active",
        "note": None,
        "title": "Real Pocuro 1200",
        "comuna": "Providencia",
        "price_clp": 255000000,
        "price_uf": 6530.5,
        "price_display_basis": "canonical_uf",
        "price_data_quality": "scraped",
        "m2": 72,
        "dormitorios": 2,
        "banos": 2,
        "estacionamientos": 1,
        "url": "https://example.test/pocuro",
        "source": "yapo",
        "listing_status": "active",
        "captured_at": "2026-06-02T10:00:00",
    },
    {
        "id": 12,
        "listing_id": 102,
        "saved_at": "2026-05-30T10:00:00",
        "saved_price_clp": 190000000,
        "saved_price_uf": 4860.0,
        "status": "active",
        "note": None,
        "title": "Real Irarrazaval 2400",
        "comuna": "Nunoa",
        "price_clp": 188000000,
        "price_uf": 4810.25,
        "price_display_basis": "canonical_uf",
        "price_data_quality": "scraped",
        "m2": 58,
        "dormitorios": 1,
        "banos": 1,
        "estacionamientos": 0,
        "url": "https://example.test/irarrazaval",
        "source": "yapo",
        "listing_status": "active",
        "captured_at": "2026-06-02T10:00:00",
    },
]

REAL_ALERTS = [
    {
        "id": 1,
        "listing_id": 101,
        "alert_type": "price_drop",
        "message": "La propiedad bajo de precio.",
        "payload": {"drop_pct": 2.5},
        "created_at": "2026-06-04T10:15:00",
        "is_read": False,
        "title": "Real Pocuro 1200",
        "comuna": "Providencia",
        "price_clp": 255000000,
    }
]


class FakePortfolioClient:
    def __init__(
        self,
        watchlist: list[dict] | None = None,
        alerts: list[dict] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.watchlist = watchlist or []
        self.alerts = alerts or []
        self.error = error
        self.watchlist_calls: list[str] = []
        self.alert_calls: list[tuple[str, int]] = []

    def list_watchlist(self, token: str) -> list[dict]:
        self.watchlist_calls.append(token)
        if self.error is not None:
            raise self.error
        return self.watchlist

    def get_alerts(self, token: str, *, limit: int = 50) -> list[dict]:
        self.alert_calls.append((token, limit))
        return self.alerts


def test_adapter_generates_demo_lab_data() -> None:
    view_model = get_portfolio_view_model()

    assert view_model.is_demo is True
    assert view_model.source_state == PORTFOLIO_DEMO_SOURCE
    assert view_model.properties
    assert view_model.summary.tracked_properties == 24
    assert {item.source_state for item in view_model.properties} == {PORTFOLIO_DEMO_SOURCE}
    assert all(item.is_demo for item in view_model.properties)


def test_all_blocks_are_marked_demo_lab() -> None:
    view_model = get_portfolio_view_model()
    marked_items = [
        view_model,
        view_model.summary,
        view_model.chart,
        *view_model.tabs,
        *view_model.properties,
        *view_model.activity,
        *view_model.ranking,
        *view_model.recommendations,
    ]

    assert marked_items
    assert {item.source_state for item in marked_items} == {PORTFOLIO_DEMO_SOURCE}
    assert all(item.is_demo is True for item in marked_items)


def test_watchlist_table_renders_demo_properties() -> None:
    view_model = get_portfolio_view_model()

    html = portfolio_view.render_property_table(view_model)

    assert 'data-testid="portfolio-watchlist"' in html
    assert "Av. Nueva Providencia 2215" in html
    assert "Valor AVM" in html
    assert "Precio publicado" in html
    assert "Delta vs AVM" in html


def test_activity_renders_demo_items() -> None:
    view_model = get_portfolio_view_model()

    html = portfolio_view.render_activity_panel(view_model.activity)

    assert 'data-testid="portfolio-activity"' in html
    assert "Actividad reciente" in html
    assert "Alerta de precio" in html
    assert "demo/lab" in html


def test_ranking_renders_demo_items() -> None:
    view_model = get_portfolio_view_model()

    html = portfolio_view.render_ranking_panel(view_model.ranking)

    assert 'data-testid="portfolio-ranking"' in html
    assert "Mayores alzas" in html
    assert "Simon Bolivar 900" in html
    assert "demo/lab" in html


def test_recommendations_render_demo_items() -> None:
    view_model = get_portfolio_view_model()

    html = portfolio_view.render_recommendations_panel(view_model.recommendations)

    assert 'data-testid="portfolio-recommendations"' in html
    assert "Oportunidad destacada" in html
    assert "Nueva publicacion relevante" in html
    assert "demo/lab" in html


def test_tabs_mark_future_sections_coming_soon() -> None:
    view_model = get_portfolio_view_model()

    html = portfolio_view.render_tabs(view_model)

    assert "Watchlist" in html
    assert "Comparados" in html
    assert "Favoritos" in html
    assert "coming soon" in html


def test_empty_state_removes_watchlist_rows() -> None:
    view_model = get_portfolio_view_model(state=PORTFOLIO_STATUS_EMPTY)

    html = portfolio_view.render_property_table(view_model)

    assert view_model.properties == ()
    assert "Sin propiedades en seguimiento" in html
    assert "watchlist" in html


def test_error_state_is_available() -> None:
    view_model = get_portfolio_view_model(error_message="Backend futuro no disponible")

    assert view_model.status == PORTFOLIO_STATUS_ERROR
    assert view_model.error_message == "Backend futuro no disponible"


def test_adapter_does_not_import_backend_or_legacy_portfolio() -> None:
    source = inspect.getsource(adapter)

    assert "ApiClient" not in source
    assert "ui.pages" not in source
    assert "import demo_portfolio" not in source


def test_real_mode_calls_watchlist_and_alerts() -> None:
    client = FakePortfolioClient(REAL_WATCHLIST, REAL_ALERTS)

    view_model = load_portfolio_view_model(
        client=client,
        token="token-123",
        demo_mode=False,
    )

    assert client.watchlist_calls == ["token-123"]
    assert client.alert_calls == [("token-123", 20)]
    assert view_model.source_state == PORTFOLIO_REAL_SOURCE
    assert view_model.is_demo is False
    assert [item.title for item in view_model.properties] == [
        "Real Pocuro 1200",
        "Real Irarrazaval 2400",
    ]
    assert {item.source_state for item in view_model.properties} == {PORTFOLIO_REAL_SOURCE}


def test_real_mode_does_not_use_demo_fixtures_for_main_table() -> None:
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )

    assert "Av. Nueva Providencia 2215" not in {item.title for item in view_model.properties}
    assert {item.is_demo for item in view_model.properties} == {False}
    assert view_model.summary.tracked_properties == 2


def test_demo_mode_uses_fixtures_without_backend() -> None:
    client = FakePortfolioClient(error=RuntimeError("should not call"))

    view_model = load_portfolio_view_model(
        client=client,
        token="token-123",
        demo_mode=True,
    )

    assert client.watchlist_calls == []
    assert view_model.is_demo is True
    assert view_model.properties


def test_real_filter_by_comuna_works() -> None:
    view_model = get_portfolio_view_model(
        PortfolioFilterCriteria(comuna="Nunoa"),
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )

    assert [item.comuna for item in view_model.properties] == ["Nunoa"]


def test_real_search_works() -> None:
    view_model = get_portfolio_view_model(
        PortfolioFilterCriteria(search="pocuro"),
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )

    assert [item.title for item in view_model.properties] == ["Real Pocuro 1200"]


def test_real_empty_watchlist_produces_empty_state() -> None:
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=[],
        alerts=[],
    )

    assert view_model.status == PORTFOLIO_STATUS_EMPTY
    assert view_model.properties == ()
    assert view_model.is_demo is False


def test_real_backend_error_produces_error_state() -> None:
    view_model = load_portfolio_view_model(
        client=FakePortfolioClient(error=RuntimeError("Backend caido")),
        token="token-123",
        demo_mode=False,
    )

    assert view_model.status == PORTFOLIO_STATUS_ERROR
    assert view_model.properties == ()
    assert view_model.error_message == "Backend caido"


def test_real_alerts_map_as_saved_listing_alerts() -> None:
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=REAL_ALERTS,
    )

    assert view_model.activity_title == "Alertas de tus guardados"
    assert view_model.activity_badge == "Backend real"
    assert view_model.activity[0].source_state == PORTFOLIO_REAL_SOURCE
    assert view_model.activity[0].is_demo is False
    assert view_model.activity[0].kind == "Alerta de precio"


def test_real_mode_keeps_avm_metrics_demo_or_coming_soon() -> None:
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )

    assert view_model.properties[0].avm_state == PORTFOLIO_STATUS_COMING_SOON
    assert view_model.properties[0].delta_state == PORTFOLIO_STATUS_COMING_SOON
    assert view_model.properties[0].trend_state == PORTFOLIO_STATUS_COMING_SOON
    assert view_model.chart.source_state == PORTFOLIO_DEMO_SOURCE
    assert view_model.chart.is_demo is True
    assert {item.source_state for item in view_model.ranking} == {PORTFOLIO_DEMO_SOURCE}
    assert {item.source_state for item in view_model.recommendations} == {PORTFOLIO_DEMO_SOURCE}


def test_real_property_row_renders_publication_cta() -> None:
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )

    html = portfolio_view.render_property_row(view_model.properties[0])

    assert "Real Pocuro 1200" in html
    assert "UF 6.530" in html
    assert "Coming soon" in html
    assert "Ver" in html
    assert "https://example.test/pocuro" in html


def test_real_property_with_legacy_price_does_not_render_or_sort_by_derived_uf() -> None:
    watchlist = [
        {
            **REAL_WATCHLIST[0],
            "listing_id": 201,
            "title": "Legacy UF",
            "price_uf": 999.0,
            "price_display_basis": "legacy_uf_missing_price_uf",
            "price_data_quality": "legacy_unrecoverable",
            "price_clp": 80_000_000,
        },
        {
            **REAL_WATCHLIST[1],
            "listing_id": 202,
            "title": "Canonical UF",
            "price_uf": 4800.0,
            "price_display_basis": "canonical_uf",
            "price_data_quality": "scraped",
            "price_clp": 190_000_000,
        },
    ]

    view_model = get_portfolio_view_model(
        PortfolioFilterCriteria(sort_by="price_asc"),
        data_mode=DATA_MODE_REAL,
        watchlist=watchlist,
        alerts=[],
    )

    assert [item.title for item in view_model.properties] == ["Canonical UF", "Legacy UF"]
    legacy = next(item for item in view_model.properties if item.title == "Legacy UF")
    assert legacy.published_price_uf == 0
    assert legacy.price_basis == "legacy_uf_missing_price_uf"
    html = portfolio_view.render_property_row(legacy)
    assert "UF 999" not in html
    assert "CLP snapshot" in html
    assert "legacy_unrecoverable" in html
