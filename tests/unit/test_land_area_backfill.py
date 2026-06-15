from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from domain.data_quality.land_area_backfill import (
    LandAreaBackfillSafetyError,
    build_apply_plan,
    build_rollback_manifest,
    execute_controlled_apply,
    load_manifest,
    manifest_summary,
    revalidate_candidate,
    write_final_report,
    write_plan_outputs,
)
from infrastructure.db.mappers import listing_from_orm
from infrastructure.db.models import ListingORM
from scripts.apply_land_area_backfill import parse_args, run_dry_run


def _orm(idx: int = 1, **overrides) -> ListingORM:
    now = datetime.now(UTC)
    values = {
        "id": idx,
        "source": "yapo",
        "external_id": f"land-{idx}",
        "title": "Casa familiar",
        "url": f"https://example.com/{idx}",
        "comuna": "nunoa",
        "property_type": "house",
        "m2": 100.0,
        "built_area_m2": 100.0,
        "land_area_m2": None,
        "usable_area_m2": None,
        "bedrooms": 3,
        "bathrooms": 2,
        "parking": 1,
        "price_clp": Decimal("200000000"),
        "price_currency": "CLP",
        "status": "active",
        "fingerprint": f"land-{idx}",
        "raw_metadata": {"description": "Superficie terreno 450 m2"},
        "scraped_at": now,
        "last_seen_at": now,
    }
    values.update(overrides)
    return ListingORM(**values)


def _manifest_row(idx: int = 1, **overrides) -> dict:
    values = {
        "listing_id": idx,
        "status": "accept_high_confidence",
        "land_area_m2_proposed": 450.0,
        "evidence_text": "Superficie terreno 450 m2",
        "parser_rule": "text.land_area_context",
    }
    values.update(overrides)
    return values


def _domain(row: ListingORM):
    listing = listing_from_orm(row)
    listing.raw_metadata = dict(row.raw_metadata or {})
    return listing


def test_load_manifest_filters_and_rejects_duplicate_ids() -> None:
    path = Path("manifest.json")
    payload = [_manifest_row(2, status="review_required"), _manifest_row(1)]
    with patch.object(Path, "read_text", return_value=json.dumps(payload)):
        rows = load_manifest(path)
    assert [row["listing_id"] for row in rows] == [1, 2]
    assert manifest_summary(rows)["accept_high_confidence"] == 1
    with (
        patch.object(Path, "read_text", return_value=json.dumps([_manifest_row(1), _manifest_row(1)])),
        pytest.raises(LandAreaBackfillSafetyError, match="duplicate listing_id"),
    ):
        load_manifest(path)


def test_revalidation_accepts_only_current_matching_house() -> None:
    decision = revalidate_candidate(_manifest_row(), _domain(_orm()))
    assert decision.decision == "apply_ready"
    assert decision.new_land_area_m2 == 450.0
    assert "parser_value_matches_manifest" in decision.validations_passed


@pytest.mark.parametrize(
    ("row_overrides", "manifest_overrides", "expected"),
    [
        ({"land_area_m2": 300.0}, {}, "skip_already_has_land_area"),
        ({"property_type": "apartment"}, {}, "skip_not_house"),
        ({}, {"land_area_m2_proposed": 50000.0}, "skip_implausible"),
        ({"status": "inactive"}, {}, "skip_conflict_current_data"),
        ({"raw_metadata": {}}, {}, "skip_conflict_current_data"),
    ],
)
def test_revalidation_skip_reasons(row_overrides, manifest_overrides, expected) -> None:
    decision = revalidate_candidate(
        _manifest_row(**manifest_overrides),
        _domain(_orm(**row_overrides)),
    )
    assert decision.decision == expected


def test_review_manifest_entry_is_never_apply_ready() -> None:
    decision = revalidate_candidate(
        _manifest_row(status="review_required"),
        _domain(_orm()),
    )
    assert decision.decision == "skip_needs_review"


def test_build_plan_and_rollback_manifest() -> None:
    row = _orm()
    plan = build_apply_plan(
        [_manifest_row(), _manifest_row(2, status="review_required")],
        {1: _domain(row)},
        houses_total=100,
        houses_with_land=10,
        manifest_path=Path("manifest.json"),
        updated_at_by_id={1: row.updated_at.isoformat() if row.updated_at else None},
    )
    rollback = build_rollback_manifest(plan, source_file=Path("manifest.json"), operator="test")
    assert plan["revalidation"]["apply_ready"] == 1
    assert plan["revalidation"]["decision_counts"]["skip_needs_review"] == 1
    assert plan["coverage"]["coverage_expected_pct"] == 11.0
    assert len(rollback["rows"]) == 1
    assert "UPDATE listings SET land_area_m2 = NULL" in rollback["rows"][0]["rollback_sql_suggested"]
    assert rollback["rows"][0]["mode"] == "rollback_proposal_not_executed"


@pytest.mark.asyncio
async def test_dry_run_does_not_modify_database(session: AsyncSession, engine: AsyncEngine) -> None:
    session.add(_orm())
    await session.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    args = parse_args(["--dry-run", "--expected-count", "1"])
    with (
        patch("scripts.apply_land_area_backfill.load_manifest", return_value=[_manifest_row()]),
        patch("scripts.apply_land_area_backfill.write_plan_outputs", return_value={}),
    ):
        result = await run_dry_run(args, session_factory=factory)
    session.expire_all()
    stored = (await session.execute(select(ListingORM).where(ListingORM.id == 1))).scalar_one()
    assert result["plan"]["revalidation"]["apply_ready"] == 1
    assert stored.land_area_m2 is None


@pytest.mark.asyncio
async def test_apply_updates_only_valid_land_area(session: AsyncSession, engine: AsyncEngine) -> None:
    original = _orm(raw_metadata={"description": "Superficie terreno 450 m2", "keep": "yes"})
    session.add(original)
    await session.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    result = await execute_controlled_apply(
        session_factory=factory,
        manifest_rows=[_manifest_row()],
        manifest_path=Path("manifest.json"),
        expected_count=1,
    )

    session.expire_all()
    stored = (await session.execute(select(ListingORM).where(ListingORM.id == 1))).scalar_one()
    assert stored.land_area_m2 == 450.0
    assert stored.built_area_m2 == 100.0
    assert stored.m2 == 100.0
    assert stored.raw_metadata == {"description": "Superficie terreno 450 m2", "keep": "yes"}
    assert result["transaction_status"] == "committed"
    assert result["rows_affected"] == 1
    assert result["verification"]["verified"] is True
    assert set(result["changed_columns_by_id"]["1"]) <= {"land_area_m2", "updated_at"}


@pytest.mark.asyncio
async def test_count_mismatch_rolls_back(session: AsyncSession, engine: AsyncEngine) -> None:
    session.add(_orm())
    await session.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    with pytest.raises(LandAreaBackfillSafetyError, match="count mismatch"):
        await execute_controlled_apply(
            session_factory=factory,
            manifest_rows=[_manifest_row()],
            manifest_path=Path("manifest.json"),
            expected_count=2,
        )
    session.expire_all()
    stored = (await session.execute(select(ListingORM).where(ListingORM.id == 1))).scalar_one()
    assert stored.land_area_m2 is None


def test_report_writers_emit_valid_json_and_markdown() -> None:
    plan = {
        "mode": "dry-run",
        "manifest_path": "manifest.json",
        "revalidation": {"apply_ready": 0, "skipped": 0, "decision_counts": {}, "affected_ids": []},
        "coverage": {"coverage_before_pct": 0, "coverage_expected_pct": 0},
        "decisions": [],
    }
    rollback = {"rows": [], "warning": "proposal only"}
    report = {"hello": "world"}
    writes: list[str] = []

    def fake_write_text(value, **kwargs):
        writes.append(value)
        return len(value)

    with (
        patch.object(Path, "mkdir"),
        patch.object(Path, "write_text", side_effect=fake_write_text),
        patch("domain.data_quality.land_area_backfill.final_markdown", return_value="# Phase 5C\n"),
    ):
        write_plan_outputs(Path("reports/test"), plan, rollback)
        write_final_report(Path("reports/test"), report)
    assert json.loads(writes[0])["mode"] == "dry-run"
    assert json.loads(writes[1])["rows"] == []
    assert writes[2].startswith("# Phase 5C")
    assert json.loads(writes[3]) == report


def test_cli_defaults_to_dry_run() -> None:
    args = parse_args([])
    assert args.apply is False
    assert args.finalize is False
    assert args.expected_count == 25
