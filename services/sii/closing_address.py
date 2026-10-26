"""Local catastro address index. Never guesses a role from a floor number.

The index is a disposable SQLite artifact, not a modification of SII source data.
Building identity retains the original SII sector and block. OSM adapters may
only supply alternative textual keys after a text miss; they cannot select roles.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from services.sii.parsing import normalize

ALIASES = {
    "AV": "AVENIDA",
    "AVDA": "AVENIDA",
    "AVD": "AVENIDA",
    "PJE": "PASAJE",
    "PSJE": "PASAJE",
    "PASA": "PASAJE",
    "PDTE": "PRESIDENTE",
    "PTE": "PRESIDENTE",
    "GRAL": "GENERAL",
    "GNRL": "GENERAL",
    "DR": "DOCTOR",
    "DRA": "DOCTORA",
    "STA": "SANTA",
    "STO": "SANTO",
    "SN": "SAN",
    "APOQ": "APOQUINDO",
    "FCO": "FRANCISCO",
    "FDEZ": "FERNANDEZ",
    "EDO": "EDUARDO",
    "CMDTE": "COMANDANTE",
    "TTE": "TENIENTE",
    "DG": "DIAGONAL",
    "DIAG": "DIAGONAL",
}
PREFIXES = {"AVENIDA", "CALLE", "PASAJE", "CAMINO", "DIAGONAL"}
UNIT = re.compile(
    r"\b(?:DEPARTAMENTO|DEPTO|DPTO|DEPT|DTO|DP[A-Z]?|DEP|APTO|APT|ESTACIONAMIENTO|ESTAC|EST|BODEGA|BOD|BD|BOX|OFICINA|OF|LOCAL|CASA)\b\s+([A-Z0-9]+(?:\s+[A-Z])?)\b"
)
FLOOR = re.compile(r"\b(?:PISO|PIS)\s*([0-9]+)\b")
TOWER = re.compile(r"\b(?:TORRE|BLOCK|BLOQUE|BL|EDIFICIO|EDIF)\s+([A-Z0-9]+)\b")


@dataclass(frozen=True)
class Address:
    street: str
    number: str | None
    unit: str | None = None
    floor: int | None = None
    tower: str | None = None


def street_key(text: str) -> str:
    tokens = [ALIASES.get(t, t) for t in normalize(text).split()]
    while tokens and tokens[0] in PREFIXES:
        tokens.pop(0)
    return " ".join(tokens)


def parse_address(raw: str) -> Address:
    text = normalize(raw)
    # Cadastral compact labels DPA/DPD identify a tower, not a new street.
    compact = re.search(r"\bDP([A-Z])\s+([A-Z0-9]+)\b", text)
    implicit = re.fullmatch(r"(.+?)\s+(\d+)\s+([A-Z])\s+(\d+)", text)
    if implicit:
        return Address(street_key(implicit[1]),str(int(implicit[2])),
                       str(int(implicit[4])),tower=implicit[3])
    unit, floor, tower = UNIT.search(text), FLOOR.search(text), TOWER.search(text)
    end = min((m.start() for m in (unit, floor, tower) if m), default=len(text))
    base = text[:end].strip()
    base = re.sub(r"\b(?:NUMERO|NUM|NRO|N)\s+(?=\d)", "", base)
    match = re.search(r"\b(\d+)(?:\s*([A-Z]))?$", base)
    # Streets such as 11 DE SEPTIEMBRE retain their initial number.
    street = base[: match.start()].strip() if match else base
    number = str(int(match[1])) + (match[2] or "") if match else None
    if not street or re.search(r"\d$",street):
        number = None
    return Address(
        street_key(street),
        number,
        re.sub(r"\s+", "", unit[1]) if unit else None,
        int(floor[1]) if floor else None,
        tower[1] if tower else compact[1] if compact else None,
    )


SCHEMA = """
CREATE TABLE role(rol TEXT PRIMARY KEY,comuna INTEGER,block INTEGER,street TEXT,
 number TEXT,unit TEXT,tower TEXT,raw TEXT,kind TEXT,year INTEGER,area REAL,source INTEGER);
CREATE INDEX building ON role(comuna,street,number);
"""


class AddressIndex:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row

    def close(self):
        self.db.close()

    def resolve(self, comuna: int, raw: str, osm_fallback=None) -> dict:
        address = parse_address(raw)
        if not address.number:
            return {"status": "unresolved", "reason": "missing_building_number", "candidates": []}
        rows = self.db.execute(
            "SELECT * FROM role WHERE comuna=? AND street=? AND number=? ORDER BY rol",
            (comuna, address.street, address.number),
        ).fetchall()
        method = "catastro_text"
        if not rows and osm_fallback is None:
            from services.sii.local_geography import street_matches
            names = {r[0] for r in self.db.execute(
                "SELECT DISTINCT street FROM role WHERE comuna=? AND number=?", (comuna,address.number))}
            found = {}
            for street in street_matches(address.street,names):
                for row in self.db.execute(
                    "SELECT * FROM role WHERE comuna=? AND street=? AND number=? ORDER BY rol",
                    (comuna,street,address.number)):
                    found[row['rol']] = row
            rows = [found[k] for k in sorted(found)]
            method = "catastro_local_alias"
        if not rows and osm_fallback is not None:
            # Offline/injected adapter returns alternative street names for the
            # same commune and civic number, never arbitrary nearby buildings.
            alternatives = osm_fallback(comuna, address.street, address.number)
            found = {}
            for street in alternatives:
                for row in self.db.execute(
                    "SELECT * FROM role WHERE comuna=? AND street=? AND number=? ORDER BY rol",
                    (comuna, street_key(street), address.number),
                ):
                    found[row["rol"]] = row
            rows = [found[k] for k in sorted(found)]
            method = "osm_text_fallback"
        if not rows:
            return {"status": "unresolved", "reason": "no_text_match", "candidates": []}
        buildings = sorted({(r["comuna"], r["block"], r["street"], r["number"]) for r in rows})
        candidates = [dict(r) for r in rows]
        if len(buildings) != 1:
            return {"status": "ambiguous", "reason": "multiple_buildings", "candidates": candidates}
        result = {
            "status": "building",
            "method": method,
            "building": list(buildings[0]),
            "candidates": candidates,
        }
        if address.unit or address.tower:
            selected = [
                r
                for r in candidates
                if (not address.unit or r["unit"] == address.unit)
                and (not address.tower or r["tower"] == address.tower)
            ]
            result["candidates"] = selected or candidates
            if len(selected) == 1:
                result.update(status="unit", role=selected[0])
            else:
                result.update(
                    status="ambiguous", reason="unit_not_unique" if selected else "unit_not_found"
                )
        elif address.floor is not None:
            result.update(status="ambiguous", reason="floor_not_recorded_in_catastro")
        return result
