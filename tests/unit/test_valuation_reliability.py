from decimal import Decimal

from core.value_objects.score import Score
from domain.valuation.comparables import valuate_with_comparables
from domain.valuation.reliability import assess_comparable_reliability
from tests.unit.factories import make_listing, make_property

UF = Decimal("37000")


def test_reliability_warns_and_downgrades_single_source_poor_geocoding() -> None:
    target = make_property(geocode_precision="comuna", coords=None)
    comparables = [
        make_listing(fingerprint=f"weak-{idx}", geocode_precision="comuna", coords=None, source="yapo")
        for idx in range(10)
    ]

    run = valuate_with_comparables(target, comparables, UF)

    assert "single_source_comparables" in run.result.reliability_warnings
    assert "poor_geocoding_comparables" in run.result.reliability_warnings
    assert run.result.base_confidence is not None
    assert run.result.confidence.value < run.result.base_confidence.value


def test_reliability_flags_high_price_m2_dispersion() -> None:
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
    comparables = [
        make_listing(fingerprint=f"spread-{idx}", m2=75, built_area_m2=75, price_clp=price, source=f"src-{idx % 2}")
        for idx, price in enumerate(prices)
    ]

    run = valuate_with_comparables(target, comparables, UF)

    assert any(
        warning in run.result.reliability_warnings
        for warning in {"high_price_m2_dispersion", "extreme_price_m2_dispersion"}
    )
    assert run.result.reliability_metrics["price_m2_iqr_pct"] is not None


def test_reliability_flags_near_duplicate_comparables() -> None:
    target = make_property()
    comparables = [
        make_listing(fingerprint=f"dup-{idx}", title="Departamento igual en Nunoa", price_clp=180_000_000)
        for idx in range(5)
    ] + [
        make_listing(fingerprint=f"unique-{idx}", title=f"Departamento unico {idx}", price_clp=180_000_000)
        for idx in range(5)
    ]

    run = valuate_with_comparables(target, comparables, UF)

    assert "near_duplicate_comparables" in run.result.reliability_warnings
    assert run.result.reliability_metrics["near_duplicate_share"] > 0


def test_reliability_does_not_penalize_diverse_precise_comparables() -> None:
    target = make_property(geocode_precision="address")
    comparables = [
        make_listing(
            fingerprint=f"strong-{idx}",
            source=f"source-{idx % 2}",
            geocode_precision="address",
            price_clp=180_000_000 + idx * 250_000,
        )
        for idx in range(10)
    ]

    run = valuate_with_comparables(target, comparables, UF)

    assert run.result.reliability_warnings == []
    assert run.result.base_confidence is not None
    assert run.result.confidence.value == run.result.base_confidence.value


def test_house_without_land_area_gets_reliability_warning() -> None:
    target = make_property(property_type="house", m2=140, built_area_m2=140, land_area_m2=400)
    comparables = [
        make_listing(
            fingerprint=f"house-no-land-{idx}",
            property_type="house",
            m2=140,
            built_area_m2=140,
            land_area_m2=None,
            source=f"source-{idx % 2}",
        )
        for idx in range(10)
    ]

    run = valuate_with_comparables(target, comparables, UF)

    assert "house_land_area_weak" in run.result.reliability_warnings


def test_reliability_helper_reports_metrics() -> None:
    target = make_property()
    comparables = [(Score.clamped(0.8), make_listing(fingerprint=f"m-{idx}")) for idx in range(5)]

    reliability = assess_comparable_reliability(
        target=target,
        scored_comparables=comparables,
        base_confidence=Score.clamped(0.8),
    )

    assert reliability.metrics["comparable_count"] == 5
    assert "low_comparable_count" in reliability.warnings
