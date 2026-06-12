"""Tests de entidad Listing."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from core.entities.listing import Listing
from core.value_objects.price import Price


def test_listing_can_be_created_with_property_type() -> None:
    listing = Listing(
        id=None,
        source="yapo",
        external_id="ext-1",
        title="Casa en Vitacura",
        comuna="vitacura",
        m2=140,
        bedrooms=4,
        bathrooms=3,
        parking=2,
        price=Price(clp=Decimal("450000000")),
        status="active",
        fingerprint="fp-1",
        scraped_at=datetime(2026, 5, 12, tzinfo=UTC),
        property_type="house",
        built_area_m2=140,
        land_area_m2=500,
    )

    assert listing.property_type == "house"
    assert listing.built_area_m2 == 140
    assert listing.land_area_m2 == 500


def test_listing_default_property_type_is_unknown() -> None:
    listing = Listing(
        id=None,
        source="yapo",
        external_id="ext-1",
        title="Propiedad sin tipo explicito",
        comuna="nunoa",
        m2=75,
        bedrooms=3,
        bathrooms=2,
        parking=1,
        price=Price(clp=Decimal("180000000")),
        status="active",
        fingerprint="fp-1",
        scraped_at=datetime(2026, 5, 12, tzinfo=UTC),
    )

    assert listing.property_type == "unknown"
