"""Generacion de fingerprints para deduplicar listings."""
from __future__ import annotations

import hashlib
import re
import unicodedata

from domain.ingestion.data_cleaning import CleanedListing

_MIN_TOKEN_LEN = 3


def make_fingerprint(cleaned: CleanedListing) -> str:
    """Hash estable para deduplicar listings completos e incompletos."""
    if not cleaned.is_complete_for_comparables:
        payload = "|".join(
            (
                cleaned.source,
                cleaned.external_id or "",
                cleaned.url or "",
                cleaned.comuna,
                _title_key(cleaned.title),
            )
        ).encode("utf-8")
        return hashlib.sha1(payload).hexdigest()

    parts = (
        cleaned.comuna,
        str(round(cleaned.m2 or 0)),
        str(cleaned.bedrooms),
        str(cleaned.bathrooms),
        str(cleaned.parking),
        _title_key(cleaned.title),
    )
    reference = cleaned.raw_metadata.get('source_property_reference') or {}
    if (isinstance(reference, dict) and cleaned.source == 'yapo' and reference.get('namespace') == 'houm'
            and reference.get('origin') == 'yapo.payload.description'
            and re.fullmatch(r'\d+', str(reference.get('value', '')))):
        # Different explicit broker property references must not collide just
        # because generic titles, rounded areas and room counts are equal.
        parts += ('yapo:houm:' + str(reference['value']),)
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()


def _title_key(title: str) -> str:
    lowered = title.lower()
    no_accents = "".join(
        ch
        for ch in unicodedata.normalize("NFD", lowered)
        if unicodedata.category(ch) != "Mn"
    )
    tokens = re.findall(r"[a-z0-9]+", no_accents)
    meaningful = sorted(t for t in tokens if len(t) >= _MIN_TOKEN_LEN)
    return "-".join(meaningful)
