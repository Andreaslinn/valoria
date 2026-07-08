from __future__ import annotations

from decimal import Decimal

from domain.valuation.engines.contracts import EngineContext, EngineRequest, EngineStatus
from domain.valuation.engines.land_building import LandBuildingV1Engine
from domain.valuation.engines.registry import default_engine_registry, experimental_engine_registry
from tests.unit.factories import make_listing, make_property

UF = Decimal("40000")


def _house(
    idx: int,
    *,
    built_area: int = 140,
    land_area: int | None = 320,
    price_uf: int | None = None,
    source: str = "scraped",
):
    return make_listing(
        fingerprint=f"lb-house-{idx}",
        comuna="nunoa",
        property_type="house",
        m2=built_area,
        built_area_m2=built_area,
        land_area_m2=land_area,
        bedrooms=3,
        bathrooms=2,
        parking=2,
        price_uf=Decimal(price_uf or (built_area * 35 + (land_area or 0) * 9)),
        price_uf_source=source,
        price_uf_confidence="high",
        raw_metadata={"microzone_id": "mz-h"},
    )


def test_land_building_abstains_for_non_house_target() -> None:
    target = make_property(property_type="apartment", m2=80, built_area_m2=80)

    result = LandBuildingV1Engine().valuate(EngineRequest(), EngineContext(target=target))

    assert result.status == EngineStatus.ABSTAINED
    assert result.error_code == "unsupported_property_type"
    assert result.to_dict()["abstention_reason"] == "unsupported_property_type"


def test_land_building_abstains_with_missing_built_area() -> None:
    target = make_property(property_type="house", m2=0, built_area_m2=None, land_area_m2=300)

    result = LandBuildingV1Engine().valuate(EngineRequest(), EngineContext(target=target))

    assert result.status == EngineStatus.ABSTAINED
    assert result.error_code == "insufficient_target_data"


def test_land_building_abstains_when_target_land_area_is_missing() -> None:
    target = make_property(property_type="house", m2=140, built_area_m2=140, land_area_m2=None)

    result = LandBuildingV1Engine().valuate(EngineRequest(), EngineContext(target=target))

    assert result.status == EngineStatus.ABSTAINED
    assert result.error_code == "missing_land_area"
    assert "missing_land_area" in result.warnings
    assert "house_land_area_weak" in result.warnings


def test_land_building_returns_success_with_components_and_diagnostics() -> None:
    target = make_property(
        comuna="nunoa",
        property_type="house",
        m2=145,
        built_area_m2=145,
        land_area_m2=330,
        geocode_precision="address",
        raw_metadata={"microzone_id": "mz-h"},
    )
    candidates = [_house(idx, built_area=135 + idx, land_area=300 + idx * 10) for idx in range(8)]

    result = LandBuildingV1Engine().valuate(
        EngineRequest(engine_name="land_building_v1"),
        EngineContext(target=target, candidates=tuple(candidates), uf_to_clp=UF),
    )

    assert result.status == EngineStatus.SUCCESS
    assert result.estimated_price_uf is not None
    assert result.range_low_clp is not None
    assert result.range_high_clp is not None
    assert result.diagnostics["model_type_used"] == "local_land_building_proxy"
    assert result.diagnostics["clean_house_candidates_count"] == 8
    assert result.diagnostics["estimated_land_component_uf"] > 0
    assert result.diagnostics["estimated_building_component_uf"] > 0
    assert result.diagnostics["land_component_share_pct"] > 0
    assert result.diagnostics["building_component_share_pct"] > 0
    assert round(
        result.diagnostics["land_component_share_pct"] + result.diagnostics["building_component_share_pct"],
        2,
    ) == 100.0


def test_land_building_excludes_candidates_with_invalid_land_area() -> None:
    target = make_property(comuna="nunoa", property_type="house", m2=140, built_area_m2=140, land_area_m2=320)
    valid = [_house(idx, land_area=300 + idx * 5) for idx in range(5)]
    invalid = [
        _house(20, land_area=None),
        _house(21, land_area=0),
        _house(22, land_area=5),
        _house(23, land_area=30_000),
        _house(24, land_area=100, source="legacy_unrecoverable"),
    ]

    result = LandBuildingV1Engine().valuate(
        EngineRequest(),
        EngineContext(target=target, candidates=tuple(valid + invalid), uf_to_clp=UF),
    )

    assert result.status == EngineStatus.SUCCESS
    assert result.diagnostics["clean_house_candidates_count"] == 5
    assert result.diagnostics["candidates_without_land_area_count"] >= 2
    assert result.diagnostics["outliers_excluded"] >= 3


def test_land_building_registry_scope_is_experimental_only() -> None:
    assert "land_building_v1" not in default_engine_registry().list()
    assert "land_building_v1" in experimental_engine_registry().list()
