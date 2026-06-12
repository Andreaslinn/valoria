from __future__ import annotations

from domain.valuation.product_classification import (
    PRODUCT_COMMERCIAL,
    PRODUCT_DEMOLITION,
    PRODUCT_INVESTMENT,
    PRODUCT_LAND_OR_SITE,
    PRODUCT_MULTI_UNIT,
    PRODUCT_REMODELING,
    PRODUCT_STANDARD_RESIDENTIAL,
    PRODUCT_UNKNOWN,
    classify_product,
    product_compatibility,
)
from tests.unit.factories import make_listing, make_property


def test_classifies_standard_house() -> None:
    evidence = classify_product(make_listing(property_type="house", title="Casa familiar en barrio residencial"))

    assert evidence.product_class == PRODUCT_STANDARD_RESIDENTIAL


def test_classifies_special_products_with_normalized_text() -> None:
    samples = [
        ("Sitio en venta excelente ubicación", PRODUCT_LAND_OR_SITE),
        ("Casa para demolición Ñuñoa", PRODUCT_DEMOLITION),
        ("Casa para remodelar completa", PRODUCT_REMODELING),
        ("Propiedad comercial uso oficina", PRODUCT_COMMERCIAL),
        ("Ideal inversión con renta mensual", PRODUCT_INVESTMENT),
        ("Dos viviendas con departamento interior", PRODUCT_MULTI_UNIT),
    ]

    for title, expected in samples:
        evidence = classify_product(make_listing(property_type="house", title=title))
        assert evidence.product_class == expected
        assert evidence.strength in {"strong", "weak"}


def test_ambiguous_terreno_does_not_turn_house_into_site() -> None:
    evidence = classify_product(make_listing(property_type="house", title="Casa familiar con amplio terreno"))

    assert evidence.product_class == PRODUCT_STANDARD_RESIDENTIAL


def test_target_without_text_is_unknown_but_excludes_strong_special_candidate() -> None:
    target = classify_product(make_property(property_type="house", raw_metadata={}))
    candidate = classify_product(make_listing(property_type="house", title="Sitio en venta"))

    compatibility = product_compatibility(target, candidate)

    assert target.product_class == PRODUCT_UNKNOWN
    assert compatibility.compatible is False


def test_classification_is_deterministic() -> None:
    listing = make_listing(property_type="house", title="Casa para remodelar")

    assert classify_product(listing) == classify_product(listing)
