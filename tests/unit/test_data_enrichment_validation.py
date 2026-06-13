from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from domain.data_quality.enrichment_audit import dataset_signature
from domain.data_quality.enrichment_validation import (
    _csv_value,
    build_enrichment_validation,
    select_department_refresh_sample,
    validate_duplicate_groups,
    validate_land_area_candidate,
    validate_microzone_candidate,
    validation_signature,
    write_validation_outputs,
)
from scripts.validate_data_enrichment_candidates import load_listings_read_only, parse_args
from tests.unit.factories import make_listing

UF = Decimal("40644.55")


def _listing(idx: int, **overrides):
    defaults = {
        "fingerprint": f"phase5b-{idx}",
        "source": "yapo",
        "status": "active",
        "property_type": "house",
        "title": "Casa familiar",
        "m2": 100,
        "built_area_m2": 100,
        "price_clp": 200_000_000,
        "price_currency": "CLP",
        "raw_metadata": {},
    }
    external_id = overrides.pop("external_id", f"ext-{idx}")
    scraped_at = overrides.pop("scraped_at", datetime(2026, 1, 1, tzinfo=UTC))
    last_seen_at = overrides.pop("last_seen_at", scraped_at)
    url = overrides.pop("url", f"https://example.com/{idx}")
    defaults.update(overrides)
    listing = make_listing(**defaults)
    listing.id = idx
    listing.external_id = external_id
    listing.scraped_at = scraped_at
    listing.last_seen_at = last_seen_at
    listing.url = url
    return listing


def _phase5a(listings) -> dict:
    return {"dataset": {"signature": dataset_signature(listings)}}


def test_land_candidate_accepts_explicit_plausible_value() -> None:
    listing = _listing(1, raw_metadata={"description": "Superficie de terreno 450 m2"})

    row = validate_land_area_candidate(listing)

    assert row["status"] == "accept_high_confidence"
    assert row["land_area_m2_proposed"] == 450
    assert row["land_to_built_ratio"] == 4.5


def test_land_candidate_rejects_implausible_value() -> None:
    listing = _listing(1, raw_metadata={"superficie_terreno": "50000"})

    row = validate_land_area_candidate(listing)

    assert row["status"] == "reject_implausible"


def test_land_candidate_requires_review_for_ambiguous_slash_pair() -> None:
    listing = _listing(1, title="Casa superficies 100/250 m2")

    row = validate_land_area_candidate(listing)

    assert row["status"] == "review_required"
    assert "slash_pair" in row["decision_reason"]


def test_land_candidate_rejects_multiple_explicit_land_values() -> None:
    listing = _listing(
        1,
        raw_metadata={"description": "Terreno 450 m2, ficha alternativa indica terreno 900 m2"},
    )

    row = validate_land_area_candidate(listing)

    assert row["status"] == "reject_conflict"
    assert row["explicit_land_values"] == [450.0, 900.0]


def test_land_candidate_detects_possible_built_area_confusion() -> None:
    listing = _listing(1, built_area_m2=100, raw_metadata={"surface_land": "100"})

    row = validate_land_area_candidate(listing)

    assert row["status"] == "reject_not_land_area"
    assert row["decision_reason"] == "same_as_built_area_without_explicit_land_rule"


def test_microzone_accepts_specific_metro_and_keeps_avenue_soft() -> None:
    metro = _listing(1, title="Casa cerca Metro Tobalaba")
    avenue = _listing(2, title="Casa en Avenida Grecia")

    metro_row = validate_microzone_candidate(metro)
    avenue_row = validate_microzone_candidate(avenue)

    assert metro_row["recommendation"] == "accept_high_confidence"
    assert metro_row["signal_type"] == "metro"
    assert avenue_row["recommendation"] == "use_only_as_soft_signal"
    assert avenue_row["false_positive_risk"] == "medium"


def test_microzone_rejects_marketing_false_positive() -> None:
    listing = _listing(1, title="Casa con amplio terreno Avenida Grecia")

    row = validate_microzone_candidate(listing)

    assert row["recommendation"] == "reject_false_positive"
    assert row["false_positive_risk"] == "high"


def test_duplicate_groups_include_similarity_and_classification() -> None:
    first = _listing(1, title="Casa familiar amplia en Nunoa", external_id="a")
    second = _listing(2, title="Amplia casa familiar en Nunoa", external_id="b")

    rows = validate_duplicate_groups([first, second])

    assert len(rows) == 1
    assert rows[0]["classification"] == "near_duplicate_high_confidence"
    assert rows[0]["max_title_similarity"] >= 0.85


def test_refresh_sample_is_representative_and_deterministic() -> None:
    listings = []
    comunas = ["santiago", "nunoa", "las_condes", "san_miguel"]
    start = datetime(2024, 1, 1, tzinfo=UTC)
    for idx in range(80):
        listings.append(
            _listing(
                idx + 1,
                property_type="apartment",
                comuna=comunas[idx % len(comunas)],
                m2=35 + idx,
                built_area_m2=35 + idx,
                usable_area_m2=35 + idx,
                price_clp=70_000_000 + idx * 5_000_000,
                price_currency="UF",
                price_uf=None,
                price_uf_source="legacy_unrecoverable",
                raw_metadata={"price_text": "UF pendiente"} if idx % 2 else {},
                last_seen_at=start + timedelta(days=idx),
            )
        )

    first = select_department_refresh_sample(listings, uf_to_clp=UF, sample_size=50)
    second = select_department_refresh_sample(list(reversed(listings)), uf_to_clp=UF, sample_size=50)

    assert len(first) == 50
    assert first == second
    assert {row["comuna"] for row in first} == set(comunas)
    assert {row["price_band"] for row in first} == {"low", "mid", "high"}
    assert {row["surface_band"] for row in first} >= {"small_lt_50", "medium_50_90", "large_gt_90"}
    assert {row["metadata_uf_signal_kind"] for row in first} == {
        "structured_currency_only",
        "textual_uf_evidence",
    }


def test_build_validation_recalculates_expected_candidate_groups() -> None:
    listings = [
        _listing(1, raw_metadata={"description": "Terreno de 450 m2"}),
        _listing(2, raw_metadata={"description": "Casa con amplio terreno y jardin"}),
        _listing(3, raw_metadata={"area_parse_warnings": ["ignored_built_area_m2_from_text"]}),
        _listing(4, title="Casa cerca Metro Tobalaba"),
    ]

    report, manifests = build_enrichment_validation(
        listings,
        phase5a_report=_phase5a(listings),
        uf_to_clp=UF,
    )

    assert report["dataset"]["matches_phase5a"] is True
    assert report["land_area"]["candidates_recalculated"] == 1
    assert report["land_mentions_without_value"]["total"] == 1
    assert report["surface_inconsistencies"]["total"] == 1
    assert len(manifests["microzone_candidates"]) == 1
    assert report["implementation_guardrails"]["database_writes"] == 0
    assert report["implementation_guardrails"]["external_requests"] == 0


def test_validation_is_deterministic() -> None:
    listings = [
        _listing(2, title="Casa Metro Tobalaba"),
        _listing(1, raw_metadata={"description": "Superficie terreno 450 m2"}),
    ]
    first_report, first_manifests = build_enrichment_validation(
        listings, phase5a_report=_phase5a(listings), uf_to_clp=UF
    )
    second_report, second_manifests = build_enrichment_validation(
        list(reversed(listings)), phase5a_report=_phase5a(listings), uf_to_clp=UF
    )

    assert validation_signature(first_report, first_manifests) == validation_signature(
        second_report, second_manifests
    )


def test_validation_does_not_attempt_external_requests() -> None:
    listing = _listing(1, raw_metadata={"description": "Superficie terreno 450 m2"})

    with patch("socket.create_connection", side_effect=AssertionError("network call attempted")):
        report, _ = build_enrichment_validation(
            [listing], phase5a_report=_phase5a([listing]), uf_to_clp=UF
        )

    assert report["implementation_guardrails"]["external_requests"] == 0


def test_outputs_include_json_manifests_and_utf8_sig_csv() -> None:
    listing = _listing(1, raw_metadata={"description": "Superficie terreno 450 m2"})
    report, manifests = build_enrichment_validation(
        [listing], phase5a_report=_phase5a([listing]), uf_to_clp=UF
    )
    opened: list[str | None] = []

    def fake_open(path, mode="r", *args, **kwargs):
        opened.append(kwargs.get("encoding"))
        return StringIO()

    with (
        patch.object(Path, "mkdir"),
        patch.object(Path, "write_text", return_value=1) as write_text,
        patch.object(Path, "open", fake_open),
    ):
        paths = write_validation_outputs(Path("reports/test"), report, manifests)

    json.loads(json.dumps(report))
    assert len(write_text.call_args_list) == 6
    assert len(opened) == 4
    assert all(encoding == "utf-8-sig" for encoding in opened)
    assert paths["land_area_backfill_candidates_json"].endswith(".json")


def test_csv_serialization_removes_trailing_space_from_embedded_lines() -> None:
    assert _csv_value("first line  \nsecond line ") == "first line\nsecond line"


@pytest.mark.asyncio
async def test_read_only_loader_rolls_back_without_commit() -> None:
    orm = SimpleNamespace(raw_metadata={})
    scalars = SimpleNamespace(all=lambda: [orm])
    execute_result = SimpleNamespace(scalars=lambda: scalars)
    session = SimpleNamespace(execute=AsyncMock(return_value=execute_result), rollback=AsyncMock())
    session.commit = AsyncMock()

    class Context:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with patch("scripts.validate_data_enrichment_candidates.listing_from_orm", return_value=_listing(1)):
        rows = await load_listings_read_only(lambda: Context())

    assert len(rows) == 1
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_cli_defaults_are_report_only_and_no_external() -> None:
    args = parse_args([])

    assert args.report_only is True
    assert args.no_external_requests is True
    assert args.refresh_sample_size == 50
