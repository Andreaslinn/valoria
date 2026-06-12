"""Tests unitarios de mappers ORM/domain."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from core.entities.listing import Listing
from core.value_objects.price import Price
from infrastructure.db.mappers import listing_from_orm, listing_to_orm


def test_listing_mapper_roundtrips_property_type() -> None:
    listing = Listing(
        id=None,
        source="yapo",
        external_id="ext-house",
        title="Casa 140/500 m2",
        comuna="vitacura",
        m2=140,
        bedrooms=4,
        bathrooms=3,
        parking=2,
        price=Price(clp=Decimal("450000000")),
        status="active",
        fingerprint="fp-house",
        scraped_at=datetime(2026, 5, 12, tzinfo=UTC),
        last_refresh_attempted_at=datetime(2026, 5, 13, tzinfo=UTC),
        last_refresh_status="ok",
        property_type="house",
        built_area_m2=140,
        land_area_m2=500,
        usable_area_m2=None,
    )

    orm = listing_to_orm(listing)
    restored = listing_from_orm(orm)

    assert orm.property_type == "house"
    assert orm.last_seen_at == listing.scraped_at
    assert restored.last_seen_at == listing.scraped_at
    assert restored.last_refresh_attempted_at == listing.last_refresh_attempted_at
    assert restored.last_refresh_status == "ok"
    assert restored.property_type == "house"
    assert restored.built_area_m2 == 140
    assert restored.land_area_m2 == 500


def test_listing_mapper_converts_missing_property_type_to_unknown() -> None:
    listing = Listing(
        id=None,
        source="yapo",
        external_id="ext-unknown",
        title="Propiedad sin senal",
        comuna="nunoa",
        m2=75,
        bedrooms=3,
        bathrooms=2,
        parking=1,
        price=Price(clp=Decimal("180000000")),
        status="active",
        fingerprint="fp-unknown",
        scraped_at=datetime(2026, 5, 12, tzinfo=UTC),
    )
    listing.property_type = None  # type: ignore[assignment]

    orm = listing_to_orm(listing)

    assert orm.property_type == "unknown"
