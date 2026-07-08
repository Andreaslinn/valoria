from __future__ import annotations

from decimal import Decimal

import pytest

from domain.valuation.engines.consensus import ValoriaConsensusV1Engine
from domain.valuation.engines.contracts import (
    EngineContext,
    EngineRequest,
    EngineResult,
    EngineStatus,
)
from domain.valuation.engines.valoria_consensus import ValoriaConsensusEngine
from domain.valuation.engines.valoria_consensus.config import ConsensusConfig
from tests.unit.factories import make_property

UF = Decimal("37000")


def _result(
    name: str,
    price: int,
    *,
    confidence: float = 0.8,
    status: str = EngineStatus.OK,
    version: str = "v1",
    warnings: tuple[str, ...] = (),
    diagnostics: dict | None = None,
) -> EngineResult:
    return EngineResult(
        engine_name=name,
        engine_version=version,
        status=status,
        estimated_price_clp=price if status == EngineStatus.OK else None,
        range_low_clp=price * 0.9 if status == EngineStatus.OK else None,
        range_high_clp=price * 1.1 if status == EngineStatus.OK else None,
        estimated_price_uf=Decimal(str(price)) / UF if status == EngineStatus.OK else None,
        confidence=confidence,
        comparables_used=8,
        warnings=warnings,
        diagnostics=diagnostics or {},
    )


def _context(*results: EngineResult, target=None, config: dict | None = None) -> EngineContext:
    return EngineContext(
        target=target or make_property(property_type="apartment"),
        uf_to_clp=UF,
        config=config or {},
        metadata={"engine_results": list(results), "product_classification": "standard_residential"},
    )


def test_consensus_uses_calibrated_segment_weights() -> None:
    legacy = _result("comparables_legacy", 100_000_000, confidence=0.6)
    canonical = _result("comparables_canonical", 120_000_000, confidence=0.9)
    config = {
        "consensus_weights": {
            "segments": {
                "apartment": {
                    "n_validation": 100,
                    "weights": {"comparables_legacy": 0.25, "comparables_canonical": 0.75},
                }
            }
        }
    }

    result = ValoriaConsensusEngine().valuate(
        EngineRequest(),
        _context(legacy, canonical, config=config),
    )

    assert result.status == EngineStatus.OK
    assert result.estimated_price_clp == Decimal("115000000.000")
    assert result.diagnostics["strategy"] == "calibrated:apartment"
    assert pytest.approx(sum(result.diagnostics["weights"].values())) == 1.0
    assert result.diagnostics["agreement"]["level"] == "moderate"


def test_consensus_excludes_failed_not_applicable_low_confidence_and_ood() -> None:
    ok = _result("comparables_canonical", 100_000_000)
    failed = _result("hedonic", 95_000_000, status=EngineStatus.ERROR)
    not_applicable = _result("house_land_building", 105_000_000, status=EngineStatus.NOT_APPLICABLE)
    low_confidence = _result("ml", 110_000_000, confidence=0.1)
    ood = _result("comparables_legacy", 90_000_000, diagnostics={"out_of_distribution": True})

    result = ValoriaConsensusEngine().valuate(
        EngineRequest(),
        _context(ok, failed, not_applicable, low_confidence, ood),
    )

    assert result.status == EngineStatus.OK
    assert result.estimated_price_clp == Decimal("100000000")
    assert result.diagnostics["weights"] == {"comparables_canonical": 1.0}
    assert result.diagnostics["engines_excluded"] == {
        "hedonic": "status_not_successful",
        "house_land_building": "not_applicable",
        "ml": "low_confidence",
        "comparables_legacy": "out_of_distribution",
    }


def test_house_land_building_is_excluded_for_apartment_targets() -> None:
    land_building = _result("house_land_building", 130_000_000)
    canonical = _result("comparables_canonical", 120_000_000)

    result = ValoriaConsensusEngine().valuate(
        EngineRequest(),
        _context(land_building, canonical, target=make_property(property_type="apartment")),
    )

    assert result.status == EngineStatus.OK
    assert result.diagnostics["engines_excluded"]["house_land_building"] == "not_applicable_to_property_type"
    assert result.diagnostics["weights"] == {"comparables_canonical": 1.0}


def test_extreme_disagreement_uses_robust_weighted_median_and_reduces_confidence() -> None:
    low = _result("comparables_canonical", 100_000_000, confidence=0.8)
    middle = _result("hedonic", 105_000_000, confidence=0.8)
    high = _result("ml", 220_000_000, confidence=0.8)

    result = ValoriaConsensusEngine().valuate(
        EngineRequest(),
        _context(low, middle, high),
    )

    assert result.estimated_price_clp == Decimal("105000000")
    assert result.diagnostics["strategy"] == "weighted_median_extreme_disagreement"
    assert "consensus_extreme_disagreement" in result.warnings
    assert "consensus_weak_agreement" in result.warnings
    assert result.confidence == pytest.approx(0.48)
    assert result.diagnostics["agreement"]["discrepant_engines"] == ["ml"]


def test_single_available_engine_is_returned_with_weight_one() -> None:
    canonical = _result("comparables_canonical", 120_000_000, confidence=0.7)

    result = ValoriaConsensusEngine().valuate(EngineRequest(), _context(canonical))

    assert result.status == EngineStatus.OK
    assert result.estimated_price_clp == Decimal("120000000")
    assert result.diagnostics["strategy"] == "single_engine"
    assert result.diagnostics["weights"] == {"comparables_canonical": 1.0}


def test_consensus_returns_insufficient_data_when_no_engine_passes_rules() -> None:
    failed = _result("hedonic", 100_000_000, status=EngineStatus.ERROR)

    result = ValoriaConsensusEngine().valuate(EngineRequest(), _context(failed))

    assert result.status == EngineStatus.INSUFFICIENT_DATA
    assert result.error_code == "no_eligible_engines"
    assert result.diagnostics["excluded_engines"] == {"hedonic": "status_not_successful"}
    assert result.diagnostics["engines_received"] == ["hedonic"]
    assert result.diagnostics["engines_used"] == []
    assert result.diagnostics["engines_abstained"] == {"hedonic": "status_not_successful"}


def test_consensus_v1_alias_abstains_without_base_engine_results() -> None:
    result = ValoriaConsensusV1Engine().valuate(EngineRequest(), _context())

    assert result.engine_name == "valoria_consensus_v1"
    assert result.status == EngineStatus.INSUFFICIENT_DATA
    assert result.error_code == "no_engine_results"
    assert result.diagnostics["engines_received"] == []
    assert result.diagnostics["weights"] == {}


def test_consensus_v1_alias_combines_artificial_engine_results() -> None:
    legacy = _result("comparables_legacy", 100_000_000, confidence=0.6)
    canonical = _result("comparables_canonical", 120_000_000, confidence=0.9)

    result = ValoriaConsensusV1Engine().valuate(EngineRequest(), _context(legacy, canonical))

    assert result.engine_name == "valoria_consensus_v1"
    assert result.status == EngineStatus.OK
    assert result.estimated_price_clp is not None
    assert result.diagnostics["engines_received"] == ["comparables_legacy", "comparables_canonical"]
    assert result.diagnostics["engines_used"] == ["comparables_legacy", "comparables_canonical"]
    assert result.diagnostics["engines_abstained"] == {}
    assert result.diagnostics["disagreement_level"] == "moderate"
    assert pytest.approx(sum(result.diagnostics["weights"].values())) == 1.0


def test_expected_version_mismatch_excludes_engine() -> None:
    engine = ValoriaConsensusEngine(
        ConsensusConfig(expected_versions={"ml": "ml_v2"})
    )
    ml = _result("ml", 100_000_000, version="ml_v1")
    canonical = _result("comparables_canonical", 110_000_000)

    result = engine.valuate(EngineRequest(), _context(ml, canonical))

    assert result.status == EngineStatus.OK
    assert result.diagnostics["engines_excluded"]["ml"] == "artifact_version_mismatch"


def test_engine_result_serializes_consensus_payload() -> None:
    canonical = _result("comparables_canonical", 120_000_000)

    payload = ValoriaConsensusEngine().valuate(EngineRequest(), _context(canonical)).to_dict()

    assert payload["engine_name"] == "valoria_consensus"
    assert payload["estimated_price_clp"] == 120_000_000.0
    assert payload["diagnostics"]["weights"] == {"comparables_canonical": 1.0}
