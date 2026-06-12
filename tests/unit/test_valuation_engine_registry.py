from __future__ import annotations

import pytest

from domain.valuation.engines.contracts import (
    EngineContext,
    EngineRequest,
    EngineResult,
    EngineStatus,
)
from domain.valuation.engines.registry import (
    DuplicateValuationEngineError,
    EngineRegistry,
    UnknownValuationEngineError,
    default_engine_registry,
)


class DummyEngine:
    name = "dummy"
    version = "v1"

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        return EngineResult(
            engine_name=self.name,
            engine_version=self.version,
            status=EngineStatus.OK,
            estimated_price_clp=100,
            confidence=0.8,
        )


def test_registry_register_get_and_list() -> None:
    registry = EngineRegistry()
    engine = DummyEngine()

    registry.register(engine)

    assert registry.get("dummy") is engine
    assert registry.list() == ["dummy"]


def test_registry_rejects_duplicate_names() -> None:
    registry = EngineRegistry()
    registry.register(DummyEngine())

    with pytest.raises(DuplicateValuationEngineError):
        registry.register(DummyEngine())


def test_registry_raises_for_unknown_engine() -> None:
    registry = EngineRegistry()

    with pytest.raises(UnknownValuationEngineError):
        registry.get("missing")


def test_default_registry_registers_legacy_and_canonical() -> None:
    registry = default_engine_registry()

    assert registry.list() == [
        "comparables_canonical",
        "comparables_canonical_outliers",
        "comparables_canonical_price_only",
        "comparables_canonical_product",
        "comparables_legacy",
    ]
    assert registry.get("comparables_canonical").version == "phase1_canonical_v1"
    assert registry.get("comparables_legacy").version == "phase0b_legacy_v1"


def test_engine_result_is_serializable() -> None:
    payload = EngineResult(
        engine_name="dummy",
        engine_version="v1",
        status=EngineStatus.OK,
        estimated_price_clp="100000000",
        confidence=1.5,
        warnings=("a",),
        diagnostics={"nested": {"value": 1}},
    ).to_dict()

    assert payload["estimated_price_clp"] == 100000000.0
    assert payload["confidence"] == 1.0
    assert payload["warnings"] == ["a"]
