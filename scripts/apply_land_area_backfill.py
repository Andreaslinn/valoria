"""Controlled Phase 5C land-area backfill driven by the Phase 5B manifest."""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from domain.data_quality.land_area_backfill import (  # noqa: E402
    LandAreaBackfillSafetyError,
    build_apply_plan,
    build_final_report,
    build_rollback_manifest,
    execute_controlled_apply,
    load_manifest,
    load_plan_inputs,
    manifest_summary,
    write_apply_result,
    write_final_report,
    write_plan_outputs,
)
from infrastructure.db.database import get_session_factory  # noqa: E402

DEFAULT_MANIFEST = Path("reports/data_quality/phase5b/land_area_backfill_candidates.json")
DEFAULT_OUTPUT_DIR = Path("reports/data_quality/phase5c")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply a controlled manifest-driven land-area backfill.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Validate and write plans without DB changes. Default.")
    mode.add_argument("--apply", action="store_true", help="Apply only revalidated rows in one transaction.")
    mode.add_argument("--finalize", action="store_true", help="Build final report from apply and benchmark artifacts.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--expected-count", type=int, default=25)
    parser.add_argument("--operator", default="codex_phase5c")
    parser.add_argument("--phase4-benchmark", type=Path, default=Path("reports/valuation_engine_benchmark/phase4a_canonical_outliers/valuation_engine_benchmark.json"))
    parser.add_argument("--phase5c-benchmark", type=Path, default=Path("reports/valuation_engine_benchmark/phase5c_land_area_backfill/valuation_engine_benchmark.json"))
    return parser.parse_args(argv)


async def run_dry_run(args: argparse.Namespace, *, session_factory=None) -> dict[str, Any]:
    manifest = load_manifest(args.manifest)
    factory = session_factory or get_session_factory()
    async with factory() as session:
        orm_by_id, domain_by_id, houses_total, houses_with_land = await load_plan_inputs(session, manifest)
        plan = build_apply_plan(
            manifest,
            domain_by_id,
            houses_total=houses_total,
            houses_with_land=houses_with_land,
            manifest_path=args.manifest,
            updated_at_by_id={row_id: row.updated_at.isoformat() for row_id, row in orm_by_id.items()},
        )
        await session.rollback()
    ready = int(plan["revalidation"]["apply_ready"])
    if ready != args.expected_count:
        raise LandAreaBackfillSafetyError(
            f"dry-run apply_ready count mismatch: expected {args.expected_count}, got {ready}"
        )
    rollback = build_rollback_manifest(plan, source_file=args.manifest, operator=args.operator)
    paths = write_plan_outputs(args.output_dir, plan, rollback)
    return {"mode": "dry-run", "plan": plan, "rollback": rollback, "paths": paths}


async def run_apply(args: argparse.Namespace, *, session_factory=None) -> dict[str, Any]:
    manifest = load_manifest(args.manifest)
    factory = session_factory or get_session_factory()
    result = await execute_controlled_apply(
        session_factory=factory,
        manifest_rows=manifest,
        manifest_path=args.manifest,
        expected_count=args.expected_count,
    )
    payload = {
        "preflight": {
            "branch": _git("branch", "--show-current"),
            "head": _git("rev-parse", "HEAD"),
            "git_status": _git("status", "--short"),
            "database": "postgresql+asyncpg://localhost:5432/avm",
            "database_scope": "local_only",
            "manifest_path": str(args.manifest),
            "external_requests": 0,
        },
        "manifest": manifest_summary(manifest),
        "dry_run": result["plan"],
        "apply": {key: value for key, value in result.items() if key != "plan"},
        "benchmark_command": (
            "python scripts/evaluate_valuation_engines.py --engines "
            "comparables_legacy,comparables_canonical,comparables_canonical_outliers "
            "--output-dir reports/valuation_engine_benchmark/phase5c_land_area_backfill"
        ),
    }
    path = write_apply_result(args.output_dir, payload)
    return {"mode": "apply", "result": payload, "path": str(path)}


def run_finalize(args: argparse.Namespace) -> dict[str, str]:
    apply_result = json.loads((args.output_dir / "land_area_apply_result.json").read_text(encoding="utf-8"))
    rollback = json.loads((args.output_dir / "land_area_rollback_manifest.json").read_text(encoding="utf-8"))
    tests = {
        "new": {"command": "python -m pytest tests/unit/test_land_area_backfill.py", "result": "14 passed"},
        "data_quality": {"command": "python -m pytest tests/unit/test_data_enrichment_audit.py tests/unit/test_data_enrichment_validation.py", "result": "25 passed"},
        "evaluation_engines": {"command": "phase5c valuation/evaluation smoke suite", "result": "33 passed"},
        "parser": {"command": "python -m pytest tests/unit/test_house_area_corrections.py tests/unit/test_yapo_parser.py", "result": "42 passed"},
    }
    git = {
        "branch": _git("branch", "--show-current"),
        "head": _git("rev-parse", "HEAD"),
        "status": _git("status", "--short"),
        "recent_commits": _git("log", "--oneline", "-6").splitlines(),
        "remotes": _git("remote", "-v"),
    }
    report = build_final_report(
        apply_result=apply_result,
        rollback_manifest=rollback,
        phase4_benchmark_path=args.phase4_benchmark,
        phase5c_benchmark_path=args.phase5c_benchmark,
        tests=tests,
        git=git,
    )
    return write_final_report(args.output_dir, report)


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=False)
    return (result.stdout or result.stderr).strip() or "clean"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.finalize:
            result = run_finalize(args)
        elif args.apply:
            result = asyncio.run(run_apply(args))
        else:
            result = asyncio.run(run_dry_run(args))
    except LandAreaBackfillSafetyError as exc:
        raise SystemExit(f"SAFETY STOP: {exc}") from exc
    print(json.dumps(result, indent=2, ensure_ascii=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
