"""In-memory registry for valuation engines."""
from __future__ import annotations

from dataclasses import dataclass, field

from domain.valuation.engines.contracts import ValuationEngine


class DuplicateValuationEngineError(ValueError):
    pass


class UnknownValuationEngineError(LookupError):
    pass


@dataclass
class EngineRegistry:
    _engines: dict[str, ValuationEngine] = field(default_factory=dict)

    def register(self, engine: ValuationEngine) -> None:
        name = str(engine.name or "").strip()
        if not name:
            raise ValueError("engine name cannot be empty")
        if name in self._engines:
            raise DuplicateValuationEngineError(f"valuation engine already registered: {name}")
        self._engines[name] = engine

    def get(self, name: str) -> ValuationEngine:
        key = str(name or "").strip()
        try:
            return self._engines[key]
        except KeyError as exc:
            raise UnknownValuationEngineError(f"valuation engine not registered: {key}") from exc

    def list(self) -> list[str]:
        return sorted(self._engines)


def default_engine_registry() -> EngineRegistry:
    """Return the offline engine registry available in this checkout."""
    from domain.valuation.engines.valoria_consensus import ValoriaConsensusEngine

    registry = EngineRegistry()
    registry.register(ValoriaConsensusEngine())
    return registry
