"""Autofill facts for a uniquely identified subject, without loading sale records."""

from __future__ import annotations

import math
import os
import sqlite3
from pathlib import Path

from services.sii.closing_address import AddressIndex


def address_details(*, address: str, comuna: str, data_dir: str | None = None):
    from services.sii.closing_opinion import SLUGS, _candidates

    code = SLUGS.get(comuna.strip().lower())
    base = {"fields": {}, "candidates": [], "candidate_count": 0}
    if code is None:
        return {
            **base,
            "status": "unavailable",
            "message": "No tenemos catastro por dirección para esta comuna.",
        }
    configured = data_dir if data_dir is not None else os.getenv("SII_CLOSING_DATA_DIR", "")
    if not configured:
        return {
            **base,
            "status": "unavailable",
            "message": "El catastro no está disponible para autocompletar.",
        }
    try:
        index = AddressIndex(Path(configured) / "address-index.sqlite")
        try:
            result = index.resolve(code, address)
        finally:
            index.close()
    except (OSError, ValueError, sqlite3.Error):
        return {
            **base,
            "status": "unavailable",
            "message": "No pudimos consultar el catastro. Puedes completar los datos manualmente.",
        }
    if result["status"] == "unresolved":
        return {
            **base,
            "status": "unavailable",
            "message": "No encontramos esa dirección. Revisa calle, número y departamento.",
        }
    role = result.get("role")
    if result["status"] == "building" and len(result["candidates"]) == 1:
        role = result["candidates"][0]
    if role is None:
        candidates, count = _candidates(result)
        return {
            **base,
            "status": "ambiguous",
            "candidates": candidates,
            "candidate_count": count,
            "message": "Hay varias unidades posibles. Completa el departamento o la torre para autocompletar sin elegir otra propiedad.",
        }
    if role["kind"] not in {"depto", "casa"}:
        return {
            **base,
            "status": "unavailable",
            "message": "La unidad identificada no es una casa o departamento. Completa los datos manualmente.",
        }
    fields = {}
    area = role.get("area")
    if area is not None and math.isfinite(area) and area > 0:
        fields["closed_area_m2"] = area
    if role.get("year"):
        fields["construction_year"] = role["year"]
    if role["kind"] in {"depto", "casa"}:
        fields["property_type"] = "apartment" if role["kind"] == "depto" else "house"
    # No linked source for rooms, baths, parking or land. Missing is unknown,
    # never zero, and no nearest listing or neighbouring unit supplies attributes.
    return {
        **base,
        "status": "resolved",
        "fields": fields,
        "source": "Catastro SII",
        "missing_fields": ["bedrooms", "bathrooms", "parking", "land_area_m2"],
        "message": "Datos de la unidad identificada en Catastro SII. Baños, dormitorios, estacionamientos y terreno no constan en esta fuente; complétalos si los conoces.",
    }
