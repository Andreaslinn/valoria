"""Tests unitarios del motor de tasación."""
from __future__ import annotations

from decimal import Decimal

import pytest

from core.exceptions import InsufficientDataError, ValidationError
from core.value_objects.location import Coordinates
from domain.valuation.comparables import (
    _too_far,
    candidate_discard_reason,
    filter_candidates,
    valuate,
    valuate_with_comparables,
)
from tests.unit.factories import make_listing, make_property

UF = Decimal("37000")


def _make_uniform_candidates(n: int, *, price_clp: int = 180_000_000) -> list:
    """n comparables idénticos al target base (75 m², 3D/2B/1P, Ñuñoa)."""
    return [
        make_listing(fingerprint=f"c{i}", price_clp=price_clp)
        for i in range(n)
    ]


class TestValidation:
    def test_rejects_zero_m2_target(self):
        target = make_property(m2=0)
        with pytest.raises(ValidationError):
            valuate(target, _make_uniform_candidates(5), UF)

    def test_rejects_missing_m2_target_without_type_error(self):
        target = make_property(m2=None, built_area_m2=None, usable_area_m2=None)
        with pytest.raises(ValidationError):
            valuate(target, _make_uniform_candidates(5), UF)

    def test_rejects_empty_comuna(self):
        target = make_property(comuna="")
        with pytest.raises(ValidationError):
            valuate(target, _make_uniform_candidates(5), UF)


class TestInsufficientData:
    def test_raises_with_zero_candidates(self):
        target = make_property()
        with pytest.raises(InsufficientDataError):
            valuate(target, [], UF)

    def test_raises_with_fewer_than_min(self):
        target = make_property()
        with pytest.raises(InsufficientDataError):
            valuate(target, _make_uniform_candidates(4), UF)

    def test_passes_with_exactly_min_comparables(self):
        target = make_property()
        result = valuate(target, _make_uniform_candidates(5), UF)
        assert result.comparables_used == 5

    def test_valuation_run_exposes_same_scored_comparables_used_by_result(self):
        target = make_property()
        run = valuate_with_comparables(target, _make_uniform_candidates(7), UF)

        assert run.result.comparables_used == len(run.scored_comparables)
        assert run.scored_comparables
        assert run.result.comparable_quality_level in {"poor", "weak", "acceptable", "strong"}
        assert run.result.comparable_quality_metrics["n_comparables"] == len(run.scored_comparables)
        assert run.result.beta_scope_status in {
            "no_data",
            "weak_data",
            "exploratory",
            "beta_supported",
            "strong_sample",
        }
        assert run.result.beta_scope_metrics["n_comparables"] == len(run.scored_comparables)


class TestFiltering:
    def test_listing_is_active_only_for_active_status(self):
        assert make_listing(status="active").is_active is True
        assert make_listing(status="removed").is_active is False

    def test_ignores_other_comunas(self):
        target = make_property(comuna="nunoa")
        candidates = [
            make_listing(fingerprint=f"n{i}", comuna="nunoa") for i in range(5)
        ] + [
            make_listing(fingerprint=f"p{i}", comuna="providencia") for i in range(5)
        ]
        result = valuate(target, candidates, UF)
        assert result.comparables_used == 5

    def test_house_does_not_compare_with_apartment(self):
        target = make_property(property_type="house", built_area_m2=140, land_area_m2=300, m2=140)
        candidates = [make_listing(fingerprint=f"a{i}", property_type="apartment", m2=140) for i in range(5)]
        with pytest.raises(InsufficientDataError):
            valuate(target, candidates, UF)
        assert candidate_discard_reason(target, candidates[0]) == "property_type_mismatch"

    def test_apartment_does_not_compare_with_house(self):
        target = make_property(property_type="apartment", m2=75)
        candidates = [
            make_listing(fingerprint=f"h{i}", property_type="house", m2=75, built_area_m2=75, land_area_m2=300)
            for i in range(5)
        ]
        with pytest.raises(InsufficientDataError):
            valuate(target, candidates, UF)
        assert candidate_discard_reason(target, candidates[0]) == "property_type_mismatch"

    def test_unknown_does_not_compare_with_apartment(self):
        target = make_property(property_type="unknown", m2=75)
        candidates = [make_listing(fingerprint=f"a{i}", property_type="apartment", m2=75) for i in range(5)]
        assert filter_candidates(target, candidates) == []
        assert candidate_discard_reason(target, candidates[0]) == "property_type_mismatch"

    def test_unknown_can_only_compare_with_unknown_and_has_lower_confidence(self):
        unknown_target = make_property(property_type="unknown", m2=75)
        unknown_candidates = [
            make_listing(fingerprint=f"u{i}", property_type="unknown", m2=75)
            for i in range(5)
        ]
        apartment_target = make_property(property_type="apartment", m2=75)
        apartment_candidates = [
            make_listing(fingerprint=f"a{i}", property_type="apartment", m2=75)
            for i in range(5)
        ]

        unknown_result = valuate(unknown_target, unknown_candidates, UF)
        apartment_result = valuate(apartment_target, apartment_candidates, UF)

        assert unknown_result.comparables_used == 5
        assert unknown_result.confidence.value < apartment_result.confidence.value

    def test_ignores_non_active_listings(self):
        target = make_property()
        candidates = [
            *_make_uniform_candidates(5),
            make_listing(fingerprint="sold", status="sold"),
            make_listing(fingerprint="removed", status="removed"),
        ]
        result = valuate(target, candidates, UF)
        assert result.comparables_used == 5

    def test_excludes_outside_m2_tolerance(self):
        target = make_property(m2=100.0)
        candidates = (
            [make_listing(fingerprint=f"ok{i}", m2=100.0) for i in range(5)]
            + [make_listing(fingerprint="small", m2=60.0)]  # fuera del -30 %
            + [make_listing(fingerprint="big", m2=140.0)]   # fuera del +30 %
        )
        result = valuate(target, candidates, UF)
        assert result.comparables_used == 5

    def test_filter_candidates_helper_standalone(self):
        target = make_property(m2=100)
        eligible = filter_candidates(
            target,
            [
                make_listing(fingerprint="ok", m2=100),
                make_listing(fingerprint="too_small", m2=50),
                make_listing(fingerprint="sold", m2=100, status="sold"),
                make_listing(fingerprint="removed", m2=100, status="removed"),
            ],
        )
        assert len(eligible) == 1
        assert eligible[0].fingerprint == "ok"

    def test_excludes_far_away_listings_when_coords_available(self):
        here = Coordinates(-33.45, -70.59)
        far = Coordinates(-33.65, -70.79)  # >15 km
        target = make_property(coords=here)
        candidates = (
            [make_listing(fingerprint=f"near{i}", coords=here) for i in range(5)]
            + [make_listing(fingerprint="far", coords=far)]
        )
        result = valuate(target, candidates, UF)
        assert result.comparables_used == 5

    def test_too_far_does_not_exclude_comuna_centroid(self):
        here = Coordinates(-33.45, -70.59)
        far = Coordinates(-33.65, -70.79)
        target = make_property(coords=here)
        centroid_candidate = make_listing(
            fingerprint="centroid",
            coords=far,
            geocode_precision="comuna_centroid",
        )
        precise_candidate = make_listing(
            fingerprint="precise",
            coords=far,
            geocode_precision="street_address",
        )

        assert _too_far(target, centroid_candidate) is False
        assert _too_far(target, precise_candidate) is True


class TestPriceEstimate:
    def test_uniform_candidates_give_exact_market_price(self):
        """Con 5 candidatos idénticos a 180M y m²=75, ppm²=2.4M, target=75m² → 180M."""
        target = make_property(m2=75.0)
        result = valuate(target, _make_uniform_candidates(5, price_clp=180_000_000), UF)
        assert result.estimated_price.clp == Decimal("180000000")

    def test_price_scales_linearly_with_target_m2(self):
        """Si el target es más grande, el precio estimado escala con los m²."""
        candidates = _make_uniform_candidates(5, price_clp=180_000_000)  # ppm² = 2.4M
        big_target = make_property(m2=90.0)  # +20 %
        result = valuate(big_target, candidates, UF)
        assert result.estimated_price.clp == Decimal("216000000")  # 2.4M x 90

    def test_more_expensive_comparables_raise_estimate(self):
        target = make_property()
        cheap = valuate(target, _make_uniform_candidates(5, price_clp=150_000_000), UF)
        expensive = valuate(
            target, _make_uniform_candidates(5, price_clp=250_000_000), UF
        )
        assert expensive.estimated_price.clp > cheap.estimated_price.clp


class TestRangeAndConfidence:
    def test_uniform_prices_give_zero_range(self):
        target = make_property()
        result = valuate(target, _make_uniform_candidates(5, price_clp=180_000_000), UF)
        assert result.price_range_low.clp == result.estimated_price.clp
        assert result.price_range_high.clp == result.estimated_price.clp

    def test_varied_prices_give_positive_range(self):
        target = make_property()
        varied = [
            make_listing(fingerprint=f"v{i}", price_clp=p)
            for i, p in enumerate([150_000_000, 170_000_000, 180_000_000,
                                   190_000_000, 220_000_000])
        ]
        result = valuate(target, varied, UF)
        assert result.price_range_low.clp < result.estimated_price.clp
        assert result.price_range_high.clp > result.estimated_price.clp

    def test_confidence_in_unit_interval(self):
        target = make_property()
        result = valuate(target, _make_uniform_candidates(5), UF)
        assert 0.0 <= result.confidence.value <= 1.0

    def test_more_comparables_give_higher_confidence(self):
        target = make_property()
        few = valuate(target, _make_uniform_candidates(5), UF)
        many = valuate(target, _make_uniform_candidates(20), UF)
        assert many.confidence.value > few.confidence.value

    def test_uf_rate_is_passed_through(self):
        target = make_property()
        result = valuate(target, _make_uniform_candidates(5), UF)
        assert result.uf_to_clp_rate == UF


class TestTopNCap:
    def test_caps_comparables_used_at_top_n(self):
        target = make_property()
        # 30 candidatos pero TOP_N_COMPARABLES=20
        result = valuate(target, _make_uniform_candidates(30), UF)
        assert result.comparables_used == 20
