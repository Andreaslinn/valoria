from __future__ import annotations

from decimal import Decimal

from domain.valuation.engines.contracts import (
    EngineContext,
    EngineRequest,
    EngineStatus,
)
from domain.valuation.engines.hedonic_baseline import HedonicBaselineV1Engine
from domain.valuation.engines.registry import default_engine_registry, experimental_engine_registry
from tests.unit.factories import make_listing, make_property

UF = Decimal("40000")


def _apartment(idx: int, *, area: int = 80, price_m2: int = 55, source: str = "scraped"):
    return make_listing(
        fingerprint=f"hed-ap-{idx}",
        comuna="nunoa",
        property_type="apartment",
        m2=area,
        built_area_m2=area,
        bedrooms=2 + idx % 2,
        bathrooms=2,
        parking=1,
        price_uf=Decimal(area * price_m2),
        price_uf_source=source,
        price_uf_confidence="high",
        raw_metadata={"microzone_id": "mz-a"},
    )


def _house(idx: int, *, land_area: int | None = 300, price_m2: int = 45):
    return make_listing(
        fingerprint=f"hed-house-{idx}",
        comuna="nunoa",
        property_type="house",
        m2=140,
        built_area_m2=140,
        land_area_m2=land_area,
        bedrooms=3,
        bathrooms=2,
        parking=2,
        price_uf=Decimal(140 * price_m2),
        price_uf_source="scraped",
        price_uf_confidence="high",
        raw_metadata={"microzone_id": "mz-h"},
    )


def test_hedonic_baseline_abstains_with_incomplete_target() -> None:
    target = make_property(property_type=None, m2=0, built_area_m2=0)

    result = HedonicBaselineV1Engine().valuate(EngineRequest(), EngineContext(target=target))

    assert result.status == EngineStatus.ABSTAINED
    assert result.error_code == "insufficient_target_data"
    assert result.to_dict()["abstention_reason"] == "insufficient_target_data"


def test_hedonic_baseline_abstains_with_few_clean_candidates() -> None:
    target = make_property(comuna="nunoa", property_type="apartment", m2=80, built_area_m2=80)
    candidates = [_apartment(1), _apartment(2)]

    result = HedonicBaselineV1Engine().valuate(
        EngineRequest(),
        EngineContext(target=target, candidates=tuple(candidates), uf_to_clp=UF),
    )

    assert result.status == EngineStatus.ABSTAINED
    assert result.error_code == "insufficient_training_data"
    assert result.diagnostics["clean_candidates_count"] == 2


def test_hedonic_baseline_returns_success_for_apartment_with_diagnostics() -> None:
    target = make_property(
        comuna="nunoa",
        property_type="apartment",
        m2=82,
        built_area_m2=82,
        bedrooms=3,
        bathrooms=2,
        parking=1,
        raw_metadata={"microzone_id": "mz-a"},
    )
    candidates = [_apartment(idx, area=78 + idx, price_m2=52 + idx) for idx in range(8)]

    result = HedonicBaselineV1Engine().valuate(
        EngineRequest(engine_name="hedonic_baseline_v1"),
        EngineContext(target=target, candidates=tuple(candidates), uf_to_clp=UF),
    )

    assert result.status == EngineStatus.SUCCESS
    assert result.estimated_price_uf is not None
    assert result.range_low_clp is not None
    assert result.range_high_clp is not None
    assert result.diagnostics["model_type_used"] == "robust_adjusted_price_m2"
    assert result.diagnostics["clean_candidates_count"] == 8
    assert result.diagnostics["property_type"] == "apartment"
    assert "built_area_m2" in result.diagnostics["used_features"]
    assert result.diagnostics["adjusted_price_m2_uf"] is not None
    assert result.diagnostics["price_provenance_breakdown"] == {"scraped": 8}


def test_hedonic_baseline_lowers_confidence_when_fallback_is_used() -> None:
    full_target = make_property(
        comuna="nunoa",
        property_type="apartment",
        m2=80,
        built_area_m2=80,
        bedrooms=3,
        bathrooms=2,
        parking=1,
        raw_metadata={"microzone_id": "mz-a"},
    )
    fallback_target = make_property(
        comuna="nunoa",
        property_type="apartment",
        m2=80,
        built_area_m2=80,
        bedrooms=None,
        bathrooms=None,
        parking=None,
        geocode_precision="comuna",
        raw_metadata={},
    )
    candidates = [_apartment(idx, area=80, price_m2=55 + idx) for idx in range(8)]
    engine = HedonicBaselineV1Engine()

    full = engine.valuate(EngineRequest(), EngineContext(target=full_target, candidates=tuple(candidates)))
    fallback = engine.valuate(EngineRequest(), EngineContext(target=fallback_target, candidates=tuple(candidates)))

    assert full.confidence is not None
    assert fallback.confidence is not None
    assert fallback.confidence < full.confidence
    assert "fallback_used" in fallback.warnings
    assert fallback.diagnostics["confidence_components"]["fallback_penalty"] < 1.0


def test_hedonic_baseline_house_without_land_area_warns_and_reduces_confidence() -> None:
    target = make_property(
        comuna="nunoa",
        property_type="house",
        m2=140,
        built_area_m2=140,
        land_area_m2=None,
        bedrooms=3,
        bathrooms=2,
        parking=2,
    )
    candidates = [_house(idx, land_area=280 + idx * 10, price_m2=44 + idx) for idx in range(8)]

    result = HedonicBaselineV1Engine().valuate(
        EngineRequest(),
        EngineContext(target=target, candidates=tuple(candidates), uf_to_clp=UF),
    )

    assert result.status == EngineStatus.SUCCESS
    assert "missing_land_area" in result.warnings
    assert "house_land_area_weak" in result.warnings
    assert result.diagnostics["land_area_available"] is False
    assert result.diagnostics["confidence_components"]["land_area_signal"] == 0.35


def test_hedonic_baseline_registry_scope_is_experimental_only() -> None:
    assert "hedonic_baseline_v1" not in default_engine_registry().list()
    assert "hedonic_baseline_v1" in experimental_engine_registry().list()
