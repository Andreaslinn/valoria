"""Read-only shadow microzone assignment.

This module classifies the best available microzone signal for audit purposes.
It does not persist anything and is intentionally conservative about what
counts as a real microzone.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.normalization.geocode_precision import canonical_geocode_precision
from domain.geocoding.geographic_microzones import geographic_microzone_for
from domain.geocoding.microzones import signals_from_value

REAL_GEOCODE_PRECISIONS = frozenset({"address", "street"})
WEAK_GEOCODE_PRECISIONS = frozenset({"unknown", "comuna", "comuna_centroid"})


@dataclass(frozen=True)
class ShadowMicrozoneAssignment:
    microzone_key: str | None
    microzone_kind: str
    confidence: str
    assignment_method: str
    is_real_microzone: bool
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "microzone_key": self.microzone_key,
            "microzone_kind": self.microzone_kind,
            "confidence": self.confidence,
            "assignment_method": self.assignment_method,
            "is_real_microzone": self.is_real_microzone,
            "warnings": list(self.warnings),
        }


def assign_shadow_microzone(value: Any) -> ShadowMicrozoneAssignment:
    """Return a non-persistent shadow microzone assignment for a listing-like value."""
    warnings = _base_warnings(value)
    geo = geographic_microzone_for(_geo_adapter(value))
    if geo.microzone is not None and geo.precision in REAL_GEOCODE_PRECISIONS:
        return ShadowMicrozoneAssignment(
            microzone_key=geo.microzone.microzone_id,
            microzone_kind="geo_500m",
            confidence=geo.microzone.confidence_level,
            assignment_method=f"geo_grid_500m:{geo.precision}:{geo.query_confidence}",
            is_real_microzone=True,
            warnings=tuple(warnings),
        )
    if geo.reason != "no_coordinates" and geo.reason != "ok":
        warnings.append(f"geo_microzone_{geo.reason}")

    textual_key, textual_confidence, textual_method = _textual_assignment(value)
    if textual_key is not None:
        return ShadowMicrozoneAssignment(
            microzone_key=textual_key,
            microzone_kind="textual",
            confidence=textual_confidence,
            assignment_method=textual_method,
            is_real_microzone=True,
            warnings=tuple(warnings),
        )

    comuna = _optional_str(_get(value, "comuna"))
    if comuna:
        return ShadowMicrozoneAssignment(
            microzone_key=f"comuna:{_normalize_key(comuna)}",
            microzone_kind="comuna_fallback",
            confidence="low",
            assignment_method="comuna_only_fallback",
            is_real_microzone=False,
            warnings=(*warnings, "comuna_fallback_not_real_microzone"),
        )

    return ShadowMicrozoneAssignment(
        microzone_key=None,
        microzone_kind="none",
        confidence="low",
        assignment_method="no_geographic_signal",
        is_real_microzone=False,
        warnings=(*warnings, "missing_comuna"),
    )


def weak_geocode_for_shadow(value: Any) -> bool:
    precision = canonical_geocode_precision(_get(value, "geocode_precision"))
    if precision in WEAK_GEOCODE_PRECISIONS:
        return True
    assignment = assign_shadow_microzone(value)
    return not assignment.is_real_microzone


def compatible_real_microzone(left: Any, right: Any) -> bool:
    left_assignment = assign_shadow_microzone(left)
    right_assignment = assign_shadow_microzone(right)
    return (
        left_assignment.is_real_microzone
        and right_assignment.is_real_microzone
        and left_assignment.microzone_kind == right_assignment.microzone_kind
        and left_assignment.microzone_key == right_assignment.microzone_key
    )


def _textual_assignment(value: Any) -> tuple[str | None, str, str]:
    signals = signals_from_value(value)
    tokens = _textual_tokens(signals)
    if not tokens:
        return None, "low", "textual:no_signal"
    token = tokens[0]
    confidence = _confidence_label(float(signals.confidence or 0.0))
    method = f"textual:{signals.reason or 'microzone_signal'}"
    return f"textual:{token}", confidence, method


def _textual_tokens(signals: Any) -> list[str]:
    tokens: list[str] = []
    if signals.nearby_metro:
        tokens.append(f"metro:{signals.nearby_metro}")
    if signals.nearby_avenue:
        tokens.append(f"avenue:{signals.nearby_avenue}")
    if signals.intersection_hint:
        tokens.append(f"intersection:{signals.intersection_hint}")
    tokens.extend(str(token) for token in signals.landmark_tokens)
    if signals.neighborhood_hint and signals.confidence >= 0.55:
        tokens.append(f"neighborhood:{signals.neighborhood_hint}")
    return sorted(set(tokens))


def _base_warnings(value: Any) -> list[str]:
    warnings: list[str] = []
    precision = canonical_geocode_precision(_get(value, "geocode_precision"))
    if precision in WEAK_GEOCODE_PRECISIONS:
        warnings.append(f"weak_geocode_precision:{precision}")
    if _lat_lon(value) == (None, None):
        warnings.append("missing_coordinates")
    return warnings


def _geo_adapter(value: Any) -> dict[str, Any]:
    lat, lon = _lat_lon(value)
    return {
        "lat": lat,
        "lon": lon,
        "comuna": _get(value, "comuna"),
        "geocode_precision": _get(value, "geocode_precision"),
        "raw_metadata": _get(value, "raw_metadata") if isinstance(_get(value, "raw_metadata"), dict) else {},
    }


def _lat_lon(value: Any) -> tuple[float | None, float | None]:
    lat = _float_or_none(_get(value, "lat"))
    lon = _float_or_none(_get(value, "lon"))
    if lat is not None or lon is not None:
        return lat, lon
    coordinates = _get(value, "coordinates")
    if coordinates is None:
        return None, None
    return _float_or_none(getattr(coordinates, "lat", None)), _float_or_none(getattr(coordinates, "lon", None))


def _confidence_label(value: float) -> str:
    if value >= 0.85:
        return "high"
    if value >= 0.55:
        return "medium"
    return "low"


def _normalize_key(value: str) -> str:
    return str(value).strip().lower().replace(" ", "_")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)
