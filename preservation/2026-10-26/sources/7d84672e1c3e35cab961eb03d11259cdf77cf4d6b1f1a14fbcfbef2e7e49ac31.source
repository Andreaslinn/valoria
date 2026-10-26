"""Honest geocoding precision guardrails.

These helpers intentionally distinguish textual location hints from usable
coordinates. A listing with a street-like hint but no coordinates is not an
address-level geocode.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from core.entities.listing import Listing, Property
from core.normalization.geocode_precision import (
    POOR_GEOCODE_PRECISIONS,
    has_location_hint,
    normalize_geocode_precision,
)

REPEATED_COORDINATE_THRESHOLD = 5


def has_valid_coordinates(value: Listing | Property) -> bool:
    coords = getattr(value, "coordinates", None)
    return coords is not None and coords.lat is not None and coords.lon is not None


def normalized_precision_for(value: Listing | Property) -> str:
    return normalize_geocode_precision(
        getattr(value, "geocode_precision", None),
        has_coords=has_valid_coordinates(value),
        raw_metadata=getattr(value, "raw_metadata", None),
        comuna=getattr(value, "comuna", None),
    )


def apply_geocoding_guardrails(
    listings: Sequence[Listing],
    *,
    repeated_threshold: int = REPEATED_COORDINATE_THRESHOLD,
) -> list[Listing]:
    """Normalize in-memory listing precision and degrade repeated coordinates.

    The function mutates the passed Listing objects intentionally: callers load
    fresh domain entities from persistence and should consume the guarded view.
    """
    guarded = list(listings)
    counts = Counter(_coord_cluster_key(listing) for listing in guarded if _coord_cluster_key(listing) is not None)

    for listing in guarded:
        precision = normalized_precision_for(listing)
        key = _coord_cluster_key(listing)
        if key is not None and counts[key] >= repeated_threshold:
            precision = "comuna_centroid"
        listing.geocode_precision = precision
    return guarded


def is_poor_geocoding(value: Listing | Property) -> bool:
    if not has_valid_coordinates(value):
        return True
    return normalized_precision_for(value) in POOR_GEOCODE_PRECISIONS


def _coord_cluster_key(listing: Listing) -> tuple[str, float, float] | None:
    if not has_valid_coordinates(listing):
        return None
    coords = listing.coordinates
    assert coords is not None
    return (listing.comuna or "unknown", round(float(coords.lat), 7), round(float(coords.lon), 7))


_has_location_hint = has_location_hint
