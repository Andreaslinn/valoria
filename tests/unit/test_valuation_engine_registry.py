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
    experimental_engine_registry,
)
from tests.unit.factories import make_property


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
    assert registry.get("comparables_canonical_outliers").version == "phase4a_canonical_outliers_v1"
    assert registry.get("comparables_legacy").version == "phase0b_legacy_v1"


def test_experimental_registry_adds_future_engines_without_changing_default() -> None:
    assert "hedonic_baseline_v1" not in default_engine_registry().list()

    registry = experimental_engine_registry()

    assert registry.list() == [
        "comparables_canonical",
        "comparables_canonical_outliers",
        "comparables_canonical_price_only",
        "comparables_canonical_product",
        "comparables_legacy",
        "hedonic_baseline_v1",
        "land_building_v1",
        "market_trends_v1",
        "microzone_geo_v1",
        "ml_challenger_v1",
        "valoria_consensus_v1",
    ]


def test_future_engine_stubs_abstain_with_valid_engine_result() -> None:
    registry = experimental_engine_registry()
    context = EngineContext(target=make_property(property_type="apartment"))

    for name in (
        "hedonic_baseline_v1",
        "ml_challenger_v1",
        "microzone_geo_v1",
        "land_building_v1",
        "market_trends_v1",
    ):
        result = registry.get(name).valuate(EngineRequest(engine_name=name), context)

        assert result.engine_name == name
        assert result.status == EngineStatus.ABSTAINED
        assert result.estimated_price_clp is None
        assert result.error_code is not None
        assert result.to_dict()["abstention_reason"] == result.error_code
        assert result.diagnostics["read_only"] is True


def test_engine_result_is_serializable() -> None:
    payload = EngineResult(
        engine_name="dummy",
        engine_version="v1",
        status=EngineStatus.OK,
        estimated_price_clp="100000000",
        estimated_price_uf="2500",
        confidence=1.5,
        warnings=("a",),
        diagnostics={
            "nested": {"value": 1},
            "range_low_uf": 2300,
            "range_high_uf": 2700,
            "data_quality": "acceptable",
            "explanation": "test explanation",
        },
        coverage_status="acceptable",
    ).to_dict()

    assert payload["estimated_price_clp"] == 100000000.0
    assert payload["estimate_uf"] == 2500.0
    assert payload["low_uf"] == 2300
    assert payload["high_uf"] == 2700
    assert payload["method_version"] == "v1"
    assert payload["coverage"] == "acceptable"
    assert payload["data_quality"] == "acceptable"
    assert payload["warning_flags"] == ["a"]
    assert payload["explanation"] == "test explanation"
    assert payload["confidence"] == 1.0
    assert payload["warnings"] == ["a"]
