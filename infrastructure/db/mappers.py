"""Mappers entre entidades de dominio (core/entities/) y modelos ORM.

El dominio NO conoce SQLAlchemy. Los repositorios usan estos mappers para
cruzar la frontera en ambos sentidos:

    Domain entity  ──to_orm()─→   ORM model   ─→  DB
    Domain entity  ←─from_orm()─  ORM model   ←─  DB
    (update existing ORM)  ←──update_orm_from_entity()──  Domain entity
"""
from __future__ import annotations

from decimal import Decimal

from core.entities.listing import Listing, Property
from core.normalization.geocode_precision import normalize_geocode_precision
from core.normalization.property_type import normalize_property_type
from core.value_objects.location import Coordinates
from core.value_objects.price import Price
from domain.geocoding.microzones import enrich_raw_metadata_with_microzones
from infrastructure.db.models import ListingORM, PropertyORM


# ─────────────────────────────────────────────────────────
#  Property ↔ PropertyORM
# ─────────────────────────────────────────────────────────
def property_to_orm(prop: Property) -> PropertyORM:
    """Crea un PropertyORM nuevo desde la entidad. Si prop.id existe, se preserva."""
    orm = PropertyORM(
        comuna=prop.comuna,
        property_type=_property_type_or_unknown(prop.property_type),
        m2=prop.m2,
        built_area_m2=prop.built_area_m2,
        land_area_m2=prop.land_area_m2,
        usable_area_m2=prop.usable_area_m2,
        bedrooms=prop.bedrooms,
        bathrooms=prop.bathrooms,
        parking=prop.parking,
        lat=prop.coordinates.lat if prop.coordinates else None,
        lon=prop.coordinates.lon if prop.coordinates else None,
    )
    if prop.id is not None:
        orm.id = prop.id
    return orm


def property_from_orm(orm: PropertyORM) -> Property:
    coords = _coords_from(orm.lat, orm.lon)
    return Property(
        id=orm.id,
        comuna=orm.comuna,
        property_type=_property_type_or_unknown(orm.property_type),
        m2=orm.m2,
        built_area_m2=orm.built_area_m2,
        land_area_m2=orm.land_area_m2,
        usable_area_m2=orm.usable_area_m2,
        bedrooms=orm.bedrooms,
        bathrooms=orm.bathrooms,
        parking=orm.parking,
        coordinates=coords,
    )


def update_property_orm(orm: PropertyORM, prop: Property) -> None:
    """Aplica los cambios de la entidad sobre un ORM ya cargado en la sesión."""
    orm.comuna = prop.comuna
    orm.property_type = _property_type_or_unknown(prop.property_type)
    orm.m2 = prop.m2
    orm.built_area_m2 = prop.built_area_m2
    orm.land_area_m2 = prop.land_area_m2
    orm.usable_area_m2 = prop.usable_area_m2
    orm.bedrooms = prop.bedrooms
    orm.bathrooms = prop.bathrooms
    orm.parking = prop.parking
    if prop.coordinates:
        orm.lat = prop.coordinates.lat
        orm.lon = prop.coordinates.lon
    else:
        orm.lat = None
        orm.lon = None


# ─────────────────────────────────────────────────────────
#  Listing ↔ ListingORM
# ─────────────────────────────────────────────────────────
def listing_to_orm(listing: Listing) -> ListingORM:
    orm = ListingORM(
        property_id=listing.property_id,
        source=listing.source,
        external_id=listing.external_id,
        title=listing.title,
        url=listing.url,
        comuna=listing.comuna,
        property_type=_property_type_or_unknown(listing.property_type),
        m2=listing.m2,
        built_area_m2=listing.built_area_m2,
        land_area_m2=listing.land_area_m2,
        usable_area_m2=listing.usable_area_m2,
        bedrooms=listing.bedrooms,
        bathrooms=listing.bathrooms,
        parking=listing.parking,
        lat=listing.coordinates.lat if listing.coordinates else None,
        lon=listing.coordinates.lon if listing.coordinates else None,
        geocode_precision=listing.geocode_precision,
        price_clp=listing.price.clp,
        price_uf=listing.price_uf,
        price_currency=listing.price_currency,
        price_uf_confidence=listing.price_uf_confidence,
        price_uf_source=listing.price_uf_source,
        price_recovery_method=listing.price_recovery_method,
        status=listing.status,
        fingerprint=listing.fingerprint,
        raw_metadata=dict(listing.raw_metadata),
        scraped_at=listing.scraped_at,
        last_seen_at=_last_seen_at_or_scraped_at(listing),
        last_refresh_attempted_at=listing.last_refresh_attempted_at,
        last_refresh_status=listing.last_refresh_status,
    )
    if listing.id is not None:
        orm.id = listing.id
    return orm


def listing_from_orm(orm: ListingORM) -> Listing:
    coords = _coords_from(orm.lat, orm.lon)
    raw_metadata = enrich_raw_metadata_with_microzones(dict(orm.raw_metadata or {}), title=orm.title)
    geocode_precision = normalize_geocode_precision(
        orm.geocode_precision,
        has_coords=coords is not None,
        raw_metadata=raw_metadata,
        comuna=orm.comuna,
    )
    # price_clp puede venir como Decimal (Postgres) o float (SQLite). Normalizamos.
    price_clp = orm.price_clp if isinstance(orm.price_clp, Decimal) else Decimal(str(orm.price_clp))
    return Listing(
        id=orm.id,
        source=orm.source,
        external_id=orm.external_id,
        title=orm.title,
        url=orm.url,
        comuna=orm.comuna,
        property_type=_property_type_or_unknown(orm.property_type),
        m2=orm.m2,
        built_area_m2=orm.built_area_m2,
        land_area_m2=orm.land_area_m2,
        usable_area_m2=orm.usable_area_m2,
        bedrooms=orm.bedrooms,
        bathrooms=orm.bathrooms,
        parking=orm.parking,
        price=Price(clp=price_clp),
        status=orm.status,
        fingerprint=orm.fingerprint,
        scraped_at=orm.scraped_at,
        last_seen_at=orm.last_seen_at or orm.scraped_at,
        last_refresh_attempted_at=orm.last_refresh_attempted_at,
        last_refresh_status=orm.last_refresh_status,
        coordinates=coords,
        geocode_precision=geocode_precision,
        property_id=orm.property_id,
        price_uf=orm.price_uf,
        price_currency=orm.price_currency,
        price_uf_confidence=orm.price_uf_confidence,
        price_uf_source=orm.price_uf_source,
        price_recovery_method=orm.price_recovery_method,
        raw_metadata=raw_metadata,
    )


def update_listing_orm(orm: ListingORM, listing: Listing) -> None:
    orm.property_id = listing.property_id
    orm.source = listing.source
    orm.external_id = listing.external_id
    orm.title = listing.title
    orm.url = listing.url
    orm.comuna = listing.comuna
    orm.property_type = _property_type_or_unknown(listing.property_type)
    orm.m2 = listing.m2
    orm.built_area_m2 = listing.built_area_m2
    orm.land_area_m2 = listing.land_area_m2
    orm.usable_area_m2 = listing.usable_area_m2
    orm.bedrooms = listing.bedrooms
    orm.bathrooms = listing.bathrooms
    orm.parking = listing.parking
    if listing.coordinates:
        orm.lat = listing.coordinates.lat
        orm.lon = listing.coordinates.lon
    else:
        orm.lat = None
        orm.lon = None
    orm.geocode_precision = listing.geocode_precision
    orm.price_clp = listing.price.clp
    orm.price_uf = listing.price_uf
    orm.price_currency = listing.price_currency
    orm.price_uf_confidence = listing.price_uf_confidence
    orm.price_uf_source = listing.price_uf_source
    orm.price_recovery_method = listing.price_recovery_method
    orm.status = listing.status
    orm.fingerprint = listing.fingerprint
    orm.raw_metadata = dict(listing.raw_metadata)
    orm.scraped_at = listing.scraped_at
    orm.last_seen_at = _last_seen_at_or_scraped_at(listing)
    orm.last_refresh_attempted_at = listing.last_refresh_attempted_at
    orm.last_refresh_status = listing.last_refresh_status


# ─────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────
def _coords_from(lat: float | None, lon: float | None) -> Coordinates | None:
    if lat is None or lon is None:
        return None
    return Coordinates(lat=lat, lon=lon)


def _property_type_or_unknown(value: str | None) -> str:
    return normalize_property_type(value)


def _last_seen_at_or_scraped_at(listing: Listing):
    return listing.last_seen_at or listing.scraped_at
