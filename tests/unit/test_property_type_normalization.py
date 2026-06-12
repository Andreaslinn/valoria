from dataclasses import dataclass

from core.normalization.property_type import normalize_property_type


@dataclass
class WithPropertyType:
    property_type: str | None


def test_normalizes_apartment_aliases() -> None:
    for value in ["apartment", "departamento", "departamentos", "depto", "dpto", "apartamento"]:
        assert normalize_property_type(value) == "apartment"


def test_normalizes_house_aliases() -> None:
    for value in ["house", "houses", "casa", "casas"]:
        assert normalize_property_type(value) == "house"


def test_normalizes_unknown_and_empty_values() -> None:
    assert normalize_property_type("unknown") == "unknown"
    assert normalize_property_type(None) == "unknown"
    assert normalize_property_type("") == "unknown"
    assert normalize_property_type("bodega") == "unknown"


def test_accepts_domain_objects_with_property_type_attribute() -> None:
    assert normalize_property_type(WithPropertyType("casa")) == "house"
    assert normalize_property_type(WithPropertyType("depto")) == "apartment"


def test_preserves_existing_office_and_land_support() -> None:
    assert normalize_property_type("oficina") == "office"
    assert normalize_property_type("terreno") == "land"
