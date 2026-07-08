"""Shared helpers for experimental valuation engine stubs."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from domain.valuation.engines.contracts import (
    EngineContext,
    EngineRequest,
    EngineResult,
    EngineStatus,
    ValuationEngineInput,
)


class FutureEngineStub:
    """Read-only engine placeholder that abstains in a controlled way."""

    name: str
    version: str
    reason: str = "not_implemented"
    description: str = "Experimental valuation engine is not implemented yet"
    required_signal: str | None = None

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        normalized_input = ValuationEngineInput.from_context(context)
        reason = self._abstention_reason(normalized_input)
        return EngineResult(
            engine_name=self.name,
            engine_version=self.version,
            status=EngineStatus.ABSTAINED,
            warnings=(reason,),
            diagnostics={
                "method_version": self.version,
                "data_quality": "not_available",
                "coverage": "abstained",
                "explanation": self.description,
                "required_signal": self.required_signal,
                "input_summary": _input_summary(normalized_input),
                "request_engine_name": request.engine_name,
                "read_only": True,
            },
            error_code=reason,
            error_message=self.description,
            coverage_status="abstained",
        )

    def _abstention_reason(self, normalized_input: ValuationEngineInput) -> str:
        if self.required_signal is None:
            return self.reason
        if getattr(normalized_input, self.required_signal) in {None, ""}:
            return f"missing_{self.required_signal}"
        return self.reason


def _input_summary(normalized_input: ValuationEngineInput) -> Mapping[str, Any]:
    return {
        "property_type": normalized_input.property_type,
        "comuna": normalized_input.comuna,
        "built_area_m2": normalized_input.built_area_m2,
        "land_area_m2": normalized_input.land_area_m2,
        "bedrooms": normalized_input.bedrooms,
        "bathrooms": normalized_input.bathrooms,
        "parking": normalized_input.parking,
        "geocode_precision": normalized_input.geocode_precision,
        "microzone_id": normalized_input.microzone_id,
        "listing_id": normalized_input.listing_id,
        "source": normalized_input.source,
    }
