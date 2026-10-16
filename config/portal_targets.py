"""Configurable, HTTP-only Portal Inmobiliario discovery targets for RM.

This module intentionally contains no scheduler or persistence wiring. The
dry-run runner consumes these targets directly and validates every accepted
detail against ``config.comunas``.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal, TypedDict


PortalOperation = Literal["venta", "arriendo"]
PortalPropertyType = Literal["apartment", "house"]


class PortalTarget(TypedDict):
    label: str
    operation: PortalOperation
    property_type: PortalPropertyType
    comuna: str
    base_url: str
    enabled: bool
    max_pages: int


PORTAL_BASE_URL = "https://www.portalinmobiliario.com"
PORTAL_TARGET_MAX_PAGES = 2

# Ordered to make a capped dry-run cover east, centre, south and west early.
PORTAL_TARGETS: tuple[PortalTarget, ...] = (
    {"label": "santiago_sale_apartment", "operation": "venta", "property_type": "apartment", "comuna": "Santiago", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "providencia_rent_apartment", "operation": "arriendo", "property_type": "apartment", "comuna": "Providencia", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "nunoa_sale_apartment", "operation": "venta", "property_type": "apartment", "comuna": "Ñuñoa", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "las_condes_rent_apartment", "operation": "arriendo", "property_type": "apartment", "comuna": "Las Condes", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "vitacura_sale_house", "operation": "venta", "property_type": "house", "comuna": "Vitacura", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "lo_barnechea_sale_house", "operation": "venta", "property_type": "house", "comuna": "Lo Barnechea", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "la_reina_rent_house", "operation": "arriendo", "property_type": "house", "comuna": "La Reina", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "macul_sale_apartment", "operation": "venta", "property_type": "apartment", "comuna": "Macul", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "san_miguel_rent_apartment", "operation": "arriendo", "property_type": "apartment", "comuna": "San Miguel", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "estacion_central_sale_apartment", "operation": "venta", "property_type": "apartment", "comuna": "Estación Central", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "independencia_rent_apartment", "operation": "arriendo", "property_type": "apartment", "comuna": "Independencia", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "penalolen_sale_house", "operation": "venta", "property_type": "house", "comuna": "Peñalolén", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "maipu_rent_house", "operation": "arriendo", "property_type": "house", "comuna": "Maipú", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "puente_alto_sale_house", "operation": "venta", "property_type": "house", "comuna": "Puente Alto", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "providencia_sale_apartment", "operation": "venta", "property_type": "apartment", "comuna": "Providencia", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "vitacura_sale_apartment", "operation": "venta", "property_type": "apartment", "comuna": "Vitacura", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "la_florida_sale_apartment", "operation": "venta", "property_type": "apartment", "comuna": "La Florida", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
    {"label": "san_miguel_sale_apartment", "operation": "venta", "property_type": "apartment", "comuna": "San Miguel", "base_url": PORTAL_BASE_URL, "enabled": True, "max_pages": 2},
)


DAILY_DISCOVERY_TARGET_BUDGET = 8
PRIORITY_APARTMENT_TARGETS = frozenset({
    "santiago_sale_apartment", "providencia_sale_apartment",
    "vitacura_sale_apartment", "la_florida_sale_apartment",
    "san_miguel_sale_apartment", "estacion_central_sale_apartment",
})


def discovery_targets(targets=PORTAL_TARGETS, *, day: date | None = None):
    """Six daily apartment communes, remaining coverage rotated within eight GETs.

    Rotation is derived from the UTC calendar and needs no scheduler/DB state.
    Every remaining enabled sale target appears within three days today.
    """
    sales = [t for t in targets if t["enabled"] and t["operation"] == "venta"]
    if len(sales) <= DAILY_DISCOVERY_TARGET_BUDGET:
        return sales
    priority = [t for t in sales if t["label"] in PRIORITY_APARTMENT_TARGETS]
    others = [t for t in sales if t["label"] not in PRIORITY_APARTMENT_TARGETS]
    slots = DAILY_DISCOVERY_TARGET_BUDGET - len(priority)
    if slots <= 0:
        raise ValueError("priority_targets_exceed_discovery_budget")
    start = ((day or datetime.now(UTC).date()).toordinal() * slots) % len(others)
    return priority + [others[(start + i) % len(others)] for i in range(slots)]
