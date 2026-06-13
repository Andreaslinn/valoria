from __future__ import annotations

import json
from io import StringIO
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from core.value_objects.location import Coordinates
from domain.data_quality.enrichment_audit import (
    build_enrichment_audit,
    classify_canonical_price_opportunity,
    classify_geocode_opportunity,
    classify_land_area_opportunity,
    classify_microzone_opportunity,
    dataset_signature,
    detect_duplicate_candidates,
    write_audit_outputs,
)
from tests.unit.factories import make_listing


UF = Decimal("40644.55")


def _listing(idx: int, **overrides):
    defaults = {
        "fingerprint": f"audit-{idx}",
        "source": "yapo",
        "status": "active",
        "property_type": "house",
        "title": "Casa familiar",
        "m2": 100,
        "built_area_m2": 100,
        "price_clp": 200_000_000,
        "price_currency": "CLP",
        "coords": None,
        "geocode_precision": "unknown",
        "raw_metadata": {},
    }
    external_id = overrides.pop("external_id", f"ext-{idx}")
    scraped_at = overrides.pop("scraped_at", datetime(2026, 1, 1, tzinfo=UTC))
    url = overrides.pop("url", f"https://example.com/{idx}")
    defaults.update(overrides)
    listing = make_listing(**defaults)
    listing.id = idx
    listing.external_id = external_id
    listing.scraped_at = scraped_at
    listing.url = url
    return listing


def test_land_area_categories_present_metadata_text_and_missing() -> None:
    present = _listing(1, land_area_m2=250)
    metadata = _listing(2, raw_metadata={"superficie_terreno": "1.200"})
    text = _listing(3, raw_metadata={"description": "Casa con superficie de terreno 450 m2"})
    missing = _listing(4, source="other", url=None)

    assert classify_land_area_opportunity(present).category == "present"
    assert classify_land_area_opportunity(metadata).category == "metadata_structured_unmapped"
    assert classify_land_area_opportunity(text).category == "text_recoverable"
    assert classify_land_area_opportunity(missing).category == "not_recoverable_current_data"


def test_land_area_thousands_normalization_is_visible() -> None:
    listing = _listing(1, raw_metadata={"description": "Superficie terreno 1.200 m2"})

    opportunity = classify_land_area_opportunity(listing)

    assert opportunity.category == "text_recoverable_thousands_normalized"
    assert opportunity.suggested_value == 1200


def test_geocode_categories_do_not_call_external_services() -> None:
    reliable = _listing(1, geocode_precision="street", coords=Coordinates(lat=-33.45, lon=-70.65))
    metadata = _listing(2, raw_metadata={"address_label": "Avenida Grecia 100"})
    title = _listing(3, title="Casa Avenida Grecia 1234")
    comuna = _listing(4)

    assert classify_geocode_opportunity(reliable).category == "already_reliable"
    assert classify_geocode_opportunity(metadata).category == "recoverable_metadata_address"
    assert classify_geocode_opportunity(title).category == "recoverable_title_street"
    assert classify_geocode_opportunity(comuna).category == "commune_only"


def test_microzone_categories_current_and_potential() -> None:
    current = _listing(
        1,
        raw_metadata={
            "nearby_metro": "tobalaba",
            "geo_microzone_tokens": ["metro:tobalaba"],
            "microzone_confidence": 0.7,
        },
    )
    potential = _listing(2, title="Casa cerca Metro Tobalaba")

    assert classify_microzone_opportunity(current).category == "current"
    assert classify_microzone_opportunity(potential).category == "potential_from_title"


def test_canonical_price_categories() -> None:
    clp = _listing(1)
    weak_uf = _listing(
        2,
        price_currency="UF",
        price_uf=Decimal("5000"),
        price_uf_source="estimated",
        price_uf_confidence="low",
    )

    assert classify_canonical_price_opportunity(clp, uf_to_clp=UF).category == "usable_clp_converted"
    assert classify_canonical_price_opportunity(weak_uf, uf_to_clp=UF).category == "estimated_low_confidence"


def test_duplicate_detection_finds_near_republication() -> None:
    first = _listing(1, source="yapo", title="Casa familiar amplia en Nunoa", external_id="a")
    second = _listing(2, source="portal", title="Amplia casa familiar Nunoa", external_id="b")

    rows = detect_duplicate_candidates([first, second])

    assert any(row["kind"] == "near_duplicate" for row in rows)


def test_report_is_deterministic_and_serializable() -> None:
    listings = [_listing(2), _listing(1, property_type="apartment", usable_area_m2=80)]

    first, _ = build_enrichment_audit(listings, uf_to_clp=UF, benchmark_cases=2, examples=2)
    second, _ = build_enrichment_audit(list(reversed(listings)), uf_to_clp=UF, benchmark_cases=2, examples=2)

    assert dataset_signature(listings) == dataset_signature(list(reversed(listings)))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_outputs_include_valid_json_markdown_and_utf8_sig_csv() -> None:
    report, csv_rows = build_enrichment_audit([_listing(1)], uf_to_clp=UF, benchmark_cases=1, examples=1)
    opened: list[tuple[str, str | None]] = []

    def fake_open(path, mode="r", *args, **kwargs):
        opened.append((mode, kwargs.get("encoding")))
        return StringIO()

    with (
        patch.object(Path, "mkdir"),
        patch.object(Path, "write_text", return_value=1) as write_text,
        patch.object(Path, "open", fake_open),
    ):
        paths = write_audit_outputs(Path("reports/test"), report, csv_rows)

    json.loads(json.dumps(report))
    assert write_text.call_args_list[0].kwargs["encoding"] == "utf-8"
    assert write_text.call_args_list[1].args[0].startswith("# Phase 5A")
    assert all(encoding == "utf-8-sig" for _, encoding in opened)
    assert paths["json"].endswith("data_enrichment_audit_latest.json")


def test_coordinate_presence_is_reported_without_promoting_centroid_to_useful() -> None:
    listing = _listing(
        1,
        coords=Coordinates(lat=-33.45, lon=-70.65),
        geocode_precision="comuna_centroid",
    )

    report, _ = build_enrichment_audit([listing], uf_to_clp=UF, benchmark_cases=1)

    assert report["coverage"]["house"]["coordinates"]["valid_count"] == 1
    assert report["coverage"]["house"]["useful_geocode"]["valid_count"] == 0
