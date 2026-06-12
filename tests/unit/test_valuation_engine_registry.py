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


def test_default_registry_registers_valoria_consensus() -> None:
    registry = default_engine_registry()

    assert registry.list() == ["valoria_consensus"]
    assert registry.get("valoria_consensus").version == "valoria_consensus_v1"
