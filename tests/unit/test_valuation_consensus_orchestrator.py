from __future__ import annotations

from decimal import Decimal

from domain.valuation.engines.consensus_orchestrator import (
    CONSENSUS_METHOD,
    run_beta_consensus,
)
from domain.valuation.engines.contracts import (
    EngineContext,
    EngineRequest,
    EngineResult,
    EngineStatus,
)
from domain.valuation.engines.registry import EngineRegistry
from tests.unit.factories import make_listing, make_property

UF = Decimal("39000")


class _StubEngine:
    def __init__(self, name: str, result: EngineResult | Exception) -> None:
        self.name = name
        self.version = f"{name}_test_v1"
        self._result = result

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _result(
    name: str,
    *,
    status: str = EngineStatus.OK,
    estimate: int | float | None = 180_000_000,
    confidence: float | None = 0.8,
    error_code: str | None = None,
    error_message: str | None = None,
) -> EngineResult:
    return EngineResult(
        engine_name=name,
        engine_version=f"{name}_test_v1",
        status=status,
        estimated_price_clp=estimate if status == EngineStatus.OK else None,
        estimated_price_uf=(Decimal(str(estimate)) / UF) if estimate is not None and estimate == estimate else None,
        range_low_clp=(Decimal(str(estimate)) - Decimal("10000000")) if estimate is not None and estimate == estimate else None,
        range_high_clp=(Decimal(str(estimate)) + Decimal("10000000")) if estimate is not None and estimate == estimate else None,
        confidence=confidence if status == EngineStatus.OK else None,
        comparables_used=8 if status == EngineStatus.OK else None,
        error_code=error_code if status == EngineStatus.OK else error_code or "test_error",
        error_message=error_message,
    )


def _registry(**results: EngineResult | Exception) -> EngineRegistry:
    registry = EngineRegistry()
    for name, result in results.items():
        registry.register(_StubEngine(name, result))
    return registry


def _run(registry: EngineRegistry):
    return run_beta_consensus(
        target=make_property(property_type="apartment", m2=75, built_area_m2=75),
        candidates=[make_listing(fingerprint=f"candidate-{idx}") for idx in range(8)],
        uf_to_clp=UF,
        published_price_provided=True,
        registry=registry,
    )


def test_two_valid_families_use_consensus_v1() -> None:
    run = _run(
        _registry(
            comparables_canonical_outliers=_result("comparables_canonical_outliers", estimate=190_000_000),
            hedonic_baseline_v1=_result("hedonic_baseline_v1", estimate=186_000_000),
        )
    )

    assert run.selected_engine_names == ["valoria_consensus_v1"]
    assert run.consensus.method == CONSENSUS_METHOD
    assert run.consensus.consensus_used is True
    assert run.consensus.valid_engine_count == 2
    assert run.consensus.engine_family_count == 2
    assert run.consensus.estimate_clp is not None
    assert set(run.consensus.engine_weights) == {
        "comparables_canonical_outliers",
        "hedonic_baseline_v1",
    }


def test_single_valid_family_keeps_current_fallback() -> None:
    run = _run(
        _registry(
            comparables_canonical_outliers=_result("comparables_canonical_outliers", estimate=190_000_000),
        )
    )

    assert run.selected_result is None
    assert run.selected_engine_names == []
    assert run.consensus.consensus_used is False
    assert run.consensus.status == "insufficient_data"
    assert run.consensus.fallback_reason == "insufficient_distinct_engine_families"
    assert run.consensus.valid_engine_count == 1
    assert run.consensus.engine_family_count == 1


def test_comparable_variants_do_not_create_false_consensus_votes() -> None:
    registry = _registry(
        comparables_canonical_outliers=_result("comparables_canonical_outliers", estimate=190_000_000),
    )
    registry.register(_StubEngine("comparables_legacy", _result("comparables_legacy", estimate=180_000_000)))
    registry.register(_StubEngine("comparables_canonical", _result("comparables_canonical", estimate=185_000_000)))

    run = _run(registry)

    names = {item.engine_name for item in run.engine_results}
    assert "comparables_legacy" not in names
    assert "comparables_canonical" not in names
    assert run.consensus.consensus_used is False
    assert run.consensus.engine_families == ["market_comparables"]


def test_abstained_engine_does_not_block_other_families() -> None:
    run = _run(
        _registry(
            comparables_canonical_outliers=_result("comparables_canonical_outliers", estimate=190_000_000),
            microzone_geo_v1=_result("microzone_geo_v1", status=EngineStatus.ABSTAINED, estimate=None),
            hedonic_baseline_v1=_result("hedonic_baseline_v1", estimate=186_000_000),
        )
    )

    assert run.consensus.consensus_used is True
    microzone = next(item for item in run.engine_results if item.engine_name == "microzone_geo_v1")
    assert microzone.status == "insufficient_data"
    assert microzone.selected_for_final is False


def test_engine_exception_is_isolated_when_fallback_or_consensus_can_continue() -> None:
    run = _run(
        _registry(
            comparables_canonical_outliers=_result("comparables_canonical_outliers"),
            microzone_geo_v1=RuntimeError("internal stack detail"),
            hedonic_baseline_v1=_result("hedonic_baseline_v1", estimate=181_000_000),
        )
    )

    assert run.consensus.consensus_used is True
    failed = next(item for item in run.engine_results if item.engine_name == "microzone_geo_v1")
    assert failed.status == "failed"
    assert failed.safe_error_message == "El motor no pudo completar la tasacion."
    assert "stack" not in failed.safe_error_message


def test_invalid_zero_negative_nan_and_error_outputs_are_excluded() -> None:
    run = _run(
        _registry(
            comparables_canonical_outliers=_result("comparables_canonical_outliers", estimate=190_000_000),
            microzone_geo_v1=_result("microzone_geo_v1", estimate=0),
            hedonic_baseline_v1=_result("hedonic_baseline_v1", estimate=-100),
            market_trends_v1=_result("market_trends_v1", estimate=float("nan")),
            land_building_v1=_result("land_building_v1", estimate=200_000_000, error_code="fatal"),
        )
    )

    assert run.consensus.consensus_used is False
    assert run.consensus.valid_engine_count == 1
    assert run.consensus.engine_families == ["market_comparables"]
    invalid = {item.engine_name: item for item in run.engine_results}
    assert invalid["microzone_geo_v1"].status == "failed"
    assert invalid["hedonic_baseline_v1"].status == "failed"
    assert invalid["market_trends_v1"].status == "failed"
    assert invalid["land_building_v1"].status == "failed"
