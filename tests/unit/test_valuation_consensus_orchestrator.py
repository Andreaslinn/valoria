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
    estimate: int | None = 180_000_000,
    error_message: str | None = None,
) -> EngineResult:
    return EngineResult(
        engine_name=name,
        engine_version=f"{name}_test_v1",
        status=status,
        estimated_price_clp=estimate if status == EngineStatus.OK else None,
        estimated_price_uf=(Decimal(estimate) / UF) if estimate is not None else None,
        range_low_clp=(estimate - 10_000_000) if estimate is not None else None,
        range_high_clp=(estimate + 10_000_000) if estimate is not None else None,
        confidence=0.8 if status == EngineStatus.OK else None,
        comparables_used=8 if status == EngineStatus.OK else None,
        error_code="test_error" if status != EngineStatus.OK else None,
        error_message=error_message,
    )


def _registry(*results: EngineResult | Exception) -> EngineRegistry:
    registry = EngineRegistry()
    names = (
        "comparables_canonical_outliers",
        "comparables_legacy",
        "comparables_canonical",
    )
    for name, result in zip(names, results, strict=True):
        registry.register(_StubEngine(name, result))
    return registry


def _run(registry: EngineRegistry):
    return run_beta_consensus(
        target=make_property(m2=75, built_area_m2=75),
        candidates=[make_listing(fingerprint=f"candidate-{idx}") for idx in range(8)],
        uf_to_clp=UF,
        published_price_provided=True,
        registry=registry,
    )


def test_consensus_selects_canonical_outliers_as_favorite() -> None:
    run = _run(
        _registry(
            _result("comparables_canonical_outliers", estimate=190_000_000),
            _result("comparables_legacy", estimate=180_000_000),
            _result("comparables_canonical", estimate=185_000_000),
        )
    )

    assert run.selected_engine_names == ["comparables_canonical_outliers"]
    assert run.consensus.method == CONSENSUS_METHOD
    assert run.consensus.estimate_clp == 190_000_000
    assert run.consensus.engine_weights == {
        "comparables_canonical_outliers": 1.0,
        "comparables_legacy": 0.0,
        "comparables_canonical": 0.0,
    }
    by_name = {item.engine_name: item for item in run.engine_results}
    assert by_name["comparables_canonical_outliers"].role == "favorite"
    assert by_name["comparables_canonical_outliers"].selected_for_final is True
    assert by_name["comparables_legacy"].role == "reference"
    assert by_name["comparables_canonical"].role == "experimental"


def test_consensus_uses_legacy_as_fallback_when_favorite_fails() -> None:
    run = _run(
        _registry(
            _result(
                "comparables_canonical_outliers",
                status=EngineStatus.ERROR,
                estimate=None,
            ),
            _result("comparables_legacy", estimate=180_000_000),
            _result("comparables_canonical", estimate=185_000_000),
        )
    )

    assert run.selected_engine_names == ["comparables_legacy"]
    assert run.consensus.estimate_clp == 180_000_000
    legacy = next(
        item for item in run.engine_results if item.engine_name == "comparables_legacy"
    )
    assert legacy.role == "fallback"
    assert legacy.selected_for_final is True


def test_missing_experimental_engine_is_reported_as_skipped() -> None:
    registry = EngineRegistry()
    registry.register(
        _StubEngine(
            "comparables_canonical_outliers",
            _result("comparables_canonical_outliers"),
        )
    )
    registry.register(
        _StubEngine("comparables_legacy", _result("comparables_legacy"))
    )

    run = _run(registry)

    experimental = next(
        item
        for item in run.engine_results
        if item.engine_name == "comparables_canonical"
    )
    assert experimental.status == "skipped"
    assert experimental.safe_error_message == "El motor no esta disponible en esta ejecucion."


def test_experimental_canonical_failure_does_not_break_favorite() -> None:
    run = _run(
        _registry(
            _result("comparables_canonical_outliers"),
            _result("comparables_legacy"),
            RuntimeError("internal stack detail"),
        )
    )

    assert run.selected_engine_names == ["comparables_canonical_outliers"]
    experimental = next(
        item
        for item in run.engine_results
        if item.engine_name == "comparables_canonical"
    )
    assert experimental.status == "failed"
    assert experimental.safe_error_message == "El motor no pudo completar la valorizacion."
    assert "stack" not in experimental.safe_error_message


def test_all_engines_failed_returns_controlled_insufficient_consensus() -> None:
    run = _run(
        _registry(
            _result(
                "comparables_canonical_outliers",
                status=EngineStatus.ERROR,
                estimate=None,
                error_message="database password was exposed here",
            ),
            _result(
                "comparables_legacy",
                status=EngineStatus.INSUFFICIENT_DATA,
                estimate=None,
                error_message="Solo 2 comparables elegibles",
            ),
            _result(
                "comparables_canonical",
                status=EngineStatus.VALIDATION_ERROR,
                estimate=None,
                error_message="raw validation internals",
            ),
        )
    )

    assert run.selected_result is None
    assert run.consensus.status == "insufficient_data"
    assert run.consensus.selected_engine_names == []
    assert all(item.selected_for_final is False for item in run.engine_results)
    assert all(
        "password" not in str(item.safe_error_message).lower()
        for item in run.engine_results
    )


def test_ablations_are_not_executed_or_reported_as_consensus_votes() -> None:
    run = _run(
        _registry(
            _result("comparables_canonical_outliers"),
            _result("comparables_legacy"),
            _result("comparables_canonical"),
        )
    )

    names = {item.engine_name for item in run.engine_results}
    assert "comparables_canonical_price_only" not in names
    assert "comparables_canonical_product" not in names
