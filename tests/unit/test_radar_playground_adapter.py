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
        "bedrooms": 2,
        "bathrooms": 1,
        "parking": 1,
        "property_type": "apartment",
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
        "uf_rate_used": 41931.34,
        "uf_rate_source": "mindicador.cl",
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

MAP_OPPORTUNITIES = [
    {
        **REAL_OPPORTUNITIES[0],
        "listing_id": 201,
        "title": "Real Mapa Providencia",
        "comuna": "Providencia",
        "lat": -33.42,
        "lon": -70.61,
        "geocode_precision": "address",
    },
    {
        **REAL_OPPORTUNITIES[0],
        "listing_id": 202,
        "title": "Real Mapa Nunoa",
        "comuna": "Nunoa",
        "discount_pct": 12.0,
        "score": 0.62,
        "lat": -33.45,
        "lon": -70.59,
        "geocode_precision": "street",
    },
    {
        **REAL_OPPORTUNITIES[0],
        "listing_id": 203,
        "title": "Weak geocode",
        "comuna": "Nunoa",
        "lat": -33.46,
        "lon": -70.6,
        "geocode_precision": "comuna_centroid",
    },
    {
        **REAL_OPPORTUNITIES[0],
        "listing_id": 204,
        "title": "House ignored",
        "comuna": "La Reina",
        "property_type": "house",
        "lat": -33.44,
        "lon": -70.55,
        "geocode_precision": "address",
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
        self.radar_calls: list[tuple[str | None, int, int | None]] = []
        self.alert_calls: list[tuple[str, int]] = []

    def get_radar_opportunities(
        self,
        *,
        token: str | None = None,
        limit: int = 20,
        bedrooms_min: int | None = None,
    ) -> list[dict]:
        self.radar_calls.append((token, limit, bedrooms_min))
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
    assert view_model.criteria.property_type == "Departamento"
    assert {item.property_type for item in view_model.opportunities} == {"Departamento"}


def test_radar_scope_defaults_to_apartment_only() -> None:
    view_model = build_radar_view_model()

    assert view_model.filters.property_types == ("Departamento",)
    assert view_model.filters.property_type_enabled is False
    assert view_model.filters.bedroom_options == ("Todos", "1+", "2+", "3+", "4+")
    assert view_model.filters.bedrooms_enabled is True
    assert view_model.criteria.property_type == "Departamento"
    assert {item.property_type for item in view_model.opportunities} == {"Departamento"}


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
    assert view_model.opportunities[0].property_type == "Departamento"
    assert view_model.opportunities[0].bedrooms == 2
    assert view_model.opportunities[0].bathrooms == 1
    assert view_model.opportunities[0].parking == 1
    assert view_model.opportunities[0].uf_rate_used == 41931.34
    assert view_model.opportunities[1].bedrooms is None
    assert view_model.opportunities[1].bathrooms is None


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


def test_real_filter_by_bedrooms_excludes_unknown_or_lower_values() -> None:
    view_model = get_radar_view_model(
        RadarFilterCriteria(bedrooms_min=2),
        data_mode=DATA_MODE_REAL,
        radar_opportunities=REAL_OPPORTUNITIES,
    )

    assert [item.title for item in view_model.opportunities] == ["Real Pocuro 1200"]
    assert all(item.bedrooms is not None and item.bedrooms >= 2 for item in view_model.opportunities)


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


def test_real_mode_context_panels_do_not_use_demo_fixtures() -> None:
    view_model = get_radar_view_model(
        data_mode=DATA_MODE_REAL,
        radar_opportunities=REAL_OPPORTUNITIES,
    )

    assert view_model.map.is_demo is False
    assert view_model.map.source_state == RADAR_REAL_SOURCE
    assert view_model.map.pins == ()
    assert view_model.map.status == "empty"
    assert {item.source_state for item in view_model.market_summary} == {RADAR_REAL_SOURCE}
    assert all(item.is_demo is False for item in view_model.market_summary)
    assert view_model.saved_searches == ()


def test_real_market_summary_calculates_from_real_results() -> None:
    view_model = get_radar_view_model(
        data_mode=DATA_MODE_REAL,
        radar_opportunities=REAL_OPPORTUNITIES,
    )

    assert view_model.summary.sample_size == 2
    assert view_model.summary.median_price_uf == 9450
    assert view_model.summary.median_price_m2_uf == 101.5
    assert view_model.summary.median_discount_pct == 10.96
    assert any(item.label == "Muestra Radar" and item.value == "2" for item in view_model.market_summary)


def test_real_market_summary_empty_is_honest() -> None:
    view_model = get_radar_view_model(data_mode=DATA_MODE_REAL, radar_opportunities=[])

    assert view_model.summary.status == "empty"
    assert view_model.summary.detail == "Datos insuficientes para resumen de mercado."
    assert view_model.market_summary == ()


def test_real_hot_zones_group_by_comuna_and_mark_low_sample() -> None:
    view_model = get_radar_view_model(
        data_mode=DATA_MODE_REAL,
        radar_opportunities=MAP_OPPORTUNITIES,
    )

    names = [zone.name for zone in view_model.hot_zones]
    assert "Nunoa" in names
    nunoa = next(zone for zone in view_model.hot_zones if zone.name == "Nunoa")
    assert nunoa.sample_size == 2
    assert nunoa.status == "sample_low"
    assert nunoa.basis == "por comuna"


def test_real_map_uses_only_reliable_apartment_coordinates() -> None:
    view_model = get_radar_view_model(
        data_mode=DATA_MODE_REAL,
        radar_opportunities=MAP_OPPORTUNITIES,
    )

    assert view_model.map.is_demo is False
    assert view_model.map.status == "available"
    assert [pin.label for pin in view_model.map.pins] == [
        "Real Mapa Providencia",
        "Real Mapa Nunoa",
    ]
    assert all(pin.geocode_precision in {"address", "street"} for pin in view_model.map.pins)
    assert all("House ignored" not in (pin.tooltip or "") for pin in view_model.map.pins)
    assert "Real Mapa Providencia" in (view_model.map.pins[0].tooltip or "")
    assert "Providencia" in (view_model.map.pins[0].tooltip or "")
    assert "UF 6.500" in (view_model.map.pins[0].tooltip or "")
    assert "descuento 14,5%" in (view_model.map.pins[0].tooltip or "")
    assert "score 72" in (view_model.map.pins[0].tooltip or "")


def test_real_map_empty_when_no_reliable_coordinates() -> None:
    weak = [{**REAL_OPPORTUNITIES[0], "lat": -33.45, "lon": -70.6, "geocode_precision": "unknown"}]

    view_model = get_radar_view_model(data_mode=DATA_MODE_REAL, radar_opportunities=weak)

    assert view_model.map.status == "empty"
    assert view_model.map.pins == ()
    assert "faltan coordenadas confiables" in (view_model.map.empty_message or "")


def test_real_score_uses_opportunity_score_and_absent_score_stays_unknown() -> None:
    with_opportunity_score = {
        **REAL_OPPORTUNITIES[0],
        "score": None,
        "opportunity_score": 0.81,
        "score_reason": "Score real desde Radar.",
    }
    without_score = {**REAL_OPPORTUNITIES[0], "listing_id": 777, "title": "Sin score real", "score": None}

    scored = adapter.map_radar_opportunity_response(with_opportunity_score, rank=1)
    unknown = adapter.map_radar_opportunity_response(without_score, rank=2)

    assert scored.score == 81
    assert scored.opportunity_score == 81
    assert scored.score_reason == "Score real desde Radar."
    assert unknown.score is None
    assert unknown.opportunity_score is None
    markup = radar_view.opportunity_card_html(unknown)
    assert "<strong>N/D</strong>" in markup
    assert "<strong>0</strong>" not in markup


def test_real_mode_initial_load_does_not_call_backend(monkeypatch) -> None:
    st.session_state.clear()
    client = FakeRadarClient(REAL_OPPORTUNITIES)
    monkeypatch.setattr(radar_view, "is_demo_mode", lambda: False)
    monkeypatch.setattr(radar_view, "get_token", lambda: "token-123")

    view_model = radar_view._load_view_model(client, None, reload_backend=False)

    assert client.radar_calls == []
    assert client.alert_calls == []
    assert view_model.status == RADAR_STATUS_EMPTY
    assert view_model.opportunities == ()
    assert view_model.criteria.property_type == "Departamento"
    assert view_model.criteria.bedrooms_min is None


def test_real_mode_loads_backend_opportunities_on_explicit_reload(monkeypatch) -> None:
    st.session_state.clear()
    client = FakeRadarClient(REAL_OPPORTUNITIES)
    monkeypatch.setattr(radar_view, "is_demo_mode", lambda: False)
    monkeypatch.setattr(radar_view, "get_token", lambda: "token-123")

    view_model = radar_view._load_view_model(client, None, reload_backend=True)

    assert client.radar_calls == [("token-123", 100, None)]
    assert view_model.opportunities[0].title == "Real Pocuro 1200"
    assert view_model.opportunities[0].is_demo is False


def test_real_mode_sends_bedrooms_filter_on_explicit_reload(monkeypatch) -> None:
    st.session_state.clear()
    client = FakeRadarClient(REAL_OPPORTUNITIES)
    monkeypatch.setattr(radar_view, "is_demo_mode", lambda: False)
    monkeypatch.setattr(radar_view, "get_token", lambda: "token-123")

    view_model = radar_view._load_view_model(
        client,
        RadarFilterCriteria(bedrooms_min=2),
        reload_backend=True,
    )

    assert client.radar_calls == [("token-123", 100, 2)]
    assert view_model.criteria.bedrooms_min == 2


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

    view_model = radar_view._load_view_model(client, None, reload_backend=True)

    assert client.radar_calls == [("token-123", 100, None)]
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
    assert "2D / 1B" in markup
    assert "UF 6.500" in markup
    assert "UF 7.600" in markup
    assert "14,5% bajo mercado" in markup
    assert "<strong>72</strong>" in markup
    assert "UF usada" in markup
    assert "$41.931" in markup
    assert "Ver publicacion" in markup
    assert "Comparar soon" in markup


def test_opportunity_card_uses_unknown_program_instead_of_zero_defaults() -> None:
    item = adapter.map_radar_opportunity_response(
        {
            "listing_id": 47759,
            "title": "Departamento en Nataniel Cox",
            "comuna": "Santiago",
            "price_uf": 1670,
            "price_clp": 70_000_000,
            "m2": 46,
            "estimated_price_uf": 2533,
            "discount_pct": 32.2,
            "score": 0.72,
            "confidence_score": 0.88,
            "url": "https://example.test/nataniel",
        },
        rank=1,
    )

    markup = radar_view.opportunity_card_html(item)

    assert "N/D / N/D / 46 m2" in markup
    assert "0D / 0B" not in markup


def test_opportunity_card_allows_explicit_studio_zero_bedrooms() -> None:
    item = adapter.map_radar_opportunity_response(
        {
            "listing_id": 201,
            "title": "Studio en Santiago Centro",
            "comuna": "Santiago",
            "price_uf": 1500,
            "price_clp": 62_000_000,
            "m2": 28,
            "bedrooms": 0,
            "bathrooms": 1,
            "estimated_price_uf": 1700,
            "discount_pct": 11.8,
            "score": 0.5,
        },
        rank=1,
    )

    markup = radar_view.opportunity_card_html(item)

    assert "Studio / 1B" in markup
    assert "0D" not in markup
