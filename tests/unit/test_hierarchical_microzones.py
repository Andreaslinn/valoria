from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from core.entities.listing import Listing
from core.value_objects.location import Coordinates
from core.value_objects.price import Price
from domain.geocoding.hierarchical_microzones import assign_hierarchical_microzone


def _listing(**changes) -> Listing:
    values = {
        "id": 1,
        "source": "test",
        "external_id": "1",
        "title": "Departamento en venta",
        "comuna": "las_condes",
        "m2": 50,
        "bedrooms": 2,
        "bathrooms": 1,
        "parking": 0,
        "price": Price(clp=Decimal("100000000")),
        "status": "active",
        "fingerprint": "fp",
        "scraped_at": datetime.now(UTC),
        "raw_metadata": {},
    }
    values.update(changes)
    return Listing(**values)


def test_comuna_centroid_does_not_produce_level_4() -> None:
    assignment = assign_hierarchical_microzone(
        _listing(geocode_precision="comuna_centroid", coordinates=Coordinates(-33.4, -70.6))
    )

    assert assignment.level_4_key is None
    assert assignment.best_available_level == 0
    assert assignment.is_fallback_only is True


def test_address_coordinates_produce_level_4() -> None:
    assignment = assign_hierarchical_microzone(
        _listing(geocode_precision="address", coordinates=Coordinates(-33.4, -70.6))
    )

    assert assignment.level_4_kind == "geo_500m"
    assert assignment.best_available_level == 4


def test_street_coordinates_produce_level_4() -> None:
    assignment = assign_hierarchical_microzone(
        _listing(geocode_precision="street", coordinates=Coordinates(-33.4, -70.6))
    )

    assert assignment.level_4_kind == "geo_500m"
    assert assignment.best_available_level == 4


def test_specific_street_and_comuna_produce_level_3_without_coordinates() -> None:
    assignment = assign_hierarchical_microzone(
        _listing(raw_metadata={"street_hint": "Calle Las Dalias"})
    )

    assert assignment.level_3_kind == "street_microzone"
    assert assignment.best_available_level == 3
    assert assignment.level_4_key is None
    assert assignment.does_not_invent_coordinates is True


def test_specific_metro_and_comuna_produce_level_2() -> None:
    assignment = assign_hierarchical_microzone(
        _listing(title="Departamento a pasos de Metro Manquehue")
    )

    assert assignment.level_2_kind == "metro_corridor"
    assert assignment.best_available_level == 2


def test_specific_avenue_and_comuna_produce_level_2_corridor() -> None:
    assignment = assign_hierarchical_microzone(
        _listing(raw_metadata={"address_label": "Av. Apoquindo"})
    )

    assert assignment.level_2_kind == "avenue_corridor"
    assert assignment.best_available_level == 2


def test_specific_intersection_produces_level_3() -> None:
    assignment = assign_hierarchical_microzone(
        _listing(raw_metadata={"street_hint": "Apoquindo con Manquehue"})
    )

    assert assignment.level_3_kind == "intersection"
    assert assignment.best_available_level == 3


def test_generic_signal_is_rejected_to_comuna_fallback() -> None:
    assignment = assign_hierarchical_microzone(
        _listing(title="Excelente ubicacion cerca de comercio")
    )

    assert assignment.best_available_level == 0
    assert assignment.is_real_microzone is False


def test_comuna_only_stays_level_0_fallback() -> None:
    assignment = assign_hierarchical_microzone(_listing())

    assert assignment.level_0_key == "comuna:las_condes"
    assert assignment.best_available_level == 0
    assert assignment.is_fallback_only is True


def test_best_available_level_chooses_finest_valid_level() -> None:
    assignment = assign_hierarchical_microzone(
        _listing(
            geocode_precision="address",
            coordinates=Coordinates(-33.4, -70.6),
            raw_metadata={"street_hint": "Calle Las Dalias"},
        )
    )

    assert assignment.level_3_kind == "street_microzone"
    assert assignment.level_4_kind == "geo_500m"
    assert assignment.best_available_level == 4


def test_assignment_never_invents_coordinates_from_text() -> None:
    assignment = assign_hierarchical_microzone(
        _listing(raw_metadata={"street_hint": "Calle Las Dalias"})
    )

    assert assignment.level_4_key is None
    assert assignment.does_not_invent_coordinates is True
