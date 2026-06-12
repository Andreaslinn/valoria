"""Run offline valuation engine benchmarks."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from core.ports.uf_service import UFRateInfo
from domain.valuation.engines.registry import UnknownValuationEngineError, default_engine_registry
from domain.valuation.evaluation.dataset import build_evaluation_cases, infer_uf_rate
from domain.valuation.evaluation.evaluator import evaluate_engines
from domain.valuation.evaluation.metrics import summarize_results
from domain.valuation.evaluation.reports import write_evaluation_reports
from infrastructure.db.database import get_session_factory
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository
from services.uf_rate import validate_real_uf_rate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate offline valuation engines")
    parser.add_argument("--engines", required=True, help="Comma-separated engine names")
    parser.add_argument("--output-dir", required=True, help="Directory for JSON/Markdown/CSV reports")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of targets")
    parser.add_argument("--property-type", choices=["apartment", "house", "unknown"], default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cutoff", default=None, help="Optional ISO datetime cutoff")
    parser.add_argument("--uf-rate", default=None, help="Real UF/CLP rate. If omitted, infer from local listings.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare dataset but do not run engines")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    engine_names = [item.strip() for item in args.engines.split(",") if item.strip()]
    registry = default_engine_registry()
    for name in engine_names:
        try:
            registry.get(name)
        except UnknownValuationEngineError as exc:
            raise SystemExit(str(exc)) from exc

    cutoff = _parse_cutoff(args.cutoff)
    async with get_session_factory()() as session:
        repo = SqlAlchemyListingRepository(session)
        listings = list(await repo.list_active(limit=None))

    uf_to_clp = _resolve_uf_rate(args.uf_rate, listings)
    cases = build_evaluation_cases(
        listings,
        limit=args.limit,
        property_type=args.property_type,
        seed=args.seed,
        cutoff=cutoff,
    )

    metadata = {
        "engines": engine_names,
        "limit": args.limit,
        "property_type": args.property_type,
        "seed": args.seed,
        "cutoff": args.cutoff,
        "dataset_active_listings": len(listings),
        "dataset_cases": len(cases),
        "dataset_signature": _dataset_signature(cases),
        "uf_to_clp": float(uf_to_clp),
        "uf_rate_source": "cli" if args.uf_rate else "local_listing_price_uf_median",
        "git_commit": _git("rev-parse", "HEAD"),
        "git_status": _git("status", "--short"),
        "dry_run": args.dry_run,
        "filters": [
            "active listings only",
            "positive CLP price",
            "positive built/usable/m2 area",
            "optional property_type",
            "optional cutoff",
            "target listing excluded from candidates",
            "same fingerprint/source external id/url excluded from candidates",
        ],
        "limitations": [
            "Active-listing benchmark; not a full temporal backtest unless cutoff is supplied.",
            "Legacy comparables still use existing production filters and same-comuna candidate logic.",
            "UF rate is data-derived from local canonical UF fields when --uf-rate is omitted.",
        ],
    }

    if args.dry_run:
        rows = []
        summary = {"global": {"total_cases": len(cases), "successful": 0, "failed": 0, "coverage_pct": 0.0}}
    else:
        rows = evaluate_engines(
            cases=cases,
            registry=registry,
            engine_names=engine_names,
            uf_to_clp=uf_to_clp,
        )
        summary = summarize_results(rows)

    paths = write_evaluation_reports(
        output_dir=Path(args.output_dir),
        rows=rows,
        summary=summary,
        metadata=metadata,
    )
    print(f"Wrote reports: {paths}")
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
            raise SystemExit("Could not infer UF rate from local listings; pass --uf-rate with a real non-fallback value")
    validate_real_uf_rate(UFRateInfo(rate=value, source="cli_or_local_data", is_fallback=False))
    return value


def _parse_cutoff(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"Invalid --cutoff ISO datetime: {raw}") from exc


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError:
        return "git_unavailable"
    text = (result.stdout or result.stderr).strip()
    return text or "clean"


def _dataset_signature(cases) -> str:
    payload = [
        {
            "target_id": case.target_id,
            "fingerprint": case.listing.fingerprint,
            "comuna": case.target.comuna,
            "property_type": case.target.property_type,
            "actual_price_clp": str(case.actual_price_clp),
            "candidate_count": len(case.candidates),
        }
        for case in cases
    ]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
