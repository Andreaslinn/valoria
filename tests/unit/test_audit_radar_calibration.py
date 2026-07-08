"""Unit tests for read-only Radar calibration audit helpers."""
from __future__ import annotations

from dataclasses import replace

from scripts.audit_radar_calibration import (
    SCENARIOS,
    conceptual_category,
    passes_scenario,
    suspected_avm_risk_reasons,
)
from scripts.audit_radar_funnel import AuditRow, EvaluatedRow
from tests.unit.factories import make_listing


def test_conservative_v1_rejects_unknown_geocode() -> None:
    row = _row(discount_pct=12, confidence=0.5, geocode_precision="unknown")

    assert not passes_scenario(row, SCENARIOS[1])


def test_high_conviction_passes_strong_row() -> None:
    row = _row(discount_pct=25, confidence=0.6, geocode_precision="street", dispersion=30)

    assert passes_scenario(row, SCENARIOS[3])
    assert conceptual_category(row) == "high_conviction_opportunity"


def test_house_safe_rejects_house_without_land_area() -> None:
    row = _row(
        property_type="house",
        discount_pct=25,
        confidence=0.6,
        geocode_precision="street",
        dispersion=30,
        land_area_m2=None,
    )

    assert not passes_scenario(row, SCENARIOS[4])


def test_suspected_avm_risk_flags_high_discount_weak_inputs() -> None:
    row = _row(
        property_type="house",
        discount_pct=35,
        confidence=0.3,
        geocode_precision="comuna",
        comparable_count=6,
        dispersion=80,
        warning_codes="single_source_comparables;house_land_area_weak",
        land_area_m2=None,
    )

    reasons = suspected_avm_risk_reasons(row)

    assert "high_discount_low_comparables" in reasons
    assert "high_discount_weak_geocoding" in reasons
    assert "high_discount_high_dispersion" in reasons


def _row(
    *,
    property_type: str = "apartment",
    discount_pct: float = 10,
    confidence: float = 0.5,
    comparable_count: int = 10,
    geocode_precision: str = "street",
    dispersion: float | None = 20,
    warning_codes: str = "",
    land_area_m2: float | None = 120,
) -> EvaluatedRow:
    listing = make_listing(fingerprint="calibration-test", property_type=property_type)
    listing.land_area_m2 = land_area_m2
    audit = AuditRow(
        listing_id=1,
        title="Test listing",
        comuna="maipu",
        property_type=property_type,
        source="yapo",
        listing_price_uf=1000,
        listing_price_clp=40_000_000,
        estimated_value_uf=1300,
        estimated_value_clp=52_000_000,
        discount_pct=discount_pct,
        opportunity_score=discount_pct / 100 * confidence,
        confidence=confidence,
        confidence_label="medium",
        engine_used="legacy",
        comparable_count=comparable_count,
        dispersion=dispersion,
        geocode_precision=geocode_precision,
        price_currency="CLP",
        price_uf_source=None,
        price_data_quality="canonical_clp",
        price_basis_used="clp",
        warning_codes=warning_codes,
        reason_entered_radar="test",
        reason_not_rejected="test",
        top_score_components="test",
        url=None,
        valuation_status="success",
    )
    return EvaluatedRow(
        listing=listing,
        audit=replace(audit),
        opportunity=None,
        valuation_attempted=True,
        valuation_success=True,
        candidate=True,
        failure_reason=None,
    )
