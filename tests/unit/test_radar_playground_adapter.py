from __future__ import annotations

import inspect

import streamlit as st

from ui.api_client import ApiError
from ui.redesign import radar_adapter as adapter
from ui.redesign import radar_view
from ui.redesign.radar_adapter import (
    DATA_MODE_REAL,
    RADAR_REAL_SOURCE,
    RADAR_STATUS_EMPTY,
    RADAR_STATUS_ERROR,
    RadarFilterCriteria,
    build_radar_view_model,
    get_radar_view_model,
)
from ui.redesign.radar_data import RADAR_DEMO_SOURCE

REAL_OPPORTUNITIES = [
    {
        "listing_id": 101,
        "title": "Real Pocuro 1200",
        "comuna": "Providencia",
        "price_uf": 6500,
        "price_clp": 253_000_000,
        "m2": 72,
        "estimated_price_uf": 7600,
        "discount_pct": 14.47,
        "score": 0.72,
        "confidence": "high",
        "confidence_score": 0.88,
        "confidence_label": "high",
        "comparables_used": 8,
        "url": "https://example.test/101",
        "warnings": [],
        "radar_verdict": "senal_fuerte",
    },
    {
        "listing_id": 102,
        "title": "Real El Golf 99",
        "comuna": "Las Condes",
        "price_uf": 12400,
        "price_clp": 483_000_000,
        "m2": 110,
        "estimated_price_uf": 13400,
        "discount_pct": 7.46,
        "score": 0.38,
        "confidence": "medium",
        "confidence_score": 0.7,
        "confidence_label": "medium",
        "comparables_used": 5,
        "url": "https://example.test/102",
        "warnings": [],
        "radar_verdict": "revisar",
    },
]


class FakeRadarClient:
    def __init__(
        self,
        opportunities: list[dict] | None = None,
        alerts: list[dict] | None = None,
        error: ApiError | None = None,
    ) -> None:
        self.opportunities = list(opportunities or [])
        self.alerts = list(alerts or [])
        self.error = error
        self.radar_calls: list[tuple[str | None, int]] = []
        self.alert_calls: list[tuple[str, int]] = []

    def get_radar_opportunities(self, *, token: str | None = None, limit: int = 20) -> list[dict]:
        self.radar_calls.append((token, limit))
        if self.error is not None:
            raise self.error
        return self.opportunities

    def get_alerts(self, token: str, *, limit: int = 50) -> list[dict]:
        self.alert_calls.append((token, limit))
        return self.alerts


def test_adapter_returns_demo_lab_opportunities() -> None:
    view_model = build_radar_view_model()

    assert view_model.is_demo is True
    assert view_model.source_state == RADAR_DEMO_SOURCE
    assert view_model.opportunities
    assert {item.source_state for item in view_model.opportunities} == {RADAR_DEMO_SOURCE}
    assert all(item.is_demo for item in view_model.opportunities)


def test_filters_by_comuna() -> None:
    view_model = build_radar_view_model(RadarFilterCriteria(comuna="Providencia"))

    assert view_model.opportunities
    assert {item.comuna for item in view_model.opportunities} == {"Providencia"}


def test_filters_by_property_type() -> None:
    view_model = build_radar_view_model(RadarFilterCriteria(property_type="Casa"))

    assert view_model.opportunities
    assert {item.property_type for item in view_model.opportunities} == {"Casa"}


def test_filters_by_minimum_score() -> None:
    view_model = build_radar_view_model(RadarFilterCriteria(min_score=85))

    assert view_model.opportunities
    assert all(item.score >= 85 for item in view_model.opportunities)


def test_ordering_by_score_desc() -> None:
    view_model = build_radar_view_model(RadarFilterCriteria(sort_by="score_desc"))

    scores = [item.score for item in view_model.opportunities]
    assert scores == sorted(scores, reverse=True)


def test_all_demo_fixture_groups_are_marked_demo_lab() -> None:
    view_model = build_radar_view_model()
    marked_items = [
        view_model,
        view_model.filters,
        view_model.summary,
        view_model.map,
        *view_model.opportunities,
        *view_model.market_summary,
        *view_model.hot_zones,
        *view_model.recent_changes,
        *view_model.saved_searches,
        *view_model.score_breakdown,
        *view_model.map.pins,
        *view_model.map.heat_zones,
    ]

    assert marked_items
    assert all(item.is_demo is True for item in marked_items)
    assert {item.source_state for item in marked_items} == {RADAR_DEMO_SOURCE}


def test_adapter_does_not_call_or_import_backend_client() -> None:
    source = inspect.getsource(adapter)

    assert "ApiClient" not in source
    assert "get_radar_opportunities" not in source


def test_real_view_model_maps_real_opportunities_without_demo_fixtures() -> None:
    view_model = get_radar_view_model(
        data_mode=DATA_MODE_REAL,
        radar_opportunities=REAL_OPPORTUNITIES,
    )

    assert view_model.is_demo is False
    assert view_model.source_state == RADAR_REAL_SOURCE
    assert [item.title for item in view_model.opportunities] == [
        "Real Pocuro 1200",
        "Real El Golf 99",
    ]
    assert {item.is_demo for item in view_model.opportunities} == {False}
    assert {item.source_state for item in view_model.opportunities} == {RADAR_REAL_SOURCE}
    assert view_model.opportunities[0].score == 72
    assert view_model.opportunities[0].status_label == "Real"


def test_real_filter_by_comuna_works() -> None:
    view_model = get_radar_view_model(
        RadarFilterCriteria(comuna="Providencia"),
        data_mode=DATA_MODE_REAL,
        radar_opportunities=REAL_OPPORTUNITIES,
    )

    assert [item.comuna for item in view_model.opportunities] == ["Providencia"]


def test_real_filter_by_minimum_score_works() -> None:
    view_model = get_radar_view_model(
        RadarFilterCriteria(min_score=50),
        data_mode=DATA_MODE_REAL,
        radar_opportunities=REAL_OPPORTUNITIES,
    )

    assert [item.listing_id if hasattr(item, "listing_id") else item.id for item in view_model.opportunities]
    assert [item.title for item in view_model.opportunities] == ["Real Pocuro 1200"]


def test_real_ordering_by_score_and_discount_work() -> None:
    by_score = get_radar_view_model(
        RadarFilterCriteria(sort_by="score_desc"),
        data_mode=DATA_MODE_REAL,
        radar_opportunities=list(reversed(REAL_OPPORTUNITIES)),
    )
    by_discount = get_radar_view_model(
        RadarFilterCriteria(sort_by="discount_desc"),
        data_mode=DATA_MODE_REAL,
        radar_opportunities=list(reversed(REAL_OPPORTUNITIES)),
    )

    assert [item.score for item in by_score.opportunities] == [72, 38]
    assert [item.discount_pct for item in by_discount.opportunities] == [14.47, 7.46]


def test_real_empty_backend_produces_empty_state() -> None:
    view_model = get_radar_view_model(data_mode=DATA_MODE_REAL, radar_opportunities=[])

    assert view_model.status == RADAR_STATUS_EMPTY
    assert view_model.opportunities == ()
    assert view_model.is_demo is False


def test_real_backend_error_produces_error_state() -> None:
    view_model = get_radar_view_model(
        data_mode=DATA_MODE_REAL,
        radar_opportunities=[],
        error_message="Radar caido",
    )

    assert view_model.status == RADAR_STATUS_ERROR
    assert view_model.opportunities == ()
    assert view_model.error_message == "Radar caido"


def test_real_alerts_map_as_saved_listing_alerts() -> None:
    view_model = get_radar_view_model(
        data_mode=DATA_MODE_REAL,
        radar_opportunities=REAL_OPPORTUNITIES,
        alerts=[
            {
                "id": 1,
                "listing_id": 101,
                "alert_type": "price_drop",
                "message": "La propiedad bajo de precio.",
                "created_at": "2026-06-04T10:15:00",
                "title": "Real Pocuro 1200",
                "comuna": "Providencia",
            }
        ],
    )

    assert view_model.recent_changes_title == "Alertas de tus guardados"
    assert view_model.recent_changes_badge == "Backend real"
    assert view_model.recent_changes[0].source_state == RADAR_REAL_SOURCE
    assert view_model.recent_changes[0].is_demo is False


def test_real_mode_keeps_map_heatmap_and_market_blocks_demo_lab() -> None:
    view_model = get_radar_view_model(
        data_mode=DATA_MODE_REAL,
        radar_opportunities=REAL_OPPORTUNITIES,
    )

    assert view_model.map.is_demo is True
    assert {pin.source_state for pin in view_model.map.pins} == {RADAR_DEMO_SOURCE}
    assert {zone.source_state for zone in view_model.map.heat_zones} == {RADAR_DEMO_SOURCE}
    assert {item.source_state for item in view_model.market_summary} == {RADAR_DEMO_SOURCE}
    assert {item.source_state for item in view_model.hot_zones} == {RADAR_DEMO_SOURCE}
    assert {item.source_state for item in view_model.saved_searches} == {RADAR_DEMO_SOURCE}


def test_real_mode_loads_backend_opportunities(monkeypatch) -> None:
    st.session_state.clear()
    client = FakeRadarClient(REAL_OPPORTUNITIES)
    monkeypatch.setattr(radar_view, "is_demo_mode", lambda: False)
    monkeypatch.setattr(radar_view, "get_token", lambda: "token-123")

    view_model = radar_view._load_view_model(client, None)

    assert client.radar_calls == [("token-123", 100)]
    assert view_model.opportunities[0].title == "Real Pocuro 1200"
    assert view_model.opportunities[0].is_demo is False


def test_demo_mode_uses_fixtures_without_backend(monkeypatch) -> None:
    st.session_state.clear()
    client = FakeRadarClient(error=ApiError("should not call"))
    monkeypatch.setattr(radar_view, "is_demo_mode", lambda: True)
    monkeypatch.setattr(radar_view, "get_token", lambda: "token-123")

    view_model = radar_view._load_view_model(client, None)

    assert client.radar_calls == []
    assert view_model.is_demo is True
    assert view_model.opportunities


def test_view_model_backend_error_from_client(monkeypatch) -> None:
    st.session_state.clear()
    client = FakeRadarClient(error=ApiError("Backend real caido", status_code=503))
    monkeypatch.setattr(radar_view, "is_demo_mode", lambda: False)
    monkeypatch.setattr(radar_view, "get_token", lambda: "token-123")

    view_model = radar_view._load_view_model(client, None)

    assert client.radar_calls == [("token-123", 100)]
    assert view_model.status == RADAR_STATUS_ERROR
    assert view_model.error_message == "Backend real caido"


def test_opportunity_list_renders_responsive_grid(monkeypatch) -> None:
    view_model = get_radar_view_model(
        data_mode=DATA_MODE_REAL,
        radar_opportunities=REAL_OPPORTUNITIES,
    )
    html_calls: list[str] = []
    monkeypatch.setattr(radar_view, "render_html", lambda markup: html_calls.append(markup))
    monkeypatch.setattr(radar_view.st, "button", lambda *args, **kwargs: False)

    radar_view.render_opportunity_list(view_model)

    markup = "\n".join(html_calls)
    assert 'class="avm-radar-opportunity-grid"' in markup
    assert markup.count('class="avm-radar-opportunity"') == 2


def test_opportunity_card_keeps_key_real_fields_and_ctas() -> None:
    view_model = get_radar_view_model(
        data_mode=DATA_MODE_REAL,
        radar_opportunities=REAL_OPPORTUNITIES,
    )

    markup = radar_view.opportunity_card_html(view_model.opportunities[0])

    assert "Real Pocuro 1200" in markup
    assert "Providencia" in markup
    assert "UF 6.500" in markup
    assert "UF 7.600" in markup
    assert "14,5% bajo mercado" in markup
    assert "<strong>72</strong>" in markup
    assert "Ver publicacion" in markup
    assert "Comparar soon" in markup
