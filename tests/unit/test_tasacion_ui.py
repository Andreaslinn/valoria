from __future__ import annotations

from ui.pages.tasacion import (
    _build_valuation_payload,
    _confidence_explanation,
    _confidence_score_text,
    _has_approx_geocoding,
    _normalize_confidence,
    _property_type_payload_value,
    _range_band_position,
    _valuation_quality_state,
    _valuation_risk_messages,
)
from ui.valuation.result import consensus_engine_rows, consensus_summary


def test_confidence_explanation_mapping() -> None:
    assert "Alta precision relativa" in _confidence_explanation("high")
    assert "margen de error" in _confidence_explanation("medium")
    assert "referencial" in _confidence_explanation("low")
    assert "No hay suficientes comparables" in _confidence_explanation("insufficient_data")
    assert _confidence_explanation("unknown") == "Confianza no disponible."


def test_numeric_confidence_is_normalized_safely() -> None:
    assert _normalize_confidence(0.8) == "high"
    assert _normalize_confidence(0.5) == "medium"
    assert _normalize_confidence(0.2) == "low"
    assert _normalize_confidence(None) == "unknown"
    assert _normalize_confidence("unexpected") == "unknown"


def test_range_band_position() -> None:
    assert _range_band_position(4000.0, 4500.0, 5000.0) == {"estimate_pct": 50.0}
    assert _range_band_position(4000.0, 3000.0, 5000.0) == {"estimate_pct": 0.0}
    assert _range_band_position(4000.0, 6000.0, 5000.0) == {"estimate_pct": 100.0}


def test_range_band_position_handles_missing_or_invalid_values() -> None:
    assert _range_band_position(None, 4500.0, 5000.0) is None
    assert _range_band_position(4000.0, None, 5000.0) is None
    assert _range_band_position(4000.0, 4500.0, None) is None
    assert _range_band_position(5000.0, 4500.0, 4000.0) is None


def test_property_type_labels_map_to_backend_values() -> None:
    assert _property_type_payload_value("Departamento") == "apartment"
    assert _property_type_payload_value("Casa") == "house"
    assert _property_type_payload_value("Oficina") == "office"
    assert _property_type_payload_value("Desconocido") == "unknown"


def test_apartment_payload_uses_built_area_and_no_land_area() -> None:
    payload = _build_valuation_payload(
        comuna=" nunoa ",
        property_type="apartment",
        built_area_m2=75.0,
        land_area_m2=None,
        dormitorios=2,
        banos=2,
        estacionamientos=1,
        precio_uf=None,
        precio_clp=None,
    )
    assert payload["property_type"] == "apartment"
    assert payload["m2"] == 75.0
    assert payload["built_area_m2"] == 75.0
    assert payload["usable_area_m2"] == 75.0
    assert payload["land_area_m2"] is None
    assert "location_query" not in payload


def test_payload_preserves_location_query_when_entered() -> None:
    payload = _build_valuation_payload(
        comuna=" nunoa ",
        property_type="apartment",
        built_area_m2=75.0,
        land_area_m2=None,
        dormitorios=2,
        banos=2,
        estacionamientos=1,
        precio_uf=None,
        precio_clp=None,
        location_query="  Mujica con Irarrázaval  ",
    )

    assert payload["location_query"] == "Mujica con Irarrázaval"


def test_house_payload_includes_built_and_land_area() -> None:
    payload = _build_valuation_payload(
        comuna="vitacura",
        property_type="house",
        built_area_m2=180.0,
        land_area_m2=520.0,
        dormitorios=4,
        banos=3,
        estacionamientos=2,
        precio_uf=15000.0,
        precio_clp=None,
    )
    assert payload["property_type"] == "house"
    assert payload["m2"] == 180.0
    assert payload["built_area_m2"] == 180.0
    assert payload["land_area_m2"] == 520.0
    assert payload["usable_area_m2"] is None


def test_valuation_quality_high_medium_low_states() -> None:
    payload = {"property_type": "apartment"}

    assert _valuation_quality_state({"confidence": "high", "comparable_count": 12}, payload)["label"] == (
        "Alta confianza"
    )
    assert _valuation_quality_state({"confidence": "medium", "comparable_count": 8}, payload)["label"] == (
        "Confianza media"
    )
    assert _valuation_quality_state({"confidence": "low", "comparable_count": 8}, payload)["label"] == (
        "Baja confianza"
    )


def test_valuation_quality_exploratory_for_low_data_or_unknown_property_type() -> None:
    assert _valuation_quality_state(
        {"confidence": "high", "comparable_count": 4},
        {"property_type": "apartment"},
    )["label"] == "Tasación exploratoria"
    assert _valuation_quality_state(
        {"confidence": "high", "comparable_count": 12, "warnings": ["low_data_mode"]},
        {"property_type": "apartment"},
    )["label"] == "Tasación exploratoria"
    assert _valuation_quality_state(
        {"confidence": "high", "comparable_count": 12},
        {"property_type": "unknown"},
    )["label"] == "Tasación exploratoria"


def test_approximate_geocoding_detection_and_message() -> None:
    result = {"warnings": ["geocoding_comuna_centroid"], "comparable_count": 8}

    assert _has_approx_geocoding(result) is True
    assert (
        "warning",
        "Ubicación aproximada a nivel de comuna; la distancia no debe interpretarse como exacta.",
    ) in _valuation_risk_messages(result, {"property_type": "apartment"})


def test_approximate_geocoding_can_come_from_comparables() -> None:
    assert _has_approx_geocoding({"comparables": [{"geocode_precision": "comuna_centroid"}]}) is True


def test_low_comparable_count_has_strong_warning() -> None:
    messages = _valuation_risk_messages(
        {"confidence": "medium", "comparable_count": 3},
        {"property_type": "house"},
    )
    assert messages[0] == (
        "strong",
        "Menos de 5 comparables elegibles. Resultado exploratorio; no debe usarse como tasación confiable.",
    )


def test_confidence_score_text_supports_numeric_and_label_values() -> None:
    assert _confidence_score_text(0.82) == "0,82"
    assert _confidence_score_text("high") == ">= 0,75"
    assert _confidence_score_text("medium") == "0,50-0,74"
    assert _confidence_score_text("low") == "< 0,50"


def test_consensus_panel_rows_show_roles_status_and_safe_errors() -> None:
    result = {
        "estimated_price_uf": 4700,
        "estimated_price_clp": 183_300_000,
        "consensus_method": "favorite_first_with_legacy_fallback_v1",
        "selected_engine_names": ["comparables_canonical_outliers"],
        "consensus": {
            "estimate_uf": 4700,
            "estimate_clp": 183_300_000,
        },
        "engine_results": [
            {
                "engine_name": "comparables_canonical_outliers",
                "role": "favorite",
                "status": "ok",
                "estimate_uf": 4700,
                "estimate_clp": 183_300_000,
                "comparables_count": 8,
                "confidence": 0.82,
                "selected_for_final": True,
                "warnings": [],
                "safe_error_message": None,
            },
            {
                "engine_name": "comparables_canonical",
                "role": "experimental",
                "status": "failed",
                "selected_for_final": False,
                "warnings": ["unexpected_error"],
                "safe_error_message": "El motor no pudo completar la valorizacion.",
                "error_message": "Traceback: database password=secret",
            },
        ],
    }

    summary = consensus_summary(result)
    rows = consensus_engine_rows(result)

    assert summary["selected_label"] == "Canonical outliers"
    assert summary["estimate_clp"] == 183_300_000
    assert rows[0]["Rol"] == "favorite"
    assert rows[0]["Estado"] == "ok"
    assert rows[0]["Seleccionado"] == "Si"
    assert rows[1]["Estado"] == "failed"
    assert rows[1]["Detalle"] == "El motor no pudo completar la valorizacion."
    assert "Traceback" not in str(rows)
    assert "password" not in str(rows)


def test_consensus_helpers_are_backward_compatible_without_optional_fields() -> None:
    result = {"estimated_price_uf": 4500, "estimated_price_clp": 175_500_000}

    assert consensus_engine_rows(result) == []
    assert consensus_summary(result)["selected_names"] == []
