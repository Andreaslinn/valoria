"""Conservative contradiction guard; never reclassifies source records from a title."""
import re
from core.normalization.property_type import normalize_property_type


def property_type_conflict(listing) -> bool:
    title = str(getattr(listing, "title", "") or "").lower()
    house = bool(re.search(r"\bcasa\s+en\s+venta\b", title))
    apartment = bool(re.search(r"\b(?:departamento|apartamento)\s+en\s+venta\b", title))
    if house == apartment:
        return False
    canonical = normalize_property_type(listing)
    return (house and canonical == "apartment") or (apartment and canonical == "house")
