"""Common contracts for offline valuation engines.

These contracts are intentionally small. They let offline evaluators run
multiple engines while the productive valuation service keeps its current
legacy flow and public DTOs unchanged.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from core.entities.listing import Listing, Property


class EngineStatus:
    OK = "ok"
    SUCCESS = "success"
    ABSTAINED = "abstained"
    FAILED = "failed"
    INSUFFICIENT_DATA = "insufficient_data"
    VALIDATION_ERROR = "validation_error"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


@dataclass(frozen=True)
class EngineRequest:
    """Stable request metadata shared by offline engine runs."""

    evaluation_id: str | None = None
    engine_name: str | None = None
    published_price_provided: bool = True
    canonical_price_enabled: bool | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EngineContext:
    """Preloaded inputs for a valuation engine.

    Engines should consume this context instead of fetching the same target,
    candidates, UF rate or configuration repeatedly.
    """

    target: Property | Listing | None = None
    candidates: Sequence[Listing] = field(default_factory=tuple)
    uf_to_clp: Decimal | None = None
    valuation_date: datetime | None = None
    config: Mapping[str, Any] = field(default_factory=dict)
    geo: Mapping[str, Any] = field(default_factory=dict)
    microzone: Any | None = None
    repositories: Mapping[str, Any] = field(default_factory=dict)
    services: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValuationEngineInput:
    """Normalized target input for future engines.

    This is an additive adapter-friendly contract. Existing comparable engines
    can keep consuming ``EngineContext.target`` directly.
    """

    target: Property | Listing | None = None
    property_type: str | None = None
    comuna: str | None = None
    address: str | None = None
    built_area_m2: float | None = None
    land_area_m2: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    parking: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    geocode_precision: str | None = None
    microzone_id: str | None = None
    listing_id: int | None = None
    source: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)
    valuation_context: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_context(cls, context: EngineContext) -> ValuationEngineInput:
        target = context.target
        return cls(
            target=target,
            property_type=_first_attr(target, "property_type", "type"),
            comuna=_first_attr(target, "comuna", "municipality"),
            address=_first_attr(target, "address", "raw_address"),
            built_area_m2=_float_or_none(_first_attr(target, "built_area_m2", "usable_area_m2", "area_m2")),
            land_area_m2=_float_or_none(_first_attr(target, "land_area_m2", "land_area")),
            bedrooms=_int_or_none(_first_attr(target, "bedrooms", "dormitorios")),
            bathrooms=_int_or_none(_first_attr(target, "bathrooms", "banos")),
            parking=_int_or_none(_first_attr(target, "parking_spaces", "parking")),
            latitude=_float_or_none(_first_attr(target, "latitude", "lat")),
            longitude=_float_or_none(_first_attr(target, "longitude", "lon", "lng")),
            geocode_precision=_first_attr(target, "geocode_precision"),
            microzone_id=_first_attr(target, "microzone_id"),
            listing_id=_int_or_none(_first_attr(target, "id", "listing_id")),
            source=_first_attr(target, "source"),
            provenance=dict(context.metadata.get("provenance") or {}),
            valuation_context=dict(context.metadata or {}),
        )


@dataclass(frozen=True)
class EngineComparable:
    listing_id: int | None
    fingerprint: str | None
    score: float
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "fingerprint": self.fingerprint,
            "score": self.score,
            "diagnostics": _json_safe(dict(self.diagnostics)),
        }


@dataclass(frozen=True)
class EngineResult:
    """Serializable output for any valuation engine."""

    engine_name: str
    engine_version: str
    status: str
    estimated_price_clp: Decimal | int | float | str | None = None
    estimated_price_uf: Decimal | int | float | str | None = None
    range_low_clp: Decimal | int | float | str | None = None
    range_high_clp: Decimal | int | float | str | None = None
    confidence: float | None = None
    comparables_used: int | None = None
    warnings: Sequence[str] = field(default_factory=tuple)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    selected_comparables: Sequence[EngineComparable] = field(default_factory=tuple)
    coverage_status: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "estimated_price_clp", _decimal_or_none(self.estimated_price_clp))
        object.__setattr__(self, "estimated_price_uf", _decimal_or_none(self.estimated_price_uf))
        object.__setattr__(self, "range_low_clp", _decimal_or_none(self.range_low_clp))
        object.__setattr__(self, "range_high_clp", _decimal_or_none(self.range_high_clp))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))
        object.__setattr__(self, "selected_comparables", tuple(self.selected_comparables))
        if self.confidence is not None:
            object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))

    @property
    def is_successful(self) -> bool:
        return self.status in {EngineStatus.OK, EngineStatus.SUCCESS} and self.estimated_price_clp is not None

    @property
    def method_version(self) -> str:
        return self.engine_version

    @property
    def abstention_reason(self) -> str | None:
        if self.status in {EngineStatus.OK, EngineStatus.SUCCESS}:
            return None
        return self.error_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_name": self.engine_name,
            "engine_version": self.engine_version,
            "method_version": self.method_version,
            "status": self.status,
            "estimated_price_clp": _json_safe(self.estimated_price_clp),
            "estimated_price_uf": _json_safe(self.estimated_price_uf),
            "estimate_uf": _json_safe(self.estimated_price_uf),
            "range_low_clp": _json_safe(self.range_low_clp),
            "range_high_clp": _json_safe(self.range_high_clp),
            "low_uf": _json_safe(self.diagnostics.get("range_low_uf")),
            "high_uf": _json_safe(self.diagnostics.get("range_high_uf")),
            "confidence": self.confidence,
            "comparables_used": self.comparables_used,
            "coverage": self.coverage_status,
            "data_quality": self.diagnostics.get("data_quality") or self.coverage_status,
            "warning_flags": list(self.warnings),
            "explanation": self.diagnostics.get("explanation"),
            "abstention_reason": self.abstention_reason,
            "warnings": list(self.warnings),
            "diagnostics": _json_safe(dict(self.diagnostics)),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "selected_comparables": [item.to_dict() for item in self.selected_comparables],
            "coverage_status": self.coverage_status,
        }


@runtime_checkable
class ValuationEngine(Protocol):
    name: str
    version: str

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        ...


def _decimal_or_none(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_safe(value.to_dict())
    return value


def _first_attr(target: object | None, *names: str) -> Any:
    if target is None:
        return None
    for name in names:
        if hasattr(target, name):
            value = getattr(target, name)
            if value is not None:
                return value
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
