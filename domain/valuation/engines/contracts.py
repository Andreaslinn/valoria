"""Common contracts for offline valuation engines."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from core.entities.listing import Listing, Property


class EngineStatus:
    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_APPLICABLE = "not_applicable"
    VALIDATION_ERROR = "validation_error"
    ERROR = "error"


@dataclass(frozen=True)
class EngineRequest:
    """Engine-level request metadata.

    The normalized physical target belongs in ``EngineContext.target``. This
    request object carries run intent and optional metadata shared by offline
    evaluation tools.
    """

    evaluation_id: str | None = None
    engine_name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EngineContext:
    """Shared immutable input context for valuation engines."""

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
class EngineResult:
    """Common engine output.

    Engines may leave fields as ``None`` when a quantity is not available. The
    diagnostics dict is the extension point for engine-specific detail.
    """

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
    coverage_status: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "estimated_price_clp", _decimal_or_none(self.estimated_price_clp))
        object.__setattr__(self, "estimated_price_uf", _decimal_or_none(self.estimated_price_uf))
        object.__setattr__(self, "range_low_clp", _decimal_or_none(self.range_low_clp))
        object.__setattr__(self, "range_high_clp", _decimal_or_none(self.range_high_clp))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))
        if self.confidence is not None:
            object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))

    @property
    def is_successful(self) -> bool:
        return self.status == EngineStatus.OK and self.estimated_price_clp is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_name": self.engine_name,
            "engine_version": self.engine_version,
            "status": self.status,
            "estimated_price_clp": _json_safe(self.estimated_price_clp),
            "estimated_price_uf": _json_safe(self.estimated_price_uf),
            "range_low_clp": _json_safe(self.range_low_clp),
            "range_high_clp": _json_safe(self.range_high_clp),
            "confidence": self.confidence,
            "comparables_used": self.comparables_used,
            "warnings": list(self.warnings),
            "diagnostics": _json_safe(dict(self.diagnostics)),
            "error_code": self.error_code,
            "error_message": self.error_message,
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
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
