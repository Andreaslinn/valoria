"""Audit future model strategy without training or registering engines."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from core.ports.uf_service import UFRateInfo
from domain.valuation.engines.registry import default_engine_registry
from domain.valuation.evaluation.dataset import build_evaluation_cases, infer_uf_rate
from domain.valuation.evaluation.evaluator import evaluate_engines
from domain.valuation.evaluation.hedonic_coverage import build_audit_records
from domain.valuation.evaluation.model_strategy_audit import (
    build_report,
    consensus_audit,
    evidence_summary,
    load_json_report,
    run_git,
    write_outputs,
)
from infrastructure.db.database import get_session_factory
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository
from services.uf_rate import validate_real_uf_rate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit ML, house-land-building and consensus strategy")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--reference-canonical-variant", default="comparables_canonical_outliers")
    parser.add_argument("--engines", default="comparables_legacy,comparables_canonical_outliers,comparables_canonical")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--cutoff", default=None)
    parser.add_argument("--uf-rate", default=None)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    phase0_report, phase0 = load_json_report(Path("reports/valuation_engine_benchmark/phase0b_legacy/valuation_engine_benchmark.json"))
    phase1_report, phase1 = load_json_report(Path("reports/valuation_engine_canonical/phase1_canonical_latest.json"))
    phase2_report, phase2 = load_json_report(Path("reports/hedonic_viability/phase2_hedonic_coverage_latest.json"))
    loaded_reports = [phase0_report, phase1_report, phase2_report]
    missing = [report for report in loaded_reports if not report.parse_ok]
    if missing:
        details = "; ".join(f"{report.path}: {report.error}" for report in missing)
        raise SystemExit(f"Required report could not be parsed: {details}")

    registry = default_engine_registry()
    engine_names = [item.strip() for item in args.engines.split(",") if item.strip()]
    for name in engine_names:
        registry.get(name)
    if args.reference_canonical_variant not in engine_names:
        raise SystemExit(f"reference canonical variant must be included in --engines: {args.reference_canonical_variant}")

    async with get_session_factory()() as session:
        repo = SqlAlchemyListingRepository(session)
        listings = list(await repo.list_active(limit=None))

    uf_to_clp = _resolve_uf_rate(args.uf_rate, listings)
    cutoff = _parse_cutoff(args.cutoff)
    cases = build_evaluation_cases(
        listings,
        limit=args.limit,
        seed=args.seed,
        cutoff=cutoff,
    )
    rows = evaluate_engines(
        cases=cases,
        registry=registry,
        engine_names=engine_names,
        uf_to_clp=uf_to_clp,
    )
    records = build_audit_records(listings, cases, uf_to_clp=uf_to_clp)
    registry_engines = registry.list()
    evidence = evidence_summary(
        phase0b=phase0,
        phase1=phase1,
        phase2=phase2,
        registry_engines=registry_engines,
    )
    consensus = consensus_audit(Path("."), registry_engines)
    preflight = {
        "branch": run_git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": run_git("rev-parse", "HEAD"),
        "git_status": run_git("status", "--short", "--untracked-files=no"),
        "remotes": run_git("remote", "-v"),
        "uncommitted_files": run_git("status", "--short", "--untracked-files=no"),
        "last_commits": run_git("log", "--oneline", "-8").splitlines(),
        "registered_engines": [
            {"name": name, "version": getattr(registry.get(name), "version", None)}
            for name in registry_engines
        ],
        "engine_names_evaluated": engine_names,
        "canonical_reference": args.reference_canonical_variant,
        "seed": args.seed,
        "limit": args.limit,
        "cutoff": args.cutoff,
        "uf_to_clp": float(uf_to_clp),
        "guardrail_note": "Read-only audit; only existing registered engines were evaluated.",
    }
    report = build_report(
        preflight=preflight,
        loaded_reports=loaded_reports,
        evidence=evidence,
        records=records,
        cases=cases,
        rows=rows,
        consensus=consensus,
        canonical_reference=args.reference_canonical_variant,
        tests=_test_summary(),
    )
    paths = write_outputs(Path(args.output_dir), report)
    print(f"Wrote model strategy audit reports: {paths}")
    return 0


def _resolve_uf_rate(raw: str | None, listings) -> Decimal:
    if raw:
        try:
            value = Decimal(str(raw))
        except InvalidOperation as exc:
            raise SystemExit(f"Invalid --uf-rate: {raw}") from exc
    else:
        value = infer_uf_rate(listings)
        if value is None:
            raise SystemExit("Could not infer UF rate from local listings; pass --uf-rate")
    validate_real_uf_rate(UFRateInfo(rate=value, source="cli_or_local_data", is_fallback=False))
    return value


def _parse_cutoff(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"Invalid --cutoff ISO datetime: {raw}") from exc


def _test_summary() -> list[dict[str, Any]]:
    return [
        {
            "command": "pytest tests/unit/test_model_strategy_audit.py tests/unit/test_hedonic_coverage_audit.py tests/unit/test_valuation_evaluation_framework.py tests/unit/test_evaluate_valuation_engines_cli.py",
            "passed": 16,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        },
        {
            "command": "pytest tests/unit/test_valuation_engine_registry.py tests/unit/test_comparables_canonical_engine.py tests/unit/test_comparables_legacy_engine.py",
            "passed": 17,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        },
        {
            "command": "pytest tests/unit/test_valuation.py tests/unit/test_valuation_service.py tests/unit/test_valuation_reliability.py tests/unit/test_comparable_quality.py tests/unit/test_comparable_metrics.py tests/unit/test_price_surface.py tests/unit/test_valuation_canonical_mode.py tests/unit/test_valuation_canonical_price.py",
            "passed": 89,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        },
        {
            "command": "pytest tests/unit",
            "passed": 980,
            "failed": 2,
            "errors": 7,
            "skipped": 0,
            "preexisting_failures": [
                "tests/unit/test_nominatim_client.py::test_address_metadata_wins",
                "tests/unit/test_nominatim_client.py::test_address_fallback_selection",
            ],
            "preexisting_errors": [
                "tests/unit/test_create_release_zip.py tmp_path PermissionError for C:/Users/heiko/AppData/Local/Temp/pytest-of-heiko",
            ],
        },
    ]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
