"""Factories mínimas para construir entidades en tests unitarios.

No usan DB — son puros objetos en memoria. Mantenemos valores sensatos
por defecto y permitimos override por kwargs.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from core.entities.listing import Listing, Property
from core.value_objects.location import Coordinates
from core.value_objects.price import Price

# Centroide de Ñuñoa — usado como referencia geográfica por defecto
_NUNOA = Coordinates(-33.4569, -70.5969)


def make_property(
    *,
    comuna: str = "nunoa",
    m2: float = 75.0,
    bedrooms: int = 3,
    bathrooms: int = 2,
    parking: int = 1,
    coords: Coordinates | None = _NUNOA,
    property_type: str | None = "apartment",
    built_area_m2: float | None = None,
    land_area_m2: float | None = None,
    usable_area_m2: float | None = None,
    geocode_precision: str | None = "address",
    raw_metadata: dict | None = None,
) -> Property:
    return Property(
        id=None,
        comuna=comuna,
        m2=m2,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        parking=parking,
        property_type=property_type,
        built_area_m2=built_area_m2 or m2,
        land_area_m2=land_area_m2,
        usable_area_m2=usable_area_m2 or (built_area_m2 or m2),
        coordinates=coords,
        geocode_precision=geocode_precision,
        raw_metadata=dict(raw_metadata or {}),
    )


def make_listing(
    *,
    fingerprint: str = "fp",
    source: str = "yapo",
    title: str | None = None,
    comuna: str = "nunoa",
    m2: float = 75.0,
    bedrooms: int = 3,
    bathrooms: int = 2,
    parking: int = 1,
    price_clp: int | Decimal = 180_000_000,
    price_uf: int | Decimal | None = None,
    price_currency: str | None = None,
    price_uf_source: str | None = None,
    price_uf_confidence: str | None = None,
    price_recovery_method: str | None = None,
    status: str = "active",
    coords: Coordinates | None = _NUNOA,
    geocode_precision: str | None = "address",
    property_type: str | None = "apartment",
    built_area_m2: float | None = None,
    land_area_m2: float | None = None,
    usable_area_m2: float | None = None,
    raw_metadata: dict | None = None,
) -> Listing:
    return Listing(
        id=None,
        source=source,
        external_id=f"ext-{fingerprint}",
        title=title or f"Depto {fingerprint}",
        comuna=comuna,
        m2=m2,
        property_type=property_type,
        built_area_m2=built_area_m2 or m2,
        land_area_m2=land_area_m2,
        usable_area_m2=usable_area_m2 or (built_area_m2 or m2),
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        parking=parking,
        price=Price(clp=Decimal(str(price_clp))),
        status=status,
        fingerprint=fingerprint,
        scraped_at=datetime.now(UTC),
        coordinates=coords,
        geocode_precision=geocode_precision,
        price_uf=Decimal(str(price_uf)) if price_uf is not None else None,
        price_currency=price_currency,
        price_uf_source=price_uf_source,
        price_uf_confidence=price_uf_confidence,
        price_recovery_method=price_recovery_method,
        raw_metadata=dict(raw_metadata or {}),
    )
