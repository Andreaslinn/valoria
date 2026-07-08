"""Read-only delta audit for hierarchy-aware comparable benchmark."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.entities.listing import Listing  # noqa: E402
from domain.geocoding.hierarchical_microzones import (  # noqa: E402
    HierarchicalMicrozoneAssignment,
    assign_hierarchical_microzone,
)
from domain.geocoding.quality import apply_geocoding_guardrails  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402
from scripts.benchmark_hierarchical_comparables import (  # noqa: E402
    CRITICAL_COMUNAS,
    build_density_index,
)

DEFAULT_BENCHMARK_JSON = Path("reports/microzones/hierarchical_comparables_benchmark_latest.json")
OUTPUT_JSON = "hierarchical_comparable_delta_audit_latest.json"
OUTPUT_MD = "hierarchical_comparable_delta_audit_latest.md"
OUTCOME_EPSILON = 0.005


@dataclass(frozen=True)
class DeltaRow:
    listing_id: int | None
    fingerprint: str
    title: str | None
    comuna: str
    property_type: str
    actual_price_uf: float | None
    baseline_estimate_uf: float | None
    challenger_estimate_uf: float | None
    baseline_ape: float
    challenger_ape: float
    delta_ape: float
    outcome: str
    subject_best_available_level: int | None
    subject_best_available_key: str | None
    subject_signal_type: str
    matched_signal_type: str
    matched_level: int
    same_level_4_count: int
    same_level_3_count: int
    same_level_2_count: int
    same_level_1_count: int
    comuna_only_count: int
    no_shared_location_signal_count: int
    hierarchy_density: int
    density_bucket: str
    warnings: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit hierarchy-aware benchmark deltas.")
    parser.add_argument("--benchmark-json", default=str(DEFAULT_BENCHMARK_JSON))
    parser.add_argument("--output-dir", default="reports/microzones")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    start = perf_counter()
    benchmark = json.loads(Path(args.benchmark_json).read_text(encoding="utf-8"))
    async with get_session_factory()() as session:
        listings = list(await SqlAlchemyListingRepository(session).list_active())

    report = build_delta_audit(
        benchmark=benchmark,
        listings=listings,
        benchmark_path=Path(args.benchmark_json),
        runtime_ms=round((perf_counter() - start) * 1000, 2),
    )
    json_path, md_path = write_outputs(report, Path(args.output_dir))
    print(
        json.dumps(
            {
                "paired_rows": report["summary"]["paired_rows"],
                "improved": report["global_delta"]["improved_count"],
                "worsened": report["global_delta"]["worsened_count"],
                "average_delta": report["global_delta"]["average_delta_ape"],
                "best_threshold": report["threshold_simulations"]["best_by_mape"]["name"],
                "best_threshold_mape": report["threshold_simulations"]["best_by_mape"]["mape_pct"],
                "json": str(json_path),
                "markdown": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_delta_audit(
    *,
    benchmark: dict[str, Any],
    listings: Sequence[Listing],
    benchmark_path: Path,
    runtime_ms: float,
) -> dict[str, Any]:
    active = apply_geocoding_guardrails([listing for listing in listings if listing.is_active])
    assignments = {_listing_key(listing): assign_hierarchical_microzone(listing) for listing in active}
    density_index = build_density_index(active, assignments)
    assignment_by_row_key = _assignment_lookup(active, assignments)
    uf_rate = Decimal(str(benchmark["summary"]["uf_rate_used"]))
    rows = [
        enrich_row(row, assignment_by_row_key, density_index, uf_rate)
        for row in benchmark.get("rows", [])
        if row.get("status") == "ok"
        and row.get("baseline_ape_pct") is not None
        and row.get("challenger_ape_pct") is not None
    ]
    rows = [row for row in rows if row is not None]
    global_delta = summarize_delta(rows)
    by_comuna = summarize_by_comuna(rows)
    thresholds = threshold_simulations(rows)
    signal_types = summarize_signal_types(rows)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": {
            "read_only": True,
            "productive_code_modified": False,
            "benchmark_path": str(benchmark_path),
            "benchmark_generated_at": benchmark.get("generated_at"),
            "property_type": benchmark["summary"].get("property_type"),
            "uf_rate_used": str(uf_rate),
            "paired_rows": len(rows),
            "runtime_ms": runtime_ms,
            "restrictions": [
                "No DB writes.",
                "No migrations.",
                "No AVM/Radar/frontend/scraper/geocoding/backfill/productive scoring changes.",
                "Delta audit reuses latest benchmark output and enriches it read-only.",
            ],
        },
        "global_delta": global_delta,
        "by_comuna": by_comuna,
        "threshold_simulations": thresholds,
        "signal_type_analysis": signal_types,
        "answers": answers(global_delta, by_comuna, thresholds, signal_types),
        "recommendation": recommendation(global_delta, thresholds, signal_types),
        "do_not_do_yet": [
            "Do not persist hierarchical assignments yet.",
            "Do not hard-filter comparables by level_2 or level_3.",
            "Do not promote the hierarchy-aware challenger to productive AVM ranking.",
            "Do not change Radar scoring from this evidence.",
            "Do not run broad external geocoding; use targeted candidates only after extraction is cleaner.",
        ],
        "rows": [asdict(row) for row in rows],
    }


def enrich_row(
    row: dict[str, Any],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    density_index: dict[int, Counter[tuple[str, str, str]]],
    uf_rate: Decimal,
) -> DeltaRow | None:
    key = _row_key(row)
    assignment = assignments.get(key)
    if assignment is None:
        return None
    match_counts = {
        "same_level_4": int(row.get("challenger_match_distribution", {}).get("same_level_4", 0)),
        "same_level_3": int(row.get("challenger_match_distribution", {}).get("same_level_3", 0)),
        "same_level_2": int(row.get("challenger_match_distribution", {}).get("same_level_2", 0)),
        "same_level_1": int(row.get("challenger_match_distribution", {}).get("same_level_1", 0)),
        "comuna_only": int(row.get("challenger_match_distribution", {}).get("comuna_only", 0)),
        "no_shared_location_signal": int(row.get("challenger_match_distribution", {}).get("no_shared_location_signal", 0)),
    }
    matched_level = highest_matched_level(match_counts)
    density = matched_density(assignment, matched_level, row, density_index)
    delta = float(row["ape_delta_pct"])
    baseline_clp = row.get("baseline_estimated_clp")
    challenger_clp = row.get("challenger_estimated_clp")
    actual_clp = row.get("actual_clp")
    return DeltaRow(
        listing_id=row.get("listing_id"),
        fingerprint=str(row.get("fingerprint") or ""),
        title=row.get("title"),
        comuna=normalize_comuna(row.get("comuna")),
        property_type=str(row.get("property_type") or ""),
        actual_price_uf=clp_to_uf(actual_clp, uf_rate),
        baseline_estimate_uf=clp_to_uf(baseline_clp, uf_rate),
        challenger_estimate_uf=clp_to_uf(challenger_clp, uf_rate),
        baseline_ape=float(row["baseline_ape_pct"]),
        challenger_ape=float(row["challenger_ape_pct"]),
        delta_ape=delta,
        outcome=outcome(delta),
        subject_best_available_level=assignment.best_available_level,
        subject_best_available_key=assignment.best_available_key,
        subject_signal_type=signal_type_for(assignment, assignment.best_available_level),
        matched_signal_type=signal_type_for(assignment, matched_level),
        matched_level=matched_level,
        same_level_4_count=match_counts["same_level_4"],
        same_level_3_count=match_counts["same_level_3"],
        same_level_2_count=match_counts["same_level_2"],
        same_level_1_count=match_counts["same_level_1"],
        comuna_only_count=match_counts["comuna_only"],
        no_shared_location_signal_count=match_counts["no_shared_location_signal"],
        hierarchy_density=density,
        density_bucket=density_bucket(density),
        warnings=tuple(assignment.warnings[:8]),
    )


def summarize_delta(rows: Sequence[DeltaRow]) -> dict[str, Any]:
    improved = [row for row in rows if row.outcome == "improved"]
    worsened = [row for row in rows if row.outcome == "worsened"]
    unchanged = [row for row in rows if row.outcome == "unchanged"]
    deltas = [row.delta_ape for row in rows]
    improvements = [abs(row.delta_ape) for row in improved]
    regressions = [row.delta_ape for row in worsened]
    return {
        "paired_rows": len(rows),
        "improved_count": len(improved),
        "worsened_count": len(worsened),
        "unchanged_count": len(unchanged),
        "improved_pct": pct(len(improved), len(rows)),
        "worsened_pct": pct(len(worsened), len(rows)),
        "average_delta_ape": round(mean(deltas), 4) if deltas else None,
        "median_delta_ape": round(percentile(deltas, 50), 4) if deltas else None,
        "p90_improvement_abs_ape": round(percentile(improvements, 90), 4) if improvements else None,
        "p90_regression_ape": round(percentile(regressions, 90), 4) if regressions else None,
        "baseline": metrics(rows, "baseline"),
        "challenger": metrics(rows, "challenger"),
        "top_hierarchy_signals_improved": top_signals(improved),
        "top_hierarchy_signals_worsened": top_signals(worsened),
        "levels_associated_with_improvement": outcome_by_level(improved),
        "levels_associated_with_regression": outcome_by_level(worsened),
        "density_buckets": summarize_groups(rows, lambda row: row.density_bucket),
    }


def summarize_by_comuna(rows: Sequence[DeltaRow]) -> list[dict[str, Any]]:
    grouped: dict[str, list[DeltaRow]] = defaultdict(list)
    for row in rows:
        grouped[row.comuna].append(row)
    result = []
    for comuna in [normalize_comuna(value) for value in CRITICAL_COMUNAS]:
        items = grouped.get(comuna, [])
        improved = [row for row in items if row.outcome == "improved"]
        worsened = [row for row in items if row.outcome == "worsened"]
        unchanged = [row for row in items if row.outcome == "unchanged"]
        result.append(
            {
                "comuna": comuna,
                "evaluations": len(items),
                "improved": len(improved),
                "worsened": len(worsened),
                "unchanged": len(unchanged),
                "net_delta_ape": round(sum(row.delta_ape for row in items), 2) if items else None,
                "mean_delta_ape": round(mean(row.delta_ape for row in items), 4) if items else None,
                "mape_baseline": metrics(items, "baseline")["mape_pct"],
                "mape_challenger": metrics(items, "challenger")["mape_pct"],
                "median_ape_baseline": metrics(items, "baseline")["median_ape_pct"],
                "median_ape_challenger": metrics(items, "challenger")["median_ape_pct"],
                "p90_baseline": metrics(items, "baseline")["p90_ape_pct"],
                "p90_challenger": metrics(items, "challenger")["p90_ape_pct"],
                "signals_that_help": top_signals(improved),
                "signals_that_hurt": top_signals(worsened),
                "top_5_improvements": [row_example(row) for row in sorted(improved, key=lambda item: item.delta_ape)[:5]],
                "top_5_regressions": [row_example(row) for row in sorted(worsened, key=lambda item: item.delta_ape, reverse=True)[:5]],
            }
        )
    return result


def threshold_simulations(rows: Sequence[DeltaRow]) -> dict[str, Any]:
    positive_comunas = {
        comuna
        for comuna, items in group_rows(rows, lambda row: row.comuna).items()
        if sum(row.delta_ape for row in items) < 0
    }
    policies = [
        ("baseline_only", lambda row: False),
        ("current_challenger", lambda row: True),
        ("level_2_density_3_plus", lambda row: row.same_level_2_count > 0 and row.hierarchy_density >= 3),
        ("level_2_density_5_plus", lambda row: row.same_level_2_count > 0 and row.hierarchy_density >= 5),
        ("level_2_density_10_plus", lambda row: row.same_level_2_count > 0 and row.hierarchy_density >= 10),
        ("ignore_level_3", lambda row: row.same_level_3_count == 0 or row.same_level_2_count > 0 or row.same_level_4_count > 0),
        (
            "level_4_or_level_2_density_5_plus",
            lambda row: row.same_level_4_count > 0 or (row.same_level_2_count > 0 and row.hierarchy_density >= 5),
        ),
        ("positive_net_delta_comunas_only", lambda row: row.comuna in positive_comunas),
    ]
    baseline_mape = hybrid_metrics(rows, lambda row: False)["mape_pct"]
    simulations = []
    for name, predicate in policies:
        data = hybrid_metrics(rows, predicate)
        data["name"] = name
        data["used_challenger_count"] = sum(1 for row in rows if predicate(row))
        data["used_challenger_pct"] = pct(data["used_challenger_count"], len(rows))
        data["coverage_pct"] = 100.0
        data["coverage_drop_pct_points"] = 0.0
        data["mape_delta_vs_baseline"] = (
            round(data["mape_pct"] - baseline_mape, 4)
            if data["mape_pct"] is not None and baseline_mape is not None
            else None
        )
        simulations.append(data)
    best = min(
        (item for item in simulations if item["mape_pct"] is not None),
        key=lambda item: item["mape_pct"],
        default={},
    )
    return {
        "positive_net_delta_comunas": sorted(positive_comunas),
        "simulations": simulations,
        "best_by_mape": best,
    }


def summarize_signal_types(rows: Sequence[DeltaRow]) -> dict[str, Any]:
    return {
        "by_subject_signal_type": summarize_groups(rows, lambda row: row.subject_signal_type),
        "by_matched_signal_type": summarize_groups(rows, lambda row: row.matched_signal_type),
        "by_subject_best_level": summarize_groups(rows, lambda row: f"level_{row.subject_best_available_level}"),
        "by_matched_level": summarize_groups(rows, lambda row: f"level_{row.matched_level}"),
    }


def answers(
    global_delta: dict[str, Any],
    by_comuna: Sequence[dict[str, Any]],
    thresholds: dict[str, Any],
    signal_types: dict[str, Any],
) -> dict[str, str]:
    best = thresholds["best_by_mape"]
    positive = [row["comuna"] for row in by_comuna if row["mean_delta_ape"] is not None and row["mean_delta_ape"] < 0]
    negative = [row["comuna"] for row in by_comuna if row["mean_delta_ape"] is not None and row["mean_delta_ape"] > 0]
    matched = signal_types["by_matched_signal_type"]
    helpful = sorted(
        matched.values(),
        key=lambda item: (item["mean_delta_ape"] if item["mean_delta_ape"] is not None else 999, -item["evaluations"]),
    )[:4]
    harmful = sorted(
        matched.values(),
        key=lambda item: (item["mean_delta_ape"] if item["mean_delta_ape"] is not None else -999, item["evaluations"]),
        reverse=True,
    )[:4]
    return {
        "why_global_neutral_or_slightly_worse": (
            "Improved and worsened cases are nearly balanced, median comparable mix remains comuna_only, "
            "and hierarchy bonuses often reshuffle within weak textual/locality evidence rather than dense real microzones."
        ),
        "subset_that_improves": ", ".join(positive) if positive else "no critical comuna has a clearly positive net delta",
        "subset_that_worsens": ", ".join(negative) if negative else "no critical comuna has a clearly negative net delta",
        "helpful_signals": ", ".join(f"{row['group']} ({row['mean_delta_ape']})" for row in helpful),
        "noisy_signals": ", ".join(f"{row['group']} ({row['mean_delta_ape']})" for row in harmful),
        "level_2_secondary_signal": (
            "keep as secondary/diagnostic; threshold simulations do not justify production ranking yet"
        ),
        "level_3_status": "ignore for ranking now except diagnostics; sparse level_3 still has too little density",
        "best_threshold_cut": (
            f"{best.get('name')} with MAPE {best.get('mape_pct')} and challenger usage "
            f"{best.get('used_challenger_pct')}%"
        ),
        "rules_to_harden": "require dense level_2, cap weak textual named corridors, and treat level_3 as hint-only",
        "missing_extraction_or_geocoding": (
            "cleaner street/corridor extraction, better distinction between true metro/avenue corridors and generic text, "
            "then targeted forward geocoding for dense/high-value groups"
        ),
    }


def recommendation(
    global_delta: dict[str, Any],
    thresholds: dict[str, Any],
    signal_types: dict[str, Any],
) -> dict[str, Any]:
    best = thresholds["best_by_mape"]
    baseline = global_delta["baseline"]["mape_pct"]
    best_mape = best.get("mape_pct")
    if best_mape is not None and baseline is not None and best_mape < baseline:
        path = "A for a stricter shadow challenger + C/D before production"
        why = "A subset/hybrid policy beats baseline directionally, but the gain should be validated on fresh snapshots."
    else:
        path = "C + D first, keep hierarchy as diagnostics"
        why = "No threshold cut materially improves MAPE enough to justify productive comparable reranking."
    return {
        "recommended_path": path,
        "why": why,
        "next_steps": [
            "Tighten extraction for weak named corridors and generic textual signals.",
            "Run a stricter shadow challenger using only level_4 and dense level_2.",
            "Target forward geocoding only for dense level_2 groups with high benchmark impact.",
            "Repeat benchmark on a later snapshot before persisting assignments.",
        ],
    }


def hybrid_metrics(rows: Sequence[DeltaRow], use_challenger) -> dict[str, Any]:
    values = [row.challenger_ape if use_challenger(row) else row.baseline_ape for row in rows]
    return {
        "n": len(values),
        "mape_pct": round(mean(values), 4) if values else None,
        "median_ape_pct": round(percentile(values, 50), 4) if values else None,
        "p90_ape_pct": round(percentile(values, 90), 4) if values else None,
    }


def metrics(rows: Sequence[DeltaRow], prefix: str) -> dict[str, Any]:
    values = [getattr(row, f"{prefix}_ape") for row in rows]
    return {
        "n": len(values),
        "mape_pct": round(mean(values), 4) if values else None,
        "median_ape_pct": round(percentile(values, 50), 4) if values else None,
        "p90_ape_pct": round(percentile(values, 90), 4) if values else None,
    }


def summarize_groups(rows: Sequence[DeltaRow], key_fn) -> dict[str, Any]:
    result = {}
    for key, items in group_rows(rows, key_fn).items():
        improved = [row for row in items if row.outcome == "improved"]
        worsened = [row for row in items if row.outcome == "worsened"]
        result[str(key)] = {
            "group": str(key),
            "evaluations": len(items),
            "improved": len(improved),
            "worsened": len(worsened),
            "unchanged": sum(row.outcome == "unchanged" for row in items),
            "mean_delta_ape": round(mean(row.delta_ape for row in items), 4) if items else None,
            "baseline_mape": metrics(items, "baseline")["mape_pct"],
            "challenger_mape": metrics(items, "challenger")["mape_pct"],
        }
    return dict(sorted(result.items(), key=lambda item: item[1]["evaluations"], reverse=True))


def group_rows(rows: Sequence[DeltaRow], key_fn) -> dict[str, list[DeltaRow]]:
    grouped: dict[str, list[DeltaRow]] = defaultdict(list)
    for row in rows:
        grouped[str(key_fn(row))].append(row)
    return grouped


def top_signals(rows: Sequence[DeltaRow]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter[f"subject:{row.subject_signal_type}"] += 1
        counter[f"matched:{row.matched_signal_type}"] += 1
        counter[f"density:{row.density_bucket}"] += 1
    return [{"signal": key, "count": count} for key, count in counter.most_common(12)]


def outcome_by_level(rows: Sequence[DeltaRow]) -> dict[str, int]:
    return dict(Counter(f"subject_level_{row.subject_best_available_level}" for row in rows))


def row_example(row: DeltaRow) -> dict[str, Any]:
    return {
        "listing_id": row.listing_id,
        "title": row.title,
        "baseline_ape": row.baseline_ape,
        "challenger_ape": row.challenger_ape,
        "delta_ape": row.delta_ape,
        "subject_level": row.subject_best_available_level,
        "subject_signal_type": row.subject_signal_type,
        "matched_signal_type": row.matched_signal_type,
        "density_bucket": row.density_bucket,
        "warnings": list(row.warnings[:4]),
    }


def write_outputs(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / OUTPUT_JSON
    md_path = output_dir / OUTPUT_MD
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: dict[str, Any]) -> str:
    global_delta = report["global_delta"]
    thresholds = report["threshold_simulations"]
    answers_data = report["answers"]
    lines = [
        "# Hierarchical Comparable Delta Audit",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Executive Summary",
        "",
        f"- Paired rows: `{report['summary']['paired_rows']}`",
        f"- Improved / worsened / unchanged: `{global_delta['improved_count']}` / `{global_delta['worsened_count']}` / `{global_delta['unchanged_count']}`",
        f"- Average delta APE: `{global_delta['average_delta_ape']}` pts",
        f"- Median delta APE: `{global_delta['median_delta_ape']}` pts",
        f"- Baseline / challenger MAPE: `{global_delta['baseline']['mape_pct']}` / `{global_delta['challenger']['mape_pct']}`",
        f"- P90 improvement: `{global_delta['p90_improvement_abs_ape']}`",
        f"- P90 regression: `{global_delta['p90_regression_ape']}`",
        "",
        "## Why It Was Neutral",
        "",
        answers_data["why_global_neutral_or_slightly_worse"],
        "",
        "## Threshold Simulations",
        "",
        "| Policy | MAPE | Median APE | P90 APE | Used Challenger % | Delta vs Baseline |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in thresholds["simulations"]:
        lines.append(
            f"| `{row['name']}` | {row['mape_pct']} | {row['median_ape_pct']} | "
            f"{row['p90_ape_pct']} | {row['used_challenger_pct']} | {row['mape_delta_vs_baseline']} |"
        )
    lines.extend(
        [
            "",
            "## Critical Comunas",
            "",
            "| Comuna | n | Improved | Worsened | Mean Delta | Baseline MAPE | Challenger MAPE |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["by_comuna"]:
        lines.append(
            f"| `{row['comuna']}` | {row['evaluations']} | {row['improved']} | {row['worsened']} | "
            f"{row['mean_delta_ape']} | {row['mape_baseline']} | {row['mape_challenger']} |"
        )
    lines.extend(
        [
            "",
            "## Signal Types",
            "",
            "| Matched signal | n | Improved | Worsened | Mean Delta | Baseline MAPE | Challenger MAPE |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for _, row in report["signal_type_analysis"]["by_matched_signal_type"].items():
        lines.append(
            f"| `{row['group']}` | {row['evaluations']} | {row['improved']} | {row['worsened']} | "
            f"{row['mean_delta_ape']} | {row['baseline_mape']} | {row['challenger_mape']} |"
        )
    lines.extend(["", "## Explicit Answers", ""])
    for key, value in answers_data.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"- Path: `{report['recommendation']['recommended_path']}`",
            f"- Why: {report['recommendation']['why']}",
            "",
            "## What Not To Do Yet",
            "",
        ]
    )
    for item in report["do_not_do_yet"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Productive Safety",
            "",
            "No DB writes, migrations, AVM/Radar/frontend changes, scrapers, external geocoding, backfills or productive scoring changes were made.",
            "",
        ]
    )
    return "\n".join(lines)


def highest_matched_level(counts: dict[str, int]) -> int:
    if counts["same_level_4"] > 0:
        return 4
    if counts["same_level_3"] > 0:
        return 3
    if counts["same_level_2"] > 0:
        return 2
    if counts["same_level_1"] > 0:
        return 1
    if counts["comuna_only"] > 0:
        return 0
    return -1


def matched_density(
    assignment: HierarchicalMicrozoneAssignment,
    matched_level: int,
    row: dict[str, Any],
    density_index: dict[int, Counter[tuple[str, str, str]]],
) -> int:
    if matched_level < 1:
        return 0
    key = getattr(assignment, f"level_{matched_level}_key")
    if not key:
        return 0
    return int(density_index[matched_level][(key, row.get("comuna"), row.get("property_type"))])


def signal_type_for(assignment: HierarchicalMicrozoneAssignment, level: int | None) -> str:
    if level == 4:
        return "geo_500m"
    if level == 3:
        if assignment.level_3_kind == "intersection":
            return "intersection"
        if assignment.level_3_kind == "street_microzone":
            return "street"
        return str(assignment.level_3_kind or "level_3_unknown")
    if level == 2:
        if assignment.level_2_kind == "metro_corridor":
            return "metro"
        if assignment.level_2_kind == "avenue_corridor":
            return "avenue_corridor"
        if assignment.level_2_kind == "named_corridor":
            return "barrio_sector_textual"
        return str(assignment.level_2_kind or "level_2_unknown")
    if level == 1:
        return "named_area"
    if level == 0:
        return "comuna_only"
    return "no_shared_location_signal"


def density_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value == 2:
        return "2"
    if value < 5:
        return "3-4"
    if value < 10:
        return "5-9"
    if value < 20:
        return "10-19"
    if value < 50:
        return "20-49"
    return "50+"


def outcome(delta: float) -> str:
    if delta < -OUTCOME_EPSILON:
        return "improved"
    if delta > OUTCOME_EPSILON:
        return "worsened"
    return "unchanged"


def clp_to_uf(value: Any, uf_rate: Decimal) -> float | None:
    if value is None or uf_rate <= 0:
        return None
    return round(float(Decimal(str(value)) / uf_rate), 2)


def pct(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator) * 100, 2) if denominator else 0.0


def percentile(values: Sequence[float], pct_value: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * pct_value / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def normalize_comuna(value: Any) -> str:
    return str(value or "").replace("_", " ").strip().lower()


def _assignment_lookup(
    listings: Sequence[Listing],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
) -> dict[str, HierarchicalMicrozoneAssignment]:
    result = {}
    for listing in listings:
        assignment = assignments[_listing_key(listing)]
        if listing.id is not None:
            result[f"id:{listing.id}"] = assignment
        if listing.fingerprint:
            result[f"fp:{listing.fingerprint}"] = assignment
    return result


def _listing_key(listing: Listing) -> str:
    return f"id:{listing.id}" if listing.id is not None else f"fp:{listing.fingerprint}"


def _row_key(row: dict[str, Any]) -> str:
    if row.get("listing_id") is not None:
        return f"id:{row['listing_id']}"
    return f"fp:{row.get('fingerprint')}"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
