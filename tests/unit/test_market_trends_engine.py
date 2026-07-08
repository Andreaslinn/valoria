from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from domain.valuation.engines.contracts import EngineContext, EngineRequest, EngineStatus
from domain.valuation.engines.market_trends import MarketTrendsV1Engine
from domain.valuation.engines.registry import default_engine_registry, experimental_engine_registry
from tests.unit.factories import make_listing, make_property

UF = Decimal("40000")
ANCHOR = datetime(2026, 7, 1, tzinfo=UTC)


def _listing(idx: int, *, price_m2: int, days_ago: int, microzone_id: str | None = "mz-t"):
    area = 80
    listing = make_listing(
        fingerprint=f"trend-{idx}",
        comuna="nunoa",
        property_type="apartment",
        m2=area,
        built_area_m2=area,
        price_uf=Decimal(price_m2 * area),
        price_uf_source="scraped",
        price_uf_confidence="high",
        raw_metadata={"microzone_id": microzone_id} if microzone_id else {},
    )
    listing.last_seen_at = ANCHOR - timedelta(days=days_ago)
    return listing


def test_market_trends_abstains_with_incomplete_target() -> None:
    target = make_property(property_type=None, m2=0, built_area_m2=0)

    result = MarketTrendsV1Engine().valuate(EngineRequest(), EngineContext(target=target))

    assert result.status == EngineStatus.ABSTAINED
    assert result.error_code == "insufficient_target_data"
    assert result.to_dict()["abstention_reason"] == "insufficient_target_data"


def test_market_trends_abstains_without_two_temporal_windows() -> None:
    target = make_property(
        comuna="nunoa",
        property_type="apartment",
        m2=80,
        built_area_m2=80,
        raw_metadata={"microzone_id": "mz-t"},
    )
    candidates = [_listing(idx, price_m2=55, days_ago=idx) for idx in range(6)]

    result = MarketTrendsV1Engine().valuate(
        EngineRequest(),
        EngineContext(target=target, candidates=tuple(candidates), uf_to_clp=UF),
    )

    assert result.status == EngineStatus.ABSTAINED
    assert result.error_code == "insufficient_trend_data"
    assert result.diagnostics["recent_count"] == 6
    assert result.diagnostics["previous_count"] == 0


def test_market_trends_returns_success_with_two_windows() -> None:
    target = make_property(
        comuna="nunoa",
        property_type="apartment",
        m2=80,
        built_area_m2=80,
        raw_metadata={"microzone_id": "mz-t"},
    )
    recent = [_listing(idx, price_m2=60 + idx, days_ago=idx * 5) for idx in range(4)]
    previous = [_listing(10 + idx, price_m2=50 + idx, days_ago=80 + idx * 5) for idx in range(4)]

    result = MarketTrendsV1Engine().valuate(
        EngineRequest(engine_name="market_trends_v1"),
        EngineContext(target=target, candidates=tuple(recent + previous), uf_to_clp=UF),
    )

    assert result.status == EngineStatus.SUCCESS
    assert result.estimated_price_uf is not None
    assert result.diagnostics["market_level_used"] == "microzone"
    assert result.diagnostics["recent_count"] == 4
    assert result.diagnostics["previous_count"] == 4
    assert result.diagnostics["trend_pct"] > 0
    assert result.diagnostics["trend_direction"] == "up"


def test_market_trends_lowers_confidence_for_comuna_fallback() -> None:
    microzone_target = make_property(
        comuna="nunoa",
        property_type="apartment",
        m2=80,
        built_area_m2=80,
        raw_metadata={"microzone_id": "mz-t"},
    )
    fallback_target = make_property(
        comuna="nunoa",
        property_type="apartment",
        m2=80,
        built_area_m2=80,
        raw_metadata={},
    )
    recent = [_listing(idx, price_m2=60, days_ago=idx * 5, microzone_id="mz-t") for idx in range(4)]
    previous = [_listing(10 + idx, price_m2=55, days_ago=80 + idx * 5, microzone_id="mz-t") for idx in range(4)]
    engine = MarketTrendsV1Engine()

    microzone = engine.valuate(EngineRequest(), EngineContext(target=microzone_target, candidates=tuple(recent + previous)))
    fallback = engine.valuate(EngineRequest(), EngineContext(target=fallback_target, candidates=tuple(recent + previous)))

    assert microzone.confidence is not None
    assert fallback.confidence is not None
    assert fallback.confidence < microzone.confidence
    assert "comuna_level_fallback" in fallback.warnings
    assert fallback.diagnostics["confidence_components"]["locality"] < 1.0


def test_market_trends_registry_scope_is_experimental_only() -> None:
    assert "market_trends_v1" not in default_engine_registry().list()
    assert "market_trends_v1" in experimental_engine_registry().list()
