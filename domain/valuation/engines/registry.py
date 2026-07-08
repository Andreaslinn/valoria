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
        name = _normalize_name(getattr(engine, "name", None))
        if name in self._engines:
            raise DuplicateValuationEngineError(f"valuation engine already registered: {name}")
        self._engines[name] = engine

    def get(self, name: str) -> ValuationEngine:
        key = _normalize_name(name)
        try:
            return self._engines[key]
        except KeyError as exc:
            raise UnknownValuationEngineError(f"valuation engine not registered: {key}") from exc

    def list(self) -> list[str]:
        return sorted(self._engines)


def default_engine_registry() -> EngineRegistry:
    from domain.valuation.engines.canonical_comparables import ComparablesCanonicalEngine
    from domain.valuation.engines.legacy_comparables import ComparablesLegacyEngine

    registry = EngineRegistry()
    registry.register(ComparablesLegacyEngine())
    registry.register(ComparablesCanonicalEngine())
    registry.register(
        ComparablesCanonicalEngine(
            name="comparables_canonical_price_only",
            variant="price_only",
        )
    )
    registry.register(
        ComparablesCanonicalEngine(
            name="comparables_canonical_product",
            variant="product",
        )
    )
    registry.register(
        ComparablesCanonicalEngine(
            name="comparables_canonical_outliers",
            variant="outliers",
        )
    )
    return registry


def experimental_engine_registry() -> EngineRegistry:
    """Return comparables plus future read-only engines.

    This registry is intentionally opt-in. Productive services should keep
    using ``default_engine_registry`` unless a feature flag explicitly says
    otherwise.
    """
    from domain.valuation.engines.consensus import ValoriaConsensusV1Engine
    from domain.valuation.engines.hedonic_baseline import HedonicBaselineV1Engine
    from domain.valuation.engines.land_building import LandBuildingV1Engine
    from domain.valuation.engines.market_trends import MarketTrendsV1Engine
    from domain.valuation.engines.microzone_geo import MicrozoneGeoV1Engine
    from domain.valuation.engines.ml import MLChallengerV1Engine

    registry = default_engine_registry()
    registry.register(HedonicBaselineV1Engine())
    registry.register(MLChallengerV1Engine())
    registry.register(MicrozoneGeoV1Engine())
    registry.register(LandBuildingV1Engine())
    registry.register(MarketTrendsV1Engine())
    registry.register(ValoriaConsensusV1Engine())
    return registry


def _normalize_name(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("engine name cannot be empty")
    return name
