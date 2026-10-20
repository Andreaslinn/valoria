"""Exact rol lookup within the selected SII commune. No address guessing."""

import re


def resolve_role(index, comuna: int, raw: str):
    empty = {"status": "unresolved", "candidates": []}
    if not isinstance(raw, str) or len(raw) > 64:
        return {**empty, "reason": "invalid_role"}
    raw = raw.translate({0x2013: "-", 0x2014: "-", 0x2212: "-"})
    match = re.fullmatch(r"\s*(?:(\d{5})\s*[-/]\s*)?(\d{1,9})\s*[-/]\s*(\d{1,9})\s*", raw)
    if not match or not int(match[2]) or not int(match[3]):
        return {**empty, "reason": "invalid_role"}
    if match[1] and int(match[1]) != comuna:
        return {**empty, "reason": "commune_mismatch"}
    key = f"{comuna}-{int(match[2])}-{int(match[3])}"
    row = index.db.execute("SELECT * FROM role WHERE rol=? AND comuna=?", (key, comuna)).fetchone()
    if row is None:
        return {**empty, "reason": "role_not_found"}
    role = dict(row)
    return {
        "status": "unit",
        "method": "catastro_role",
        "role": role,
        "candidates": [role],
        "building": [role["comuna"], role["block"], role["street"], role["number"]],
    }


def role_message(reason):
    return {
        "invalid_role": "Ingresa el rol como manzana-predio, por ejemplo 1234-56.",
        "commune_mismatch": "El código de comuna del rol no coincide con la comuna seleccionada.",
        "role_not_found": "No encontramos ese rol en la comuna seleccionada. Revisa el número y la comuna.",
    }.get(reason, "No pudimos identificar ese rol.")
