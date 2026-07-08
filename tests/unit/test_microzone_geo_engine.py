from __future__ import annotations

from decimal import Decimal

from domain.valuation.engines.contracts import EngineContext, EngineRequest, EngineStatus
from domain.valuation.engines.microzone_geo import MicrozoneGeoV1Engine
from domain.valuation.engines.registry import default_engine_registry, experimental_engine_registry
from tests.unit.factories import make_listing, make_property

UF = Decimal("40000")


def _listing(idx: int, *, price_m2: int, microzone_id: str | None = None):
    area = 80
    return make_listing(
        fingerprint=f"geo-{idx}",
        comuna="nunoa",
        property_type="apartment",
        m2=area,
        built_area_m2=area,
        price_uf=Decimal(price_m2 * area),
        price_uf_source="scraped",
        price_uf_confidence="high",
        raw_metadata={"microzone_id": microzone_id} if microzone_id else {},
    )


def test_microzone_geo_abstains_with_incomplete_target() -> None:
    target = make_property(property_type=None, m2=0, built_area_m2=0)

    result = MicrozoneGeoV1Engine().valuate(EngineRequest(), EngineContext(target=target))

    assert result.status == EngineStatus.ABSTAINED
    assert result.error_code == "insufficient_target_data"
    assert result.to_dict()["abstention_reason"] == "insufficient_target_data"


def test_microzone_geo_returns_success_with_sufficient_comuna_data() -> None:
    target = make_property(comuna="nunoa", property_type="apartment", m2=80, built_area_m2=80)
    candidates = [_listing(idx, price_m2=50 + idx) for idx in range(6)]

    result = MicrozoneGeoV1Engine().valuate(
        EngineRequest(engine_name="microzone_geo_v1"),
        EngineContext(target=target, candidates=tuple(candidates), uf_to_clp=UF),
    )

    assert result.status == EngineStatus.SUCCESS
    assert result.estimated_price_uf == Decimal("4200.0")
    assert result.estimated_price_clp == Decimal("168000000.0")
    assert "comuna_level_fallback" in result.warnings
    assert "weak_microzone" in result.warnings
    assert result.diagnostics["market_level_used"] == "comuna"
    assert result.diagnostics["same_comuna_count"] == 6


def test_microzone_geo_uses_microzone_id_when_available() -> None:
    target = make_property(
        comuna="nunoa",
        property_type="apartment",
        m2=80,
        built_area_m2=80,
        raw_metadata={"microzone_id": "mz-1"},
    )
    candidates = [
        _listing(1, price_m2=60, microzone_id="mz-1"),
        _listing(2, price_m2=62, microzone_id="mz-1"),
        _listing(3, price_m2=64, microzone_id="mz-1"),
        _listing(4, price_m2=50, microzone_id="mz-2"),
        _listing(5, price_m2=52, microzone_id="mz-2"),
        _listing(6, price_m2=54, microzone_id="mz-2"),
    ]

    result = MicrozoneGeoV1Engine().valuate(
        EngineRequest(),
        EngineContext(target=target, candidates=tuple(candidates), uf_to_clp=UF),
    )

    assert result.status == EngineStatus.SUCCESS
    assert result.estimated_price_uf == Decimal("4960")
    assert result.diagnostics["market_level_used"] == "microzone"
    assert result.diagnostics["target_microzone_id"] == "mz-1"
    assert result.diagnostics["same_microzone_count"] == 3
    assert result.diagnostics["premium_vs_comuna_pct"] > 0
    assert "comuna_level_fallback" not in result.warnings


def test_microzone_geo_lowers_confidence_for_comuna_fallback() -> None:
    candidates = [_listing(idx, price_m2=50 + idx, microzone_id="mz-1") for idx in range(10)]
    microzone_target = make_property(
        comuna="nunoa",
        property_type="apartment",
        m2=80,
        built_area_m2=80,
        raw_metadata={"microzone_id": "mz-1"},
    )
    fallback_target = make_property(
        comuna="nunoa",
        property_type="apartment",
        m2=80,
        built_area_m2=80,
        raw_metadata={},
    )
    engine = MicrozoneGeoV1Engine()

    microzone = engine.valuate(EngineRequest(), EngineContext(target=microzone_target, candidates=tuple(candidates)))
    fallback = engine.valuate(EngineRequest(), EngineContext(target=fallback_target, candidates=tuple(candidates)))

    assert microzone.confidence is not None
    assert fallback.confidence is not None
    assert fallback.confidence < microzone.confidence
    assert fallback.diagnostics["confidence_components"]["territorial_specificity"] < 1.0


def test_microzone_geo_registry_scope_is_experimental_only() -> None:
    assert "microzone_geo_v1" not in default_engine_registry().list()
    assert "microzone_geo_v1" in experimental_engine_registry().list()
