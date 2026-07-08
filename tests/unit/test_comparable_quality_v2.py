from __future__ import annotations

from decimal import Decimal

from domain.valuation.comparable_quality_v2 import (
    QualityThresholds,
    comparable_quality_flags,
    filter_by_quality,
    safe_price_m2_uf,
    trimmed_mean_estimator,
    winsorized_mean_estimator,
)
from tests.unit.factories import make_listing, make_property

UF_RATE = Decimal("40000")


def test_safe_price_m2_uf_uses_native_uf_when_available() -> None:
    listing = make_listing(m2=50, built_area_m2=50, price_clp=200_000_000, price_uf=4_000)

    assert safe_price_m2_uf(listing, UF_RATE) == 80


def test_safe_price_m2_uf_converts_clp_and_ignores_zero_area() -> None:
    listing = make_listing(m2=0, built_area_m2=0, usable_area_m2=0, price_clp=200_000_000)

    assert safe_price_m2_uf(listing, UF_RATE) is None


def test_low_outlier_flags_against_subject_and_references() -> None:
    subject = make_property(m2=50, built_area_m2=50)
    comparable = make_listing(m2=50, built_area_m2=50, price_clp=80_000_000)

    result = comparable_quality_flags(
        comparable,
        subject=subject,
        subject_price_m2_uf=100,
        comuna_median_price_m2_uf=100,
        pool_median_price_m2_uf=100,
        uf_rate=UF_RATE,
    )

    assert "price_m2_too_low_vs_subject" in result.flags
    assert "price_m2_too_low_vs_comuna_median" in result.flags
    assert "economic_outlier" in result.flags


def test_high_outlier_flags_against_subject_and_references() -> None:
    subject = make_property(m2=50, built_area_m2=50)
    comparable = make_listing(m2=50, built_area_m2=50, price_clp=400_000_000)

    result = comparable_quality_flags(
        comparable,
        subject=subject,
        subject_price_m2_uf=100,
        comuna_median_price_m2_uf=100,
        pool_median_price_m2_uf=100,
        uf_rate=UF_RATE,
    )

    assert "price_m2_too_high_vs_subject" in result.flags
    assert "price_m2_too_high_vs_pool_median" in result.flags
    assert result.strict_economic_outlier is True


def test_winsorized_estimator_caps_extremes() -> None:
    values = [100, 101, 102, 103, 104, 105, 106, 107, 108, 400]

    result = winsorized_mean_estimator(values, winsor_ratio=0.10)

    assert result is not None
    assert result < sum(values) / len(values)


def test_trimmed_estimator_removes_tails() -> None:
    values = [10, 100, 101, 102, 103, 104, 105, 500]

    result = trimmed_mean_estimator(values, trim_ratio=0.125)

    assert result == 102.5


def test_mild_filter_keeps_enough_comparables() -> None:
    listings = [make_listing(fingerprint=f"c{i}") for i in range(6)]
    flags = {
        "c0": comparable_quality_flags(
            listings[0],
            uf_rate=UF_RATE,
            subject_price_m2_uf=100,
            comuna_median_price_m2_uf=100,
            pool_median_price_m2_uf=100,
            thresholds=QualityThresholds(strict_reference_low_ratio=0.1, strict_reference_high_ratio=10),
        )
    }

    result = filter_by_quality(
        [(0.8, listing) for listing in listings],
        flags,
        mode="mild",
        key_fn=lambda item: item.fingerprint,
        min_comparables=5,
    )

    assert len(result) == 6


def test_missing_surface_or_price_is_ignored_without_crashing() -> None:
    listing = make_listing(m2=0, built_area_m2=0, usable_area_m2=0, price_clp=0)

    result = comparable_quality_flags(
        listing,
        uf_rate=UF_RATE,
        subject_price_m2_uf=100,
        comuna_median_price_m2_uf=100,
        pool_median_price_m2_uf=100,
    )

    assert "missing_or_invalid_price_m2" in result.flags
    assert result.price_m2_uf is None
