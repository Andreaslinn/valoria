from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from core.entities.listing import Listing
from core.value_objects.location import Coordinates
from core.value_objects.price import Price
from domain.geocoding.microzone_shadow import assign_shadow_microzone


def _listing(**changes) -> Listing:
    values = {
        "id": 1,
        "source": "test",
        "external_id": "1",
        "title": "Departamento Metro Parque Almagro",
        "comuna": "santiago",
        "m2": 50,
        "bedrooms": 2,
        "bathrooms": 1,
        "parking": 0,
        "price": Price(clp=Decimal("100000000")),
        "status": "active",
        "fingerprint": "fp",
        "scraped_at": datetime.now(UTC),
    }
    values.update(changes)
    return Listing(**values)


def test_assigns_geo_500m_only_for_real_precision_coordinates() -> None:
    assignment = assign_shadow_microzone(
        _listing(
            title="Departamento",
            geocode_precision="address",
            coordinates=Coordinates(lat=-33.425, lon=-70.61),
            raw_metadata={"geocode_query_confidence": "high"},
        )
    )

    assert assignment.microzone_kind == "geo_500m"
    assert assignment.is_real_microzone is True
    assert assignment.microzone_key is not None
    assert assignment.microzone_key.startswith("geo500:santiago:")


def test_comuna_centroid_is_not_real_microzone() -> None:
    assignment = assign_shadow_microzone(
        _listing(
            title="Departamento",
            geocode_precision="comuna_centroid",
            coordinates=Coordinates(lat=-33.425, lon=-70.61),
        )
    )

    assert assignment.microzone_kind == "comuna_fallback"
    assert assignment.is_real_microzone is False
    assert "weak_geocode_precision:comuna_centroid" in assignment.warnings


def test_textual_signal_can_assign_real_shadow_microzone_without_coordinates() -> None:
    assignment = assign_shadow_microzone(_listing())

    assert assignment.microzone_kind == "textual"
    assert assignment.is_real_microzone is True
    assert assignment.microzone_key == "textual:landmark:parque almagro"
    assert "missing_coordinates" in assignment.warnings


def test_no_textual_signal_falls_back_to_comuna_explicitly() -> None:
    assignment = assign_shadow_microzone(
        _listing(title="Departamento amplio", raw_metadata={})
    )

    assert assignment.microzone_kind == "comuna_fallback"
    assert assignment.is_real_microzone is False
    assert assignment.microzone_key == "comuna:santiago"
