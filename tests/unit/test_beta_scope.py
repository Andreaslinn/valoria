from __future__ import annotations

from domain.valuation.beta_scope import assess_beta_scope
from domain.valuation.comparable_quality import ComparableQuality
from tests.unit.factories import make_listing, make_property


def _quality(level: str, *, n: int = 12, dispersion: float = 25.0, address_ratio: float = 0.1) -> ComparableQuality:
    return ComparableQuality(
        level=level,
        risk_flags=(),
        metrics={
            "n_comparables": n,
            "price_per_m2_dispersion": dispersion,
            "address_level_geo_ratio": address_ratio,
            "property_type_consistency": 1.0,
        },
    )


def test_no_data_when_segment_has_no_candidates() -> None:
    result = assess_beta_scope(
        target=make_property(comuna="nunoa", property_type="apartment"),
        candidate_pool=[],
        comparable_quality=_quality("poor", n=0),
    )

    assert result.status == "no_data"
    assert "no_segment_sample" in result.flags


def test_weak_data_when_segment_sample_is_too_small() -> None:
    candidates = [
        make_listing(fingerprint=f"c{i}", property_type="apartment", m2=75)
        for i in range(6)
    ]

    result = assess_beta_scope(
        target=make_property(property_type="apartment", m2=75),
        candidate_pool=candidates,
        comparable_quality=_quality("acceptable", n=6),
    )

    assert result.status == "weak_data"
    assert "low_segment_sample" in result.flags


def test_exploratory_for_reasonable_sample_but_weak_quality() -> None:
    candidates = [
        make_listing(fingerprint=f"c{i}", property_type="apartment", m2=75)
        for i in range(35)
    ]

    result = assess_beta_scope(
        target=make_property(property_type="apartment", m2=75),
        candidate_pool=candidates,
        comparable_quality=_quality("weak", n=12, dispersion=30),
    )

    assert result.status == "exploratory"
    assert "weak_comparable_quality" in result.flags


def test_beta_supported_for_reasonable_segment_without_strong_geocode() -> None:
    candidates = [
        make_listing(fingerprint=f"c{i}", property_type="apartment", m2=75)
        for i in range(40)
    ]

    result = assess_beta_scope(
        target=make_property(property_type="apartment", m2=75),
        candidate_pool=candidates,
        comparable_quality=_quality("acceptable", n=12, dispersion=30, address_ratio=0.0),
    )

    assert result.status == "beta_supported"
    assert "weak_geocode_quality" in result.flags


def test_strong_sample_requires_density_quality_and_some_geocode() -> None:
    candidates = [
        make_listing(fingerprint=f"c{i}", property_type="apartment", m2=75)
        for i in range(90)
    ]

    result = assess_beta_scope(
        target=make_property(property_type="apartment", m2=75),
        candidate_pool=candidates,
        comparable_quality=_quality("strong", n=20, dispersion=20, address_ratio=0.08),
    )

    assert result.status == "strong_sample"
    assert result.metrics["segment_sample_count"] == 90
    assert result.metrics["m2_bucket_sample_count"] == 90


def test_scope_does_not_count_other_property_types() -> None:
    candidates = [
        make_listing(fingerprint=f"h{i}", property_type="house", m2=75, built_area_m2=75, land_area_m2=300)
        for i in range(50)
    ]

    result = assess_beta_scope(
        target=make_property(property_type="apartment", m2=75),
        candidate_pool=candidates,
        comparable_quality=_quality("acceptable", n=0),
    )

    assert result.status == "no_data"
    assert result.metrics["segment_sample_count"] == 0
