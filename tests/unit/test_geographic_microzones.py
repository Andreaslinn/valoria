from __future__ import annotations

from domain.geocoding.geographic_microzones import (
    build_geographic_microzone_report,
    geographic_microzone_for,
)


def _listing(**overrides):
    listing = {
        "id": 1,
        "title": "Departamento",
        "comuna": "providencia",
        "property_type": "apartment",
        "status": "active",
        "lat": -33.425,
        "lon": -70.61,
        "geocode_precision": "street",
        "raw_metadata": {
            "geocode_query_source": "metadata_address",
            "geocode_query_confidence": "medium",
        },
    }
    listing.update(overrides)
    return listing


def test_no_creates_microzone_with_comuna_centroid() -> None:
    decision = geographic_microzone_for(
        _listing(geocode_precision="comuna_centroid")
    )

    assert decision.microzone is None
    assert decision.reason == "excluded_precision:comuna_centroid"


def test_no_creates_microzone_with_title_inferred_low_confidence() -> None:
    decision = geographic_microzone_for(
        _listing(
            raw_metadata={
                "geocode_query_source": "title_inferred_street",
                "geocode_query_confidence": "low",
            }
        )
    )

    assert decision.microzone is None
    assert decision.reason == "excluded_title_inferred_low_confidence"


def test_creates_microzone_with_metadata_address_street_medium() -> None:
    decision = geographic_microzone_for(_listing())

    assert decision.microzone is not None
    assert decision.microzone.microzone_id.startswith("geo500:providencia:")
    assert decision.microzone.confidence == 0.72


def test_groups_nearby_coordinates_in_same_microzone() -> None:
    first = geographic_microzone_for(_listing(lat=-33.425, lon=-70.61))
    second = geographic_microzone_for(_listing(lat=-33.4252, lon=-70.6101))

    assert first.microzone is not None
    assert second.microzone is not None
    assert first.microzone.microzone_id == second.microzone.microzone_id


def test_separates_far_coordinates() -> None:
    first = geographic_microzone_for(_listing(lat=-33.425, lon=-70.61))
    second = geographic_microzone_for(_listing(lat=-33.435, lon=-70.62))

    assert first.microzone is not None
    assert second.microzone is not None
    assert first.microzone.microzone_id != second.microzone.microzone_id


def test_report_runs_without_writing_db() -> None:
    listings = [
        _listing(id=1),
        _listing(id=2, lat=-33.4252, lon=-70.6101),
        _listing(
            id=3,
            raw_metadata={
                "geocode_query_source": "title_inferred_street",
                "geocode_query_confidence": "low",
            },
        ),
        _listing(id=4, geocode_precision="comuna_centroid"),
        _listing(id=5, status="inactive"),
    ]

    report = build_geographic_microzone_report(listings, min_comparables=2)

    assert report["summary"]["active_listings"] == 4
    assert report["summary"]["geographic_microzone_listings"] == 2
    assert report["summary"]["geographic_microzone_count"] == 1
    assert report["summary"]["sufficient_microzone_count"] == 1
    reasons = {row["value"]: row["count"] for row in report["reason_counts"]}
    assert reasons["excluded_title_inferred_low_confidence"] == 1
    assert reasons["excluded_precision:comuna_centroid"] == 1
