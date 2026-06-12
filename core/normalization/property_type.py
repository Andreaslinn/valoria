"""Canonical property type normalization.

Keep this module intentionally small and pure. Rich inference from text belongs
in ingestion/scraper code; this helper only normalizes already extracted values.
"""
from __future__ import annotations

from typing import Any

APARTMENT_ALIASES = {
    "apartment",
    "apartments",
    "apartamento",
    "apartamentos",
    "departamento",
    "departamentos",
    "depto",
    "dpto",
}
HOUSE_ALIASES = {"house", "houses", "casa", "casas"}
OFFICE_ALIASES = {"office", "oficina", "oficinas"}
LAND_ALIASES = {"land", "terreno", "terrenos", "sitio", "sitios", "lote", "lotes"}


def normalize_property_type(value: Any, *, default: str = "unknown") -> str:
    """Return the canonical property type for a raw value or domain object."""
    raw = getattr(value, "property_type", value)
    text = str(raw or "").strip().lower()
    if not text:
        return default
    if text in APARTMENT_ALIASES:
        return "apartment"
    if text in HOUSE_ALIASES:
        return "house"
    if text in OFFICE_ALIASES:
        return "office"
    if text in LAND_ALIASES:
        return "land"
    if text == "unknown":
        return "unknown"
    return default
