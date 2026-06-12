"""Read-only geographic microzones from trusted listing coordinates.

This module deliberately does not feed valuation or comparable scoring. It is a
data-quality layer for auditing future geo-based comparable improvements.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from core.normalization.geocode_precision import canonical_geocode_precision

DEFAULT_GRID_METERS = 500
MIN_COMPARABLES_PER_GEO_MICROZONE = 5
_METERS_PER_LAT_DEGREE = 111_320.0
_BLOCKED_LOW_CONFIDENCE_SOURCES = {"title_inferred_street", "url_inferred", "metadata_location_text"}


@dataclass(frozen=True)
class GeographicMicrozone:
    microzone_id: str
    comuna: str
    lat_index: int
    lon_index: int
    grid_meters: int
    confidence: float
    confidence_level: str
    reason: str


@dataclass(frozen=True)
class GeographicMicrozoneDecision:
    microzone: GeographicMicrozone | None
    eligible: bool
    reason: str
    precision: str
    query_source: str
    query_confidence: str


def geographic_microzone_for(
    value: Any,
    *,
    grid_meters: int = DEFAULT_GRID_METERS,
    allow_title_inferred: bool = False,
) -> GeographicMicrozoneDecision:
    """Return a geographic microzone decision without mutating the input."""
    lat = _float_or_none(_get(value, "lat"))
    lon = _float_or_none(_get(value, "lon"))
    raw_metadata = _raw_metadata(value)
    precision = canonical_geocode_precision(_get(value, "geocode_precision"))
    query_source = _norm(raw_metadata.get("geocode_query_source"), "legacy_unknown")
    query_confidence = _norm(raw_metadata.get("geocode_query_confidence"), "unknown")

    if lat is None or lon is None:
        return _decision(None, "no_coordinates", precision, query_source, query_confidence)
    if precision in {"unknown", "comuna", "comuna_centroid"}:
        return _decision(None, f"excluded_precision:{precision}", precision, query_source, query_confidence)
    if query_source == "title_inferred_street" and query_confidence == "low" and not allow_title_inferred:
        return _decision(None, "excluded_title_inferred_low_confidence", precision, query_source, query_confidence)
    if query_confidence == "low" and query_source in _BLOCKED_LOW_CONFIDENCE_SOURCES:
        return _decision(None, f"excluded_low_confidence_source:{query_source}", precision, query_source, query_confidence)

    comuna = _norm(_get(value, "comuna"), "unknown")
    lat_index, lon_index = geographic_microzone_indices(lat, lon, grid_meters=grid_meters)
    confidence = geographic_microzone_confidence(precision=precision, query_confidence=query_confidence)
    level = _confidence_level(confidence)
    microzone = GeographicMicrozone(
        microzone_id=f"geo{grid_meters}:{comuna}:{lat_index}:{lon_index}",
        comuna=comuna,
        lat_index=lat_index,
        lon_index=lon_index,
        grid_meters=grid_meters,
        confidence=confidence,
        confidence_level=level,
        reason=f"{precision}:{query_confidence}",
    )
    return GeographicMicrozoneDecision(
        microzone=microzone,
        eligible=True,
        reason="ok",
        precision=precision,
        query_source=query_source,
        query_confidence=query_confidence,
    )


def geographic_microzone_indices(lat: float, lon: float, *, grid_meters: int = DEFAULT_GRID_METERS) -> tuple[int, int]:
    lat_step = grid_meters / _METERS_PER_LAT_DEGREE
    lon_step = grid_meters / (_METERS_PER_LAT_DEGREE * max(0.2, math.cos(math.radians(lat))))
    return round(lat / lat_step), round(lon / lon_step)


def geographic_microzone_confidence(*, precision: str, query_confidence: str) -> float:
    precision = canonical_geocode_precision(precision)
    query_confidence = _norm(query_confidence, "unknown")
    base = {
        "address": 0.9,
        "street": 0.72,
    }.get(precision, 0.0)
    adjustment = {
        "high": 0.05,
        "medium": 0.0,
        "unknown": -0.08,
        "low": -0.18,
    }.get(query_confidence, -0.08)
    return round(max(0.0, min(1.0, base + adjustment)), 3)


def _confidence_level(confidence: float) -> str:
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.65:
        return "medium"
    if confidence > 0:
        return "low"
    return "none"


def build_geographic_microzone_report(
    listings: list[dict[str, Any]],
    *,
    grid_meters: int = DEFAULT_GRID_METERS,
    min_comparables: int = MIN_COMPARABLES_PER_GEO_MICROZONE,
) -> dict[str, Any]:
    active = [row for row in listings if _norm(row.get("status"), "active") == "active"]
    decisions = [
        (row, geographic_microzone_for(row, grid_meters=grid_meters))
        for row in active
    ]
    eligible = [(row, decision) for row, decision in decisions if decision.microzone is not None]
    by_microzone: dict[str, list[tuple[dict[str, Any], GeographicMicrozoneDecision]]] = defaultdict(list)
    for row, decision in eligible:
        assert decision.microzone is not None
        by_microzone[decision.microzone.microzone_id].append((row, decision))

    reason_counts = Counter(decision.reason for _, decision in decisions)
    source_counts = Counter(decision.query_source for _, decision in decisions)
    confidence_counts = Counter(decision.query_confidence for _, decision in decisions)
    precision_counts = Counter(decision.precision for _, decision in decisions)
    microzone_rows = _microzone_rows(by_microzone, min_comparables=min_comparables)
    by_comuna = _coverage_by_comuna(active, eligible)

    return {
        "summary": {
            "active_listings": len(active),
            "with_coordinates": sum(_float_or_none(row.get("lat")) is not None and _float_or_none(row.get("lon")) is not None for row in active),
            "geographic_microzone_listings": len(eligible),
            "geographic_microzone_coverage_pct": _pct(len(eligible), len(active)),
            "geographic_microzone_count": len(by_microzone),
            "sufficient_microzone_count": sum(row["has_sufficient_comparables"] for row in microzone_rows),
            "grid_meters": grid_meters,
            "min_comparables": min_comparables,
        },
        "reason_counts": _counter_rows(reason_counts),
        "query_source_counts": _counter_rows(source_counts),
        "query_confidence_counts": _counter_rows(confidence_counts),
        "precision_counts": _counter_rows(precision_counts),
        "by_comuna": by_comuna,
        "microzones": microzone_rows,
        "examples": _examples(eligible),
        "excluded_examples": _excluded_examples(decisions),
    }


def _microzone_rows(
    by_microzone: dict[str, list[tuple[dict[str, Any], GeographicMicrozoneDecision]]],
    *,
    min_comparables: int,
) -> list[dict[str, Any]]:
    rows = []
    for microzone_id, items in by_microzone.items():
        first = items[0][1].microzone
        assert first is not None
        property_types = Counter(_norm(row.get("property_type"), "unknown") for row, _ in items)
        rows.append(
            {
                "microzone_id": microzone_id,
                "comuna": first.comuna,
                "listing_count": len(items),
                "property_type_counts": dict(property_types),
                "max_property_type_count": max(property_types.values()) if property_types else 0,
                "has_sufficient_comparables": any(count >= min_comparables for count in property_types.values()),
                "avg_confidence": round(sum(decision.microzone.confidence for _, decision in items if decision.microzone) / len(items), 3),
                "sample_listing_ids": [row.get("id") for row, _ in items[:5]],
            }
        )
    return sorted(rows, key=lambda row: (-row["listing_count"], row["comuna"], row["microzone_id"]))


def _coverage_by_comuna(
    active: list[dict[str, Any]],
    eligible: list[tuple[dict[str, Any], GeographicMicrozoneDecision]],
) -> list[dict[str, Any]]:
    active_by_comuna = Counter(_norm(row.get("comuna"), "unknown") for row in active)
    eligible_by_comuna = Counter(_norm(row.get("comuna"), "unknown") for row, _ in eligible)
    rows = []
    for comuna, total in active_by_comuna.items():
        count = eligible_by_comuna[comuna]
        rows.append({"comuna": comuna, "active_listings": total, "geographic_microzone_listings": count, "coverage_pct": _pct(count, total)})
    return sorted(rows, key=lambda row: (row["coverage_pct"], -row["active_listings"], row["comuna"]))


def _examples(rows: list[tuple[dict[str, Any], GeographicMicrozoneDecision]], *, limit: int = 20) -> list[dict[str, Any]]:
    examples = []
    for row, decision in rows[:limit]:
        microzone = decision.microzone
        assert microzone is not None
        examples.append(
            {
                "id": row.get("id"),
                "comuna": row.get("comuna"),
                "property_type": row.get("property_type"),
                "geocode_precision": decision.precision,
                "query_source": decision.query_source,
                "query_confidence": decision.query_confidence,
                "microzone_id": microzone.microzone_id,
                "confidence": microzone.confidence,
                "title": row.get("title"),
            }
        )
    return examples


def _excluded_examples(
    decisions: list[tuple[dict[str, Any], GeographicMicrozoneDecision]],
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    examples = []
    for row, decision in decisions:
        if decision.microzone is not None:
            continue
        examples.append(
            {
                "id": row.get("id"),
                "comuna": row.get("comuna"),
                "property_type": row.get("property_type"),
                "geocode_precision": decision.precision,
                "query_source": decision.query_source,
                "query_confidence": decision.query_confidence,
                "reason": decision.reason,
                "title": row.get("title"),
            }
        )
        if len(examples) >= limit:
            break
    return examples


def _decision(
    microzone: GeographicMicrozone | None,
    reason: str,
    precision: str,
    query_source: str,
    query_confidence: str,
) -> GeographicMicrozoneDecision:
    return GeographicMicrozoneDecision(
        microzone=microzone,
        eligible=microzone is not None,
        reason=reason,
        precision=precision,
        query_source=query_source,
        query_confidence=query_confidence,
    )


def _counter_rows(counter: Counter[str]) -> list[dict[str, Any]]:
    total = sum(counter.values())
    return [
        {"value": key, "count": value, "pct": _pct(value, total)}
        for key, value in counter.most_common()
    ]


def _raw_metadata(value: Any) -> dict[str, Any]:
    raw = _get(value, "raw_metadata")
    return raw if isinstance(raw, dict) else {}


def _get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm(value: Any, default: str) -> str:
    text = str(value or "").strip().lower()
    return text or default


def _pct(part: int | float, total: int | float) -> float:
    return round((float(part) / float(total)) * 100, 2) if total else 0.0
