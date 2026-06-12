from core.value_objects.score import Score
from domain.valuation.comparable_metrics import (
    address_geocode_share,
    address_level_geo_ratio,
)
from domain.valuation.comparable_quality import assess_comparable_quality
from domain.valuation.reliability import assess_comparable_reliability
from tests.unit.factories import make_listing, make_property


def _scored(listings, score: float = 0.82):
    return [(Score.clamped(score), listing) for listing in listings]


def test_address_metrics_keep_quality_and_reliability_semantics_separate() -> None:
    target = make_property(geocode_precision="address")
    listings = [
        make_listing(fingerprint="addr-1", geocode_precision="address"),
        make_listing(fingerprint="addr-2", geocode_precision="address"),
        make_listing(fingerprint="addr-3", geocode_precision="address"),
        make_listing(fingerprint="comuna-1", geocode_precision="comuna"),
    ]

    assert address_level_geo_ratio(listings) == 0.75
    assert address_geocode_share(target, listings) == 0.8


def test_quality_and_reliability_share_dispersion_metric_but_not_signal_names() -> None:
    target = make_property(m2=75, built_area_m2=75)
    prices = [
        80_000_000,
        90_000_000,
        100_000_000,
        300_000_000,
        340_000_000,
        380_000_000,
        410_000_000,
        450_000_000,
    ]
    listings = [
        make_listing(
            fingerprint=f"shared-dispersion-{idx}",
            m2=75,
            built_area_m2=75,
            price_clp=price,
            source=f"src-{idx % 2}",
        )
        for idx, price in enumerate(prices)
    ]

    quality = assess_comparable_quality(target=target, scored_comparables=_scored(listings))
    reliability = assess_comparable_reliability(
        target=target,
        scored_comparables=_scored(listings),
        base_confidence=Score.clamped(0.9),
    )

    assert abs(quality.metrics["price_per_m2_dispersion"] - reliability.metrics["price_m2_iqr_pct"]) <= 0.01
    assert "high_dispersion" in quality.risk_flags
    assert any(
        warning in reliability.warnings
        for warning in {"high_price_m2_dispersion", "extreme_price_m2_dispersion"}
    )
