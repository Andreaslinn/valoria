from __future__ import annotations

from domain.geocoding.microzones import extract_microzone_signals, microzone_similarity_bonus
from domain.valuation.scoring import similarity_score
from tests.unit.factories import make_listing, make_property


def test_extracts_and_normalizes_metro() -> None:
    signals = extract_microzone_signals(title="Depto a pasos de METRO Parque Almagro")

    assert signals.nearby_metro == "parque almagro"
    assert "metro:parque almagro" in signals.landmark_tokens
    assert signals.confidence >= 0.55


def test_extracts_avenue_variants() -> None:
    signals = extract_microzone_signals(title="Casa cerca de Av. Vicuña Mackenna")

    assert signals.nearby_avenue == "vicuna mackenna"
    assert "avenue:vicuna mackenna" in signals.landmark_tokens


def test_rejects_generic_metro_central_false_positive() -> None:
    signals = extract_microzone_signals(title="Casa en venta en Estación Central")

    assert signals.nearby_metro is None
    assert signals.confidence == 0.0


def test_microzone_bonus_for_same_metro() -> None:
    target = make_property(raw_metadata={"geo_signals": extract_microzone_signals(title="Metro Parque Almagro").as_dict()})
    candidate = make_listing(
        raw_metadata={"geo_signals": extract_microzone_signals(title="A pasos de metro parque almagro").as_dict()}
    )

    bonus, reasons = microzone_similarity_bonus(target, candidate)

    assert bonus > 0
    assert "same_metro:parque almagro" in reasons


def test_no_bonus_for_low_confidence_marketing_text() -> None:
    target = make_property(raw_metadata={"geo_signals": extract_microzone_signals(title="gran oportunidad").as_dict()})
    candidate = make_listing(raw_metadata={"geo_signals": extract_microzone_signals(title="gran oportunidad").as_dict()})

    assert microzone_similarity_bonus(target, candidate) == (0.0, [])


def test_microzone_bonus_increases_similarity_conservatively() -> None:
    target = make_property(
        coords=None,
        geocode_precision="comuna",
        raw_metadata={"geo_signals": extract_microzone_signals(title="Rotonda Atenas").as_dict()},
    )
    same = make_listing(
        fingerprint="same",
        bedrooms=2,
        coords=None,
        geocode_precision="comuna",
        raw_metadata={"geo_signals": extract_microzone_signals(title="Casa cercana a Rotonda Atenas").as_dict()},
    )
    other = make_listing(fingerprint="other", bedrooms=2, coords=None, geocode_precision="comuna")

    assert similarity_score(target, same).value > similarity_score(target, other).value
    assert same.raw_metadata["last_microzone_score_bonus"] <= 0.08


def test_extracts_pedro_de_valdivia_without_prefix() -> None:
    signals = extract_microzone_signals(title="Departamento Pedro de Valdivia cercano a comercio")

    assert signals.nearby_avenue == "pedro de valdivia"


def test_extracts_rotonda_atenas_landmark() -> None:
    signals = extract_microzone_signals(title="Casa cercana a Rotonda Atenas")

    assert "landmark:rotonda atenas" in signals.landmark_tokens
    assert signals.confidence >= 0.55


def test_extracts_intersection_hint() -> None:
    signals = extract_microzone_signals(title="Casa Av Macul con Rodrigo de Araya")

    assert signals.intersection_hint == "macul y rodrigo de araya"
    assert "intersection:macul y rodrigo de araya" in signals.landmark_tokens


def test_rejects_calle_tranquila_false_positive() -> None:
    signals = extract_microzone_signals(title="Venta casa en calle tranquila")

    assert signals.confidence == 0.0
    assert signals.reason.startswith("rejected:")


def test_rejects_gran_oportunidad_false_positive() -> None:
    signals = extract_microzone_signals(title="Gran oportunidad amplia casa")

    assert signals.confidence == 0.0
    assert signals.reason.startswith("rejected:")


def test_rejects_excelente_ubicacion_false_positive() -> None:
    signals = extract_microzone_signals(title="Excelente ubicación para vivir")

    assert signals.confidence == 0.0
    assert signals.reason.startswith("rejected:")


def test_different_clear_microzones_penalize_conservatively() -> None:
    target = make_property(
        comuna="santiago",
        raw_metadata={"geo_signals": extract_microzone_signals(title="Metro Parque Almagro").as_dict()},
    )
    candidate = make_listing(
        comuna="santiago",
        raw_metadata={"geo_signals": extract_microzone_signals(title="Metro Pedro de Valdivia").as_dict()},
    )

    penalty, reasons = microzone_similarity_bonus(target, candidate)

    assert penalty < 0
    assert reasons == ["different_clear_microzone"]


def test_different_microzones_do_not_penalize_across_comunas() -> None:
    target = make_property(
        comuna="santiago",
        raw_metadata={"geo_signals": extract_microzone_signals(title="Metro Parque Almagro").as_dict()},
    )
    candidate = make_listing(
        comuna="providencia",
        raw_metadata={"geo_signals": extract_microzone_signals(title="Metro Pedro de Valdivia").as_dict()},
    )

    penalty, reasons = microzone_similarity_bonus(target, candidate)

    assert penalty == 0.0
    assert reasons == []
