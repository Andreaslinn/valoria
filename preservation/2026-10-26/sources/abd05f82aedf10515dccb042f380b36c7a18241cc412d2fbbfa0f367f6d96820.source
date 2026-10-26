"""Offline engine evaluator."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from domain.valuation.engines.contracts import EngineContext, EngineRequest
from domain.valuation.engines.registry import EngineRegistry
from domain.valuation.evaluation.dataset import EvaluationCase


@dataclass(frozen=True)
class EngineEvaluationRow:
    case_id: str
    target_id: int | None
    engine_name: str
    engine_version: str | None
    status: str
    actual_price_clp: Decimal
    estimated_price_clp: Decimal | None
    absolute_percentage_error: float | None
    signed_percentage_error: float | None
    elapsed_ms: float
    property_type: str
    comuna: str
    geocode_precision: str | None
    has_land_area: bool
    comparables_used: int | None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    error_code: str | None = None
    error_message: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "target_id": self.target_id,
            "engine_name": self.engine_name,
            "engine_version": self.engine_version,
            "status": self.status,
            "actual_price_clp": float(self.actual_price_clp),
            "estimated_price_clp": float(self.estimated_price_clp) if self.estimated_price_clp is not None else None,
            "absolute_percentage_error": self.absolute_percentage_error,
            "signed_percentage_error": self.signed_percentage_error,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "property_type": self.property_type,
            "comuna": self.comuna,
            "geocode_precision": self.geocode_precision,
            "has_land_area": self.has_land_area,
            "comparables_used": self.comparables_used,
            "warnings": list(self.warnings),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "diagnostics": self.diagnostics,
        }


def evaluate_engines(
    *,
    cases: list[EvaluationCase],
    registry: EngineRegistry,
    engine_names: list[str],
    uf_to_clp: Decimal,
) -> list[EngineEvaluationRow]:
    rows: list[EngineEvaluationRow] = []
    for case_index, case in enumerate(cases):
        for engine_name in engine_names:
            engine = registry.get(engine_name)
            request = EngineRequest(
                evaluation_id=f"case-{case_index}",
                engine_name=engine_name,
                published_price_provided=True,
            )
            context = EngineContext(
                target=case.target,
                candidates=case.candidates,
                uf_to_clp=uf_to_clp,
                metadata=case.metadata,
            )
            start = time.perf_counter()
            try:
                result = engine.valuate(request, context)
            except Exception as exc:  # pragma: no cover - hard boundary for offline evaluator
                elapsed_ms = (time.perf_counter() - start) * 1000
                rows.append(
                    EngineEvaluationRow(
                        case_id=f"case-{case_index}",
                        target_id=case.target_id,
                        engine_name=engine_name,
                        engine_version=getattr(engine, "version", None),
                        status="error",
                        actual_price_clp=case.actual_price_clp,
                        estimated_price_clp=None,
                        absolute_percentage_error=None,
                        signed_percentage_error=None,
                        elapsed_ms=elapsed_ms,
                        property_type=case.target.property_type,
                        comuna=case.target.comuna,
                        geocode_precision=case.target.geocode_precision,
                        has_land_area=bool(case.target.land_area_m2 and case.target.land_area_m2 > 0),
                        comparables_used=None,
                        warnings=("unexpected_engine_exception",),
                        error_code="unexpected_engine_exception",
                        error_message=str(exc),
                    )
                )
                continue

            elapsed_ms = (time.perf_counter() - start) * 1000
            estimated = result.estimated_price_clp
            signed = _signed_pct_error(estimated, case.actual_price_clp)
            rows.append(
                EngineEvaluationRow(
                    case_id=f"case-{case_index}",
                    target_id=case.target_id,
                    engine_name=result.engine_name,
                    engine_version=result.engine_version,
                    status=result.status,
                    actual_price_clp=case.actual_price_clp,
                    estimated_price_clp=estimated,
                    absolute_percentage_error=abs(signed) if signed is not None else None,
                    signed_percentage_error=signed,
                    elapsed_ms=elapsed_ms,
                    property_type=case.target.property_type,
                    comuna=case.target.comuna,
                    geocode_precision=case.target.geocode_precision,
                    has_land_area=bool(case.target.land_area_m2 and case.target.land_area_m2 > 0),
                    comparables_used=result.comparables_used,
                    warnings=tuple(result.warnings),
                    error_code=result.error_code,
                    error_message=result.error_message,
                    diagnostics=dict(result.diagnostics),
                )
            )
    return rows


def _signed_pct_error(estimate: Decimal | None, actual: Decimal) -> float | None:
    if estimate is None or actual <= 0:
        return None
    return float((estimate - actual) / actual * Decimal("100"))
