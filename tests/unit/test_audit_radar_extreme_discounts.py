"""Unit tests for Radar extreme discount audit helpers."""
from __future__ import annotations

from dataclasses import replace

from scripts.audit_radar_extreme_discounts import (
    comparable_bucket,
    radar_quality_flags,
    root_causes_for,
)
from scripts.audit_radar_funnel import AuditRow, EvaluatedRow
from tests.unit.factories import make_listing


def test_comparable_bucket_boundaries() -> None:
    assert comparable_bucket(None) == "missing"
    assert comparable_bucket(4) == "<5"
    assert comparable_bucket(5) == "5-9"
    assert comparable_bucket(10) == "10-14"
    assert comparable_bucket(15) == "15-19"
    assert comparable_bucket(20) == ">=20"


def test_radar_quality_flags_marks_weak_extreme_inputs() -> None:
    row = _row(
        confidence=0.3,
        comparable_count=6,
        geocode_precision="comuna",
        warning_codes="single_source_comparables;high_dispersion",
        land_area_m2=None,
        property_type="house",
    )

    flags = radar_quality_flags(row).split(";")

    assert "low_confidence" in flags
    assert "low_comparable_count" in flags
    assert "weak_geocoding" in flags
    assert "house_missing_land_area" in flags


def test_root_causes_flags_legacy_like_avm_risk() -> None:
    row = _row(
        discount_pct=62,
        confidence=0.32,
        geocode_precision="unknown",
        warning_codes="single_source_comparables;high_dispersion",
        price_data_quality="legacy_unrecoverable",
    )

    causes = root_causes_for(row, [])

    assert "likely_avm_overvaluation" in causes
    assert "wrong_comparables" in causes
    assert "price_parse_or_currency_issue" in causes
    assert "weak_geocoding" in causes


def _row(
    *,
    discount_pct: float = 55,
    confidence: float = 0.5,
    comparable_count: int = 20,
    geocode_precision: str = "street",
    warning_codes: str = "",
    price_data_quality: str = "canonical_clp",
    land_area_m2: float | None = 120,
    property_type: str = "apartment",
) -> EvaluatedRow:
    listing = make_listing(fingerprint="extreme-test", property_type=property_type)
    listing.land_area_m2 = land_area_m2
    audit = AuditRow(
        listing_id=1,
        title="Extreme test listing",
        comuna="maipu",
        property_type=property_type,
        source="yapo",
        listing_price_uf=1000,
        listing_price_clp=40_000_000,
        estimated_value_uf=2200,
        estimated_value_clp=88_000_000,
        discount_pct=discount_pct,
        opportunity_score=discount_pct / 100 * confidence,
        confidence=confidence,
        confidence_label="medium",
        engine_used="legacy",
        comparable_count=comparable_count,
        dispersion=70,
        geocode_precision=geocode_precision,
        price_currency="CLP",
        price_uf_source="scraped",
        price_data_quality=price_data_quality,
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
