from __future__ import annotations

import pytest
import streamlit as st

from ui.api_client import ApiError
from ui.redesign import tasar_playground_adapter as adapter
from ui.redesign.tasar_playground import (
    DEFAULT_COMUNA_SLUG,
    NAV_ITEMS,
    UNKNOWN_PREFILL_COMUNA_KEY,
    _apply_url_prefill_to_tasar_state,
    _comuna_for_payload,
    _comuna_index,
    _first_present,
    _load_recent_user_activity,
    _normalize_price_trend_for_chart,
    _resolve_comuna_slug,
    _trend_reason_label,
    render_recent_activity,
)
from ui.redesign.tasar_playground_adapter import (
    build_tasar_risk_report_contract,
    get_tasar_payload_from_form,
    map_valuation_response_to_view_model,
    run_valuation_for_tasar,
)
from ui.valuation.form import build_valuation_payload, property_type_payload_value


class FakeClient:
    def __init__(self, response: dict | None = None) -> None:
        self.response = response or {"estimated_price_uf": 5100, "status": "ok"}
        self.calls: list[tuple[dict, str | None]] = []

    def create_valuation(self, payload: dict, token: str | None = None) -> dict:
        self.calls.append((payload, token))
        return self.response


class FailingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, str | None]] = []

    def create_valuation(self, payload: dict, token: str | None = None) -> dict:
        self.calls.append((payload, token))
        raise ApiError("Backend real caido", status_code=503)


class ActivityClient:
    def __init__(self, response: dict | None = None, error: ApiError | None = None) -> None:
        self.response = response or {"status": "empty", "events": []}
        self.error = error
        self.calls: list[tuple[str | None, int]] = []

    def get_tasar_recent_activity(self, *, token: str | None = None, limit: int = 3) -> dict:
        self.calls.append((token, limit))
        if self.error is not None:
            raise self.error
        return self.response


class DummyContainer:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_tasar_playground_navigation_matches_dashboard_layout_targets() -> None:
    labels = [label for _slug, label, _page in NAV_ITEMS]
    pages = [page for _slug, _label, page in NAV_ITEMS]

    assert labels == ["Tasar propiedad", "Radar premium", "Portafolio", "Alertas"]
    assert pages == ["Tasar propiedad", "Radar", "Portafolio", "Alertas Lab"]


def test_get_tasar_payload_from_form_reuses_legacy_contract_for_apartment() -> None:
    payload = get_tasar_payload_from_form(
        comuna=" providencia ",
        property_type="apartment",
        built_area_m2=75.0,
        land_area_m2=180.0,
        dormitorios=3,
        banos=2,
        estacionamientos=1,
        precio_uf=6400.0,
        precio_clp=252_000_000,
    )

    assert payload == {
        "comuna": "providencia",
        "property_type": "apartment",
        "m2": 75.0,
        "built_area_m2": 75.0,
        "land_area_m2": None,
        "usable_area_m2": 75.0,
        "dormitorios": 3,
        "banos": 2,
        "estacionamientos": 1,
        "precio_publicado_uf": 6400.0,
        "precio_publicado_clp": 252_000_000,
    }


def test_get_tasar_payload_from_form_keeps_house_land_area() -> None:
    payload = get_tasar_payload_from_form(
        comuna="la_reina",
        property_type="house",
        built_area_m2=140.0,
        land_area_m2=300.0,
        dormitorios=4,
        banos=3,
        estacionamientos=2,
        precio_uf=None,
        precio_clp=None,
    )

    assert payload["m2"] == 140.0
    assert payload["built_area_m2"] == 140.0
    assert payload["land_area_m2"] == 300.0
    assert payload["usable_area_m2"] is None


def test_playground_payload_uses_selected_backend_comuna_slug_for_controlled_case() -> None:
    selected_comuna = _resolve_comuna_slug("Vitacura")
    assert selected_comuna == "vitacura"

    legacy_payload = build_valuation_payload(
        comuna=selected_comuna,
        property_type=property_type_payload_value("Casa"),
        built_area_m2=221.0,
        land_area_m2=512.0,
        dormitorios=5,
        banos=5,
        estacionamientos=1,
        precio_uf=None,
        precio_clp=None,
    )
    playground_payload = get_tasar_payload_from_form(
        comuna=_comuna_for_payload(selected_comuna),
        property_type=property_type_payload_value("Casa"),
        built_area_m2=221.0,
        land_area_m2=512.0,
        dormitorios=5,
        banos=5,
        estacionamientos=1,
        precio_uf=None,
        precio_clp=None,
    )

    assert playground_payload == legacy_payload
    assert playground_payload["comuna"] == "vitacura"


def test_comuna_for_payload_only_strips_and_does_not_lowercase_free_text() -> None:
    assert _comuna_for_payload(" Vitacura ") == "Vitacura"
    assert _comuna_for_payload("LAS CONDES") == "LAS CONDES"


def test_comuna_selector_resolves_readable_labels_to_backend_slugs() -> None:
    assert _resolve_comuna_slug("Vitacura") == "vitacura"
    assert _resolve_comuna_slug("Ñuñoa") == "nunoa"
    assert _resolve_comuna_slug("Las Condes") == "las_condes"
    assert _comuna_index("Vitacura") == _comuna_index("vitacura")


def test_first_present_preserves_zero_values_for_real_form_defaults() -> None:
    data = {"precio_publicado_uf": 0.0, "precio_publicado_clp": 0}

    assert _first_present(data, "precio_publicado_uf", "price_uf", default=6400.0) == 0.0
    assert _first_present(data, "precio_publicado_clp", "price_clp", default=252_000_000) == 0


def test_url_prefill_updates_real_playground_widget_state() -> None:
    st.session_state.clear()

    _apply_url_prefill_to_tasar_state(
        {
            "property_type": "house",
            "comuna": "Vitacura",
            "built_area_m2": 221,
            "land_area_m2": 512,
            "dormitorios": 5,
            "banos": 5,
            "estacionamientos": 1,
            "precio_publicado_uf": 0,
            "precio_publicado_clp": 0,
            "url": "https://www.yapo.cl/inmuebles/casa-vitacura-demo",
        },
        fallback_url="https://www.yapo.cl/inmuebles/casa-vitacura-demo",
    )

    assert st.session_state["tasar_pg_property_type"] == "Casa"
    assert st.session_state["tasar_pg_comuna"] == "vitacura"
    assert st.session_state["tasar_pg_built_area_m2"] == 221.0
    assert st.session_state["tasar_pg_land_area_m2"] == 512.0
    assert st.session_state["tasar_pg_dormitorios"] == 5
    assert st.session_state["tasar_pg_banos"] == 5
    assert st.session_state["tasar_pg_estacionamientos"] == 1
    assert st.session_state["tasar_pg_precio_uf"] == 0.0
    assert st.session_state["tasar_pg_precio_clp"] == 0


def test_url_prefill_unknown_comuna_keeps_selector_valid_and_sets_warning() -> None:
    st.session_state.clear()

    _apply_url_prefill_to_tasar_state(
        {
            "property_type": "apartment",
            "comuna": "Marte Centro",
            "built_area_m2": 75,
            "url": "https://www.yapo.cl/inmuebles/depto-marte-demo",
        },
        fallback_url="https://www.yapo.cl/inmuebles/depto-marte-demo",
    )

    assert st.session_state["tasar_pg_comuna"] == DEFAULT_COMUNA_SLUG
    assert st.session_state[UNKNOWN_PREFILL_COMUNA_KEY] == "Marte Centro"


def test_load_recent_user_activity_uses_real_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ActivityClient({"status": "partial", "events": [{"title": "Tasaste una propiedad"}]})
    monkeypatch.setattr("ui.redesign.tasar_playground.get_token", lambda: "token-123")

    activity = _load_recent_user_activity(client)  # type: ignore[arg-type]

    assert activity["status"] == "partial"
    assert client.calls == [("token-123", 3)]


def test_load_recent_user_activity_handles_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ActivityClient(error=ApiError("Backend caido", status_code=503))
    monkeypatch.setattr("ui.redesign.tasar_playground.get_token", lambda: "token-123")

    activity = _load_recent_user_activity(client)  # type: ignore[arg-type]

    assert activity["status"] == "not_available"
    assert activity["events"] == []


def test_recent_activity_panel_renders_real_user_events(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, list] = {"headers": [], "badges": [], "html": []}
    monkeypatch.setattr("ui.redesign.tasar_playground.st.container", lambda **kwargs: DummyContainer())
    monkeypatch.setattr(
        "ui.redesign.tasar_playground.render_panel_header",
        lambda title, action: calls["headers"].append((title, action)),
    )
    monkeypatch.setattr(
        "ui.redesign.tasar_playground.render_status_badge",
        lambda *args: calls["badges"].append(args),
    )
    monkeypatch.setattr("ui.redesign.tasar_playground.render_html", lambda html: calls["html"].append(html))

    render_recent_activity(
        {
            "status": "partial",
            "events": [
                {
                    "event_type": "valuation_created",
                    "title": "Tasaste una propiedad",
                    "description": "Departamento en Providencia · UF 6.294",
                    "occurred_at": "2026-06-25T10:28:00Z",
                }
            ],
        }
    )

    markup = "\n".join(calls["html"])
    assert calls["headers"] == [("Actividad reciente", "Historial parcial")]
    assert calls["badges"] == []
    assert "Tasaste una propiedad" in markup
    assert "Departamento en Providencia" in markup
    assert "Coming soon" not in markup


def test_recent_activity_panel_renders_honest_empty_state(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, list] = {"headers": [], "badges": []}
    monkeypatch.setattr("ui.redesign.tasar_playground.st.container", lambda **kwargs: DummyContainer())
    monkeypatch.setattr(
        "ui.redesign.tasar_playground.render_panel_header",
        lambda title, action: calls["headers"].append((title, action)),
    )
    monkeypatch.setattr(
        "ui.redesign.tasar_playground.render_status_badge",
        lambda *args: calls["badges"].append(args),
    )

    render_recent_activity({"status": "empty", "events": []})

    assert calls["headers"] == [("Actividad reciente", "Sin actividad")]
    assert calls["badges"][0][1] == "empty"
    assert "No hay actividad reciente registrada" in calls["badges"][0][2]


def test_run_valuation_for_tasar_real_calls_api_client_with_token() -> None:
    payload = {"comuna": "providencia", "m2": 75.0}
    client = FakeClient({"estimated_price_uf": 6200, "confidence": "high"})

    result = run_valuation_for_tasar(client, payload, token="token-123", demo_mode=False)

    assert result == {"estimated_price_uf": 6200, "confidence": "high"}
    assert client.calls == [(payload, "token-123")]


def test_run_valuation_for_tasar_real_requires_token() -> None:
    client = FakeClient()

    with pytest.raises(ApiError) as exc:
        run_valuation_for_tasar(client, {"comuna": "providencia"}, token=None, demo_mode=False)

    assert exc.value.status_code == 401
    assert client.calls == []


def test_run_valuation_for_tasar_real_error_does_not_fallback_to_demo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FailingClient()
    payload = {"comuna": "providencia", "m2": 75.0}

    def fail_demo() -> dict:
        raise AssertionError("get_demo_valuation_result must not be called in real mode")

    monkeypatch.setattr(adapter, "get_demo_valuation_result", fail_demo)

    with pytest.raises(ApiError) as exc:
        run_valuation_for_tasar(client, payload, token="token-123", demo_mode=False)

    assert exc.value.message == "Backend real caido"
    assert exc.value.status_code == 503
    assert client.calls == [(payload, "token-123")]


def test_run_valuation_for_tasar_demo_uses_demo_result_without_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    demo_result = {"estimated_price_uf": 4820, "confidence": "high", "comparables": []}
    monkeypatch.setattr(adapter, "get_demo_valuation_result", lambda: dict(demo_result))

    result = run_valuation_for_tasar(client, {"comuna": "nunoa"}, token=None, demo_mode=True)

    assert result["estimated_price_uf"] == 4820
    assert result["is_demo"] is True
    assert result["source"] == "demo"
    assert client.calls == []


def test_map_valuation_response_to_view_model_maps_real_backend_fields() -> None:
    response = {
        "estimated_price_uf": 6850,
        "estimated_price_clp": 267_300_000,
        "price_range_low_uf": 6200,
        "price_range_high_uf": 7600,
        "price_range_low_clp": 241_900_000,
        "price_range_high_clp": 292_700_000,
        "confidence": "high",
        "confidence_score": 0.87,
        "comparable_count": 1,
        "price_m2_uf": 91.3,
        "warnings": ["low_data_mode"],
        "comparables": [
            {
                "title": "Suecia 150",
                "comuna": "providencia",
                "price_uf": 6900,
                "price_clp": 269_100_000,
                "m2": 75,
                "similarity": 0.91,
                "url": "https://example.test/listing/1",
            }
        ],
    }

    view_model = map_valuation_response_to_view_model(response, payload={"comuna": "providencia"}, source="real")

    assert view_model is not None
    assert view_model.is_demo is False
    assert view_model.estimated_value_uf == 6850.0
    assert view_model.estimated_value_clp == 267_300_000.0
    assert view_model.price_range_low_uf == 6200.0
    assert view_model.price_range_high_clp == 292_700_000.0
    assert view_model.price_m2_uf == 91.3
    assert view_model.confidence_key == "high"
    assert view_model.confidence_score == 0.87
    assert view_model.comparable_count == 1
    assert view_model.warnings == ("low_data_mode",)
    assert view_model.warning_summary.count == 1
    assert view_model.warning_summary.details[0].human_label == "Muestra de datos limitada"
    assert view_model.comparables[0].title == "Suecia 150"
    assert view_model.comparables[0].price_uf == 6900.0


def test_playground_view_model_preserves_consensus_payload_for_secondary_panel() -> None:
    response = {
        "estimated_price_uf": 4700,
        "estimated_price_clp": 183_300_000,
        "confidence": "high",
        "consensus": {"status": "ok", "estimate_clp": 183_300_000},
        "engine_results": [
            {
                "engine_name": "comparables_canonical_outliers",
                "role": "favorite",
                "status": "ok",
                "selected_for_final": True,
            }
        ],
    }

    view_model = map_valuation_response_to_view_model(response, source="real")

    assert view_model is not None
    assert view_model.raw["consensus"]["status"] == "ok"
    assert view_model.raw["engine_results"][0]["role"] == "favorite"


def test_map_valuation_response_to_view_model_accepts_aliases_and_nested_range() -> None:
    response = {
        "valor_estimado_uf": "6200",
        "valor_estimado_clp": "241800000",
        "rango": {"min_uf": "5900", "max_uf": "6500"},
        "reliability": 0.61,
        "comparables_used": "2",
        "warnings": "published_price_not_provided",
        "comparables": [
            {
                "address_label": "Los Leones 2100",
                "commune": "providencia",
                "precio_uf": "6100",
                "built_area_m2": "72",
                "dormitorios": "2",
                "banos": "2",
                "estacionamientos": "1",
                "score": "0.84",
                "listing_url": "https://example.test/listing/2",
            }
        ],
    }

    view_model = map_valuation_response_to_view_model(response, source="demo")

    assert view_model is not None
    assert view_model.is_demo is True
    assert view_model.estimated_value_uf == 6200.0
    assert view_model.estimated_value_clp == 241_800_000.0
    assert view_model.price_range_low_uf == 5900.0
    assert view_model.price_range_high_uf == 6500.0
    assert view_model.confidence_key == "medium"
    assert view_model.confidence_score == 0.61
    assert view_model.comparable_count == 2
    assert view_model.warnings == ("published_price_not_provided",)
    assert view_model.comparables[0].title == "Los Leones 2100"
    assert view_model.comparables[0].bedrooms == 2
    assert view_model.comparables[0].url == "https://example.test/listing/2"


def test_map_valuation_response_keeps_raw_warnings_and_adds_technical_details() -> None:
    response = {
        "estimated_price_uf": 5200,
        "warnings": ["poor_geocoding_comparables", "future_backend_warning"],
    }

    view_model = map_valuation_response_to_view_model(response, source="real")

    assert view_model is not None
    assert view_model.warnings == ("poor_geocoding_comparables", "future_backend_warning")
    assert view_model.raw["warnings"] == ["poor_geocoding_comparables", "future_backend_warning"]
    assert view_model.warning_summary.count == 2
    assert [detail.code for detail in view_model.warning_summary.details] == [
        "poor_geocoding_comparables",
        "future_backend_warning",
    ]
    assert view_model.warning_summary.details[0].human_label == "Comparables con ubicacion debil"
    assert view_model.warning_summary.details[1].known is False


def test_location_intelligence_available_uses_real_backend_fields() -> None:
    response = {
        "estimated_price_uf": 5200,
        "comuna": "providencia",
        "geocoding_precision": "address",
        "lat": -33.42,
        "lon": -70.61,
        "microzone": "metro:los_leones",
        "comparable_count": 20,
        "comparable_quality_level": "strong",
        "comparable_quality_metrics": {
            "address_level_geo_ratio": 0.82,
            "same_microzone_ratio": 0.64,
        },
        "geo_signals": {"metro": "Los Leones", "park": None},
        "warnings": [],
    }

    view_model = map_valuation_response_to_view_model(response, payload={"comuna": "providencia"}, source="real")

    assert view_model is not None
    location = view_model.location_intelligence
    assert location.status == "available"
    assert location.comuna == "providencia"
    assert location.coordinates == (-33.42, -70.61)
    assert location.geocoding_precision == "address"
    assert location.microzone_status == "available"
    assert location.comparable_count == 20
    assert location.comparable_location_quality == "alta"
    assert location.geo_signals == ("Los Leones", "metro:los_leones")
    assert location.reasons == ()


def test_location_intelligence_partial_translates_location_warnings() -> None:
    response = {
        "estimated_price_uf": 5200,
        "comparable_count": 5,
        "warnings": ["weak_microzone", "poor_geocoding_comparables"],
        "comparable_quality_metrics": {"address_level_geo_ratio": 0.28},
    }

    view_model = map_valuation_response_to_view_model(response, payload={"comuna": "nunoa"}, source="real")

    assert view_model is not None
    location = view_model.location_intelligence
    assert location.status == "partial"
    assert location.comuna == "nunoa"
    assert location.microzone_status == "limited"
    assert location.comparable_location_quality == "baja"
    assert [warning.human_label for warning in location.location_warnings] == [
        "Microzona limitada",
        "Comparables con ubicacion debil",
    ]
    assert "weak_microzone" not in location.summary
    assert "poor_geocoding_comparables" not in location.summary


def test_location_intelligence_not_available_has_honest_reasons() -> None:
    view_model = map_valuation_response_to_view_model({"estimated_price_uf": 5200}, source="real")

    assert view_model is not None
    location = view_model.location_intelligence
    assert location.status == "not_available"
    assert location.summary == "Inteligencia local no disponible para esta tasacion."
    assert {
        "no_geocoding_data",
        "no_microzone_data",
        "no_geo_signals",
        "insufficient_location_coverage",
    }.issubset(set(location.reasons))


def test_location_intelligence_does_not_treat_demo_fixture_as_real_data() -> None:
    view_model = map_valuation_response_to_view_model(
        {
            "estimated_price_uf": 5200,
            "source": "demo",
            "comuna": "providencia",
            "geo_signals": {"metro": "Los Leones"},
        },
        source="demo",
    )

    assert view_model is not None
    location = view_model.location_intelligence
    assert location.status == "not_available"
    assert location.geo_signals == ()
    assert location.reasons == ("demo_data_not_used_as_real_location_intelligence",)


def test_price_trend_contract_normalizes_to_existing_chart_data() -> None:
    trend = _normalize_price_trend_for_chart(
        {
            "status": "partial",
            "period_months": 12,
            "points": [
                {"month": "2026-01", "median_price_m2_uf": 80.0, "sample_count": 3},
                {"month": "2026-02", "median_price_m2_uf": 82.5, "sample_count": 4},
            ],
            "latest_value": 82.5,
            "coverage_count": 7,
            "source": "price_history",
        }
    )

    assert trend["title"] == "Tendencia de precio (UF/m2)"
    assert trend["period"] == "12 meses"
    assert trend["values"] == [80.0, 82.5]
    assert trend["labels"] == ["2026-01", "2026-02"]
    assert trend["status"] == "partial"


def test_price_trend_not_available_reason_is_human_readable() -> None:
    assert (
        _trend_reason_label({"reasons": ["insufficient_monthly_points"]})
        == "Faltan puntos mensuales reales."
    )


def test_map_valuation_response_without_comparables_keeps_empty_list() -> None:
    response = {
        "estimated_price_uf": 7084.45,
        "estimated_price_clp": 262_124_809,
        "confidence": "medium",
        "comparable_count": 0,
        "price_m2_uf": 94.46,
        "comparables": [],
    }

    view_model = map_valuation_response_to_view_model(response, source="real")

    assert view_model is not None
    assert view_model.is_demo is False
    assert view_model.comparable_count == 0
    assert view_model.comparables == ()


def test_tasar_risk_report_contract_uses_real_html_generator() -> None:
    payload = {
        "comuna": "nunoa",
        "property_type": "apartment",
        "m2": 75.0,
        "built_area_m2": 75.0,
        "precio_publicado_uf": 4500.0,
    }
    response = {
        "estimated_price_uf": 5200.0,
        "estimated_price_clp": 205_000_000,
        "price_range_low_uf": 4900.0,
        "price_range_high_uf": 5500.0,
        "confidence": "medium",
        "comparable_count": 1,
        "price_m2_uf": 69.33,
        "warnings": [],
        "comparables": [
            {
                "listing_id": 10,
                "title": "Comparable",
                "comuna": "nunoa",
                "price_uf": 5100.0,
                "m2": 74.0,
                "similarity": 0.82,
            }
        ],
    }
    view_model = map_valuation_response_to_view_model(response, payload=payload, source="real")

    contract = build_tasar_risk_report_contract(view_model, payload=payload)

    assert contract.risk_report_available is True
    assert contract.risk_report_status == "available"
    assert contract.required_data == ()
    assert contract.source == "ui.components.risk_report_html"
    assert contract.risk_report_html is not None
    assert contract.investment_report_html == contract.risk_report_html
    assert contract.listing_report_html is None
    assert contract.investment_file_name is not None
    assert contract.investment_file_name.startswith("investment_intelligence_report_nunoa_")
    assert "Investment Intelligence Report" in contract.risk_report_html
    assert "Valuation Analysis" in contract.risk_report_html


def test_tasar_risk_report_contract_generates_dual_reports_for_listing_context() -> None:
    payload = {
        "comuna": "nunoa",
        "property_type": "apartment",
        "m2": 75.0,
        "built_area_m2": 75.0,
        "precio_publicado_uf": 4500.0,
    }
    response = {
        "estimated_price_uf": 5200.0,
        "estimated_price_clp": 205_000_000,
        "confidence": "medium",
        "comparable_count": 2,
        "warnings": ["publication_history_missing", "single_source_comparables"],
        "comparables": [{"title": "Comparable", "price_uf": 5100.0, "m2": 74.0}],
    }
    lookup = {
        "url": "https://example.test/listing/123",
        "source": "portal",
        "listing_id": 123,
        "listing_data": {
            "listing_id": 123,
            "url": "https://example.test/listing/123",
            "source": "portal",
        },
    }
    view_model = map_valuation_response_to_view_model(response, payload=payload, source="real")

    contract = build_tasar_risk_report_contract(view_model, payload=payload, lookup_result=lookup)

    assert contract.risk_report_available is True
    assert contract.investment_report_html is not None
    assert contract.listing_report_html is not None
    assert contract.investment_file_name is not None
    assert contract.listing_file_name is not None
    assert contract.investment_file_name.startswith("investment_intelligence_report_nunoa_")
    assert contract.listing_file_name.startswith("listing_risk_report_nunoa_")
    assert "Investment Intelligence Report" in contract.investment_report_html
    assert "Listing Risk / Opportunity Report" in contract.listing_report_html
    assert "Historial de publicacion incompleto" not in contract.investment_report_html
    assert "Historial de publicacion incompleto" in contract.listing_report_html


def test_tasar_risk_report_contract_requires_valuation_before_result() -> None:
    contract = build_tasar_risk_report_contract(None, payload={"comuna": "nunoa"})

    assert contract.risk_report_available is False
    assert contract.risk_report_status == "requires_valuation"
    assert contract.risk_report_html is None
    assert contract.required_data == ("valuation_result",)


def test_tasar_risk_report_contract_does_not_generate_from_demo() -> None:
    view_model = map_valuation_response_to_view_model(
        {"estimated_price_uf": 5200.0, "is_demo": True, "source": "demo", "comparables": [{"price_uf": 5100}]},
        payload={"comuna": "nunoa", "m2": 75.0},
        source="demo",
    )

    contract = build_tasar_risk_report_contract(view_model, payload={"comuna": "nunoa", "m2": 75.0})

    assert contract.risk_report_available is False
    assert contract.risk_report_status == "not_available"
    assert contract.required_data == ("real_valuation_result",)


def test_tasar_risk_report_contract_requires_comparables_for_real_report() -> None:
    view_model = map_valuation_response_to_view_model(
        {
            "estimated_price_uf": 5200.0,
            "estimated_price_clp": 205_000_000,
            "confidence": "medium",
            "comparable_count": 0,
            "comparables": [],
        },
        payload={"comuna": "nunoa", "m2": 75.0},
        source="real",
    )

    contract = build_tasar_risk_report_contract(view_model, payload={"comuna": "nunoa", "m2": 75.0})

    assert contract.risk_report_available is False
    assert contract.risk_report_status == "requires_comparables"
    assert contract.risk_report_html is None
    assert contract.required_data == ("comparables",)
