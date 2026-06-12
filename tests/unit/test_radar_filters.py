"""Tests unitarios de los filtros de calidad del radar."""
from __future__ import annotations

from decimal import Decimal

import pytest

from core.entities.opportunity import Opportunity
from core.value_objects.price import Price
from core.value_objects.score import Score
from domain.radar.filters import apply_quality_filters, top_n
from tests.unit.factories import make_listing


def _make_opp(
    *,
    fingerprint: str = "fp",
    discount: float = 0.10,
    confidence: float = 0.80,
    comparables: int = 10,
    market_price: int = 200_000_000,
) -> Opportunity:
    return Opportunity(
        listing=make_listing(fingerprint=fingerprint),
        market_price=Price(clp=Decimal(market_price)),
        discount_pct=discount,
        confidence=Score(confidence),
        comparables_used=comparables,
    )


class TestApplyQualityFilters:
    def test_keeps_all_when_defaults_satisfied(self):
        opps = [_make_opp(fingerprint="a"), _make_opp(fingerprint="b")]
        result = apply_quality_filters(opps)
        assert len(result) == 2

    def test_filters_out_low_confidence(self):
        low = _make_opp(fingerprint="low", confidence=0.30)
        high = _make_opp(fingerprint="high", confidence=0.90)
        result = apply_quality_filters([low, high])
        fingerprints = {o.listing.fingerprint for o in result}
        assert fingerprints == {"high"}

    def test_filters_out_insufficient_comparables(self):
        thin = _make_opp(fingerprint="thin", comparables=3)
        rich = _make_opp(fingerprint="rich", comparables=15)
        result = apply_quality_filters([thin, rich])
        assert [o.listing.fingerprint for o in result] == ["rich"]

    def test_custom_min_confidence(self):
        mid = _make_opp(fingerprint="mid", confidence=0.60)
        # Default 0.5 lo deja pasar; threshold 0.7 lo filtra
        assert len(apply_quality_filters([mid])) == 1
        assert len(apply_quality_filters([mid], min_confidence=0.7)) == 0

    def test_min_discount_optional(self):
        small = _make_opp(fingerprint="small", discount=0.06)
        big = _make_opp(fingerprint="big", discount=0.25)
        # Sin min_discount ambas pasan
        assert len(apply_quality_filters([small, big])) == 2
        # Con min_discount=0.10 solo la grande
        filtered = apply_quality_filters([small, big], min_discount=0.10)
        assert [o.listing.fingerprint for o in filtered] == ["big"]

    def test_preserves_input_order(self):
        """El orden del input se mantiene — el sorting es responsabilidad del detector."""
        opps = [
            _make_opp(fingerprint=f"fp{i}", discount=0.10 + i * 0.02)
            for i in range(5)
        ]
        result = apply_quality_filters(opps)
        assert [o.listing.fingerprint for o in result] == [f"fp{i}" for i in range(5)]

    def test_empty_input_returns_empty(self):
        assert apply_quality_filters([]) == []


class TestValidation:
    def test_rejects_invalid_min_confidence(self):
        with pytest.raises(ValueError):
            apply_quality_filters([], min_confidence=-0.1)
        with pytest.raises(ValueError):
            apply_quality_filters([], min_confidence=1.5)

    def test_rejects_negative_min_comparables(self):
        with pytest.raises(ValueError):
            apply_quality_filters([], min_comparables=-1)

    def test_rejects_invalid_min_discount(self):
        with pytest.raises(ValueError):
            apply_quality_filters([], min_discount=1.5)


class TestTopN:
    def test_returns_first_n(self):
        opps = [_make_opp(fingerprint=f"fp{i}") for i in range(10)]
        result = top_n(opps, 3)
        assert len(result) == 3
        assert [o.listing.fingerprint for o in result] == ["fp0", "fp1", "fp2"]

    def test_n_greater_than_list_returns_all(self):
        opps = [_make_opp(fingerprint="a"), _make_opp(fingerprint="b")]
        assert len(top_n(opps, 10)) == 2

    def test_n_zero_returns_empty(self):
        opps = [_make_opp(fingerprint="a")]
        assert top_n(opps, 0) == []

    def test_negative_n_raises(self):
        with pytest.raises(ValueError):
            top_n([], -1)
