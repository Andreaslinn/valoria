"""Controlled, manifest-driven land-area backfill helpers for Phase 5C."""
from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.entities.listing import Listing
from core.normalization.property_type import normalize_property_type
from domain.data_quality.enrichment_validation import validate_land_area_candidate
from domain.valuation.evaluation.dataset import build_evaluation_cases
from infrastructure.db.mappers import listing_from_orm
from infrastructure.db.models import ListingORM

ACCEPT_STATUS = "accept_high_confidence"
APPLY_READY = "apply_ready"
MIN_LAND_AREA_M2 = 20.0
MAX_LAND_AREA_M2 = 20_000.0
MIN_LAND_TO_BUILT_RATIO = 0.25
MAX_LAND_TO_BUILT_RATIO = 30.0
ALLOWED_CHANGED_COLUMNS = frozenset({"land_area_m2", "updated_at"})


class LandAreaBackfillSafetyError(RuntimeError):
    """Raised when a controlled backfill invariant is not satisfied."""


@dataclass(frozen=True)
class CandidateDecision:
    listing_id: int
    manifest_status: str
    decision: str
    reason: str
    old_land_area_m2: float | None
    old_updated_at: str | None
    new_land_area_m2: float | None
    built_area_m2: float | None
    land_to_built_ratio: float | None
    evidence: str
    parser_rule: str
    validations_passed: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise LandAreaBackfillSafetyError("land-area manifest must be a JSON list")
    rows: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            raise LandAreaBackfillSafetyError("every manifest entry must be an object")
        listing_id = _int_or_none(raw.get("listing_id"))
        if listing_id is None:
            raise LandAreaBackfillSafetyError("manifest entry missing listing_id")
        if listing_id in seen_ids:
            raise LandAreaBackfillSafetyError(f"duplicate listing_id in manifest: {listing_id}")
        seen_ids.add(listing_id)
        rows.append(dict(raw))
    return sorted(rows, key=lambda row: int(row["listing_id"]))


def manifest_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row.get("status") or "missing") for row in rows)
    return {
        "total_candidates": len(rows),
        "accept_high_confidence": counts[ACCEPT_STATUS],
        "review_required": counts["review_required"],
        "rejected": sum(count for status, count in counts.items() if status.startswith("reject_")),
        "other_or_not_applicable": sum(
            count
            for status, count in counts.items()
            if status not in {ACCEPT_STATUS, "review_required"} and not status.startswith("reject_")
        ),
        "status_counts": dict(sorted(counts.items())),
    }


def revalidate_candidate(manifest_row: dict[str, Any], listing: Listing | None) -> CandidateDecision:
    listing_id = int(manifest_row["listing_id"])
    manifest_status = str(manifest_row.get("status") or "missing")
    proposed = _positive_float(manifest_row.get("land_area_m2_proposed"))
    evidence = str(manifest_row.get("evidence_text") or "")
    parser_rule = str(manifest_row.get("parser_rule") or manifest_row.get("origin_field") or "")
    if manifest_status != ACCEPT_STATUS:
        return _decision(listing_id, manifest_status, "skip_needs_review", "manifest_status_not_accepted", listing, proposed, evidence, parser_rule)
    if listing is None:
        return _decision(listing_id, manifest_status, "skip_missing_listing", "listing_not_found", None, proposed, evidence, parser_rule)
    if normalize_property_type(listing) != "house":
        return _decision(listing_id, manifest_status, "skip_not_house", "current_property_type_is_not_house", listing, proposed, evidence, parser_rule)
    if not listing.is_active:
        return _decision(listing_id, manifest_status, "skip_conflict_current_data", "listing_is_not_active", listing, proposed, evidence, parser_rule)
    if _positive_float(listing.land_area_m2) is not None:
        return _decision(listing_id, manifest_status, "skip_already_has_land_area", "land_area_is_no_longer_null", listing, proposed, evidence, parser_rule)
    if proposed is None or proposed < MIN_LAND_AREA_M2 or proposed > MAX_LAND_AREA_M2:
        return _decision(listing_id, manifest_status, "skip_implausible", "proposed_value_outside_plausible_range", listing, proposed, evidence, parser_rule)
    built = _positive_float(listing.built_area_m2 or listing.usable_area_m2 or listing.m2)
    if built is None:
        return _decision(listing_id, manifest_status, "skip_conflict_current_data", "current_built_area_missing", listing, proposed, evidence, parser_rule)
    ratio = proposed / built
    if ratio < MIN_LAND_TO_BUILT_RATIO or ratio > MAX_LAND_TO_BUILT_RATIO:
        return _decision(listing_id, manifest_status, "skip_implausible", "land_to_built_ratio_outside_plausible_range", listing, proposed, evidence, parser_rule)
    if not evidence.strip() or not _current_text_available(listing):
        return _decision(listing_id, manifest_status, "skip_ambiguous", "current_text_evidence_missing", listing, proposed, evidence, parser_rule)
    current_validation = validate_land_area_candidate(listing)
    current_value = _positive_float(current_validation.get("land_area_m2_proposed"))
    if current_validation.get("status") != ACCEPT_STATUS:
        return _decision(
            listing_id,
            manifest_status,
            "skip_conflict_current_data",
            f"phase5b_revalidation_status:{current_validation.get('status')}",
            listing,
            proposed,
            evidence,
            parser_rule,
        )
    if current_value is None or not math.isclose(current_value, proposed, rel_tol=0.0, abs_tol=0.01):
        return _decision(listing_id, manifest_status, "skip_conflict_current_data", "current_parser_value_differs_from_manifest", listing, proposed, evidence, parser_rule)
    current_rule = str(current_validation.get("parser_rule") or "")
    if current_rule != parser_rule:
        return _decision(listing_id, manifest_status, "skip_conflict_current_data", "current_parser_rule_differs_from_manifest", listing, proposed, evidence, parser_rule)
    validations = (
        "manifest_accept_high_confidence",
        "listing_exists",
        "listing_active",
        "property_type_house",
        "current_land_area_null",
        "positive_plausible_value",
        "built_area_present",
        "plausible_land_to_built_ratio",
        "text_evidence_available",
        "phase5b_revalidation_accepts",
        "parser_value_matches_manifest",
        "parser_rule_matches_manifest",
    )
    return CandidateDecision(
        listing_id=listing_id,
        manifest_status=manifest_status,
        decision=APPLY_READY,
        reason="all_phase5c_guardrails_passed",
        old_land_area_m2=None,
        old_updated_at=None,
        new_land_area_m2=proposed,
        built_area_m2=built,
        land_to_built_ratio=round(ratio, 4),
        evidence=evidence,
        parser_rule=parser_rule,
        validations_passed=validations,
    )


def build_apply_plan(
    manifest_rows: Sequence[dict[str, Any]],
    listings_by_id: dict[int, Listing],
    *,
    houses_total: int,
    houses_with_land: int,
    manifest_path: Path,
    updated_at_by_id: dict[int, str | None] | None = None,
) -> dict[str, Any]:
    decisions = [revalidate_candidate(row, listings_by_id.get(int(row["listing_id"]))) for row in manifest_rows]
    counts = Counter(item.decision for item in decisions)
    ready = [item for item in decisions if item.decision == APPLY_READY]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "dry-run",
        "manifest_path": str(manifest_path),
        "manifest_summary": manifest_summary(manifest_rows),
        "revalidation": {
            "apply_ready": len(ready),
            "skipped": len(decisions) - len(ready),
            "decision_counts": dict(sorted(counts.items())),
            "affected_ids": [item.listing_id for item in ready],
        },
        "coverage": {
            "active_houses": houses_total,
            "houses_with_land_before": houses_with_land,
            "coverage_before_pct": _pct(houses_with_land, houses_total),
            "houses_with_land_expected": houses_with_land + len(ready),
            "coverage_expected_pct": _pct(houses_with_land + len(ready), houses_total),
            "absolute_count_delta": len(ready),
            "percentage_point_delta": round(_pct(houses_with_land + len(ready), houses_total) - _pct(houses_with_land, houses_total), 2),
        },
        "decisions": [
            {**item.to_dict(), "old_updated_at": (updated_at_by_id or {}).get(item.listing_id)}
            for item in decisions
        ],
        "guardrails": {
            "database_modified": False,
            "external_requests": 0,
            "allowed_column": "land_area_m2",
            "review_required_excluded": True,
        },
    }


def build_rollback_manifest(plan: dict[str, Any], *, source_file: Path, operator: str) -> dict[str, Any]:
    timestamp = datetime.now(UTC).isoformat()
    rows = []
    for decision in plan["decisions"]:
        if decision["decision"] != APPLY_READY:
            continue
        listing_id = int(decision["listing_id"])
        rows.append(
            {
                "listing_id": listing_id,
                "old_land_area_m2": decision["old_land_area_m2"],
                "new_land_area_m2": decision["new_land_area_m2"],
                "old_updated_at": decision.get("old_updated_at"),
                "evidence": decision["evidence"],
                "source_file": str(source_file),
                "timestamp": timestamp,
                "reason": "phase5b_accept_high_confidence_revalidated_phase5c",
                "operator": operator,
                "mode": "rollback_proposal_not_executed",
                "rollback_sql_suggested": (
                    "UPDATE listings SET land_area_m2 = NULL "
                    f"WHERE id = {listing_id} AND land_area_m2 = {decision['new_land_area_m2']};"
                ),
            }
        )
    return {
        "warning": "Rollback proposal only. Review current values and execute transactionally; this file is not an automatic script.",
        "generated_at": timestamp,
        "source_file": str(source_file),
        "rows": rows,
    }


async def load_plan_inputs(
    session: AsyncSession,
    manifest_rows: Sequence[dict[str, Any]],
    *,
    lock_rows: bool = False,
) -> tuple[dict[int, ListingORM], dict[int, Listing], int, int]:
    ids = [int(row["listing_id"]) for row in manifest_rows]
    stmt = select(ListingORM).where(ListingORM.id.in_(ids)).order_by(ListingORM.id)
    if lock_rows:
        stmt = stmt.with_for_update()
    orm_rows = list((await session.execute(stmt)).scalars().all())
    orm_by_id = {row.id: row for row in orm_rows}
    domain_by_id: dict[int, Listing] = {}
    for row in orm_rows:
        listing = listing_from_orm(row)
        listing.raw_metadata = dict(row.raw_metadata or {})
        domain_by_id[row.id] = listing
    houses_total, houses_with_land = (
        await session.execute(
            select(
                func.count(ListingORM.id),
                func.count(ListingORM.id).filter(ListingORM.land_area_m2.is_not(None)),
            ).where(ListingORM.status == "active", ListingORM.property_type == "house")
        )
    ).one()
    return orm_by_id, domain_by_id, int(houses_total or 0), int(houses_with_land or 0)


async def execute_controlled_apply(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    manifest_rows: Sequence[dict[str, Any]],
    manifest_path: Path,
    expected_count: int,
) -> dict[str, Any]:
    started = datetime.now(UTC)
    before_snapshots: dict[int, dict[str, Any]] = {}
    changed_columns: dict[int, list[str]] = {}
    async with session_factory() as session:
        try:
            async with session.begin():
                orm_by_id, domain_by_id, houses_total, houses_with_land = await load_plan_inputs(
                    session, manifest_rows, lock_rows=True
                )
                plan = build_apply_plan(
                    manifest_rows,
                    domain_by_id,
                    houses_total=houses_total,
                    houses_with_land=houses_with_land,
                    manifest_path=manifest_path,
                    updated_at_by_id={row_id: row.updated_at.isoformat() for row_id, row in orm_by_id.items()},
                )
                ready = [row for row in plan["decisions"] if row["decision"] == APPLY_READY]
                if len(ready) != expected_count:
                    raise LandAreaBackfillSafetyError(
                        f"apply_ready count mismatch: expected {expected_count}, got {len(ready)}"
                    )
                for decision in ready:
                    listing_id = int(decision["listing_id"])
                    orm_row = orm_by_id[listing_id]
                    before_snapshots[listing_id] = model_snapshot(orm_row)
                    result = await session.execute(
                        update(ListingORM)
                        .where(
                            ListingORM.id == listing_id,
                            ListingORM.property_type == "house",
                            ListingORM.land_area_m2.is_(None),
                        )
                        .values(land_area_m2=float(decision["new_land_area_m2"]))
                    )
                    if result.rowcount != 1:
                        raise LandAreaBackfillSafetyError(
                            f"rowcount mismatch for listing {listing_id}: {result.rowcount}"
                        )
                session.expire_all()
                updated_rows = list(
                    (
                        await session.execute(
                            select(ListingORM)
                            .where(ListingORM.id.in_([int(row["listing_id"]) for row in ready]))
                            .order_by(ListingORM.id)
                        )
                    ).scalars().all()
                )
                if len(updated_rows) != len(ready):
                    raise LandAreaBackfillSafetyError("post-update row count mismatch")
                expected_values = {int(row["listing_id"]): float(row["new_land_area_m2"]) for row in ready}
                for row in updated_rows:
                    after = model_snapshot(row)
                    changed = snapshot_changed_columns(before_snapshots[row.id], after)
                    changed_columns[row.id] = changed
                    unexpected = set(changed) - ALLOWED_CHANGED_COLUMNS
                    if unexpected:
                        raise LandAreaBackfillSafetyError(
                            f"unexpected columns changed for listing {row.id}: {sorted(unexpected)}"
                        )
                    if not math.isclose(float(row.land_area_m2 or 0), expected_values[row.id], abs_tol=0.01):
                        raise LandAreaBackfillSafetyError(f"post-update land value mismatch for listing {row.id}")
            transaction_status = "committed"
        except Exception:
            await session.rollback()
            raise

    verification = await verify_post_apply(
        session_factory=session_factory,
        ready_rows=ready,
        before_snapshots=before_snapshots,
    )
    finished = datetime.now(UTC)
    return {
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 3),
        "transaction_status": transaction_status,
        "expected_rows": expected_count,
        "rows_affected": len(ready),
        "affected_ids": [int(row["listing_id"]) for row in ready],
        "changed_columns_by_id": {str(key): value for key, value in sorted(changed_columns.items())},
        "verification": verification,
        "plan": plan,
    }


async def verify_post_apply(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    ready_rows: Sequence[dict[str, Any]],
    before_snapshots: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    ids = [int(row["listing_id"]) for row in ready_rows]
    expected = {int(row["listing_id"]): float(row["new_land_area_m2"]) for row in ready_rows}
    async with session_factory() as session:
        rows = list(
            (
                await session.execute(select(ListingORM).where(ListingORM.id.in_(ids)).order_by(ListingORM.id))
            ).scalars().all()
        )
        houses_total, houses_with_land = (
            await session.execute(
                select(
                    func.count(ListingORM.id),
                    func.count(ListingORM.id).filter(ListingORM.land_area_m2.is_not(None)),
                ).where(ListingORM.status == "active", ListingORM.property_type == "house")
            )
        ).one()
        active_rows = list(
            (
                await session.execute(select(ListingORM).where(ListingORM.status == "active").order_by(ListingORM.id))
            ).scalars().all()
        )
        listings = []
        for row in active_rows:
            listing = listing_from_orm(row)
            listing.raw_metadata = dict(row.raw_metadata or {})
            listings.append(listing)
        value_mismatches = [
            row.id
            for row in rows
            if not math.isclose(float(row.land_area_m2 or 0), expected[row.id], abs_tol=0.01)
        ]
        unexpected_changes = {
            str(row.id): sorted(
                set(snapshot_changed_columns(before_snapshots[row.id], model_snapshot(row)))
                - ALLOWED_CHANGED_COLUMNS
            )
            for row in rows
        }
        rows_reloaded = len(rows)
        await session.rollback()
    unexpected_changes = {key: value for key, value in unexpected_changes.items() if value}
    cases = build_evaluation_cases(listings, seed=42)
    target_ids = {case.target_id for case in cases}
    affected_target_ids = sorted(set(ids) & target_ids)
    affected_comparable_ids = sorted(
        listing_id
        for listing_id in ids
        if any(any(candidate.id == listing_id for candidate in case.candidates) for case in cases)
    )
    candidate_memberships = sum(
        1
        for case in cases
        for candidate in case.candidates
        if candidate.id in set(ids)
    )
    return {
        "rows_reloaded": rows_reloaded,
        "value_mismatch_ids": value_mismatches,
        "unexpected_column_changes": unexpected_changes,
        "active_houses": int(houses_total or 0),
        "houses_with_land_after": int(houses_with_land or 0),
        "coverage_after_pct": _pct(int(houses_with_land or 0), int(houses_total or 0)),
        "benchmark_universe": {
            "evaluation_cases": len(cases),
            "affected_targets": len(affected_target_ids),
            "affected_target_ids": affected_target_ids,
            "affected_comparables": len(affected_comparable_ids),
            "affected_comparable_ids": affected_comparable_ids,
            "candidate_memberships": candidate_memberships,
        },
        "verified": not value_mismatches and not unexpected_changes and rows_reloaded == len(ids),
    }


def model_snapshot(row: ListingORM) -> dict[str, Any]:
    return {column.name: _json_value(getattr(row, column.name)) for column in ListingORM.__table__.columns}


def snapshot_changed_columns(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(key for key in before if before.get(key) != after.get(key))


def write_plan_outputs(output_dir: Path, plan: dict[str, Any], rollback: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_json = output_dir / "land_area_apply_plan.json"
    rollback_json = output_dir / "land_area_rollback_manifest.json"
    plan_md = output_dir / "land_area_apply_plan.md"
    plan_json.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    rollback_json.write_text(json.dumps(rollback, indent=2, ensure_ascii=False), encoding="utf-8")
    plan_md.write_text(plan_markdown(plan, rollback), encoding="utf-8")
    return {"plan_json": str(plan_json), "rollback_json": str(rollback_json), "plan_markdown": str(plan_md)}


def write_apply_result(output_dir: Path, payload: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "land_area_apply_result.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def build_final_report(
    *,
    apply_result: dict[str, Any],
    rollback_manifest: dict[str, Any],
    phase4_benchmark_path: Path,
    phase5c_benchmark_path: Path,
    tests: dict[str, Any],
    git: dict[str, Any],
) -> dict[str, Any]:
    phase4 = _benchmark_extract(phase4_benchmark_path)
    phase5c = _benchmark_extract(phase5c_benchmark_path)
    return {
        "preflight": apply_result["preflight"],
        "manifest": apply_result["manifest"],
        "dry_run": apply_result["dry_run"],
        "apply": apply_result["apply"],
        "post_apply": apply_result["apply"]["verification"],
        "benchmark": {
            "command": apply_result.get("benchmark_command"),
            "phase4a": phase4,
            "phase5c": phase5c,
            "comparison": _benchmark_comparison(phase4, phase5c),
        },
        "rollback": {
            "manifest_path": "reports/data_quality/phase5c/land_area_rollback_manifest.json",
            "rows": len(rollback_manifest.get("rows", [])),
            "executed": False,
            "instructions": rollback_manifest.get("warning"),
        },
        "tests": tests,
        "git": git,
        "guardrails": {
            "only_land_area_updated": True,
            "microzones_updated": 0,
            "geocoding_updated": 0,
            "prices_updated": 0,
            "duplicates_deleted": 0,
            "external_requests": 0,
            "migrations_created_or_run": 0,
            "production_changed": False,
        },
    }


def write_final_report(output_dir: Path, report: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "land_area_backfill_latest.json"
    md_path = output_dir / "land_area_backfill_latest.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    md_path.write_text(final_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def plan_markdown(plan: dict[str, Any], rollback: dict[str, Any]) -> str:
    rv = plan["revalidation"]
    coverage = plan["coverage"]
    lines = [
        "# Phase 5C Land Area Apply Plan",
        "",
        f"- Mode: `{plan['mode']}`",
        f"- Manifest: `{plan['manifest_path']}`",
        f"- Apply ready: `{rv['apply_ready']}`",
        f"- Skipped: `{rv['skipped']}`",
        f"- Decisions: `{rv['decision_counts']}`",
        f"- Coverage before: `{coverage['coverage_before_pct']}%`",
        f"- Expected coverage: `{coverage['coverage_expected_pct']}%`",
        f"- Affected IDs: `{rv['affected_ids']}`",
        "",
        "## Rollback",
        "",
        f"- Proposed rows: `{len(rollback['rows'])}`",
        f"- Warning: {rollback['warning']}",
    ]
    return "\n".join(lines) + "\n"


def final_markdown(report: dict[str, Any]) -> str:
    dry = report["dry_run"]
    apply = report["apply"]
    post = report["post_apply"]
    comparison = report["benchmark"]["comparison"]
    lines = [
        "# Phase 5C Controlled Land Area Backfill",
        "",
        "## Preflight",
        "",
        f"- Branch: `{report['preflight'].get('branch')}`",
        f"- HEAD before apply: `{report['preflight'].get('head')}`",
        f"- Database: `{report['preflight'].get('database')}`",
        f"- Manifest: `{report['preflight'].get('manifest_path')}`",
        "",
        "## Manifest And Dry-run",
        "",
        f"- Manifest summary: `{report['manifest']}`",
        f"- Apply ready: `{dry['revalidation']['apply_ready']}`",
        f"- Skipped: `{dry['revalidation']['skipped']}`",
        f"- Expected coverage: `{dry['coverage']['coverage_expected_pct']}%`",
        "",
        "## Apply",
        "",
        f"- Transaction: `{apply['transaction_status']}`",
        f"- Rows affected: `{apply['rows_affected']}`",
        f"- Duration seconds: `{apply['duration_seconds']}`",
        f"- Verified: `{post['verified']}`",
        "",
        "## Coverage",
        "",
        f"- Before: `{dry['coverage']['houses_with_land_before']}/{dry['coverage']['active_houses']}` ({dry['coverage']['coverage_before_pct']}%)",
        f"- After: `{post['houses_with_land_after']}/{post['active_houses']}` ({post['coverage_after_pct']}%)",
        "",
        "## Benchmark Comparison",
        "",
        "| Engine | Segment | F4A MAPE | F5C MAPE | F4A Median | F5C Median | F4A P90 | F5C P90 | F4A Coverage | F5C Coverage |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for engine, segments in comparison.items():
        for segment, values in segments.items():
            before = values["phase4a"]
            after = values["phase5c"]
            lines.append(
                f"| `{engine}` | `{segment}` | {before.get('mape_pct')} | {after.get('mape_pct')} | "
                f"{before.get('median_ape_pct')} | {after.get('median_ape_pct')} | "
                f"{before.get('p90_ape_pct')} | {after.get('p90_ape_pct')} | "
                f"{before.get('coverage_pct')} | {after.get('coverage_pct')} |"
            )
    lines.extend(("", "## Rollback", "", f"- `{report['rollback']}`", "", "## Tests", ""))
    for name, payload in report["tests"].items():
        if isinstance(payload, dict):
            lines.append(f"- `{name}`: `{payload.get('result')}` - `{payload.get('command')}`")
    lines.extend(("", "## Git", "", f"- `{report['git']}`", "", "## Guardrails", ""))
    lines.extend(f"- `{key}`: `{value}`" for key, value in report["guardrails"].items())
    return "\n".join(lines) + "\n"


def _benchmark_extract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows", [])
    engines = sorted({str(row.get("engine_name")) for row in rows})
    segments: dict[str, dict[str, Any]] = {}
    for engine in engines:
        engine_rows = [row for row in rows if row.get("engine_name") == engine]
        segments[engine] = {
            "global": _row_summary(engine_rows),
            "apartment": _row_summary([row for row in engine_rows if row.get("property_type") == "apartment"]),
            "house": _row_summary([row for row in engine_rows if row.get("property_type") == "house"]),
            "house_with_land": _row_summary(
                [row for row in engine_rows if row.get("property_type") == "house" and row.get("has_land_area")]
            ),
            "house_without_land": _row_summary(
                [row for row in engine_rows if row.get("property_type") == "house" and not row.get("has_land_area")]
            ),
        }
    return {
        "path": str(path),
        "dataset_signature": payload.get("metadata", {}).get("dataset_signature"),
        "dataset_cases": payload.get("metadata", {}).get("dataset_cases"),
        "engines": payload.get("metadata", {}).get("engines"),
        "segments": segments,
    }


def _benchmark_comparison(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    common = sorted(set(before["segments"]) & set(after["segments"]))
    return {
        engine: {
            segment: {
                "phase4a": before["segments"][engine][segment],
                "phase5c": after["segments"][engine][segment],
                "mape_delta_pct_points": _delta(
                    before["segments"][engine][segment].get("mape_pct"),
                    after["segments"][engine][segment].get("mape_pct"),
                ),
            }
            for segment in ("global", "apartment", "house", "house_with_land", "house_without_land")
        }
        for engine in common
    }


def _row_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in rows if row.get("estimated_price_clp") is not None and row.get("absolute_percentage_error") is not None]
    apes = [float(row["absolute_percentage_error"]) for row in successful]
    return {
        "total_cases": len(rows),
        "successful": len(successful),
        "coverage_pct": _pct(len(successful), len(rows)),
        "mape_pct": round(sum(apes) / len(apes), 2) if apes else None,
        "median_ape_pct": round(float(median(apes)), 2) if apes else None,
        "p90_ape_pct": _percentile(apes, 90),
        "error_gt_50_pct": _pct(sum(value > 50 for value in apes), len(apes)) if apes else None,
        "error_gt_100_pct": _pct(sum(value > 100 for value in apes), len(apes)) if apes else None,
    }


def _decision(listing_id, manifest_status, decision, reason, listing, proposed, evidence, parser_rule):
    built = _positive_float(
        (listing.built_area_m2 or listing.usable_area_m2 or listing.m2) if listing is not None else None
    )
    ratio = proposed / built if proposed and built else None
    return CandidateDecision(
        listing_id=listing_id,
        manifest_status=manifest_status,
        decision=decision,
        reason=reason,
        old_land_area_m2=_positive_float(listing.land_area_m2) if listing is not None else None,
        old_updated_at=None,
        new_land_area_m2=proposed,
        built_area_m2=built,
        land_to_built_ratio=round(ratio, 4) if ratio is not None else None,
        evidence=evidence,
        parser_rule=parser_rule,
        validations_passed=(),
    )


def _current_text_available(listing: Listing) -> bool:
    metadata = listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}
    return any(
        isinstance(value, str) and value.strip()
        for value in (listing.title, metadata.get("description"), metadata.get("detail_text"), metadata.get("card_text"))
    )


def _positive_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "as_tuple"):
        return str(value)
    return value


def _pct(value: int, total: int) -> float:
    return round(value * 100 / total, 2) if total else 0.0


def _delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return round(after - before, 2)


def _percentile(values: Sequence[float], pct: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = (len(ordered) - 1) * pct / 100
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)
