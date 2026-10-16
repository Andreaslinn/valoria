"""Original source address evidence and candidate keys, never property identity."""
import hashlib
import re
import unicodedata

from config.comunas import normalize_comuna, is_known_comuna


def candidate_building_key(address, commune):
    """Conservative street+number+commune candidate; no coordinate clustering.

    A key does not certify that two listings occupy the same physical building.
    Ranges, intersections, units and addresses without a street number abstain.
    """
    if not isinstance(address, str) or not commune or not is_known_comuna(commune):
        return None
    comuna = normalize_comuna(commune)
    if not comuna:
        return None
    street = address.split(",", 1)[0].strip()
    street = "".join(c for c in unicodedata.normalize("NFKD", street.casefold())
                     if not unicodedata.combining(c))
    if re.search(r"\b(km|kilometro|esquina|s/n|depto|departamento|oficina|torre|block)\b|\d\s*[-/]\s*\d", street):
        return None
    match = re.fullmatch(r"([a-z .]+?)\s+(\d{1,6})", street)
    if not match:
        return None
    name = re.sub(r"[^a-z ]", "", match[1])
    name = " ".join(name.split())
    if len(name) < 3:
        return None
    normalized = f"{comuna}|{name}|{int(match[2])}"
    return {"version": "building-candidate-v1", "key": "bc1:" + hashlib.sha256(normalized.encode()).hexdigest(),
            "basis": "source_street_number_commune", "normalized": normalized,
            "certified_building": False}
