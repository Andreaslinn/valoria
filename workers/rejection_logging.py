"""Bounded, allowlisted rejection diagnostics; never serialize a raw listing."""
import math
import re
from decimal import Decimal


FIELDS = ("price_clp", "m2", "bedrooms", "bathrooms", "parking", "scraped_at", "source", "url", "comuna", "title", "external_id", "lat", "lon")


def safe_value(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if len(str(value)) <= 64 else "<redacted:large-number>"
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (str, Decimal)) and re.fullmatch(r"[+-]?\d{1,20}(?:\.\d{1,20})?(?:[eE][+-]?\d{1,3})?", str(value)):
        return str(value)
    return "<redacted:" + type(value).__name__ + ">"


def rejection_record(raw, error):
    message = str(error)
    field = next((name for name in FIELDS if message.startswith(name + " ")), None)
    if field is None and message.startswith("Campo requerido ausente"):
        field = next((name for name in FIELDS if message.endswith(repr(name))), None)
    if message.startswith("missing_price:"):
        field = "price_clp"
    if message.startswith("invalid_url:"):
        field = "url"
    if type(error).__name__ == "UnknownComunaError":
        field = "comuna"
    reason = "validation_error"
    for fragment, code in (("bajo el minimo", "below_minimum"), ("fuera de rango", "out_of_range"),
                           ("Campo requerido ausente", "required_missing"), ("missing_price:", "missing_price"),
                           ("no numerico", "not_numeric"), ("no entero", "not_integer"),
                           ("no puede ser negativo", "negative_value"), ("no puede ser booleano", "boolean_value")):
        if fragment in message:
            reason = code
            break
    metadata = raw.get("raw_metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    source = raw.get("source")
    parser = metadata.get("parser_source")
    external_id = str(raw.get("external_id") or "")
    return {"event": "listing_validation_rejected", "listing_id": external_id if re.fullmatch(r"\d{1,64}", external_id) else "<redacted>",
            "id_kind": "source_external_id", "source": source if source in {"yapo", "portalinmobiliario"} else "unknown",
            "field": field or "unknown", "received_value": safe_value(raw.get(field)) if field else None,
            "received_type": type(raw.get(field)).__name__ if field else "unknown", "reason": reason,
            "parser_source": parser if parser in {"yapo_search_dom", "yapo_search_payload", "yapo_detail_payload"} else None,
            "price_uf": safe_value(raw.get("price_uf")), "uf_rate_used": safe_value(metadata.get("uf_rate_used"))}
