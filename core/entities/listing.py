"""Entidades de dominio para publicaciones y propiedades."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from core.value_objects.location import Coordinates
from core.value_objects.price import Price


@dataclass
class Property:
    """Inmueble fisico. Agrupa listings del mismo inmueble."""

    id: int | None
    comuna: str
    m2: float
    bedrooms: int
    bathrooms: int
    parking: int
    property_type: str = "unknown"
    built_area_m2: float | None = None
    land_area_m2: float | None = None
    usable_area_m2: float | None = None
    coordinates: Coordinates | None = None
    geocode_precision: str | None = None
    raw_metadata: dict = field(default_factory=dict)


@dataclass
class Listing:
    """Publicacion de venta."""

    id: int | None
    source: str
    external_id: str | None
    title: str
    comuna: str
    m2: float | None
    bedrooms: int
    bathrooms: int
    parking: int
    price: Price
    status: str
    fingerprint: str
    scraped_at: datetime
    last_seen_at: datetime | None = None
    last_refresh_attempted_at: datetime | None = None
    last_refresh_status: str | None = None
    url: str | None = None
    property_type: str = "unknown"
    built_area_m2: float | None = None
    land_area_m2: float | None = None
    usable_area_m2: float | None = None
    coordinates: Coordinates | None = None
    geocode_precision: str | None = None
    property_id: int | None = None
    price_uf: Decimal | None = None
    price_currency: str | None = None
    price_uf_confidence: str | None = None
    price_uf_source: str | None = None
    price_recovery_method: str | None = None
    raw_metadata: dict = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_appraisal(self) -> bool:
        """True si es una tasacion generada por el usuario."""
        return self.status == "appraisal_result"
