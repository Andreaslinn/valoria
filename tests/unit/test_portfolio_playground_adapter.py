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
        "property_type": "apartment",
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
        "property_type": "house",
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
        self.portfolio_summary_calls: list[str] = []
        self.portfolio_items_calls: list[str] = []
        self.portfolio_capabilities_calls: list[str] = []
        self.created_comparisons: list[tuple[str, str | None]] = []
        self.added_comparison_items: list[tuple[str, int, int | None, int | None]] = []
        self.removed_comparison_items: list[tuple[str, int, int]] = []

    def list_watchlist(self, token: str) -> list[dict]:
        self.watchlist_calls.append(token)
        if self.error is not None:
            raise self.error
        return self.watchlist

    def get_alerts(self, token: str, *, limit: int = 50) -> list[dict]:
        self.alert_calls.append((token, limit))
        return self.alerts

    def get_portfolio_summary(self, token: str) -> dict:
        self.portfolio_summary_calls.append(token)
        if self.error is not None:
            raise self.error
        return {
            "tracked_properties": len(self.watchlist),
            "unread_alert_count": len(self.alerts),
            "average_avm_variation": {
                "available": False,
                "status": "needs_history",
                "reason": "needs_repeated_avm_snapshots",
            },
            "upside": {
                "available": False,
                "status": "needs_snapshot",
                "reason": "needs_portfolio_avm_snapshot",
            },
            "history": {
                "available": False,
                "status": "needs_history",
                "reason": "needs_repeated_avm_snapshots",
            },
        }

    def get_portfolio_items(self, token: str) -> dict:
        self.portfolio_items_calls.append(token)
        return {"items": adapter._legacy_watchlist_to_portfolio_items(self.watchlist)}

    def get_portfolio_capabilities(self, token: str) -> dict:
        self.portfolio_capabilities_calls.append(token)
        return {
            "compared": {
                "available": False,
                "status": "not_available",
                "reason": "needs_compared_event_model",
            },
            "favorites": {
                "available": False,
                "status": "not_available",
                "reason": "needs_favorites_model",
            },
            "recommendations": {
                "available": False,
                "status": "not_available",
                "reason": "portfolio_recommendation_engine_not_implemented",
            },
        }

    def create_portfolio_comparison(self, token: str, *, title: str | None = None) -> dict:
        self.created_comparisons.append((token, title))
        return {"comparison": {"id": 77, "item_count": 0, "is_ready": False}, "items": []}

    def list_portfolio_comparisons(self, token: str) -> dict:
        return {"comparisons": []}

    def get_portfolio_comparison(self, token: str, comparison_id: int) -> dict:
        return {"comparison": {"id": comparison_id, "item_count": 0, "is_ready": False}, "items": []}

    def add_portfolio_comparison_item(
        self,
        token: str,
        comparison_id: int,
        *,
        listing_id: int | None = None,
        watchlist_item_id: int | None = None,
    ) -> dict:
        self.added_comparison_items.append((token, comparison_id, listing_id, watchlist_item_id))
        return {
            "comparison": {"id": comparison_id, "item_count": 1, "is_ready": False},
            "items": [{"id": 900, "listing_id": listing_id, "watchlist_item_id": watchlist_item_id}],
        }

    def remove_portfolio_comparison_item(self, token: str, comparison_id: int, item_id: int) -> dict:
        self.removed_comparison_items.append((token, comparison_id, item_id))
        return {"comparison": {"id": comparison_id, "item_count": 0, "is_ready": False}, "items": []}


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


def test_real_mode_calls_portfolio_backend() -> None:
    client = FakePortfolioClient(REAL_WATCHLIST, REAL_ALERTS)

    view_model = load_portfolio_view_model(
        client=client,
        token="token-123",
        demo_mode=False,
    )

    assert client.portfolio_summary_calls == ["token-123"]
    assert client.portfolio_items_calls == ["token-123"]
    assert client.portfolio_capabilities_calls == ["token-123"]
    assert client.watchlist_calls == []
    assert client.alert_calls == []
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


def test_real_filter_by_property_type_uses_watchlist_field() -> None:
    view_model = get_portfolio_view_model(
        PortfolioFilterCriteria(property_type="apartment"),
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )

    assert view_model.filters.property_types == ("Todos", "apartment", "house")
    assert [item.title for item in view_model.properties] == ["Real Pocuro 1200"]


def test_real_filter_by_property_type_combines_with_other_filters() -> None:
    view_model = get_portfolio_view_model(
        PortfolioFilterCriteria(
            comuna="Nunoa",
            status="En seguimiento",
            property_type="house",
            search="irarrazaval",
        ),
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )

    assert [item.title for item in view_model.properties] == ["Real Irarrazaval 2400"]


def test_all_property_type_filter_keeps_all_real_properties() -> None:
    view_model = get_portfolio_view_model(
        PortfolioFilterCriteria(property_type="Todos"),
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )

    assert [item.title for item in view_model.properties] == [
        "Real Pocuro 1200",
        "Real Irarrazaval 2400",
    ]


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


def test_real_summary_uses_backend_alert_count_without_activity_fixtures() -> None:
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=REAL_ALERTS,
    )

    assert view_model.activity_title == "Alertas de tus guardados"
    assert view_model.activity_badge == "Backend real"
    assert view_model.summary.active_alerts == 1
    assert view_model.activity == ()


def test_real_mode_keeps_avm_metrics_demo_or_coming_soon() -> None:
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )

    assert view_model.properties[0].avm_state == PORTFOLIO_STATUS_COMING_SOON
    assert view_model.properties[0].delta_state == PORTFOLIO_STATUS_COMING_SOON
    assert view_model.properties[0].trend_state == PORTFOLIO_STATUS_COMING_SOON
    assert view_model.summary.average_variation_pct is None
    assert view_model.summary.upside_potential_uf is None
    assert view_model.chart.source_state == PORTFOLIO_REAL_SOURCE
    assert view_model.chart.is_demo is False
    assert view_model.chart.points == ()
    assert view_model.ranking == ()
    assert view_model.recommendations == ()
    chart_html = portfolio_view.render_chart(view_model.chart)
    assert "Historial AVM no disponible" in chart_html
    assert "UF 6.720" not in chart_html


def test_real_mode_shows_backend_snapshot_values_when_available() -> None:
    items = adapter._legacy_watchlist_to_portfolio_items(REAL_WATCHLIST)
    items[0]["avm"] = {
        "available": True,
        "status": "available",
        "estimated_value_uf": 7200,
        "estimated_value_clp": 288000000,
    }
    items[0]["delta"] = {
        "available": True,
        "status": "available",
        "delta_uf": 670,
        "delta_pct": 10.26,
    }
    summary = {
        "tracked_properties": 2,
        "unread_alert_count": 1,
        "average_avm_variation": {
            "available": False,
            "status": "needs_history",
            "reason": "needs_repeated_avm_snapshots",
        },
        "upside": {
            "available": True,
            "status": "available",
            "total_upside_uf": 670,
            "average_delta_pct": 10.26,
        },
        "history": {
            "available": False,
            "status": "needs_history",
            "reason": "needs_repeated_avm_snapshots",
        },
    }

    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        summary=summary,
        items=items,
        capabilities={},
    )

    first = view_model.properties[0]
    assert first.avm_state != PORTFOLIO_STATUS_COMING_SOON
    assert first.avm_value_uf == 7200
    assert first.delta_state != PORTFOLIO_STATUS_COMING_SOON
    assert first.delta_uf == 670
    assert view_model.summary.upside_potential_uf == 670


def test_compare_selection_toggles_and_enforces_maximum() -> None:
    selected, message = adapter.toggle_compare_selection((), "101")
    assert selected == ("101",)
    assert message is None

    selected, message = adapter.toggle_compare_selection(selected, "101")
    assert selected == ()
    assert message is None

    selected = ("101", "102", "103", "104")
    updated, message = adapter.toggle_compare_selection(selected, "105")
    assert updated == selected
    assert message == "Maximo 4 propiedades para comparar."


def test_compare_cta_requires_two_selected_properties() -> None:
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )

    one_selected = adapter.build_compare_view_model(view_model, ("101",))
    two_selected = adapter.build_compare_view_model(view_model, ("101", "102"))

    assert one_selected.can_compare is False
    assert "Falta seleccionar" in portfolio_view.render_compare_cta(one_selected)
    assert "Seleccion insuficiente" in portfolio_view.render_compare_cta(one_selected)
    assert two_selected.can_compare is True
    assert "Ir a comparar" in portfolio_view.render_compare_cta(two_selected)


def test_compare_table_renders_selected_real_data_without_inventing_avm_or_delta() -> None:
    items = adapter._legacy_watchlist_to_portfolio_items(REAL_WATCHLIST)
    items[0]["avm"] = {
        "available": True,
        "status": "available",
        "estimated_value_uf": 7200,
        "estimated_value_clp": 288000000,
    }
    items[0]["delta"] = {
        "available": True,
        "status": "available",
        "delta_uf": 670,
        "delta_pct": 10.26,
    }
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        items=items,
        capabilities={},
    )
    compare_vm = adapter.build_compare_view_model(view_model, ("101", "102"))

    html = portfolio_view.render_compare_table(compare_vm)

    assert 'data-testid="portfolio-compared"' in html
    assert "Real Pocuro 1200" in html
    assert "Real Irarrazaval 2400" in html
    assert "Departamento" in html
    assert "Casa" in html
    assert "UF 7.200" in html
    assert "+10,3%" in html
    assert "+UF 670" in html
    assert "needs_current_valuation" in html
    assert "UF 999" not in html


def test_compare_selected_state_renders_on_existing_row_action() -> None:
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )

    html = portfolio_view.render_property_table(view_model, selected_ids=("101",))

    assert "portfolio_cmp=101" not in html
    assert "href=\"?portfolio_cmp" not in html
    assert "avm-portfolio-action--selected" in html
    assert "Cmp*" in html


def test_cmp_uses_real_streamlit_button_not_link_or_query_param() -> None:
    source = inspect.getsource(portfolio_view)

    assert "href=\"?portfolio_cmp" not in source
    assert "COMPARE_QUERY_PARAM" not in source
    assert "window.open" not in source
    assert "st.link_button" not in source
    assert "portfolio_cmp_row_" in source
    assert "st.button(" in source
    assert '"Cmp*" if selected else "Cmp"' in source
    assert "_render_compare_action_bar" not in source
    assert "Comparados\")" not in source
    assert "{item.title[:18]}" not in source


def test_watchlist_functional_table_keeps_cmp_inside_actions_column() -> None:
    table_source = inspect.getsource(portfolio_view._render_watchlist_functional_table)
    actions_source = inspect.getsource(portfolio_view._render_watchlist_row_actions)
    header_source = inspect.getsource(portfolio_view._watchlist_header_html)

    assert "_render_watchlist_row_actions(" in table_source
    assert "action_cols = st.columns(3" in actions_source
    assert "_view_action_link(item)" in actions_source
    assert "portfolio_cmp_row_" in actions_source
    assert "portfolio_alert_row_" in actions_source
    assert "data-testid=\"portfolio-watchlist\"" in header_source
    assert "portfolio_compare_download_html" not in table_source
    assert "portfolio_compare_download_html" not in actions_source


def test_compare_cta_has_no_fake_link_action() -> None:
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )
    compare_vm = adapter.build_compare_view_model(view_model, ("101", "102"))

    html = portfolio_view.render_compare_cta(compare_vm)

    assert "Ir a comparar" in html
    assert "<a" not in html
    assert "avm-portfolio-compare-count" in html


def test_toggle_compare_item_calls_api_client_and_updates_selection() -> None:
    client = FakePortfolioClient(REAL_WATCHLIST, REAL_ALERTS)
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )
    portfolio_view.st.session_state.clear()

    portfolio_view._toggle_compare_item(
        view_model.properties[0],
        client=client,
        token="token-123",
        comparison=None,
    )

    assert client.created_comparisons == [("token-123", "Comparacion de Portafolio")]
    assert client.added_comparison_items == [("token-123", 77, 101, None)]
    assert portfolio_view.st.session_state[portfolio_view.COMPARE_SELECTION_KEY] == ["101"]
    assert portfolio_view.st.session_state[portfolio_view.COMPARE_NOTICE_KEY] == "Agregada a comparacion."


def test_toggle_compare_item_removes_selected_api_item() -> None:
    client = FakePortfolioClient(REAL_WATCHLIST, REAL_ALERTS)
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )
    comparison = {
        "comparison": {"id": 77, "item_count": 1, "is_ready": False},
        "items": [{"id": 900, "listing_id": 101}],
    }
    portfolio_view.st.session_state.clear()

    portfolio_view._toggle_compare_item(
        view_model.properties[0],
        client=client,
        token="token-123",
        comparison=comparison,
    )

    assert client.removed_comparison_items == [("token-123", 77, 900)]
    assert portfolio_view.st.session_state[portfolio_view.COMPARE_SELECTION_KEY] == []
    assert portfolio_view.st.session_state[portfolio_view.COMPARE_NOTICE_KEY] == "Removida de comparacion."


def test_toggle_compare_item_surfaces_api_error() -> None:
    class ErrorComparisonClient(FakePortfolioClient):
        def add_portfolio_comparison_item(
            self,
            token: str,
            comparison_id: int,
            *,
            listing_id: int | None = None,
            watchlist_item_id: int | None = None,
        ) -> dict:
            raise RuntimeError("backend down")

    client = ErrorComparisonClient(REAL_WATCHLIST, REAL_ALERTS)
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )
    portfolio_view.st.session_state.clear()

    portfolio_view._toggle_compare_item(
        view_model.properties[0],
        client=client,
        token="token-123",
        comparison=None,
    )

    assert portfolio_view.st.session_state[portfolio_view.COMPARE_NOTICE_KEY] == "backend down"


def test_toggle_compare_item_blocks_more_than_four_before_api_call() -> None:
    client = FakePortfolioClient(REAL_WATCHLIST, REAL_ALERTS)
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )
    comparison = {
        "comparison": {"id": 77, "item_count": 4, "is_ready": True},
        "items": [
            {"id": 1, "listing_id": 201},
            {"id": 2, "listing_id": 202},
            {"id": 3, "listing_id": 203},
            {"id": 4, "listing_id": 204},
        ],
    }
    portfolio_view.st.session_state.clear()

    portfolio_view._toggle_compare_item(
        view_model.properties[0],
        client=client,
        token="token-123",
        comparison=comparison,
    )

    assert client.added_comparison_items == []
    assert portfolio_view.st.session_state[portfolio_view.COMPARE_NOTICE_KEY] == "Maximo 4 propiedades para comparar."


def test_real_tabs_enable_compared_but_keep_favorites_coming_soon() -> None:
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )

    tab_states = {tab.label: tab.state for tab in view_model.tabs}

    assert tab_states["Comparados"] != PORTFOLIO_STATUS_COMING_SOON
    assert tab_states["Favoritos"] == PORTFOLIO_STATUS_COMING_SOON


def test_real_mode_keeps_snapshot_sections_coming_soon_when_backend_unavailable() -> None:
    view_model = get_portfolio_view_model(
        data_mode=DATA_MODE_REAL,
        watchlist=REAL_WATCHLIST,
        alerts=[],
    )

    assert view_model.properties[0].avm_value_uf == 0
    assert view_model.properties[0].avm_state == PORTFOLIO_STATUS_COMING_SOON
    assert view_model.summary.average_variation_pct is None
    assert view_model.summary.upside_potential_uf is None


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
