"""Read-only, additive Tasar opinion. No current valuation or SII rule changes."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import date
from functools import lru_cache
from pathlib import Path

from services.sii.closing_address import AddressIndex
from services.sii.closing_confidence import is_trusted
from services.sii.closing_knn import ClosingKNN

FROZEN_RULE_SHA256 = "57ddad8d5276f9b06240904404ef14c7cd75d190e9446888a670822d4debd94d"
SLUGS = {
    "santiago": 13101,
    "estacion_central": 14157,
    "providencia": 15103,
    "nunoa": 15105,
    "las_condes": 15108,
    "la_florida": 15128,
    "vitacura": 15160,
    "san_miguel": 16106,
}
RULE_PATH = Path(__file__).parents[2] / "reports/sii/closing_confidence_20261019/frozen-rule.json"


def unavailable(code, message, **extra):
    return {"status": "unavailable", "reason_code": code, "message": message, **extra}


@lru_cache(maxsize=2)
def _model(path: str, stamp: int, rule_path: str, rule_stamp: int):
    raw = Path(rule_path).read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(raw).hexdigest() != FROZEN_RULE_SHA256:
        raise ValueError("Frozen confidence rule differs from the validated rule")
    return ClosingKNN(json.loads(Path(path).read_text(encoding="utf8"))), json.loads(raw)


def _candidates(resolution):
    # Only anonymous building options. Never emit roles, civic/unit numbers or
    # third-party addresses, including through the ambiguity/error path.
    groups = sorted(
        {
            (r["comuna"], r["block"], r["street"], r["number"] or "")
            for r in resolution["candidates"]
        }
    )
    count = len(groups) if len(groups) > 1 else len(resolution["candidates"])
    kind = "Edificio" if len(groups) > 1 else "Unidad"
    return [
        {"id": f"option-{i + 1}", "label": f"{kind} candidato {i + 1}"}
        for i in range(min(count, 20))
    ], count


def build_opinion(
    *,
    address: str,
    comuna: str,
    property_type: str | None,
    area: float,
    as_of: date | None = None,
    data_dir: str | None = None,
):
    as_of = as_of or date.today()
    code = SLUGS.get(comuna.strip().lower())
    kind = {"apartment": "depto", "house": "casa", "depto": "depto", "casa": "casa"}.get(
        property_type or ""
    )
    if code is None or kind is None:
        return unavailable(
            "outside_coverage",
            "La segunda opinión SII no tiene cobertura suficiente para esta comuna o tipo de propiedad.",
        )
    configured = data_dir if data_dir is not None else os.getenv("SII_CLOSING_DATA_DIR", "")
    if not configured:
        return unavailable(
            "data_unavailable", "No hay datos SII disponibles para calcular la segunda opinión."
        )
    if not isinstance(address, str) or not address.strip() or len(address) > 512:
        return unavailable("invalid_address", "Revisa la dirección e incluye calle y número.")
    root = Path(configured)
    index_path, closings_path = root / "address-index.sqlite", root / "closings.json"
    try:
        model, rule = _model(
            str(closings_path.resolve()),
            closings_path.stat().st_mtime_ns,
            str(RULE_PATH.resolve()),
            RULE_PATH.stat().st_mtime_ns,
        )
        index = AddressIndex(index_path)
        try:
            resolution = index.resolve(code, address)
        finally:
            index.close()
    except (OSError, ValueError, KeyError, sqlite3.Error):
        return unavailable(
            "data_unavailable",
            "No hay datos SII suficientes disponibles para calcular la segunda opinión.",
        )
    if resolution["status"] == "ambiguous":
        candidates, count = _candidates(resolution)
        return {
            "status": "ambiguous",
            "reason_code": "ambiguous_address",
            "message": "La dirección coincide con varias opciones. Completa la torre o el departamento para distinguirlas.",
            "candidates": candidates,
            "candidate_count": count,
        }
    if resolution["status"] == "unresolved":
        return unavailable(
            "address_not_resolved",
            "No se pudo resolver la dirección en el catastro. Revisa calle, número y departamento.",
        )
    residential = [r for r in resolution["candidates"] if r["kind"] == kind]
    role = resolution.get("role")
    if role is not None and role["kind"] != kind:
        return unavailable(
            "property_type_mismatch", "El tipo de propiedad no coincide con la unidad del catastro."
        )
    if role is None and len(residential) == 1:
        role = residential[0]
    if role is not None:
        target_area, year = role["area"], role["year"]
        target_role = role["rol"]
        area_basis = "catastro_closed"
    else:
        years = {r["year"] for r in residential if r["year"]}
        if not residential or len(years) != 1 or any(not r["year"] for r in residential):
            return unavailable(
                "unit_required",
                "Indica el departamento para identificar su superficie cerrada y año de construcción.",
            )
        target_area, year = area, next(iter(years))
        target_role = "__unidentified_subject_unit__"
        area_basis = "user_area_building_resolved"
    if not target_area or target_area <= 0 or not year or year > as_of.year:
        return unavailable(
            "missing_unit_fields",
            "Faltan superficie cerrada o año de construcción suficientes en el catastro.",
        )
    building = resolution["building"]
    target = {
        "rol": target_role,
        "comuna": code,
        "block": building[1],
        "kind": kind,
        "date": as_of.isoformat(),
        "area": target_area,
        "year": year,
        "building": "|".join(map(str, building)),
    }
    prediction = model.estimate(target)
    if prediction["status"] != "ok":
        return unavailable(
            "insufficient_closings",
            "No hay diez cierres SII comparables suficientes para esta propiedad.",
        )
    dates = sorted(c["fecha"] for c in prediction["comparables"])
    trusted = is_trusted(rule, target, prediction)
    # The frozen rule stays untouched. The user-authorized presentation policy
    # displays out-of-zone raw kNN estimates as Referencial, never as high trust.
    return {
        "status": "available",
        "confidence_label": "Confianza alta" if trusted else "Referencial",
        "value_uf": prediction["value_uf"],
        "p25_uf": prediction["p25_uf"],
        "p75_uf": prediction["p75_uf"],
        "comparable_count": len(dates),
        "closing_dates": dates,
        "date_min": dates[0],
        "date_max": dates[-1],
        "area_m2": target_area,
        "area_basis": area_basis,
        "message": (
            "Coincide con una zona validada en 2025H2."
            if trusted
            else "Fuera de la zona de confianza validada. Úsala como referencia."
        ),
        "scope_message": (
            "Unidad identificada en el catastro."
            if role
            else "Edificio resuelto; la unidad no está identificada. Se usa la superficie ingresada."
        ),
    }
