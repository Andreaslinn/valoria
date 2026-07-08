from __future__ import annotations

from decimal import Decimal

from domain.valuation.engines.consensus import ValoriaConsensusV1Engine
from domain.valuation.engines.contracts import (
    EngineContext,
    EngineRequest,
    EngineResult,
    EngineStatus,
)
from domain.valuation.engines.experimental_lab import run_experimental_engine_lab
from domain.valuation.engines.registry import (
    EngineRegistry,
    default_engine_registry,
    experimental_engine_registry,
)
from tests.unit.factories import make_listing, make_property

UF = Decimal("40000")


class _FailingEngine:
    name = "failing_engine"
    version = "test_v1"

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        raise RuntimeError("boom from test")


class _StaticEngine:
    def __init__(
        self,
        name: str,
        price_clp: int,
        confidence: float = 0.8,
        warnings: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.version = "test_v1"
        self.price_clp = price_clp
        self.confidence = confidence
        self.warnings = warnings

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        return EngineResult(
            engine_name=self.name,
            engine_version=self.version,
            status=EngineStatus.SUCCESS,
            estimated_price_clp=self.price_clp,
            estimated_price_uf=Decimal(self.price_clp) / UF,
            range_low_clp=Decimal(self.price_clp) * Decimal("0.9"),
            range_high_clp=Decimal(self.price_clp) * Decimal("1.1"),
            confidence=self.confidence,
            warnings=self.warnings,
            diagnostics={"data_quality": "strong", "explanation": f"{self.name} test estimate"},
            coverage_status="strong_test",
        )


def _apartment(idx: int, *, price_m2: int = 55):
    area = 80
    return make_listing(
        fingerprint=f"lab-ap-{idx}",
        comuna="nunoa",
        property_type="apartment",
        m2=area,
        built_area_m2=area,
        bedrooms=2 + idx % 2,
        bathrooms=2,
        parking=1,
        price_uf=Decimal(area * price_m2),
        price_uf_source="scraped",
        price_uf_confidence="high",
        raw_metadata={"microzone_id": "mz-a"},
    )


def _house(idx: int):
    built = 140 + idx
    land = 300 + idx * 8
    return make_listing(
        fingerprint=f"lab-house-{idx}",
        comuna="nunoa",
        property_type="house",
        m2=built,
        built_area_m2=built,
        land_area_m2=land,
        bedrooms=3,
        bathrooms=2,
        parking=2,
        price_uf=Decimal(built * 35 + land * 9),
        price_uf_source="scraped",
        price_uf_confidence="high",
        raw_metadata={"microzone_id": "mz-h"},
    )


def _comparable(idx: int, *, price: int = 200_000_000):
    return make_listing(
        fingerprint=f"lab-comp-{idx}",
        comuna="nunoa",
        property_type="house",
        title="Casa familiar",
        m2=100,
        built_area_m2=100,
        price_clp=price,
        price_currency="CLP",
    )


def test_lab_runs_microzone_and_hedonic_with_consensus_for_apartment() -> None:
    target = make_property(
        comuna="nunoa",
        property_type="apartment",
        m2=80,
        built_area_m2=80,
        bedrooms=3,
        bathrooms=2,
        parking=1,
        raw_metadata={"microzone_id": "mz-a"},
    )
    context = EngineContext(
        target=target,
        candidates=tuple(_apartment(idx, price_m2=52 + idx) for idx in range(8)),
        uf_to_clp=UF,
    )

    run = run_experimental_engine_lab(
        context,
        engine_names=("microzone_geo_v1", "hedonic_baseline_v1"),
    )

    assert [result.engine_name for result in run.engine_results] == ["microzone_geo_v1", "hedonic_baseline_v1"]
    assert all(result.status == EngineStatus.SUCCESS for result in run.engine_results)
    assert run.consensus_result is not None
    assert run.consensus_result.engine_name == "valoria_consensus_v1"
    assert run.consensus_result.status == EngineStatus.OK
    assert run.consensus_result.diagnostics["engines_used"] == ["microzone_geo_v1", "hedonic_baseline_v1"]
    assert run.consensus_result.diagnostics["engines_failed"] == {}
    assert round(sum(row["final_normalized_weight"] for row in run.weight_audit), 6) == 1.0
    assert run.consensus_result.diagnostics["weight_audit"] == run.weight_audit
    payload = run.to_dict()
    assert payload["valuation_verdict"]["estimate_uf"] is not None
    assert payload["engine_breakdown"][0]["weight"] > 0
    assert payload["consensus_audit"]["engines_used"] == ["microzone_geo_v1", "hedonic_baseline_v1"]


def test_lab_runs_comparables_canonical_outliers_when_context_is_compatible() -> None:
    target = make_property(
        comuna="nunoa",
        property_type="house",
        m2=100,
        built_area_m2=100,
        raw_metadata={"title": "Casa familiar"},
    )
    candidates = [_comparable(idx, price=200_000_000 + idx * 1_000_000) for idx in range(8)]

    run = run_experimental_engine_lab(
        EngineContext(target=target, candidates=tuple(candidates), uf_to_clp=Decimal("40000")),
        engine_names=("comparables_canonical_outliers",),
        include_consensus=False,
    )

    result = run.engine_results[0]
    assert result.engine_name == "comparables_canonical_outliers"
    assert result.status == EngineStatus.OK
    assert run.weight_audit[0]["engine_name"] == "comparables_canonical_outliers"
    assert run.weight_audit[0]["final_normalized_weight"] == 1.0
    assert run.to_dict()["engine_breakdown"][0]["engine_name"] == "comparables_canonical_outliers"
    assert run.to_dict()["engine_breakdown"][0]["weight"] == 1.0


def test_lab_keeps_comparables_abstention_weight_zero_when_data_is_insufficient() -> None:
    target = make_property(comuna="nunoa", property_type="house", m2=100, built_area_m2=100)
    candidates = [_comparable(idx) for idx in range(3)]

    run = run_experimental_engine_lab(
        EngineContext(target=target, candidates=tuple(candidates), uf_to_clp=Decimal("40000")),
        engine_names=("comparables_canonical_outliers",),
        include_consensus=False,
    )

    assert run.engine_results[0].status == EngineStatus.INSUFFICIENT_DATA
    assert run.weight_audit[0]["final_normalized_weight"] == 0.0


def test_lab_runs_land_building_for_house_with_land_area() -> None:
    target = make_property(
        comuna="nunoa",
        property_type="house",
        m2=145,
        built_area_m2=145,
        land_area_m2=330,
        raw_metadata={"microzone_id": "mz-h"},
    )
    context = EngineContext(
        target=target,
        candidates=tuple(_house(idx) for idx in range(8)),
        uf_to_clp=UF,
    )

    run = run_experimental_engine_lab(
        context,
        engine_names=("land_building_v1",),
        include_consensus=False,
    )

    assert run.consensus_result is None
    result = run.engine_results[0]
    assert result.engine_name == "land_building_v1"
    assert result.status == EngineStatus.SUCCESS
    assert result.diagnostics["estimated_land_component_uf"] > 0
    assert run.weight_audit[0]["final_normalized_weight"] == 1.0


def test_lab_keeps_land_building_abstention_for_apartment_without_failing() -> None:
    target = make_property(property_type="apartment", m2=80, built_area_m2=80)

    run = run_experimental_engine_lab(
        EngineContext(target=target, candidates=tuple(_apartment(idx) for idx in range(8)), uf_to_clp=UF),
        engine_names=("land_building_v1",),
        include_consensus=True,
    )

    assert run.engine_results[0].status == EngineStatus.ABSTAINED
    assert run.engine_results[0].error_code == "unsupported_property_type"
    assert run.consensus_result is not None
    assert run.consensus_result.status == EngineStatus.ABSTAINED
    assert run.consensus_result.error_code == "insufficient_successful_engines"
    assert run.weight_audit[0]["final_normalized_weight"] == 0.0
    assert run.weight_audit[0]["applicability_modifier"] == 0.0


def test_lab_captures_failed_engine_without_breaking_run() -> None:
    registry = experimental_engine_registry()
    registry.register(_FailingEngine())

    run = run_experimental_engine_lab(
        EngineContext(target=make_property(), candidates=tuple(_apartment(idx) for idx in range(8)), uf_to_clp=UF),
        engine_names=("failing_engine", "microzone_geo_v1"),
        include_consensus=False,
        registry=registry,
    )

    failed = run.engine_results[0]
    assert failed.status == EngineStatus.FAILED
    assert failed.error_code == "engine_execution_failed"
    assert failed.diagnostics["error_type"] == "RuntimeError"
    assert run.engine_results[1].engine_name == "microzone_geo_v1"


def test_lab_consensus_abstains_with_less_than_two_successful_engines() -> None:
    context = EngineContext(
        target=make_property(raw_metadata={"microzone_id": "mz-a"}),
        candidates=tuple(_apartment(idx) for idx in range(8)),
        uf_to_clp=UF,
    )

    run = run_experimental_engine_lab(context, engine_names=("microzone_geo_v1",))

    assert run.consensus_result is not None
    assert run.consensus_result.status == EngineStatus.ABSTAINED
    assert run.consensus_result.error_code == "insufficient_successful_engines"
    assert run.consensus_result.diagnostics["engines_used"] == ["microzone_geo_v1"]
    assert run.consensus_result.diagnostics["weights"] == {}
    assert round(sum(row["final_normalized_weight"] for row in run.weight_audit), 6) == 1.0


def test_lab_consensus_combines_artificial_consistent_results() -> None:
    registry = EngineRegistry()
    registry.register(_StaticEngine("engine_a", 100_000_000, confidence=0.8))
    registry.register(_StaticEngine("engine_b", 104_000_000, confidence=0.9))
    registry.register(ValoriaConsensusV1Engine())

    run = run_experimental_engine_lab(
        EngineContext(target=make_property(), uf_to_clp=UF),
        engine_names=("engine_a", "engine_b"),
        registry=registry,
    )

    assert run.consensus_result is not None
    assert run.consensus_result.status == EngineStatus.OK
    assert run.consensus_result.estimated_price_clp is not None
    assert run.consensus_result.diagnostics["engines_used"] == ["engine_a", "engine_b"]
    assert run.consensus_result.diagnostics["disagreement_level"] == "strong"
    assert sum(run.consensus_result.diagnostics["weights"].values()) == 1.0
    assert run.consensus_result.diagnostics["consensus_method_version"] == "experimental_consensus_lab_v1"
    assert run.to_dict()["valuation_verdict"]["low_uf"] is not None


def test_lab_weight_audit_reduces_critical_warning_weight() -> None:
    registry = EngineRegistry()
    registry.register(_StaticEngine("engine_clean", 100_000_000, confidence=0.8))
    registry.register(_StaticEngine("engine_warned", 100_000_000, confidence=0.8, warnings=("weak_microzone",)))
    registry.register(ValoriaConsensusV1Engine())

    run = run_experimental_engine_lab(
        EngineContext(target=make_property(), uf_to_clp=UF),
        engine_names=("engine_clean", "engine_warned"),
        registry=registry,
    )

    by_name = {row["engine_name"]: row for row in run.weight_audit}
    assert by_name["engine_warned"]["critical_warning_modifier"] < 1.0
    assert by_name["engine_warned"]["final_normalized_weight"] < by_name["engine_clean"]["final_normalized_weight"]


def test_lab_does_not_change_productive_registry_scope() -> None:
    default_names = default_engine_registry().list()

    assert "microzone_geo_v1" not in default_names
    assert "hedonic_baseline_v1" not in default_names
    assert "land_building_v1" not in default_names
    assert "valoria_consensus_v1" not in default_names
