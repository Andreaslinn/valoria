"""Runtime flags for valuation experiments."""
from __future__ import annotations

import os

VALUATION_CANONICAL_PRICE_ENABLED_ENV = "VALUATION_CANONICAL_PRICE_ENABLED"
VALUATION_CANONICAL_PRICE_SEGMENTED_ENV = "VALUATION_CANONICAL_PRICE_SEGMENTED"
VALORIA_USE_CONSENSUS_ENV = "VALORIA_USE_CONSENSUS"

CANONICAL_PRICE_SEGMENT_ALLOWLIST = frozenset({
    "vitacura::house",
    "nunoa::house",
    "la_reina::apartment",
    "recoleta::house",
    "independencia::house",
    "estacion_central::house",
    "maipu::house",
})

CANONICAL_PRICE_SEGMENT_DENYLIST = frozenset({
    "santiago::apartment",
    "las_condes::apartment",
    "estacion_central::apartment",
    "san_miguel::apartment",
})


def valuation_canonical_price_enabled() -> bool:
    """Return whether valuation should use canonical UF-aware price basis.

    Defaults to false so production valuation remains legacy CLP/m2 unless the
    experiment is explicitly enabled.
    """
    value = os.getenv(VALUATION_CANONICAL_PRICE_ENABLED_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def valuation_canonical_price_segmented_enabled() -> bool:
    """Return whether canonical price can be activated by target segment."""
    value = os.getenv(VALUATION_CANONICAL_PRICE_SEGMENTED_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def valoria_consensus_enabled() -> bool:
    """Return whether the productive valuation flow should run beta consensus."""
    value = os.getenv(VALORIA_USE_CONSENSUS_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def canonical_price_segment_key(comuna: str | None, property_type: str | None) -> str:
    return f"{_normalize_segment_part(comuna)}::{_normalize_segment_part(property_type)}"


def canonical_price_enabled_for_segment(comuna: str | None, property_type: str | None) -> bool:
    """Return whether the target segment is allowed for UF-aware valuation."""
    segment = canonical_price_segment_key(comuna, property_type)
    if segment in CANONICAL_PRICE_SEGMENT_DENYLIST:
        return False
    return segment in CANONICAL_PRICE_SEGMENT_ALLOWLIST


def _normalize_segment_part(value: str | None) -> str:
    return str(value or "unknown").strip().lower().replace(" ", "_")
