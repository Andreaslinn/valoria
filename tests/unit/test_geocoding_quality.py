from __future__ import annotations

from core.value_objects.location import Coordinates
from domain.geocoding.quality import (
    apply_geocoding_guardrails,
    is_poor_geocoding,
    normalize_geocode_precision,
)
from tests.unit.factories import make_listing


def test_address_without_coordinates_is_not_allowed() -> None:
    precision = normalize_geocode_precision(
        "address",
        has_coords=False,
        raw_metadata={"address_label": "Avenida Portugal"},
        comuna="santiago",
    )

    assert precision == "street"


def test_comuna_centroid_without_coordinates_degrades_to_comuna() -> None:
    assert normalize_geocode_precision(
        "comuna_centroid",
        has_coords=False,
        raw_metadata={},
        comuna="santiago",
    ) == "comuna"


def test_repeated_coordinates_are_degraded_to_comuna_centroid() -> None:
    coords = Coordinates(-33.4377752, -70.6505796)
    listings = [
        make_listing(fingerprint=f"fp-{idx}", comuna="santiago", coords=coords, geocode_precision="address")
        for idx in range(5)
    ]

    guarded = apply_geocoding_guardrails(listings)

    assert {listing.geocode_precision for listing in guarded} == {"comuna_centroid"}


def test_house_without_coordinates_is_poor_geocoding_even_if_labeled_address() -> None:
    listing = make_listing(
        fingerprint="house",
        property_type="house",
        coords=None,
        geocode_precision="address",
    )

    assert is_poor_geocoding(listing)

