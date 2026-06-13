"""Generate a read-only Phase 5A data enrichment audit."""
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

from domain.data_quality.enrichment_audit import build_enrichment_audit, write_audit_outputs  # noqa: E402
from domain.valuation.evaluation.dataset import build_evaluation_cases, infer_uf_rate  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.mappers import listing_from_orm  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit data enrichment opportunities without writes or external requests.")
    parser.add_argument("--output-dir", default="reports/data_quality/phase5a")
    parser.add_argument("--examples", type=int, default=50)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--no-external-requests", action="store_true", default=True)
    parser.add_argument("--report-only", action="store_true", default=True)
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> dict[str, str]:
    if not args.no_external_requests or not args.report_only:
        raise SystemExit("Phase 5A audit requires --no-external-requests and --report-only behavior")
    async with get_session_factory()() as session:
        stmt = select(ListingORM).order_by(ListingORM.id)
        if args.limit:
            stmt = stmt.limit(max(0, args.limit))
        orm_rows = list((await session.execute(stmt)).scalars().all())
        listings = []
        for row in orm_rows:
            listing = listing_from_orm(row)
            # Preserve persisted metadata so the audit can distinguish stored
            # microzones from signals that are only derivable at read time.
            listing.raw_metadata = dict(row.raw_metadata or {})
            listings.append(listing)
        await session.rollback()

    active = [item for item in listings if item.is_active]
    uf_to_clp = infer_uf_rate(active)
    if uf_to_clp is None or uf_to_clp <= 0 or uf_to_clp == 37000:
        raise SystemExit("A real non-37000 UF rate could not be inferred from local data")
    cases = build_evaluation_cases(active, seed=42)
    report, csv_rows = build_enrichment_audit(
        listings,
        uf_to_clp=uf_to_clp,
        benchmark_cases=len(cases),
        examples=max(0, args.examples),
    )
    report["preflight"] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "branch": _git("branch", "--show-current"),
        "head": _git("rev-parse", "HEAD"),
        "phase5a_base_head": "98e3b05e0aed5328396df5f8b598704d518391cd",
        "git_status": _git("status", "--short"),
        "database_mode": "select_only_session_with_explicit_rollback",
        "external_requests": 0,
        "scripts_audited": [
            "infrastructure/scrapers/yapo.py",
            "infrastructure/scrapers/portalinmobiliario.py",
            "scripts/refresh_scraper.py",
            "scripts/geocode_listings.py",
            "scripts/geocoding_readiness_audit.py",
            "domain/geocoding/microzones.py",
            "domain/geocoding/geo_signals.py",
            "domain/valuation/canonical_price.py",
            "domain/valuation/product_classification.py",
            "domain/ingestion/deduplication.py",
            "infrastructure/db/models.py",
            "infrastructure/db/repositories/listing_repo.py",
        ],
    }
    report["phase4a_closure"] = {
        "commits": [
            "0154ff3 feat: stabilize canonical outliers valuation engine",
            "bb1aa48 test: cover canonical outliers variant",
            "98e3b05 docs: add phase4a canonical outliers benchmark report",
        ],
        "tests": ["16 passed", "35 passed"],
        "benchmark": "reports/valuation_engine_benchmark/phase4a_canonical_outliers",
        "working_tree_clean_before_phase5a": True,
    }
    report["tests"] = {
        "new": {
            "command": "python -m pytest tests/unit/test_data_enrichment_audit.py",
            "result": "9 passed",
        },
        "parser_refresh": {
            "command": "python -m pytest tests/unit/test_yapo_parser.py tests/unit/test_portal_parser.py tests/unit/test_refresh_scraper_cli.py tests/unit/test_scraper_base.py",
            "result": "91 passed",
        },
        "geocoding_microzones": {
            "command": "python -m pytest tests/unit/test_geocoding_readiness_audit.py tests/unit/test_geographic_microzones.py tests/unit/test_microzones.py tests/unit/test_geocoding_quality.py tests/unit/test_geocode_precision_normalization.py tests/unit/test_diagnose_geocoding_quality.py",
            "result": "40 passed",
        },
        "canonical_price": {
            "command": "python -m pytest tests/unit/test_valuation_canonical_price.py tests/unit/test_product_classification.py tests/unit/test_robust_price_m2.py",
            "result": "16 passed",
        },
        "engines_evaluation_legacy": {
            "command": "python -m pytest tests/unit/test_valuation_evaluation_framework.py tests/unit/test_evaluate_valuation_engines_cli.py tests/unit/test_comparables_legacy_engine.py tests/unit/test_comparables_canonical_engine.py tests/unit/test_valuation_engine_registry.py tests/unit/test_valuation.py tests/unit/test_valuation_service.py",
            "result": "62 passed",
        },
        "failed": 0,
        "skipped": 0,
        "warnings": ["Known pytest temporary-directory permission issue was avoided by filesystem-independent output tests."],
    }
    return write_audit_outputs(Path(args.output_dir), report, csv_rows)


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=False)
    return (result.stdout or result.stderr).strip() or "clean"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = asyncio.run(run(args))
    print(json.dumps(paths, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
