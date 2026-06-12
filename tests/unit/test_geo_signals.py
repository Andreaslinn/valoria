from __future__ import annotations

from types import SimpleNamespace

from domain.geocoding.geo_signals import (
    enrich_raw_metadata_with_geo_signals,
    recover_geo_signals,
)
from scripts.geocode_listings import build_geocoding_query_plan


def _candidate_values(metadata: dict) -> list[str]:
    return [item["value"] for item in metadata["geo_signal_candidates"]]


def test_extracts_clean_metro_candidate() -> None:
    recovery = recover_geo_signals(title="Depto a pasos de Metro Irarrázaval")

    metro = next(item for item in recovery.candidates if item.signal_type == "metro")
    assert metro.value == "Metro Irarrázaval"
    assert metro.normalized_value == "metro_irarrazaval"
    assert metro.source == "title"
    assert metro.confidence == "low"


def test_extracts_avenue_and_street_candidates() -> None:
    metadata = enrich_raw_metadata_with_geo_signals(
        {},
        title="Departamento Av. Antonio Varas y Calle Portugal",
    )

    values = _candidate_values(metadata)
    assert "Av. Antonio Varas y Calle Portugal" in values
    assert "Calle Portugal" in values


def test_extracts_intersection_candidate() -> None:
    recovery = recover_geo_signals(title="Departamento Manuel Montt / Valenzuela Castillo")

    intersection = next(item for item in recovery.candidates if item.signal_type == "intersection")
    assert intersection.value == "Manuel Montt y Valenzuela Castillo"
    assert intersection.rule == "intersection_pattern"


def test_extracts_barrio_and_sector_candidates() -> None:
    recovery = recover_geo_signals(title="Depto en Barrio Italia, sector Santa Isabel")

    types = {item.signal_type for item in recovery.candidates}
    assert "barrio" in types
    assert "sector" in types


def test_rejects_marketing_location_noise() -> None:
    recovery = recover_geo_signals(title="Venta casa en calle tranquila con excelente vista")

    assert not recovery.candidates
    assert any(item["reason"] == "marketing_text" for item in recovery.rejected)


def test_cleans_caracteristicas_suffix_from_metro() -> None:
    metadata = enrich_raw_metadata_with_geo_signals(
        {"address_label": "Metro Principe de GalesCARACTERÍSTICAS"},
        title="Departamento en venta",
    )

    metro = next(item for item in metadata["geo_signal_candidates"] if item["signal_type"] == "metro")
    assert metro["value"] == "Metro Principe de Gales"
    assert "CARACTER" not in metro["value"]


def test_preserves_existing_raw_metadata() -> None:
    metadata = enrich_raw_metadata_with_geo_signals(
        {"existing_key": "keep", "nearby_avenue": "vicuna mackenna"},
        title="Departamento en Ñuñoa",
    )

    assert metadata["existing_key"] == "keep"
    assert any(item["source"] == "existing_microzone_metadata" for item in metadata["geo_signal_candidates"])


def test_title_geo_signal_candidate_does_not_promote_to_metadata_address() -> None:
    listing = SimpleNamespace(
        title="Departamento en Emilio Vaisse",
        comuna="nunoa",
        raw_metadata={
            "geo_signal_candidates": [
                {
                    "value": "Emilio Vaisse",
                    "normalized_value": "emilio_vaisse",
                    "signal_type": "street",
                    "source": "title",
                    "confidence": "low",
                    "rule": "department_in_street",
                    "raw_text": "Departamento en Emilio Vaisse",
                    "created_by_version": "geo_signal_recovery_v1",
                }
            ]
        },
    )

    plan = build_geocoding_query_plan(listing)

    assert plan.query_source == "title_inferred_street"
    assert plan.query_confidence == "low"
