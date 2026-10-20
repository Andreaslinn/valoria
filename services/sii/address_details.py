"""Autofill facts for a uniquely identified subject, without loading sale records."""

from __future__ import annotations

import math
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from services.sii.closing_address import AddressIndex


def _extra_facts(root: Path, role: dict):
    """Only join the exact subject role AND source snapshot; optional old datasets work."""
    path = root / "address-details.sqlite"
    if not path.is_file():
        return {}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT land_area_m2,source_period FROM facts WHERE rol=? AND source_id=?",
                (role["rol"], role["source"]),
            ).fetchone()
            return dict(row) if row else {}
    except (OSError, sqlite3.Error):
        return {}


def address_details(
    *, address: str = "", comuna: str, data_dir: str | None = None, rol: str | None = None
):
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
            if rol is not None:
                from services.sii.role_lookup import resolve_role

                result = resolve_role(index, code, rol)
            else:
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
        if rol is not None:
            from services.sii.role_lookup import role_message

            return {**base, "status": "unavailable", "message": role_message(result["reason"])}
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
    extra = _extra_facts(Path(configured), role)
    land = extra.get("land_area_m2")
    if (
        role["kind"] == "casa"
        and isinstance(land, (float, int))
        and math.isfinite(land)
        and land > 0
    ):
        fields["land_area_m2"] = land
    # No linked source for rooms, baths or parking. Missing is unknown,
    # never zero, and no nearest listing or neighbouring unit supplies attributes.
    return {
        **base,
        "status": "resolved",
        "fields": fields,
        "source": "Catastro SII",
        "source_period": extra.get("source_period"),
        "missing_fields": ["bedrooms", "bathrooms", "parking"]
        + ([] if "land_area_m2" in fields else ["land_area_m2"]),
        "message": "Encontramos datos de esta propiedad en el catastro.",
        # The address belongs to the exact subject explicitly requested by rol,
        # never a comparable, candidate or neighbouring property.
        **({"subject_address": role["raw"]} if rol is not None else {}),
    }
