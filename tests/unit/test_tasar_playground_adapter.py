from __future__ import annotations

import pytest
import streamlit as st

from ui.api_client import ApiError
from ui.redesign import tasar_playground_adapter as adapter
from ui.redesign.tasar_playground import (
    DEFAULT_COMUNA_SLUG,
    UNKNOWN_PREFILL_COMUNA_KEY,
    _apply_url_prefill_to_tasar_state,
    _comuna_for_payload,
    _comuna_index,
    _first_present,
    _resolve_comuna_slug,
)
from ui.redesign.tasar_playground_adapter import (
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
    assert view_model.comparables[0].title == "Suecia 150"
    assert view_model.comparables[0].price_uf == 6900.0


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
