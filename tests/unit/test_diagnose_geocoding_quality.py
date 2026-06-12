from __future__ import annotations

from scripts.diagnose_geocoding_quality import (
    GeoListing,
    build_report,
    classify_geocode_risk,
    coordinate_issue,
    normalize_precision,
)


def test_normalize_precision_null() -> None:
    assert normalize_precision(None) == "unknown"
    assert normalize_precision("  ") == "unknown"
    assert normalize_precision("Street_Address") == "address"


def test_coordinate_issue_detects_missing_and_ranges() -> None:
    assert coordinate_issue(None, -70.6) == "missing_coordinates"
    assert coordinate_issue(0, 0) == "zero_zero"
    assert coordinate_issue(-10, -70.6) == "outside_chile"
    assert coordinate_issue(-33.4, -80) == "outside_chile"
    assert coordinate_issue(-38.7, -72.6) == "outside_rm"
    assert coordinate_issue(-38.7, -72.6, focus_rm=False) is None


def test_classify_geocode_risk_levels() -> None:
    assert classify_geocode_risk(precision=None, lat=None, lon=None).level == "CRITICAL"
    assert classify_geocode_risk(precision=None, lat=-33.4, lon=-70.6).level == "WARNING"
    assert classify_geocode_risk(precision="comuna_centroid", lat=-33.4, lon=-70.6).level == "WARNING"
    assert classify_geocode_risk(
        precision="exact",
        lat=-33.4,
        lon=-70.6,
        repeated_coord_count=5,
    ).level == "SUSPECT"
    assert classify_geocode_risk(precision="street_address", lat=-33.4, lon=-70.6).level == "OK"


def test_report_precision_counts_are_canonical() -> None:
    listings = [
        GeoListing(1, "active", "nunoa", "A", None, "yapo", "street_address", -33.4, -70.6),
        GeoListing(2, "active", "nunoa", "B", None, "yapo", "street_name", -33.4, -70.61),
        GeoListing(3, "active", "nunoa", "C", None, "yapo", "landmark_or_sector", -33.4, -70.62),
        GeoListing(4, "active", "nunoa", "D", None, "yapo", None, -33.4, -70.63),
    ]

    report = build_report(listings)

    assert report["precision_active"] == {"address": 1, "street": 2, "unknown": 1}
    assert report["summary"]["active_missing_geocode_precision"] == 1
