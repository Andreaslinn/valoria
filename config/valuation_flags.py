"""Runtime flags for valuation experiments."""
from __future__ import annotations

import os

VALUATION_CANONICAL_PRICE_ENABLED_ENV = "VALUATION_CANONICAL_PRICE_ENABLED"
VALUATION_CANONICAL_PRICE_SEGMENTED_ENV = "VALUATION_CANONICAL_PRICE_SEGMENTED"
VALORIA_USE_CONSENSUS_ENV = "VALORIA_USE_CONSENSUS"
VALORIA_EXPERIMENTAL_ENGINE_LAB_ENABLED_ENV = "VALORIA_EXPERIMENTAL_ENGINE_LAB_ENABLED"
VALUATION_QUALITY_V2_APPLY_MODE_ENV = "VALUATION_QUALITY_V2_APPLY_MODE"
VALUATION_QUALITY_V2_ALLOWED_PROPERTY_TYPES_ENV = "VALUATION_QUALITY_V2_ALLOWED_PROPERTY_TYPES"
VALUATION_QUALITY_V2_BLOCKED_COMUNAS_ENV = "VALUATION_QUALITY_V2_BLOCKED_COMUNAS"
VALUATION_QUALITY_V2_P90_RISK_COMUNAS_ENV = "VALUATION_QUALITY_V2_P90_RISK_COMUNAS"
VALUATION_QUALITY_V2_MIN_VALID_COMPARABLES_ENV = "VALUATION_QUALITY_V2_MIN_VALID_COMPARABLES"
VALUATION_QUALITY_V2_MAX_POOL_DISPERSION_ENV = "VALUATION_QUALITY_V2_MAX_POOL_DISPERSION"
VALUATION_QUALITY_V2_MAX_DELTA_VS_BASELINE_PCT_ENV = "VALUATION_QUALITY_V2_MAX_DELTA_VS_BASELINE_PCT"

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


def experimental_engine_lab_enabled() -> bool:
    """Return whether valuation responses should include experimental lab metadata.

    Defaults to false so productive valuation behavior and payloads remain on
    the current path unless an operator explicitly enables the lab surface.
    """
    value = os.getenv(VALORIA_EXPERIMENTAL_ENGINE_LAB_ENABLED_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def valuation_quality_v2_apply_mode() -> str:
    """Return CQ v2 mode: off, shadow, or guarded.

    Defaults to off so current productive valuation behavior remains unchanged.
    """
    value = os.getenv(VALUATION_QUALITY_V2_APPLY_MODE_ENV, "off").strip().lower()
    return value if value in {"off", "shadow", "guarded"} else "off"


def valuation_quality_v2_allowed_property_types() -> frozenset[str]:
    return _csv_set(os.getenv(VALUATION_QUALITY_V2_ALLOWED_PROPERTY_TYPES_ENV, "apartment"))


def valuation_quality_v2_blocked_comunas() -> frozenset[str]:
    return _csv_set(
        os.getenv(
            VALUATION_QUALITY_V2_BLOCKED_COMUNAS_ENV,
            "estacion central,la reina,macul",
        )
    )


def valuation_quality_v2_p90_risk_comunas() -> frozenset[str]:
    return _csv_set(
        os.getenv(
            VALUATION_QUALITY_V2_P90_RISK_COMUNAS_ENV,
            "la reina,las condes,maipu,nunoa",
        )
    )


def valuation_quality_v2_min_valid_comparables() -> int:
    return _int_env(VALUATION_QUALITY_V2_MIN_VALID_COMPARABLES_ENV, 5)


def valuation_quality_v2_max_pool_dispersion() -> float:
    return _float_env(VALUATION_QUALITY_V2_MAX_POOL_DISPERSION_ENV, 75.0)


def valuation_quality_v2_max_delta_vs_baseline_pct() -> float:
    return _float_env(VALUATION_QUALITY_V2_MAX_DELTA_VS_BASELINE_PCT_ENV, 0.25)


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


def _csv_set(value: str) -> frozenset[str]:
    return frozenset(
        item.strip().lower().replace("_", " ")
        for item in value.split(",")
        if item.strip()
    )


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default
