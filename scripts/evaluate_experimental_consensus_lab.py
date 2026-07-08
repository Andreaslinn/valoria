"""Evaluate the experimental consensus lab on active listing asking prices."""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from typing import Any

from core.ports.uf_service import UFRateInfo
from domain.valuation.engines.contracts import EngineContext, EngineResult
from domain.valuation.engines.experimental_lab import (
    DEFAULT_LAB_ENGINE_NAMES,
    run_experimental_engine_lab,
)
from domain.valuation.evaluation.dataset import build_evaluation_cases, infer_uf_rate
from infrastructure.db.database import get_session_factory
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository
from services.uf_rate import validate_real_uf_rate

OUTPUT_DIR = Path("reports/valuation_engine_benchmark/experimental_consensus_lab")
JSON_REPORT = OUTPUT_DIR / "experimental_consensus_benchmark_latest.json"
MD_REPORT = OUTPUT_DIR / "experimental_consensus_benchmark_latest.md"
BASELINE_ENGINE = "comparables_canonical_outliers"
CONSENSUS_ENGINE = "valoria_consensus_v1"
ASKING_PRICE_WARNING = (
    "This benchmark compares estimates against active listing asking prices, not closed sale prices, "
    "bank appraisals, or notarial transaction values. Use it for relative engine comparison only."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the experimental Valoria consensus lab")
    parser.add_argument("--limit", type=int, default=100, help="Maximum target listings to evaluate")
    parser.add_argument("--property-type", choices=["all", "apartment", "house"], default="all")
    parser.add_argument("--uf-rate", default=None, help="Real UF/CLP rate. If omitted, infer from local listings.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument(
        "--engines",
        default=",".join(DEFAULT_LAB_ENGINE_NAMES),
        help="Comma-separated engine names to run in the experimental lab",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    engine_names = tuple(item.strip() for item in args.engines.split(",") if item.strip())
    async with get_session_factory()() as session:
        repo = SqlAlchemyListingRepository(session)
        listings = list(await repo.list_active(limit=None))

    uf_to_clp = _resolve_uf_rate(args.uf_rate, listings)
    property_type = None if args.property_type == "all" else args.property_type
    cases = build_evaluation_cases(
        listings,
        limit=args.limit,
        property_type=property_type,
        seed=args.seed,
    )
    rows: list[dict[str, Any]] = []
    weight_rows: list[dict[str, Any]] = []
    case_summaries: list[dict[str, Any]] = []

    for case_index, case in enumerate(cases):
        context = EngineContext(
            target=case.target,
            candidates=case.candidates,
            uf_to_clp=uf_to_clp,
            metadata=case.metadata,
        )
        start = time.perf_counter()
        run = run_experimental_engine_lab(context, engine_names=engine_names, include_consensus=True)
        elapsed_ms = (time.perf_counter() - start) * 1000
        case_id = f"case-{case_index}"
        all_results = [*run.engine_results]
        if run.consensus_result is not None:
            all_results.append(run.consensus_result)
        for result in all_results:
            rows.append(_row_from_result(case_id, case, result, elapsed_ms=elapsed_ms))
        for item in run.weight_audit:
            weight_rows.append({
                **item,
                "case_id": case_id,
                "target_id": case.target_id,
                "property_type": case.target.property_type,
                "comuna": case.target.comuna,
            })
        case_summaries.append(_case_summary(case_id, case, run))

    summary = {
        "by_engine": _summaries_by(rows, "engine_name"),
        "by_engine_property_type": _summaries_by(rows, lambda row: f"{row['engine_name']}:{row['property_type']}"),
        "by_property_type": _summaries_by(rows, "property_type"),
        "by_geocode_precision": _summaries_by(rows, "geocode_precision"),
        "by_microzone_available": _summaries_by(rows, "microzone_available"),
        "by_house_land_available": _summaries_by(
            [row for row in rows if row["property_type"] == "house"],
            "land_area_available",
        ),
        "by_price_uf_source": _summaries_by(rows, "price_uf_source"),
        "by_consensus_confidence_bucket": _summaries_by(
            [row for row in rows if row["engine_name"] == CONSENSUS_ENGINE],
            "confidence_bucket",
        ),
        "by_comuna": _summaries_by(rows, "comuna", min_count=5),
        "comparisons_vs_baseline": _comparisons_vs_baseline(rows),
        "consensus_vs_best_individual": _consensus_vs_best_individual(rows),
        "weight_audit": _weight_audit_summary(weight_rows),
        "cases_consensus_improves_vs_baseline": _consensus_deltas(case_summaries, improved=True),
        "cases_consensus_worsens_vs_baseline": _consensus_deltas(case_summaries, improved=False),
    }
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "engines": list(engine_names),
        "limit": args.limit,
        "property_type": args.property_type,
        "seed": args.seed,
        "dataset_active_listings": len(listings),
        "dataset_cases": len(cases),
        "uf_to_clp": float(uf_to_clp),
        "uf_rate_source": "cli" if args.uf_rate else "local_listing_price_uf_median",
        "git_commit": _git("rev-parse", "HEAD"),
        "git_status": _git("status", "--short"),
        "warning": ASKING_PRICE_WARNING,
        "read_only": True,
    }
    report = {
        "metadata": metadata,
        "summary": summary,
        "rows": rows,
        "weight_rows": weight_rows,
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / JSON_REPORT.name
    md_path = output_dir / MD_REPORT.name
    json_path.write_text(json.dumps(_json_safe(report), indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_markdown_report(metadata, summary), encoding="utf-8")
    print(f"Wrote reports: {json_path}, {md_path}")
    return 0


def _row_from_result(case_id: str, case, result: EngineResult, *, elapsed_ms: float) -> dict[str, Any]:
    signed = _signed_pct_error(result.estimated_price_clp, case.actual_price_clp)
    return {
        "case_id": case_id,
        "target_id": case.target_id,
        "engine_name": result.engine_name,
        "engine_version": result.engine_version,
        "status": result.status,
        "actual_price_clp": case.actual_price_clp,
        "actual_price_uf": case.actual_price_uf,
        "estimated_price_clp": result.estimated_price_clp,
        "estimated_price_uf": result.estimated_price_uf,
        "absolute_percentage_error": abs(signed) if signed is not None else None,
        "signed_percentage_error": signed,
        "elapsed_ms": round(elapsed_ms, 3),
        "property_type": case.target.property_type,
        "comuna": case.target.comuna,
        "geocode_precision": case.target.geocode_precision or "unknown",
        "microzone_available": bool(_microzone_id(case.target)),
        "land_area_available": bool(case.target.land_area_m2 and case.target.land_area_m2 > 0),
        "price_uf_source": getattr(case.listing, "price_uf_source", None) or "unknown",
        "confidence": result.confidence,
        "confidence_bucket": _confidence_bucket(result.confidence),
        "warnings": list(result.warnings),
        "error_code": result.error_code,
        "coverage": result.coverage_status,
        "data_quality": result.diagnostics.get("data_quality"),
    }


def _case_summary(case_id: str, case, run) -> dict[str, Any]:
    apes = {
        result.engine_name: abs(_signed_pct_error(result.estimated_price_clp, case.actual_price_clp))
        for result in [*run.engine_results, *( [run.consensus_result] if run.consensus_result else [] )]
        if _signed_pct_error(result.estimated_price_clp, case.actual_price_clp) is not None
    }
    return {
        "case_id": case_id,
        "target_id": case.target_id,
        "property_type": case.target.property_type,
        "comuna": case.target.comuna,
        "apes": apes,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    success = [row for row in rows if row["absolute_percentage_error"] is not None]
    apes = [float(row["absolute_percentage_error"]) for row in success]
    statuses = Counter(str(row["status"]) for row in rows)
    return {
        "total_cases": total,
        "success_count": len(success),
        "abstained_count": sum(statuses[status] for status in ("abstained", "insufficient_data", "not_applicable")),
        "failed_count": sum(statuses[status] for status in ("failed", "error", "validation_error")),
        "coverage_pct": round(len(success) / total * 100, 2) if total else 0.0,
        "mape_pct": _mean(apes),
        "median_ape_pct": _median(apes),
        "p75_ape_pct": _percentile(apes, 75),
        "p90_ape_pct": _percentile(apes, 90),
        "error_gt_50_pct": _rate([value for value in apes if value > 50], apes),
    }


def _summaries_by(rows: list[dict[str, Any]], key: str | Any, *, min_count: int = 1) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = key(row) if callable(key) else row.get(key)
        grouped[str(value)].append(row)
    return {
        group_key: _summary(group_rows)
        for group_key, group_rows in sorted(grouped.items())
        if len(group_rows) >= min_count
    }


def _comparisons_vs_baseline(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_case_engine = {(row["case_id"], row["engine_name"]): row for row in rows}
    case_ids = sorted({row["case_id"] for row in rows})
    engines = sorted({row["engine_name"] for row in rows if row["engine_name"] != BASELINE_ENGINE})
    result = {}
    for engine in engines:
        wins = losses = ties = 0
        deltas: list[float] = []
        for case_id in case_ids:
            base = by_case_engine.get((case_id, BASELINE_ENGINE))
            other = by_case_engine.get((case_id, engine))
            if not base or not other:
                continue
            base_ape = base["absolute_percentage_error"]
            other_ape = other["absolute_percentage_error"]
            if base_ape is None or other_ape is None:
                continue
            delta = float(other_ape) - float(base_ape)
            deltas.append(delta)
            if abs(delta) < 1e-9:
                ties += 1
            elif delta < 0:
                wins += 1
            else:
                losses += 1
        result[engine] = {
            "intersection_cases": len(deltas),
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "avg_delta_ape_pct": _mean(deltas),
        }
    return result


def _consensus_vs_best_individual(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["case_id"]].append(row)
    wins = losses = ties = compared = 0
    deltas: list[float] = []
    for group_rows in grouped.values():
        consensus = next((row for row in group_rows if row["engine_name"] == CONSENSUS_ENGINE), None)
        if not consensus or consensus["absolute_percentage_error"] is None:
            continue
        individual_apes = [
            row["absolute_percentage_error"]
            for row in group_rows
            if row["engine_name"] != CONSENSUS_ENGINE and row["absolute_percentage_error"] is not None
        ]
        if not individual_apes:
            continue
        compared += 1
        best = min(float(value) for value in individual_apes)
        delta = float(consensus["absolute_percentage_error"]) - best
        deltas.append(delta)
        if abs(delta) < 1e-9:
            ties += 1
        elif delta < 0:
            wins += 1
        else:
            losses += 1
    return {
        "intersection_cases": compared,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "avg_delta_ape_pct": _mean(deltas),
    }


def _weight_audit_summary(weight_rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in weight_rows:
        grouped[f"{row['property_type']}:{row['engine_name']}"].append(row)
    result = {}
    for key, rows in sorted(grouped.items()):
        weights = [float(row["final_normalized_weight"]) for row in rows]
        reasons = Counter(str(row["weight_reason"]) for row in rows if float(row["final_normalized_weight"]) < 0.05)
        warning_counter: Counter[str] = Counter()
        for row in rows:
            warning_counter.update(str(row.get("weight_reason") or "").split(", "))
        result[key] = {
            "cases": len(rows),
            "avg_weight": _mean(weights),
            "median_weight": _median(weights),
            "p25_weight": _percentile(weights, 25),
            "p75_weight": _percentile(weights, 75),
            "zero_weight_pct": _rate([value for value in weights if value == 0], weights),
            "top_low_weight_reasons": dict(reasons.most_common(5)),
            "top_weight_adjustments": dict(warning_counter.most_common(5)),
        }
    return result


def _consensus_deltas(case_summaries: list[dict[str, Any]], *, improved: bool) -> list[dict[str, Any]]:
    selected = []
    for case in case_summaries:
        apes = case["apes"]
        consensus = apes.get(CONSENSUS_ENGINE)
        baseline = apes.get(BASELINE_ENGINE)
        if consensus is None or baseline is None:
            continue
        delta = consensus - baseline
        if (improved and delta < 0) or (not improved and delta > 0):
            selected.append({**case, "consensus_delta_vs_baseline": round(delta, 2)})
    return sorted(selected, key=lambda item: abs(item["consensus_delta_vs_baseline"]), reverse=True)[:10]


def _markdown_report(metadata: dict[str, Any], summary: dict[str, Any]) -> str:
    lines = [
        "# Experimental Consensus Lab Benchmark",
        "",
        f"Generated at: `{metadata['generated_at']}`",
        "",
        f"> **Warning:** {ASKING_PRICE_WARNING}",
        "",
        "## Executive Summary",
        "",
        f"- Dataset cases: `{metadata['dataset_cases']}` from `{metadata['dataset_active_listings']}` active listings.",
        f"- Engines: `{', '.join(metadata['engines'])}`.",
        "- Recommendation: do not activate production consensus from this benchmark alone; use it to compare relative signal quality.",
        "",
        "## By Engine",
        "",
        "| Engine | Coverage | MAPE | Median APE | P75 | P90 | >50% err | Success | Abstained | Failed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for engine, row in summary["by_engine"].items():
        lines.append(
            f"| {engine} | {row['coverage_pct']} | {_fmt(row['mape_pct'])} | {_fmt(row['median_ape_pct'])} | "
            f"{_fmt(row['p75_ape_pct'])} | {_fmt(row['p90_ape_pct'])} | {_fmt(row['error_gt_50_pct'])} | "
            f"{row['success_count']} | {row['abstained_count']} | {row['failed_count']} |"
        )
    lines.extend([
        "",
        "## Comparisons vs Comparables Outliers",
        "",
        "| Engine | Intersection | Wins | Losses | Ties | Avg Delta APE |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for engine, row in summary["comparisons_vs_baseline"].items():
        lines.append(
            f"| {engine} | {row['intersection_cases']} | {row['wins']} | {row['losses']} | {row['ties']} | {_fmt(row['avg_delta_ape_pct'])} |"
        )
    best = summary["consensus_vs_best_individual"]
    lines.extend([
        "",
        "## Consensus vs Best Individual",
        "",
        f"- Intersection: `{best['intersection_cases']}`",
        f"- Wins/losses/ties: `{best['wins']}/{best['losses']}/{best['ties']}`",
        f"- Avg delta APE: `{_fmt(best['avg_delta_ape_pct'])}`",
        "",
        "## Weight Audit by Property Type",
        "",
        "| Segment/Engine | Avg | Median | P25 | P75 | Zero % |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for key, row in summary["weight_audit"].items():
        lines.append(
            f"| {key} | {_fmt(row['avg_weight'])} | {_fmt(row['median_weight'])} | {_fmt(row['p25_weight'])} | "
            f"{_fmt(row['p75_weight'])} | {_fmt(row['zero_weight_pct'])} |"
        )
    lines.extend([
        "",
        "## Next Recommendation",
        "",
        "- If consensus beats or matches comparables with stable coverage, tune weights by segment next.",
        "- If consensus underperforms, inspect engines with high weight and poor delta APE before any activation.",
        "- Keep production untouched until benchmark uses stronger validation data than active asking prices.",
        "",
    ])
    return "\n".join(lines)


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


def _signed_pct_error(estimate: Decimal | None, actual: Decimal) -> float | None:
    if estimate is None or actual <= 0:
        return None
    return float((estimate - actual) / actual * Decimal("100"))


def _microzone_id(value: object | None) -> str | None:
    metadata = getattr(value, "raw_metadata", None) or {}
    if isinstance(metadata, dict):
        for key in ("microzone_id", "microzone", "microzone_key", "subcomuna", "neighborhood"):
            if metadata.get(key):
                return str(metadata[key])
    return None


def _confidence_bucket(confidence: float | None) -> str:
    if confidence is None:
        return "unknown"
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.55:
        return "medium"
    if confidence >= 0.35:
        return "low"
    return "very_low"


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _median(values: list[float]) -> float | None:
    return round(float(median(values)), 2) if values else None


def _percentile(values: list[float], pct: int) -> float | None:
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


def _rate(selected: list[Any], population: list[Any]) -> float | None:
    return round(len(selected) / len(population) * 100, 2) if population else None


def _fmt(value: Any) -> str:
    return "" if value is None else str(value)


def _git(*args: str) -> str:
    try:
        result = subprocess.run(["git", *args], check=False, capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return "git_unavailable"
    text = (result.stdout or result.stderr).strip()
    return text or "clean"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
