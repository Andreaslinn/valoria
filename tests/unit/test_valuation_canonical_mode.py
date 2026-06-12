from __future__ import annotations

from decimal import Decimal

import pytest

from core.exceptions import InsufficientDataError
from domain.valuation.comparables import valuate

from tests.unit.factories import make_listing, make_property

UF = Decimal("37000")


def test_default_keeps_legacy_clp_price_basis() -> None:
    target = make_property(m2=75.0)
    candidates = [
        make_listing(
            fingerprint=f"uf{i}",
            price_clp=200_000_000,
            price_currency="UF",
            price_uf=Decimal("4000"),
            price_uf_source="scraped",
            price_uf_confidence="high",
        )
        for i in range(5)
    ]

    result = valuate(target, candidates, UF)

    assert result.estimated_price.clp.quantize(Decimal("1")) == Decimal("200000000")
    assert result.reliability_metrics["canonical_price_enabled"] is False


def test_canonical_mode_uses_uf_not_historical_clp_snapshot() -> None:
    target = make_property(m2=75.0)
    candidates = [
        make_listing(
            fingerprint=f"uf{i}",
            price_clp=200_000_000,
            price_currency="UF",
            price_uf=Decimal("4000"),
            price_uf_source="scraped",
            price_uf_confidence="high",
        )
        for i in range(5)
    ]

    result = valuate(target, candidates, UF, canonical_price_enabled=True)

    assert result.estimated_price.clp == Decimal("148000000.0000")
    assert result.comparables_used == 5
    assert result.reliability_metrics["canonical_price_enabled"] is True
    assert result.reliability_metrics["canonical_price_coverage"] == 1.0


def test_canonical_mode_can_be_enabled_by_environment_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VALUATION_CANONICAL_PRICE_ENABLED", "true")
    target = make_property(m2=75.0)
    candidates = [
        make_listing(
            fingerprint=f"uf{i}",
            price_clp=200_000_000,
            price_currency="UF",
            price_uf=Decimal("4000"),
            price_uf_source="scraped",
            price_uf_confidence="high",
        )
        for i in range(5)
    ]

    result = valuate(target, candidates, UF)

    assert result.estimated_price.clp == Decimal("148000000.0000")
    assert result.reliability_metrics["canonical_price_enabled"] is True
    assert result.reliability_metrics["canonical_price_mode"] == "canonical"


def test_canonical_mode_converts_clp_to_uf_for_run() -> None:
    target = make_property(m2=75.0)
    candidates = [
        make_listing(
            fingerprint=f"clp{i}",
            price_clp=37_000_000,
            price_currency="CLP",
            price_uf=None,
        )
        for i in range(5)
    ]

    result = valuate(target, candidates, UF, canonical_price_enabled=True)

    assert result.estimated_price.clp.quantize(Decimal("1")) == Decimal("37000000")
    assert result.reliability_metrics["canonical_price_enabled"] is True
    assert result.reliability_metrics["mixed_currency_share"] == 0.0


def test_canonical_mode_excludes_estimated_low_and_legacy_prices() -> None:
    target = make_property(m2=75.0)
    candidates = [
        make_listing(
            fingerprint=f"weak{i}",
            price_clp=148_000_000,
            price_currency="UF",
            price_uf=Decimal("4000"),
            price_uf_source="estimated",
            price_uf_confidence="medium",
        )
        for i in range(5)
    ]

    with pytest.raises(InsufficientDataError, match="precio canonico usable"):
        valuate(target, candidates, UF, canonical_price_enabled=True)


def test_canonical_mode_reports_price_quality_metrics() -> None:
    target = make_property(m2=75.0)
    candidates = [
        make_listing(
            fingerprint="weak",
            price_clp=148_000_000,
            price_currency="UF",
            price_uf=Decimal("4000"),
            price_uf_source="estimated",
            price_uf_confidence="medium",
        ),
        *[
            make_listing(
                fingerprint=f"uf{i}",
                price_clp=180_000_000,
                price_currency="UF",
                price_uf=Decimal("4000"),
                price_uf_source="scraped",
                price_uf_confidence="high",
            )
            for i in range(3)
        ],
        *[
            make_listing(
                fingerprint=f"clp{i}",
                price_clp=148_000_000,
                price_currency="CLP",
                price_uf=None,
            )
            for i in range(2)
        ],
    ]

    result = valuate(target, candidates, UF, canonical_price_enabled=True)

    metrics = result.reliability_metrics
    assert metrics["canonical_price_enabled"] is True
    assert metrics["selected_canonical_comparables"] == 5
    assert metrics["mixed_currency_share"] == 0.4
    assert metrics["excluded_price_quality_count"]["estimated_or_low"] >= 1


def test_segmented_flag_enables_allowlisted_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VALUATION_CANONICAL_PRICE_ENABLED", raising=False)
    monkeypatch.setenv("VALUATION_CANONICAL_PRICE_SEGMENTED", "true")
    target = make_property(comuna="vitacura", property_type="house", m2=75.0)
    candidates = [
        make_listing(
            fingerprint=f"uf{i}",
            comuna="vitacura",
            property_type="house",
            price_clp=200_000_000,
            price_currency="UF",
            price_uf=Decimal("4000"),
            price_uf_source="scraped",
            price_uf_confidence="high",
        )
        for i in range(5)
    ]

    result = valuate(target, candidates, UF)

    assert result.estimated_price.clp == Decimal("148000000.0000")
    assert result.reliability_metrics["canonical_price_enabled"] is True
    assert result.reliability_metrics["canonical_price_mode"] == "canonical"
    assert result.reliability_metrics["canonical_price_segment"] == "vitacura::house"


def test_segmented_flag_keeps_denylisted_segment_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VALUATION_CANONICAL_PRICE_ENABLED", raising=False)
    monkeypatch.setenv("VALUATION_CANONICAL_PRICE_SEGMENTED", "true")
    target = make_property(comuna="santiago", property_type="apartment", m2=75.0)
    candidates = [
        make_listing(
            fingerprint=f"uf{i}",
            comuna="santiago",
            property_type="apartment",
            price_clp=200_000_000,
            price_currency="UF",
            price_uf=Decimal("4000"),
            price_uf_source="scraped",
            price_uf_confidence="high",
        )
        for i in range(5)
    ]

    result = valuate(target, candidates, UF)

    assert result.estimated_price.clp.quantize(Decimal("1")) == Decimal("200000000")
    assert result.reliability_metrics["canonical_price_enabled"] is False
    assert result.reliability_metrics["canonical_price_mode"] == "legacy"
    assert result.reliability_metrics["canonical_price_segment"] == "santiago::apartment"


def test_segmented_flag_keeps_unlisted_segment_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VALUATION_CANONICAL_PRICE_ENABLED", raising=False)
    monkeypatch.setenv("VALUATION_CANONICAL_PRICE_SEGMENTED", "true")
    target = make_property(comuna="providencia", property_type="apartment", m2=75.0)
    candidates = [
        make_listing(
            fingerprint=f"uf{i}",
            comuna="providencia",
            property_type="apartment",
            price_clp=200_000_000,
            price_currency="UF",
            price_uf=Decimal("4000"),
            price_uf_source="scraped",
            price_uf_confidence="high",
        )
        for i in range(5)
    ]

    result = valuate(target, candidates, UF)

    assert result.estimated_price.clp.quantize(Decimal("1")) == Decimal("200000000")
    assert result.reliability_metrics["canonical_price_enabled"] is False
    assert result.reliability_metrics["canonical_price_segment"] == "providencia::apartment"
