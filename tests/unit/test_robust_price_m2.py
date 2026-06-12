from __future__ import annotations

from domain.valuation.product_classification import classify_product
from domain.valuation.robust_price_m2 import RobustFilterConfig, robust_filter_listings
from tests.unit.factories import make_listing, make_property


def _classes(listings):
    return {f"fp:{listing.fingerprint}": classify_product(listing) for listing in listings}


def test_robust_filter_keeps_homogeneous_sample() -> None:
    target = make_property(property_type="house", m2=100, built_area_m2=100)
    listings = [
        make_listing(fingerprint=f"h-{idx}", property_type="house", m2=100, built_area_m2=100, price_clp=200_000_000 + idx)
        for idx in range(8)
    ]

    result = robust_filter_listings(
        target=target,
        listings=listings,
        product_classes=_classes(listings),
        min_comparables=5,
        config=RobustFilterConfig(),
    )

    assert len(result.kept) == 8
    assert result.high_outliers == ()
    assert result.low_outliers == ()


def test_robust_filter_excludes_high_outlier_without_target_price() -> None:
    target = make_property(property_type="house", m2=100, built_area_m2=100)
    normal = [
        make_listing(fingerprint=f"h-{idx}", property_type="house", m2=100, built_area_m2=100, price_clp=200_000_000)
        for idx in range(8)
    ]
    outlier = make_listing(fingerprint="high", property_type="house", m2=100, built_area_m2=100, price_clp=600_000_000)

    result = robust_filter_listings(
        target=target,
        listings=[*normal, outlier],
        product_classes=_classes([*normal, outlier]),
        min_comparables=5,
        config=RobustFilterConfig(),
    )

    assert outlier in result.high_outliers
    assert outlier not in result.kept
    assert result.reference.method in {"percentile_house_high_tail", "iqr_house_high_tail"}


def test_robust_filter_does_not_filter_small_sample() -> None:
    target = make_property(property_type="house", m2=100, built_area_m2=100)
    listings = [
        make_listing(fingerprint=f"h-{idx}", property_type="house", m2=100, built_area_m2=100, price_clp=price)
        for idx, price in enumerate([100_000_000, 200_000_000, 700_000_000, 210_000_000])
    ]

    result = robust_filter_listings(
        target=target,
        listings=listings,
        product_classes=_classes(listings),
        min_comparables=5,
        config=RobustFilterConfig(),
    )

    assert len(result.kept) == 4
    assert result.reference.method == "sample_too_small"
