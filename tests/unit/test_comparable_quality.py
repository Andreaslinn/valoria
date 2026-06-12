from __future__ import annotations

from core.value_objects.score import Score
from domain.valuation.comparable_quality import assess_comparable_quality
from tests.unit.factories import make_listing, make_property


def _scored(listings, score: float = 0.82):
    return [(Score.clamped(score), listing) for listing in listings]


def _microzone(value: str) -> dict:
    return {
        "geo_signals": {
            "nearby_metro": value,
            "nearby_avenue": None,
            "neighborhood_hint": None,
            "intersection_hint": None,
            "landmark_tokens": [f"metro:{value}"],
            "confidence": 0.8,
            "reason": "test",
        }
    }


def test_strong_comparable_set_has_expected_metrics() -> None:
    target = make_property(raw_metadata=_microzone("parque almagro"))
    listings = [
        make_listing(
            fingerprint=f"c{i}",
            price_clp=180_000_000 + i * 1_000_000,
            raw_metadata=_microzone("parque almagro"),
        )
        for i in range(12)
    ]

    result = assess_comparable_quality(target=target, scored_comparables=_scored(listings, 0.86))

    assert result.level in {"acceptable", "strong"}
    assert result.metrics["n_comparables"] == 12
    assert result.metrics["property_type_consistency"] == 1.0
    assert result.metrics["same_comuna_ratio"] == 1.0
    assert result.metrics["same_microzone_ratio"] == 1.0
    assert "mixed_property_type" not in result.risk_flags


def test_low_count_and_missing_microzone_are_flagged() -> None:
    target = make_property(raw_metadata={})
    listings = [make_listing(fingerprint=f"c{i}") for i in range(5)]

    result = assess_comparable_quality(target=target, scored_comparables=_scored(listings))

    assert result.level in {"weak", "poor"}
    assert "low_comparable_count" in result.risk_flags
    assert "weak_microzone" in result.risk_flags


def test_mixed_property_type_is_flagged() -> None:
    target = make_property(property_type="apartment")
    listings = [
        make_listing(fingerprint=f"a{i}", property_type="apartment")
        for i in range(8)
    ] + [
        make_listing(fingerprint="h1", property_type="house", built_area_m2=75, land_area_m2=200)
    ]

    result = assess_comparable_quality(target=target, scored_comparables=_scored(listings))

    assert "mixed_property_type" in result.risk_flags
    assert result.metrics["property_type_consistency"] < 1.0


def test_high_price_m2_dispersion_and_outlier_pressure_are_reported() -> None:
    target = make_property()
    prices = [
        110_000_000,
        115_000_000,
        118_000_000,
        400_000_000,
        420_000_000,
        450_000_000,
        500_000_000,
        550_000_000,
    ]
    listings = [
        make_listing(fingerprint=f"c{i}", price_clp=price, m2=60, built_area_m2=60)
        for i, price in enumerate(prices)
    ]

    result = assess_comparable_quality(target=target, scored_comparables=_scored(listings))

    assert "high_dispersion" in result.risk_flags
    assert result.metrics["price_per_m2_dispersion"] >= 60
    assert result.metrics["outlier_pressure"] >= 0


def test_weak_geolocation_and_sparse_m2_bucket_are_flagged() -> None:
    target = make_property(m2=75, built_area_m2=75)
    listings = [
        make_listing(
            fingerprint=f"c{i}",
            m2=120,
            built_area_m2=120,
            coords=None,
            geocode_precision="comuna",
        )
        for i in range(10)
    ]

    result = assess_comparable_quality(target=target, scored_comparables=_scored(listings))

    assert "weak_geolocation" in result.risk_flags
    assert "sparse_m2_bucket" in result.risk_flags
    assert result.metrics["address_level_geo_ratio"] == 0.0
    assert result.metrics["m2_bucket_coverage"] == 0.0
