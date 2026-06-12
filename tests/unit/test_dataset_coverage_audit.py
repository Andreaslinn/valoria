from datetime import UTC, datetime, timedelta

from scripts.dataset_coverage_audit import build_audit


def _listing(
    listing_id: int,
    *,
    comuna: str = "san miguel",
    property_type: str = "apartment",
    m2: float = 70,
    built_area_m2: float | None = None,
    usable_area_m2: float | None = None,
    land_area_m2: float | None = None,
    price: int = 140_000_000,
    title: str = "Departamento cercano a metro lo ovalle",
    status: str = "active",
    source: str = "yapo",
    scraped_days_ago: int = 1,
    lat: float | None = None,
    lon: float | None = None,
    geocode_precision: str | None = "street",
    raw_metadata: dict | None = None,
) -> dict:
    return {
        "id": listing_id,
        "source": source,
        "external_id": str(listing_id),
        "fingerprint": f"fp-{listing_id}",
        "title": title,
        "url": f"https://example.com/{listing_id}",
        "comuna": comuna,
        "property_type": property_type,
        "m2": m2,
        "built_area_m2": m2 if built_area_m2 is None else built_area_m2,
        "usable_area_m2": usable_area_m2,
        "land_area_m2": land_area_m2,
        "bedrooms": 2,
        "bathrooms": 2,
        "parking": 1,
        "lat": lat,
        "lon": lon,
        "geocode_precision": geocode_precision,
        "price_clp": price,
        "status": status,
        "raw_metadata": raw_metadata or {"location_text": "Metro Lo Ovalle"},
        "scraped_at": datetime.now(UTC) - timedelta(days=scraped_days_ago),
    }


def test_audit_classifies_beta_ready_segment_with_enough_diverse_data() -> None:
    listings = [
        _listing(
            i,
            m2=45 + (i % 4) * 20,
            price=(45 + (i % 4) * 20) * 2_000_000,
            title=f"Departamento cercano a metro lo ovalle {i}",
        )
        for i in range(1, 61)
    ]

    report = build_audit(listings, {}, generated_at=datetime.now(UTC))

    segment = report["beta_readiness"][0]
    assert segment["comuna"] == "san miguel"
    assert segment["property_type"] == "apartment"
    assert segment["beta_status"] == "beta_ready"
    assert segment["canonical_beta_status"] == "beta_supported"


def test_audit_hides_segments_with_less_than_20_useful_listings() -> None:
    listings = [_listing(i, property_type="house", m2=120) for i in range(1, 10)]

    report = build_audit(listings, {}, generated_at=datetime.now(UTC))

    segment = report["beta_readiness"][0]
    assert segment["property_type"] == "house"
    assert segment["beta_status"] == "hide_in_beta"
    assert segment["canonical_beta_status"] == "weak_data"
    assert segment["reason"] == "less_than_20_useful_listings"


def test_property_type_viability_is_separated_by_type() -> None:
    apartments = [
        _listing(
            i,
            property_type="apartment",
            m2=60 + (i % 3) * 20,
            price=(60 + (i % 3) * 20) * 2_000_000,
            title=f"Departamento cercano a metro lo ovalle {i}",
        )
        for i in range(1, 61)
    ]
    houses = [_listing(100 + i, property_type="house", m2=140) for i in range(1, 8)]

    report = build_audit(apartments + houses, {}, generated_at=datetime.now(UTC))

    viability = {row["property_type"]: row for row in report["property_type_viability"]}
    assert viability["apartment"]["status"] == "beta_candidate"
    assert viability["house"]["status"] == "inviable"


def test_price_history_usable_requires_two_points() -> None:
    listings = [_listing(1), _listing(2), _listing(3)]

    report = build_audit(listings, {1: 1, 2: 2, 3: 4}, generated_at=datetime.now(UTC))

    assert report["price_history"]["listings_with_history"] == 3
    assert report["price_history"]["listings_with_2plus_history"] == 2


def test_audit_reports_only_canonical_geocode_precision_labels() -> None:
    listings = [
        _listing(1, geocode_precision="street_address", lat=-33.45, lon=-70.6),
        _listing(2, geocode_precision="street_name", lat=-33.45, lon=-70.61),
        _listing(3, geocode_precision="landmark_or_sector", lat=-33.45, lon=-70.62),
        _listing(4, geocode_precision="exact", lat=-33.45, lon=-70.63),
        _listing(5, geocode_precision=None, lat=None, lon=None),
    ]

    report = build_audit(listings, {}, generated_at=datetime.now(UTC))

    counts = {row["value"]: row["count"] for row in report["by_geocode_precision"]}
    assert counts == {"address": 2, "street": 2, "unknown": 1}
    assert all(row["geocode_precision"] in {"address", "street", "comuna", "comuna_centroid", "unknown"} for row in report["chart_data"]["coordinates"])


def test_audit_reports_area_quality_coverage() -> None:
    listings = [
        _listing(1, property_type="house", m2=120, built_area_m2=120, land_area_m2=300),
        _listing(2, property_type="house", m2=140, built_area_m2=140, land_area_m2=None),
        _listing(
            3,
            property_type="apartment",
            m2=70,
            built_area_m2=75,
            usable_area_m2=70,
            raw_metadata={"area_parse_version": "area_parser_v2"},
        ),
    ]

    report = build_audit(listings, {}, generated_at=datetime.now(UTC))

    assert report["summary"]["house_land_area_coverage_pct"] == 50.0
    assert report["summary"]["apartment_usable_area_coverage_pct"] == 100.0
    assert report["summary"]["area_parse_provenance_count"] == 1
    quality_by_type = {
        row["property_type"]: row
        for row in report["area_quality"]["by_property_type"]
    }
    assert quality_by_type["house"]["land_area_m2_pct"] == 50.0
    assert report["area_quality"]["worst_house_land_area_comunas"][0]["missing_land_area_m2"] == 1


def test_audit_reports_geographic_microzone_coverage() -> None:
    listings = [
        _listing(
            1,
            lat=-33.425,
            lon=-70.61,
            geocode_precision="street",
            raw_metadata={
                "geocode_query_source": "metadata_address",
                "geocode_query_confidence": "medium",
            },
        ),
        _listing(
            2,
            lat=-33.4252,
            lon=-70.6101,
            geocode_precision="street",
            raw_metadata={
                "geocode_query_source": "metadata_street_hint",
                "geocode_query_confidence": "medium",
            },
        ),
        _listing(
            3,
            lat=-33.426,
            lon=-70.611,
            geocode_precision="street",
            raw_metadata={
                "geocode_query_source": "title_inferred_street",
                "geocode_query_confidence": "low",
            },
        ),
        _listing(4, lat=-33.43, lon=-70.62, geocode_precision="comuna_centroid"),
    ]

    report = build_audit(listings, {}, generated_at=datetime.now(UTC))

    assert report["summary"]["geographic_microzone_count"] == 1
    assert report["summary"]["geographic_microzone_pct"] == 50.0
    reasons = {row["reason"]: row["count"] for row in report["geographic_microzones"]["exclusion_reasons"]}
    assert reasons["excluded_title_inferred_low_confidence"] == 1
    assert reasons["excluded_precision:comuna_centroid"] == 1
