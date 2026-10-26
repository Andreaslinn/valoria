"""Property-type scope controls for Radar beta."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from core.entities.listing import Listing
from core.normalization.property_type import normalize_property_type

DEFAULT_RADAR_ALLOWED_PROPERTY_TYPES: tuple[str, ...] = ("apartment",)
RADAR_APARTMENT_ONLY_NOTE = "Radar beta: por ahora analiza solo departamentos."
RADAR_APARTMENT_ONLY_LABEL = "Departamentos"
RADAR_ALL_TYPES_LABEL = "Departamentos y casas"


@dataclass(frozen=True)
class RadarPropertyScope:
    included: tuple[Listing, ...]
    allowed_property_types: tuple[str, ...]
    excluded_by_property_type_count: dict[str, int]
    houses_on_hold_count: int
    radar_scope_note: str
    radar_scope_label: str


def parse_allowed_property_types(raw: str | Iterable[str] | None) -> tuple[str, ...]:
    """Normalize a comma-separated env value into Radar property-type slugs."""
    if raw is None:
        return DEFAULT_RADAR_ALLOWED_PROPERTY_TYPES
    candidates = raw.split(",") if isinstance(raw, str) else raw

    allowed: list[str] = []
    for value in candidates:
        normalized = normalize_property_type(str(value).strip())
        if not normalized or normalized == "unknown" or normalized in allowed:
            continue
        allowed.append(normalized)
    return tuple(allowed) or DEFAULT_RADAR_ALLOWED_PROPERTY_TYPES


def apply_radar_property_scope(
    listings: Sequence[Listing],
    allowed_property_types: Sequence[str],
) -> RadarPropertyScope:
    allowed = parse_allowed_property_types(allowed_property_types)
    allowed_set = set(allowed)
    included: list[Listing] = []
    excluded = Counter[str]()

    for listing in listings:
        property_type = normalize_property_type(listing)
        if property_type in allowed_set:
            included.append(listing)
        else:
            excluded[property_type] += 1

    return RadarPropertyScope(
        included=tuple(included),
        allowed_property_types=allowed,
        excluded_by_property_type_count=dict(sorted(excluded.items())),
        houses_on_hold_count=excluded.get("house", 0),
        radar_scope_note=_scope_note(allowed),
        radar_scope_label=_scope_label(allowed),
    )


def _scope_note(allowed_property_types: Sequence[str]) -> str:
    if "house" in set(allowed_property_types):
        return "Radar beta: analiza departamentos y casas."
    return RADAR_APARTMENT_ONLY_NOTE


def _scope_label(allowed_property_types: Sequence[str]) -> str:
    if "house" in set(allowed_property_types):
        return RADAR_ALL_TYPES_LABEL
    return RADAR_APARTMENT_ONLY_LABEL
