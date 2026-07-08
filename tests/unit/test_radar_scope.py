from __future__ import annotations

from domain.radar.scope import apply_radar_property_scope, parse_allowed_property_types
from tests.unit.factories import make_listing


def test_parse_allowed_property_types_defaults_to_apartment() -> None:
    assert parse_allowed_property_types(None) == ("apartment",)
    assert parse_allowed_property_types("") == ("apartment",)


def test_parse_allowed_property_types_supports_future_house_reactivation() -> None:
    assert parse_allowed_property_types("apartment,house,apartment") == ("apartment", "house")


def test_apply_radar_property_scope_counts_excluded_houses() -> None:
    apartment = make_listing(fingerprint="apt", property_type="apartment")
    house = make_listing(fingerprint="house", property_type="house")

    scope = apply_radar_property_scope([apartment, house], ("apartment",))

    assert scope.included == (apartment,)
    assert scope.allowed_property_types == ("apartment",)
    assert scope.excluded_by_property_type_count == {"house": 1}
    assert scope.houses_on_hold_count == 1
    assert scope.radar_scope_label == "Departamentos"
