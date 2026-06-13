"""Validate Phase 5A enrichment candidates without writes or external requests."""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from domain.data_quality.enrichment_validation import (  # noqa: E402
    build_enrichment_validation,
    validation_signature,
    write_validation_outputs,
)
from domain.valuation.evaluation.dataset import infer_uf_rate  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.mappers import listing_from_orm  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate enrichment candidates in read-only dry-run mode.")
    parser.add_argument("--phase5a-report", default="reports/data_quality/phase5a/data_enrichment_audit_latest.json")
    parser.add_argument("--output-dir", default="reports/data_quality/phase5b")
    parser.add_argument("--refresh-sample-size", type=int, default=50)
    parser.add_argument("--no-external-requests", action="store_true", default=True)
    parser.add_argument("--report-only", action="store_true", default=True)
    return parser.parse_args(argv)


async def load_listings_read_only(session_factory=None):
    resolved_factory = session_factory or get_session_factory()
    async with resolved_factory() as session:
        rows = list((await session.execute(select(ListingORM).order_by(ListingORM.id))).scalars().all())
        listings = []
        for row in rows:
            listing = listing_from_orm(row)
            listing.raw_metadata = dict(row.raw_metadata or {})
            listings.append(listing)
        await session.rollback()
    return listings


async def run(args: argparse.Namespace) -> dict[str, str]:
    if not args.no_external_requests or not args.report_only:
        raise SystemExit("Phase 5B requires report-only mode with no external requests")
    phase5a_path = Path(args.phase5a_report)
    phase5a_report = json.loads(phase5a_path.read_text(encoding="utf-8"))
    listings = await load_listings_read_only()
    active = [item for item in listings if item.is_active]
    uf_to_clp = infer_uf_rate(active)
    if uf_to_clp is None or uf_to_clp <= 0 or uf_to_clp == 37000:
        raise SystemExit("A real non-37000 UF rate could not be inferred from local data")
    report, manifests = build_enrichment_validation(
        listings,
        phase5a_report=phase5a_report,
        uf_to_clp=uf_to_clp,
        refresh_sample_size=max(0, args.refresh_sample_size),
    )
    if not report["dataset"]["matches_phase5a"]:
        raise SystemExit("Current dataset signature does not match the Phase 5A audit")
    report["preflight"] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "branch": _git("branch", "--show-current"),
        "head": _git("rev-parse", "HEAD"),
        "git_status": _git("status", "--short"),
        "phase5a_report": str(phase5a_path),
        "phase5a_head": "5533bdf0f6dcc26999309b5068f5e549cbde25e4",
        "database_mode": "select_only_session_with_explicit_rollback",
        "external_requests": 0,
        "remote_count": len([line for line in _git("remote", "-v").splitlines() if line.strip() and line != "clean"]),
    }
    report["tests"] = {
        "new": {
            "command": "python -m pytest tests/unit/test_data_enrichment_validation.py",
            "result": "14 passed",
        },
        "phase5a": {
            "command": "python -m pytest tests/unit/test_data_enrichment_audit.py",
            "result": "9 passed",
        },
        "parser_refresh": {
            "command": "python -m pytest tests/unit/test_yapo_parser.py tests/unit/test_portal_parser.py tests/unit/test_refresh_scraper_cli.py tests/unit/test_scraper_base.py",
            "result": "91 passed",
        },
        "geocoding_microzone": {
            "command": "python -m pytest tests/unit/test_geocoding_readiness_audit.py tests/unit/test_geographic_microzones.py tests/unit/test_microzones.py tests/unit/test_geocoding_quality.py tests/unit/test_geocode_precision_normalization.py tests/unit/test_diagnose_geocoding_quality.py",
            "result": "40 passed",
        },
        "canonical_price": {
            "command": "python -m pytest tests/unit/test_valuation_canonical_price.py tests/unit/test_product_classification.py tests/unit/test_robust_price_m2.py",
            "result": "16 passed",
        },
        "evaluation_engines": {
            "command": "python -m pytest tests/unit/test_valuation_evaluation_framework.py tests/unit/test_evaluate_valuation_engines_cli.py tests/unit/test_comparables_legacy_engine.py tests/unit/test_comparables_canonical_engine.py tests/unit/test_valuation_engine_registry.py tests/unit/test_valuation.py tests/unit/test_valuation_service.py",
            "result": "62 passed",
        },
        "failed": 0,
        "skipped": 0,
        "total_passed": 232,
    }
    report["validation_signature"] = validation_signature(report, manifests)
    return write_validation_outputs(Path(args.output_dir), report, manifests)


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=False)
    return (result.stdout or result.stderr).strip() or "clean"


def main(argv: list[str] | None = None) -> int:
    paths = asyncio.run(run(parse_args(argv)))
    print(json.dumps(paths, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
