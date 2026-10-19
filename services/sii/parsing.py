"""Strict latin-1 parsers pinned to the official non-agricultural layout.

https://www.sii.cl/bbrr/descargas/estructura_detalle_catastral.pdf
Roles: 19 fields; construction: 11 fields. One optional final pipe.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal

COMUNAS = {
    13101: "SANTIAGO",
    14157: "ESTACION CENTRAL",
    15103: "PROVIDENCIA",
    15105: "ÑUÑOA",
    15108: "LAS CONDES",
    15128: "LA FLORIDA",
    15160: "VITACURA",
    16106: "SAN MIGUEL",
    15161: "LO BARNECHEA",
    15132: "LA REINA",
    14158: "HUECHURABA",
}
EXPECTED_MEDIANS = {
    15160: 95.9,
    15108: 87.7,
    15105: 80.3,
    15103: 76.9,
    15128: 73.2,
    13101: 55.1,
    16106: 51.1,
    14157: 47.8,
}
FILE_RE = re.compile(r"BRTMPCATAS(NL|N)_(20\d{2})_([12])_(\d{5})(?:\.txt)?$", re.I)


def normalize(text: str) -> str:
    text = "".join(
        c for c in unicodedata.normalize("NFKD", text.upper()) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", text)).strip()


BY_NAME = {normalize(v): k for k, v in COMUNAS.items()}
BY_NAME["NUNOA"] = 15105  # spelling in the official PDF's commune table
BY_NAME.update({"SANTIAGO CENTRO": 13101, "SANTIAGO OESTE": 13134, "SANTIAGO SUR": 13135})
RAW_CODES = set(COMUNAS) | {13134, 13135}


def comuna(text: str) -> int | None:
    normalized = normalize(text)
    code = int(normalized) if normalized.isdecimal() else BY_NAME.get(normalized)
    return code if code in RAW_CODES else None


def address(raw: str) -> tuple[str, str | None, str | None]:
    text = normalize(raw)
    # A unit marker has priority over the first street number (e.g. 11 SEPTIEMBRE).
    unit_match = re.search(
        r"\b(DP|DEPTO|DPTO|DEP|DEPARTAMENTO|CASA|EST|ESTAC|BD|BOD|BODEGA)\s+([A-Z0-9]+)", text
    )
    unit = unit_match.group(2) if unit_match else None
    base = text[: unit_match.start()].strip() if unit_match else text
    match = re.search(r"\b(\d+[A-Z]?)$", base)
    return (base[: match.start()].strip(), match.group(1), unit) if match else (base, None, unit)


def property_type(destino: str, raw: str) -> str:
    tokens = set(normalize(raw).split())
    if destino == "H" and tokens & {"DP", "DEPTO", "DPTO", "DEP"}:
        return "depto"
    if destino == "Z" or tokens & {"BX", "BOX", "EST", "ESTAC", "ESTACIONAMIENTO"}:
        return "estac"
    if destino == "L" or tokens & {"BD", "BOD", "BODEGA"}:
        return "bodega"
    if destino == "H":
        return "casa"
    return "otro"


def fields(raw: str, count: int) -> list[str]:
    result = raw.rstrip("\r\n").split("|")
    if len(result) == count + 1 and result[-1] == "":
        result.pop()
    if len(result) != count:
        raise ValueError(
            f"layout_mismatch: expected {count} fields, obtained {len(result)}; consult official PDF"
        )
    return [x.strip() for x in result]


def integer(text: str) -> int:
    return int(text) if text else 0


def decimal(text: str) -> Decimal | None:
    if not text.strip():
        return None
    # Public F2890 uses comma decimal and no thousands separator.
    result = Decimal(text.strip().replace(",", "."))
    if not result.is_finite():
        raise ValueError("non_finite_amount")
    return result


def day(text: str):
    if not text.strip() or text.strip() == "00000000":
        return None
    return datetime.strptime(text.strip(), "%Y%m%d").date()


def dates(fi: str, fe: str):
    result, errors = [], []
    for name, text in (("fi", fi), ("fe", fe)):
        try:
            if text.strip() and text.strip() != "00000000" and len(text.strip()) != 8:
                raise ValueError("date_length")
            result.append(day(text))
        except ValueError:
            result.append(None)
            errors.append(name + "_invalida")
    return *result, errors


def catastro_row(raw: str, kind: str, expected_comuna: int, source_id: int):
    f = fields(raw, 19 if kind == "N" else 11)
    rol = tuple(integer(v) for v in f[:3])
    accepted = {13101, 13134, 13135} if expected_comuna == 13101 else {expected_comuna}
    if rol[0] not in accepted:
        raise ValueError(f"commune_mismatch: filename={expected_comuna}, row={rol[0]}")
    if kind == "N":
        street, number, unit = address(f[3])
        return (
            source_id,
            *rol,
            f[3],
            street,
            number,
            unit,
            f[6],
            property_type(f[6], f[3]),
            integer(f[14]),
            integer(f[4]),
            integer(f[5]),
            raw,
        )
    return (
        source_id,
        *rol,
        integer(f[3]),
        f[8],
        f[4],
        f[5],
        integer(f[6]) or None,
        integer(f[7]),
        f[9] == "CA",
        f[9],
        integer(f[10]),
        raw,
    )
