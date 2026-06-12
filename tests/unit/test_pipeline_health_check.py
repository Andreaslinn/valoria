from datetime import UTC, datetime

from core.assessment.status_codes import PIPELINE_ALERT_CODES
from scripts.pipeline_health_check import (
    THRESHOLDS,
    build_health_report,
    evaluate_health,
    overall_status,
)


def test_pipeline_threshold_codes_are_registered_assessment_codes() -> None:
    assert {threshold.code for threshold in THRESHOLDS} <= PIPELINE_ALERT_CODES


def _listing(
    listing_id: int,
    *,
    source: str = "yapo",
    status: str = "active",
    comuna: str = "nunoa",
    property_type: str = "apartment",
    m2: float | None = 70,
    built_area_m2: float | None = None,
    land_area_m2: float | None = None,
    usable_area_m2: float | None = None,
    price: int | None = 140_000_000,
    bedrooms: int | None = 2,
    bathrooms: int | None = 2,
    title: str | None = None,
    lat: float | None = -33.45,
    lon: float | None = -70.6,
    geocode_precision: str | None = "address",
    raw_metadata: dict | None = None,
) -> dict:
    return {
        "id": listing_id,
        "source": source,
        "external_id": str(listing_id),
        "fingerprint": f"fp-{listing_id}",
        "title": title or f"Departamento cerca metro central {listing_id}",
        "comuna": comuna,
        "property_type": property_type,
        "m2": m2,
        "built_area_m2": m2 if built_area_m2 is None else built_area_m2,
        "land_area_m2": land_area_m2,
        "usable_area_m2": m2 if usable_area_m2 is None else usable_area_m2,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "lat": lat,
        "lon": lon,
        "geocode_precision": geocode_precision,
        "price_clp": price,
        "status": status,
        "raw_metadata": raw_metadata or {"location_text": "Metro Central"},
    }


def test_evaluate_health_marks_critical_parse_rate() -> None:
    alerts = evaluate_health(
        {
            "active_listings": 1200,
            "new_active_listings_since_baseline": 5,
            "price_parse_rate_pct": 80,
            "m2_parse_rate_pct": 99,
            "rooms_parse_rate_pct": 99,
            "covered_comunas": 15,
            "top_comuna_pct": 10,
            "useful_coords_pct": 20,
            "useful_microzone_pct": 30,
            "price_history_usable_pct": 30,
            "top_source_pct": 50,
        },
        has_baseline=True,
    )

    assert any(alert["code"] == "price_parse_rate_low" and alert["status"] == "CRITICAL" for alert in alerts)
    assert overall_status(alerts) == "CRITICAL"


def test_build_report_compares_new_active_keys_against_baseline() -> None:
    baseline = {
        "generated_at": "2026-05-25T00:00:00+00:00",
        "metrics": {"active_listings": 1, "price_parse_rate_pct": 100, "m2_parse_rate_pct": 100},
        "snapshot": {"active_listing_keys": ["yapo|1"]},
    }
    listings = [_listing(1), _listing(2)]

    report = build_health_report(listings, {1: 2, 2: 2}, baseline=baseline, generated_at=datetime.now(UTC))

    assert report["metrics"]["new_active_listings_since_baseline"] == 1
    assert report["baseline"]["available"] is True


def test_missing_baseline_does_not_alert_on_new_listings() -> None:
    report = build_health_report([_listing(i, comuna=f"comuna_{i % 12}") for i in range(1, 1201)], {}, generated_at=datetime.now(UTC))

    assert report["metrics"]["new_active_listings_since_baseline"] is None
    assert all(alert["code"] != "new_listings_low" for alert in report["alerts"])


def test_health_report_flags_low_microzone_and_single_source_dependency() -> None:
    listings = [
        _listing(
            i,
            lat=None,
            lon=None,
            geocode_precision="comuna",
            raw_metadata={"description": "gran oportunidad"},
            title=f"Casa amplia oportunidad {i}",
            comuna=f"comuna_{i % 12}",
        )
        for i in range(1, 1201)
    ]

    report = build_health_report(listings, {}, generated_at=datetime.now(UTC))

    codes = {alert["code"] for alert in report["alerts"]}
    assert "useful_coords_low" in codes
    assert "microzone_rate_low" in codes
    assert "single_source_dependency_high" in codes


def test_health_report_canonicalizes_legacy_precision_aliases_for_useful_coords() -> None:
    listings = [
        _listing(i, geocode_precision="street_address", comuna=f"comuna_{i % 12}")
        for i in range(1, 601)
    ] + [
        _listing(700 + i, geocode_precision="street_name", comuna=f"comuna_{i % 12}")
        for i in range(1, 601)
    ]

    report = build_health_report(listings, {}, generated_at=datetime.now(UTC))

    assert report["metrics"]["useful_coords_pct"] == 100.0
    assert all(alert["code"] != "useful_coords_low" for alert in report["alerts"])


def test_health_report_includes_structural_area_quality_metrics() -> None:
    listings = [
        _listing(1, property_type="house", m2=120, built_area_m2=120, land_area_m2=300, comuna="nunoa"),
        _listing(2, property_type="house", m2=140, built_area_m2=140, land_area_m2=None, comuna="macul"),
        _listing(
            3,
            property_type="apartment",
            m2=70,
            built_area_m2=75,
            usable_area_m2=70,
            comuna="nunoa",
            raw_metadata={"area_parse_version": "area_parser_v2"},
        ),
    ]

    report = build_health_report(listings, {}, generated_at=datetime.now(UTC))

    assert report["metrics"]["house_land_area_coverage_pct"] == 50.0
    assert report["metrics"]["apartment_usable_area_coverage_pct"] == 100.0
    assert report["metrics"]["area_parse_provenance_count"] == 1
    built_by_type = {
        row["property_type"]: row["coverage_pct"]
        for row in report["distributions"]["built_area_coverage_by_type"]
    }
    assert built_by_type["house"] == 100.0
    assert report["distributions"]["top_house_land_area_gaps_by_comuna"][0]["comuna"] == "macul"
