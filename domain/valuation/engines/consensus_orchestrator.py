"""Minimal production orchestrator for the private-beta valuation consensus."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from core.entities.listing import Listing, Property
from domain.valuation.engines.contracts import (
    EngineContext,
    EngineRequest,
    EngineResult,
    EngineStatus,
)
from domain.valuation.engines.registry import (
    EngineRegistry,
    UnknownValuationEngineError,
    default_engine_registry,
)

CONSENSUS_METHOD = "favorite_first_with_legacy_fallback_v1"

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EngineSpec:
    name: str
    role: str


_ENGINE_SPECS = (
    _EngineSpec("comparables_canonical_outliers", "favorite"),
    _EngineSpec("comparables_legacy", "reference"),
    _EngineSpec("comparables_canonical", "experimental"),
)


@dataclass(frozen=True)
class BetaEngineResult:
    engine_name: str
    engine_version: str
    role: str
    status: str
    estimate_uf: float | None
    estimate_clp: int | None
    range_low_uf: float | None
    range_high_uf: float | None
    confidence: float | None
    comparables_count: int | None
    selected_for_final: bool
    warnings: list[str]
    safe_error_message: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "engine_name": self.engine_name,
            "engine_version": self.engine_version,
            "role": self.role,
            "status": self.status,
            "estimate_uf": self.estimate_uf,
            "estimate_clp": self.estimate_clp,
            "range_low_uf": self.range_low_uf,
            "range_high_uf": self.range_high_uf,
            "confidence": self.confidence,
            "comparables_count": self.comparables_count,
            "selected_for_final": self.selected_for_final,
            "warnings": list(self.warnings),
            "safe_error_message": self.safe_error_message,
        }


@dataclass(frozen=True)
class BetaConsensus:
    status: str
    method: str
    estimate_uf: float | None
    estimate_clp: int | None
    range_low_uf: float | None
    range_high_uf: float | None
    confidence: float | None
    selected_engine_names: list[str]
    engine_weights: dict[str, float]

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "method": self.method,
            "estimate_uf": self.estimate_uf,
            "estimate_clp": self.estimate_clp,
            "range_low_uf": self.range_low_uf,
            "range_high_uf": self.range_high_uf,
            "confidence": self.confidence,
            "selected_engine_names": list(self.selected_engine_names),
            "engine_weights": dict(self.engine_weights),
        }


@dataclass(frozen=True)
class BetaConsensusRun:
    selected_result: EngineResult | None
    raw_results: list[EngineResult]
    engine_results: list[BetaEngineResult]
    consensus: BetaConsensus

    @property
    def selected_engine_names(self) -> list[str]:
        if self.selected_result is None:
            return []
        return [self.selected_result.engine_name]


def run_beta_consensus(
    *,
    target: Property,
    candidates: list[Listing],
    uf_to_clp: Decimal,
    published_price_provided: bool,
    registry: EngineRegistry | None = None,
) -> BetaConsensusRun:
    """Run the beta engine set and select favorite first, then legacy fallback."""
    engine_registry = registry or default_engine_registry()
    request = EngineRequest(
        published_price_provided=published_price_provided,
        metadata={"orchestrator": CONSENSUS_METHOD},
    )
    context = EngineContext(
        target=target,
        candidates=tuple(candidates),
        uf_to_clp=uf_to_clp,
    )
    raw_results = [
        _run_engine(engine_registry, spec, request=request, context=context)
        for spec in _ENGINE_SPECS
    ]
    selected = _select_final(raw_results)
    selected_name = selected.engine_name if selected is not None else None
    normalized = [
        _normalize_result(
            result,
            spec=spec,
            uf_to_clp=uf_to_clp,
            selected_name=selected_name,
        )
        for spec, result in zip(_ENGINE_SPECS, raw_results, strict=True)
    ]
    selected_names = [selected_name] if selected_name is not None else []
    weights = {
        item.engine_name: 1.0 if item.selected_for_final else 0.0
        for item in normalized
    }
    consensus = BetaConsensus(
        status="ok" if selected is not None else "insufficient_data",
        method=CONSENSUS_METHOD,
        estimate_uf=_decimal_float(selected.estimated_price_uf) if selected else None,
        estimate_clp=_decimal_int(selected.estimated_price_clp) if selected else None,
        range_low_uf=_clp_to_uf(selected.range_low_clp, uf_to_clp) if selected else None,
        range_high_uf=_clp_to_uf(selected.range_high_clp, uf_to_clp) if selected else None,
        confidence=selected.confidence if selected else None,
        selected_engine_names=selected_names,
        engine_weights=weights,
    )
    _log.info(
        "valuation_consensus_completed method=%s selected=%s statuses=%s",
        CONSENSUS_METHOD,
        selected_name or "none",
        {item.engine_name: item.status for item in normalized},
    )
    return BetaConsensusRun(
        selected_result=selected,
        raw_results=raw_results,
        engine_results=normalized,
        consensus=consensus,
    )


def _run_engine(
    registry: EngineRegistry,
    spec: _EngineSpec,
    *,
    request: EngineRequest,
    context: EngineContext,
) -> EngineResult:
    try:
        engine = registry.get(spec.name)
    except UnknownValuationEngineError:
        return EngineResult(
            engine_name=spec.name,
            engine_version="unavailable",
            status=EngineStatus.NOT_APPLICABLE,
            warnings=("engine_not_registered",),
            error_code="engine_not_registered",
            error_message="Configured valuation engine is not registered",
        )
    try:
        return engine.valuate(request, context)
    except Exception:  # pragma: no cover - defensive orchestration boundary
        _log.exception("valuation_consensus_engine_failed engine=%s", spec.name)
        return EngineResult(
            engine_name=spec.name,
            engine_version=engine.version,
            status=EngineStatus.ERROR,
            warnings=("unexpected_error",),
            error_code="unexpected_error",
            error_message="Valuation engine failed unexpectedly",
        )


def _select_final(results: list[EngineResult]) -> EngineResult | None:
    by_name = {result.engine_name: result for result in results}
    favorite = by_name.get("comparables_canonical_outliers")
    if favorite is not None and favorite.is_successful:
        return favorite
    legacy = by_name.get("comparables_legacy")
    if legacy is not None and legacy.is_successful:
        return legacy
    return None


def _normalize_result(
    result: EngineResult,
    *,
    spec: _EngineSpec,
    uf_to_clp: Decimal,
    selected_name: str | None,
) -> BetaEngineResult:
    selected = result.engine_name == selected_name
    role = "fallback" if selected and result.engine_name == "comparables_legacy" else spec.role
    return BetaEngineResult(
        engine_name=result.engine_name,
        engine_version=result.engine_version,
        role=role,
        status=_public_status(result),
        estimate_uf=_decimal_float(result.estimated_price_uf),
        estimate_clp=_decimal_int(result.estimated_price_clp),
        range_low_uf=_clp_to_uf(result.range_low_clp, uf_to_clp),
        range_high_uf=_clp_to_uf(result.range_high_clp, uf_to_clp),
        confidence=result.confidence,
        comparables_count=result.comparables_used,
        selected_for_final=selected,
        warnings=_dedupe(result.warnings),
        safe_error_message=_safe_error_message(result),
    )


def _public_status(result: EngineResult) -> str:
    if result.is_successful:
        return "ok"
    if result.status == EngineStatus.INSUFFICIENT_DATA:
        return "insufficient_data"
    if result.status == EngineStatus.NOT_APPLICABLE:
        return "skipped"
    return "failed"


def _safe_error_message(result: EngineResult) -> str | None:
    status = _public_status(result)
    if status == "ok":
        return None
    if status == "insufficient_data":
        return "No hay suficientes datos comparables para este motor."
    if status == "skipped":
        return "El motor no esta disponible en esta ejecucion."
    if result.status == EngineStatus.VALIDATION_ERROR:
        return "El motor no pudo validar los datos de entrada."
    return "El motor no pudo completar la valorizacion."


def _clp_to_uf(value: Decimal | None, uf_to_clp: Decimal) -> float | None:
    if value is None:
        return None
    return round(float(value / uf_to_clp), 2)


def _decimal_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _decimal_int(value: Decimal | None) -> int | None:
    return round(value) if value is not None else None


def _dedupe(values: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(values))
