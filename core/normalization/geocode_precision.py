"""Canonical geocode precision labels and ranking.

Official AVM vocabulary:
    address: verified usable coordinates at address level.
    street: street/avenue/landmark textual hint, not exact coordinates.
    comuna: known comuna only, no usable coordinates.
    comuna_centroid: coordinates are a comuna/cluster fallback.
    unknown: no usable location signal.

Legacy aliases are accepted at boundaries, then folded into the canonical
labels above. In particular, legacy ``exact`` means ``address``.
"""
from __future__ import annotations

from typing import Any

CANONICAL_GEOCODE_PRECISIONS = frozenset({"address", "street", "comuna", "comuna_centroid", "unknown"})
ADDRESS_LEVEL_PRECISIONS = frozenset({"address"})
POOR_GEOCODE_PRECISIONS = frozenset({"unknown", "comuna", "comuna_centroid"})
LOCATION_HINT_METADATA_KEYS = ("address", "address_label", "street_hint", "neighborhood", "subcomuna")

_ALIASES = {
    "exact": "address",
    "street_address": "address",
    "address": "address",
    "street": "street",
    "street_name": "street",
    "landmark_or_sector": "street",
    "intersection": "street",
    "comuna": "comuna",
    "comuna_centroid": "comuna_centroid",
    "legacy_unknown": "unknown",
    "unknown": "unknown",
    "null": "unknown",
    "none": "unknown",
    "": "unknown",
}

GEOCODE_PRECISION_RANK = {
    "unknown": 0,
    "comuna": 1,
    "comuna_centroid": 2,
    "street": 3,
    "address": 4,
}


def canonical_geocode_precision(value: Any) -> str:
    """Map any known precision label or legacy alias to the canonical label."""
    if value is None:
        return "unknown"
    text = str(value).strip().lower()
    return _ALIASES.get(text, "unknown")


def normalize_geocode_precision(
    value: Any,
    *,
    has_coords: bool,
    raw_metadata: dict[str, Any] | None = None,
    comuna: str | None = None,
) -> str:
    """Return the precision the system may honestly use for scoring.

    A listing cannot be ``address`` without usable coordinates. If it has only
    text such as address_label/street_hint, it is capped at ``street``.
    """
    precision = canonical_geocode_precision(value)
    metadata = raw_metadata or {}
    has_hint = has_location_hint(metadata)
    has_comuna = bool(comuna and comuna != "unknown")

    if not has_coords:
        if precision in {"address", "street"}:
            if has_hint:
                return "street"
            return "comuna" if has_comuna else "unknown"
        if precision in {"comuna", "comuna_centroid"}:
            return "comuna" if has_comuna else "unknown"
        return "unknown"

    if precision == "comuna":
        return "comuna_centroid"
    return precision


def geocode_precision_rank(value: Any) -> int:
    """Rank canonical or legacy precision labels from weakest to strongest."""
    return GEOCODE_PRECISION_RANK[canonical_geocode_precision(value)]


def has_location_hint(raw_metadata: dict[str, Any] | None) -> bool:
    metadata = raw_metadata or {}
    return any(str(metadata.get(key) or "").strip() for key in LOCATION_HINT_METADATA_KEYS)
