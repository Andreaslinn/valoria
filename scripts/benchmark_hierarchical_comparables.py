"""Read-only hierarchy-aware comparable benchmark.

This script benchmarks a challenger ranking that uses hierarchical microzones
as a diagnostic bonus/penalty. It does not modify AVM, Radar, DB rows,
migrations, frontend code, scraping, geocoding, or productive scoring.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constants import MIN_COMPARABLES, TOP_N_COMPARABLES  # noqa: E402
from core.entities.listing import Listing, Property  # noqa: E402
from core.exceptions import InsufficientDataError, ValidationError  # noqa: E402
from core.normalization.property_type import normalize_property_type as _property_type  # noqa: E402
from core.value_objects.score import Score  # noqa: E402
from domain.geocoding.hierarchical_microzones import (  # noqa: E402
    HierarchicalMicrozoneAssignment,
    assign_hierarchical_microzone,
)
from domain.geocoding.quality import apply_geocoding_guardrails  # noqa: E402
from domain.radar.price_basis import canonical_discount_pct, radar_price_basis  # noqa: E402
from domain.valuation.comparable_metrics import comparable_price_m2_iqr_pct  # noqa: E402
from domain.valuation.comparables import (  # noqa: E402
    filter_candidates,
    score_and_rank,
    valuate_with_comparables,
)
from domain.valuation.hierarchical_comparable_diagnostics import (  # noqa: E402
    HierarchicalComparableDiagnostics,
    diagnose_hierarchical_comparable,
    hierarchy_aware_rerank,
)
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import UFRateORM  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402
from scripts.audit_radar_funnel import EvaluatedRow, evaluate_universe  # noqa: E402

CRITICAL_COMUNAS = (
    "las condes",
    "providencia",
    "nunoa",
    "santiago",
    "vitacura",
    "estacion central",
    "san miguel",
    "la florida",
    "macul",
    "independencia",
)
OUTPUT_JSON = "hierarchical_comparables_benchmark_latest.json"
OUTPUT_MD = "hierarchical_comparables_benchmark_latest.md"


@dataclass(frozen=True)
class BenchmarkRow:
    listing_id: int | None
    fingerprint: str
    title: str | None
    comuna: str
    property_type: str
    actual_clp: float
    baseline_estimated_clp: float | None
    challenger_estimated_clp: float | None
    baseline_ape_pct: float | None
    challenger_ape_pct: float | None
    ape_delta_pct: float | None
    baseline_comparables_used: int
    challenger_comparables_used: int
    eligible_comparables: int
    baseline_dispersion_uf_m2: float | None
    challenger_dispersion_uf_m2: float | None
    baseline_same_level_4_ratio: float
    baseline_same_level_3_ratio: float
    baseline_same_level_2_ratio: float
    baseline_same_level_1_ratio: float
    baseline_comuna_only_ratio: float
    baseline_no_shared_location_signal_ratio: float
    challenger_same_level_4_ratio: float
    challenger_same_level_3_ratio: float
    challenger_same_level_2_ratio: float
    challenger_same_level_1_ratio: float
    challenger_comuna_only_ratio: float
    challenger_no_shared_location_signal_ratio: float
    challenger_match_distribution: dict[str, int]
    subject_geo_strength: str
    status: str
    reason: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark hierarchy-aware comparable reranking.")
    parser.add_argument("--uf-rate", type=Decimal)
    parser.add_argument("--output-dir", default="reports/microzones")
    parser.add_argument("--property-type", default="apartment", choices=["apartment", "house"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--min-samples", type=int, default=5)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    start = perf_counter()
    async with get_session_factory()() as session:
        listings = list(await SqlAlchemyListingRepository(session).list_active())
        uf_rate = args.uf_rate or await _latest_uf_rate(session)
    if uf_rate is None:
        raise SystemExit("No UF rate provided and no local uf_rates row found. Pass --uf-rate.")

    report = run_benchmark(
        listings,
        uf_rate=uf_rate,
        property_type=args.property_type,
        limit=args.limit,
        min_samples=args.min_samples,
        runtime_ms=0.0,
    )
    report["summary"]["runtime_ms"] = round((perf_counter() - start) * 1000, 2)
    json_path, md_path = write_outputs(report, Path(args.output_dir))
    print(
        json.dumps(
            {
                "property_type": args.property_type,
                "targets": report["summary"]["total_evaluable_targets"],
                "baseline_coverage_pct": report["summary"]["coverage_baseline_pct"],
                "challenger_coverage_pct": report["summary"]["coverage_challenger_pct"],
                "baseline_mape_pct": report["summary"]["mape_baseline_pct"],
                "challenger_mape_pct": report["summary"]["mape_challenger_pct"],
                "json": str(json_path),
                "markdown": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def run_benchmark(
    listings: Sequence[Listing],
    *,
    uf_rate: Decimal,
    property_type: str = "apartment",
    limit: int | None = None,
    min_samples: int = 5,
    runtime_ms: float = 0.0,
) -> dict[str, Any]:
    active = apply_geocoding_guardrails([listing for listing in listings if listing.is_active])
    active = [listing for listing in active if _has_valid_area(listing) and listing.price.clp > 0]
    assignments = {_listing_key(listing): assign_hierarchical_microzone(listing) for listing in active}
    density_index = build_density_index(active, assignments)
    targets = [
        listing for listing in _deduplicate_targets(active)
        if _property_type(listing) == property_type
    ]
    targets.sort(key=lambda listing: int(listing.id or 0))
    if limit is not None:
        targets = targets[:limit]

    rows = [
        evaluate_listing(
            target,
            active,
            assignments=assignments,
            density_index=density_index,
            uf_rate=uf_rate,
        )
        for target in targets
    ]
    successful = [row for row in rows if row.status == "ok"]
    evaluated = evaluate_universe(active, uf_rate)
    radar = radar_diagnostics(evaluated, rows, uf_rate=uf_rate, property_type=property_type)
    summary = global_summary(
        rows,
        active=active,
        uf_rate=uf_rate,
        property_type=property_type,
        min_samples=min_samples,
        runtime_ms=runtime_ms,
    )
    by_comuna = comuna_summary(rows)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": summary,
        "methodology": methodology(property_type),
        "global_metrics": {
            "baseline": metric_block(successful, prefix="baseline"),
            "challenger": metric_block(successful, prefix="challenger"),
            "delta": delta_block(successful),
            "hierarchy_mix_baseline": hierarchy_mix(successful, prefix="baseline"),
            "hierarchy_mix_challenger": hierarchy_mix(successful, prefix="challenger"),
        },
        "density": density_summary(density_index),
        "by_comuna": by_comuna,
        "radar_diagnostics": radar,
        "explicit_answers": explicit_answers(summary, by_comuna, radar),
        "recommendation": recommendation(summary, radar),
        "do_not_do_yet": [
            "Do not persist assignments from this benchmark.",
            "Do not hard-filter level_2 or level_3 comparables.",
            "Do not change Radar scoring or AVM productive scoring.",
            "Do not run broad external geocoding or backfills.",
            "Do not use sparse level_3 street signals as strong comparable filters.",
        ],
        "rows": [asdict(row) for row in rows],
    }


def evaluate_listing(
    target_listing: Listing,
    active: Sequence[Listing],
    *,
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    density_index: dict[int, Counter[tuple[str, str, str]]],
    uf_rate: Decimal,
) -> BenchmarkRow:
    actual_clp = float(target_listing.price.clp)
    target = listing_as_property(target_listing)
    candidates = [
        listing for listing in exclude_leakage(target_listing, active)
        if _property_type(listing) == _property_type(target_listing)
    ]
    eligible = filter_candidates(target, candidates)
    base_failed = _base_row(target_listing, actual_clp, len(eligible))
    if len(eligible) < MIN_COMPARABLES:
        return _replace_row(base_failed, status="failed", reason="insufficient_comparables")

    try:
        baseline_run = valuate_with_comparables(target, candidates, uf_rate)
    except (InsufficientDataError, ValidationError) as exc:
        return _replace_row(base_failed, status="failed", reason=type(exc).__name__)

    initial_scored = score_and_rank(target, eligible)
    subject_assignment = assignments[_listing_key(target_listing)]
    challenger = hierarchy_aware_rerank(
        initial_scored,
        subject_assignment=subject_assignment,
        comparable_assignments=assignments,
        density_index=density_index,
        listing_key_fn=_listing_key,
        top_n=TOP_N_COMPARABLES,
    )
    if len(challenger) < MIN_COMPARABLES:
        return _replace_row(base_failed, status="failed", reason="challenger_insufficient_comparables")

    baseline_scored = baseline_run.scored_comparables
    baseline_comparables = [listing for _, listing in baseline_scored]
    challenger_scored = [(score, listing) for score, listing, _ in challenger]
    challenger_comparables = [listing for _, listing, _ in challenger]
    challenger_estimate = weighted_total_estimate(target, challenger_scored)
    baseline_estimate = float(baseline_run.result.estimated_price.clp)
    baseline_ape = ape_pct(baseline_estimate, actual_clp)
    challenger_ape = ape_pct(challenger_estimate, actual_clp)
    baseline_mix = comparable_mix(target_listing, baseline_comparables, assignments, density_index)
    challenger_mix = comparable_mix_from_diagnostics([diagnostics for _, _, diagnostics in challenger])
    return BenchmarkRow(
        listing_id=target_listing.id,
        fingerprint=target_listing.fingerprint,
        title=target_listing.title,
        comuna=target_listing.comuna,
        property_type=_property_type(target_listing),
        actual_clp=round(actual_clp, 2),
        baseline_estimated_clp=round(baseline_estimate, 2),
        challenger_estimated_clp=round(challenger_estimate, 2),
        baseline_ape_pct=baseline_ape,
        challenger_ape_pct=challenger_ape,
        ape_delta_pct=round(challenger_ape - baseline_ape, 2),
        baseline_comparables_used=len(baseline_comparables),
        challenger_comparables_used=len(challenger_comparables),
        eligible_comparables=len(eligible),
        baseline_dispersion_uf_m2=dispersion_uf_m2(baseline_comparables, uf_rate),
        challenger_dispersion_uf_m2=dispersion_uf_m2(challenger_comparables, uf_rate),
        baseline_same_level_4_ratio=baseline_mix["same_level_4_ratio"],
        baseline_same_level_3_ratio=baseline_mix["same_level_3_ratio"],
        baseline_same_level_2_ratio=baseline_mix["same_level_2_ratio"],
        baseline_same_level_1_ratio=baseline_mix["same_level_1_ratio"],
        baseline_comuna_only_ratio=baseline_mix["comuna_only_ratio"],
        baseline_no_shared_location_signal_ratio=baseline_mix["no_shared_location_signal_ratio"],
        challenger_same_level_4_ratio=challenger_mix["same_level_4_ratio"],
        challenger_same_level_3_ratio=challenger_mix["same_level_3_ratio"],
        challenger_same_level_2_ratio=challenger_mix["same_level_2_ratio"],
        challenger_same_level_1_ratio=challenger_mix["same_level_1_ratio"],
        challenger_comuna_only_ratio=challenger_mix["comuna_only_ratio"],
        challenger_no_shared_location_signal_ratio=challenger_mix["no_shared_location_signal_ratio"],
        challenger_match_distribution=challenger_mix["match_distribution"],
        subject_geo_strength=next(iter(challenger), (None, None, None))[2].subject_geo_strength if challenger else "none",
        status="ok",
        reason=None,
    )


def global_summary(
    rows: Sequence[BenchmarkRow],
    *,
    active: Sequence[Listing],
    uf_rate: Decimal,
    property_type: str,
    min_samples: int,
    runtime_ms: float,
) -> dict[str, Any]:
    successful = [row for row in rows if row.status == "ok"]
    status = "ok" if len(successful) >= min_samples else "insufficient_data"
    return {
        "status": status,
        "read_only": True,
        "productive_code_modified": False,
        "uf_rate_used": str(uf_rate),
        "property_type": property_type,
        "active_listings": len(active),
        "active_in_scope": sum(1 for listing in active if _property_type(listing) == property_type),
        "total_evaluable_targets": len(rows),
        "successful_paired_evaluations": len(successful),
        "coverage_baseline_pct": pct(sum(row.baseline_estimated_clp is not None for row in rows), len(rows)),
        "coverage_challenger_pct": pct(sum(row.challenger_estimated_clp is not None for row in rows), len(rows)),
        "mape_baseline_pct": metric_block(successful, prefix="baseline")["mape_pct"],
        "mape_challenger_pct": metric_block(successful, prefix="challenger")["mape_pct"],
        "median_ape_baseline_pct": metric_block(successful, prefix="baseline")["median_ape_pct"],
        "median_ape_challenger_pct": metric_block(successful, prefix="challenger")["median_ape_pct"],
        "p90_ape_baseline_pct": metric_block(successful, prefix="baseline")["p90_ape_pct"],
        "p90_ape_challenger_pct": metric_block(successful, prefix="challenger")["p90_ape_pct"],
        "runtime_ms": runtime_ms,
    }


def metric_block(rows: Sequence[BenchmarkRow], *, prefix: str) -> dict[str, Any]:
    values = [
        getattr(row, f"{prefix}_ape_pct")
        for row in rows
        if getattr(row, f"{prefix}_ape_pct") is not None
    ]
    dispersions = [
        getattr(row, f"{prefix}_dispersion_uf_m2")
        for row in rows
        if getattr(row, f"{prefix}_dispersion_uf_m2") is not None
    ]
    return {
        "n": len(values),
        "mape_pct": round(mean(values), 2) if values else None,
        "median_ape_pct": round(percentile(values, 50), 2) if values else None,
        "p90_ape_pct": round(percentile(values, 90), 2) if values else None,
        "dispersion_uf_m2_p50": round(percentile(dispersions, 50), 2) if dispersions else None,
        "dispersion_uf_m2_p90": round(percentile(dispersions, 90), 2) if dispersions else None,
    }


def delta_block(rows: Sequence[BenchmarkRow]) -> dict[str, Any]:
    paired = [row for row in rows if row.ape_delta_pct is not None]
    improved = [row for row in paired if row.ape_delta_pct < 0]
    worsened = [row for row in paired if row.ape_delta_pct > 0]
    unchanged = [row for row in paired if row.ape_delta_pct == 0]
    deltas = [row.ape_delta_pct for row in paired if row.ape_delta_pct is not None]
    return {
        "paired": len(paired),
        "improved_count": len(improved),
        "worsened_count": len(worsened),
        "unchanged_count": len(unchanged),
        "improved_pct": pct(len(improved), len(paired)),
        "worsened_pct": pct(len(worsened), len(paired)),
        "mean_ape_delta_pct": round(mean(deltas), 2) if deltas else None,
        "median_ape_delta_pct": round(percentile(deltas, 50), 2) if deltas else None,
    }


def hierarchy_mix(rows: Sequence[BenchmarkRow], *, prefix: str) -> dict[str, Any]:
    return {
        "same_level_4_ratio": quantiles(getattr(row, f"{prefix}_same_level_4_ratio") for row in rows),
        "same_level_3_ratio": quantiles(getattr(row, f"{prefix}_same_level_3_ratio") for row in rows),
        "same_level_2_ratio": quantiles(getattr(row, f"{prefix}_same_level_2_ratio") for row in rows),
        "same_level_1_ratio": quantiles(getattr(row, f"{prefix}_same_level_1_ratio") for row in rows),
        "comuna_only_ratio": quantiles(getattr(row, f"{prefix}_comuna_only_ratio") for row in rows),
        "no_shared_location_signal_ratio": quantiles(getattr(row, f"{prefix}_no_shared_location_signal_ratio") for row in rows),
    }


def comuna_summary(rows: Sequence[BenchmarkRow]) -> list[dict[str, Any]]:
    grouped: dict[str, list[BenchmarkRow]] = defaultdict(list)
    for row in rows:
        grouped[normalize_comuna(row.comuna)].append(row)
    result = []
    for comuna in CRITICAL_COMUNAS:
        key = normalize_comuna(comuna)
        items = grouped.get(key, [])
        successful = [row for row in items if row.status == "ok"]
        distribution = Counter()
        for row in successful:
            distribution.update(row.challenger_match_distribution)
        improved = sorted(
            [row for row in successful if row.ape_delta_pct is not None and row.ape_delta_pct < 0],
            key=lambda row: row.ape_delta_pct or 0,
        )[:5]
        worsened = sorted(
            [row for row in successful if row.ape_delta_pct is not None and row.ape_delta_pct > 0],
            key=lambda row: row.ape_delta_pct or 0,
            reverse=True,
        )[:5]
        result.append(
            {
                "comuna": key,
                "evaluable_targets": len(items),
                "evaluated": len(successful),
                "coverage_baseline_pct": pct(sum(row.baseline_estimated_clp is not None for row in items), len(items)),
                "coverage_challenger_pct": pct(sum(row.challenger_estimated_clp is not None for row in items), len(items)),
                "mape_baseline_pct": metric_block(successful, prefix="baseline")["mape_pct"],
                "mape_challenger_pct": metric_block(successful, prefix="challenger")["mape_pct"],
                "median_ape_baseline_pct": metric_block(successful, prefix="baseline")["median_ape_pct"],
                "median_ape_challenger_pct": metric_block(successful, prefix="challenger")["median_ape_pct"],
                "p90_baseline_pct": metric_block(successful, prefix="baseline")["p90_ape_pct"],
                "p90_challenger_pct": metric_block(successful, prefix="challenger")["p90_ape_pct"],
                "hierarchy_match_distribution": dict(distribution),
                "examples_improved": [example(row) for row in improved],
                "examples_worsened": [example(row) for row in worsened],
            }
        )
    return result


def radar_diagnostics(
    evaluated: Sequence[EvaluatedRow],
    benchmark_rows: Sequence[BenchmarkRow],
    *,
    uf_rate: Decimal,
    property_type: str,
) -> dict[str, Any]:
    rows_by_key = {_row_key(row): row for row in benchmark_rows if row.status == "ok"}
    opportunities = [row for row in evaluated if row.candidate]
    in_scope = [row for row in opportunities if _property_type(row.listing) == property_type]
    over_60 = [row for row in in_scope if (row.audit.discount_pct or 0) > 60]
    changed = []
    for radar_row in over_60:
        benchmark = rows_by_key.get(_listing_key(radar_row.listing))
        if benchmark is None or benchmark.challenger_estimated_clp is None:
            changed.append({"status": "no_benchmark_row", "listing_id": radar_row.listing.id})
            continue
        basis = radar_price_basis(radar_row.listing)
        challenger_discount = canonical_discount_pct(
            market_price_clp=Decimal(str(benchmark.challenger_estimated_clp)),
            listing_basis=basis,
            uf_to_clp=uf_rate,
        )
        baseline_discount = canonical_discount_pct(
            market_price_clp=Decimal(str(benchmark.baseline_estimated_clp or 0)),
            listing_basis=basis,
            uf_to_clp=uf_rate,
        )
        changed.append(
            {
                "status": "ok",
                "listing_id": radar_row.listing.id,
                "comuna": radar_row.audit.comuna,
                "baseline_discount_pct": round((baseline_discount or 0) * 100, 2) if baseline_discount is not None else None,
                "challenger_discount_pct": round((challenger_discount or 0) * 100, 2) if challenger_discount is not None else None,
                "baseline_extreme": baseline_discount is not None and baseline_discount > 0.60,
                "challenger_extreme": challenger_discount is not None and challenger_discount > 0.60,
                "has_hierarchy_density": any(
                    value > 0 for key, value in benchmark.challenger_match_distribution.items()
                    if key in {"same_level_4", "same_level_3", "same_level_2"}
                ),
                "title": radar_row.audit.title,
            }
        )
    ok = [row for row in changed if row["status"] == "ok"]
    lowered = [
        row for row in ok
        if row["baseline_discount_pct"] is not None
        and row["challenger_discount_pct"] is not None
        and row["challenger_discount_pct"] < row["baseline_discount_pct"]
    ]
    worsened = [
        row for row in ok
        if row["baseline_discount_pct"] is not None
        and row["challenger_discount_pct"] is not None
        and row["challenger_discount_pct"] > row["baseline_discount_pct"]
    ]
    return {
        "radar_opportunities_total": len(opportunities),
        "radar_opportunities_in_scope": len(in_scope),
        "discount_over_60_in_scope": len(over_60),
        "discount_over_60_with_benchmark": len(ok),
        "discount_over_60_still_extreme": sum(row["challenger_extreme"] for row in ok),
        "discount_over_60_lowered": len(lowered),
        "discount_over_60_worsened": len(worsened),
        "discount_over_60_without_hierarchy_density": sum(not row["has_hierarchy_density"] for row in ok),
        "examples_over_60": ok[:30],
        "scope_note": f"Radar diagnostic is restricted to property_type={property_type}; houses are not part of the primary benchmark.",
    }


def explicit_answers(summary: dict[str, Any], by_comuna: Sequence[dict[str, Any]], radar: dict[str, Any]) -> dict[str, str]:
    baseline = summary["mape_baseline_pct"]
    challenger = summary["mape_challenger_pct"]
    if baseline is None or challenger is None:
        accuracy_answer = "insufficient paired benchmark data"
    elif challenger + 0.5 < baseline:
        accuracy_answer = "improves MAPE directionally"
    elif challenger <= baseline + 0.5:
        accuracy_answer = "mostly preserves MAPE and explains confidence/locality"
    else:
        accuracy_answer = "does not improve MAPE yet; useful mainly as diagnostic"
    benefiting = sorted(
        (
            row for row in by_comuna
            if row["mape_baseline_pct"] is not None and row["mape_challenger_pct"] is not None
        ),
        key=lambda row: row["mape_challenger_pct"] - row["mape_baseline_pct"],
    )[:5]
    return {
        "does_hierarchy_improve_mape": accuracy_answer,
        "level_2_secondary_signal": "yes, but only as ranking/diagnostic signal with density thresholds",
        "level_3_status": "wait for more density; sparse level_3 is hint-only",
        "use_for_comparable_reranking": "possible as a shadow/challenger path; needs holdout/stability before production",
        "use_only_as_diagnostic": "safe today and immediately useful for confidence explanation",
        "persist_assignments": "no; keep read-only until taxonomy and benchmark stability are versioned",
        "best_benefit_comunas": ", ".join(row["comuna"] for row in benefiting) if benefiting else "insufficient data",
        "radar_extreme_effect": (
            f"{radar['discount_over_60_still_extreme']} still extreme, "
            f"{radar['discount_over_60_lowered']} lowered, "
            f"{radar['discount_over_60_worsened']} worsened"
        ),
    }


def recommendation(summary: dict[str, Any], radar: dict[str, Any]) -> dict[str, Any]:
    baseline = summary["mape_baseline_pct"]
    challenger = summary["mape_challenger_pct"]
    coverage_gap = abs(summary["coverage_baseline_pct"] - summary["coverage_challenger_pct"])
    if baseline is not None and challenger is not None and challenger <= baseline + 0.5 and coverage_gap <= 1.0:
        path = "A in shadow, B diagnostic in product wording later, D targeted before persistence"
        why = "The challenger preserves coverage and does not materially hurt MAPE, but density is still uneven."
    else:
        path = "B + D first, keep A out of production"
        why = "Hierarchy is useful for diagnostics/confidence, but the benchmark is not strong enough for productive reranking."
    return {
        "recommended_path": path,
        "why": why,
        "radar_note": radar["scope_note"],
    }


def methodology(property_type: str) -> dict[str, Any]:
    return {
        "read_only": True,
        "productive_code_modified": False,
        "baseline": "current comparable filters and score ranking via valuate_with_comparables",
        "challenger": "same eligible pool, hierarchy-aware score bonus/penalty, no exclusions by microzone",
        "scope": f"primary benchmark restricted to {property_type}",
        "coverage_rule": "challenger preserves baseline candidate pool; failures should match baseline unless weights are invalid",
    }


def build_density_index(
    listings: Sequence[Listing],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
) -> dict[int, Counter[tuple[str, str, str]]]:
    index = {level: Counter() for level in (1, 2, 3, 4)}
    for listing in listings:
        assignment = assignments[_listing_key(listing)]
        for level in (1, 2, 3, 4):
            key = getattr(assignment, f"level_{level}_key")
            if key:
                index[level][(key, listing.comuna, _property_type(listing))] += 1
    return index


def density_summary(index: dict[int, Counter[tuple[str, str, str]]]) -> dict[str, Any]:
    return {
        f"level_{level}": {
            "groups": len(counter),
            "useful_3_plus": sum(1 for value in counter.values() if value >= 3),
            "useful_5_plus": sum(1 for value in counter.values() if value >= 5),
            "top_groups": [
                {"key": key, "comuna": comuna, "property_type": prop, "count": count}
                for (key, comuna, prop), count in counter.most_common(10)
            ],
        }
        for level, counter in index.items()
    }


def comparable_mix(
    subject: Listing,
    comparables: Sequence[Listing],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    density_index: dict[int, Counter[tuple[str, str, str]]],
) -> dict[str, Any]:
    diagnostics = [
        diagnose_hierarchical_comparable(
            assignments[_listing_key(subject)],
            assignments[_listing_key(comparable)],
            density_index=density_index,
            comparable_comuna=comparable.comuna,
            property_type=_property_type(comparable),
        )
        for comparable in comparables
    ]
    return comparable_mix_from_diagnostics(diagnostics)


def comparable_mix_from_diagnostics(diagnostics: Sequence[HierarchicalComparableDiagnostics]) -> dict[str, Any]:
    total = len(diagnostics)
    distribution = Counter(match_label(item) for item in diagnostics)
    return {
        "same_level_4_ratio": ratio(distribution["same_level_4"], total),
        "same_level_3_ratio": ratio(distribution["same_level_3"], total),
        "same_level_2_ratio": ratio(distribution["same_level_2"], total),
        "same_level_1_ratio": ratio(distribution["same_level_1"], total),
        "comuna_only_ratio": ratio(distribution["comuna_only"], total),
        "no_shared_location_signal_ratio": ratio(distribution["no_shared_location_signal"], total),
        "match_distribution": dict(distribution),
    }


def match_label(item: HierarchicalComparableDiagnostics) -> str:
    if item.same_level_4:
        return "same_level_4"
    if item.same_level_3:
        return "same_level_3"
    if item.same_level_2:
        return "same_level_2"
    if item.same_level_1:
        return "same_level_1"
    if item.comuna_only:
        return "comuna_only"
    return "no_shared_location_signal"


def weighted_total_estimate(target: Property, scored: Sequence[tuple[Score, Listing]]) -> float:
    area = built_area(target)
    if area is None or area <= 0:
        raise ValidationError("target area must be positive")
    total_weight = Decimal("0")
    weighted_ppm2 = Decimal("0")
    for score, listing in scored:
        candidate_area = built_area(listing)
        if candidate_area is None or candidate_area <= 0:
            continue
        weight = Decimal(str(score.value))
        weighted_ppm2 += weight * (listing.price.clp / Decimal(str(candidate_area)))
        total_weight += weight
    if total_weight <= 0:
        raise InsufficientDataError("hierarchy challenger weights sum to zero")
    return float((weighted_ppm2 / total_weight) * Decimal(str(area)))


def dispersion_uf_m2(comparables: Sequence[Listing], uf_rate: Decimal) -> float | None:
    value = comparable_price_m2_iqr_pct(comparables)
    if value is None:
        return None
    _ = uf_rate
    return round(float(value), 2)


def write_outputs(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / OUTPUT_JSON
    md_path = output_dir / OUTPUT_MD
    json_path.write_text(json.dumps(json_safe(report), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    delta = report["global_metrics"]["delta"]
    answers = report["explicit_answers"]
    radar = report["radar_diagnostics"]
    lines = [
        "# Hierarchical Comparables Benchmark",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Executive Summary",
        "",
        f"- Scope: `{summary['property_type']}`",
        f"- Evaluable targets: `{summary['total_evaluable_targets']}`",
        f"- Paired evaluations: `{summary['successful_paired_evaluations']}`",
        f"- Coverage baseline/challenger: `{summary['coverage_baseline_pct']}%` / `{summary['coverage_challenger_pct']}%`",
        f"- MAPE baseline/challenger: `{summary['mape_baseline_pct']}%` / `{summary['mape_challenger_pct']}%`",
        f"- Median APE baseline/challenger: `{summary['median_ape_baseline_pct']}%` / `{summary['median_ape_challenger_pct']}%`",
        f"- P90 APE baseline/challenger: `{summary['p90_ape_baseline_pct']}%` / `{summary['p90_ape_challenger_pct']}%`",
        f"- Improved/worsened/unchanged: `{delta['improved_count']}` / `{delta['worsened_count']}` / `{delta['unchanged_count']}`",
        f"- Mean APE delta: `{delta['mean_ape_delta_pct']}` pts",
        "",
        "## Hierarchy Mix",
        "",
        "| Metric | Baseline p50 | Challenger p50 |",
        "| --- | ---: | ---: |",
    ]
    baseline_mix = report["global_metrics"]["hierarchy_mix_baseline"]
    challenger_mix = report["global_metrics"]["hierarchy_mix_challenger"]
    for key in (
        "same_level_4_ratio",
        "same_level_3_ratio",
        "same_level_2_ratio",
        "same_level_1_ratio",
        "comuna_only_ratio",
        "no_shared_location_signal_ratio",
    ):
        lines.append(f"| `{key}` | {baseline_mix[key]['p50']} | {challenger_mix[key]['p50']} |")
    lines.extend(
        [
            "",
            "## Comunas Criticas",
            "",
            "| Comuna | n | Baseline MAPE | Challenger MAPE | Baseline p90 | Challenger p90 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["by_comuna"]:
        lines.append(
            f"| `{row['comuna']}` | {row['evaluated']} | {row['mape_baseline_pct']} | "
            f"{row['mape_challenger_pct']} | {row['p90_baseline_pct']} | {row['p90_challenger_pct']} |"
        )
    lines.extend(
        [
            "",
            "## Radar Read-Only",
            "",
            f"- Opportunities in scope: `{radar['radar_opportunities_in_scope']}`",
            f"- >60% in scope: `{radar['discount_over_60_in_scope']}`",
            f"- >60% still extreme with challenger: `{radar['discount_over_60_still_extreme']}`",
            f"- >60% lowered/worsened: `{radar['discount_over_60_lowered']}` / `{radar['discount_over_60_worsened']}`",
            f"- >60% without hierarchy density: `{radar['discount_over_60_without_hierarchy_density']}`",
            f"- Scope note: {radar['scope_note']}",
            "",
            "## Explicit Answers",
            "",
        ]
    )
    for key, value in answers.items():
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
            "No DB writes, migrations, Radar/AVM/frontend changes, scrapers, external geocoding, backfills or productive scoring changes were made.",
            "",
        ]
    )
    return "\n".join(lines)


def _base_row(target: Listing, actual_clp: float, eligible: int) -> BenchmarkRow:
    return BenchmarkRow(
        listing_id=target.id,
        fingerprint=target.fingerprint,
        title=target.title,
        comuna=target.comuna,
        property_type=_property_type(target),
        actual_clp=round(actual_clp, 2),
        baseline_estimated_clp=None,
        challenger_estimated_clp=None,
        baseline_ape_pct=None,
        challenger_ape_pct=None,
        ape_delta_pct=None,
        baseline_comparables_used=0,
        challenger_comparables_used=0,
        eligible_comparables=eligible,
        baseline_dispersion_uf_m2=None,
        challenger_dispersion_uf_m2=None,
        baseline_same_level_4_ratio=0.0,
        baseline_same_level_3_ratio=0.0,
        baseline_same_level_2_ratio=0.0,
        baseline_same_level_1_ratio=0.0,
        baseline_comuna_only_ratio=0.0,
        baseline_no_shared_location_signal_ratio=0.0,
        challenger_same_level_4_ratio=0.0,
        challenger_same_level_3_ratio=0.0,
        challenger_same_level_2_ratio=0.0,
        challenger_same_level_1_ratio=0.0,
        challenger_comuna_only_ratio=0.0,
        challenger_no_shared_location_signal_ratio=0.0,
        challenger_match_distribution={},
        subject_geo_strength="none",
        status="not_evaluated",
        reason=None,
    )


def _replace_row(row: BenchmarkRow, **changes: Any) -> BenchmarkRow:
    values = asdict(row)
    values.update(changes)
    return BenchmarkRow(**values)


def example(row: BenchmarkRow) -> dict[str, Any]:
    return {
        "listing_id": row.listing_id,
        "title": row.title,
        "baseline_ape_pct": row.baseline_ape_pct,
        "challenger_ape_pct": row.challenger_ape_pct,
        "ape_delta_pct": row.ape_delta_pct,
        "match_distribution": row.challenger_match_distribution,
    }


def exclude_leakage(target: Listing, candidates: Sequence[Listing]) -> list[Listing]:
    filtered = []
    seen_fingerprints: set[str] = set()
    for candidate in candidates:
        if candidate.id is not None and target.id == candidate.id:
            continue
        if candidate.fingerprint and candidate.fingerprint == target.fingerprint:
            continue
        if target.property_id is not None and candidate.property_id == target.property_id:
            continue
        if target.source and target.external_id and candidate.source == target.source and candidate.external_id == target.external_id:
            continue
        if candidate.fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(candidate.fingerprint)
        filtered.append(candidate)
    return filtered


def _deduplicate_targets(listings: Sequence[Listing]) -> list[Listing]:
    result = []
    seen: set[tuple[str, str]] = set()
    for listing in listings:
        key = (listing.source, listing.external_id or listing.fingerprint)
        if key in seen or listing.fingerprint in {item.fingerprint for item in result}:
            continue
        seen.add(key)
        result.append(listing)
    return result


def listing_as_property(listing: Listing) -> Property:
    area = built_area(listing) or 0
    return Property(
        id=listing.property_id,
        comuna=listing.comuna,
        m2=area,
        property_type=_property_type(listing),
        built_area_m2=listing.built_area_m2 or area,
        land_area_m2=listing.land_area_m2,
        usable_area_m2=listing.usable_area_m2,
        bedrooms=listing.bedrooms,
        bathrooms=listing.bathrooms,
        parking=listing.parking,
        coordinates=listing.coordinates,
        geocode_precision=listing.geocode_precision,
        raw_metadata=listing.raw_metadata,
    )


def built_area(value: Listing | Property) -> float | None:
    return getattr(value, "built_area_m2", None) or getattr(value, "usable_area_m2", None) or value.m2


def _has_valid_area(listing: Listing) -> bool:
    area = built_area(listing)
    return area is not None and area > 0


def ape_pct(estimate: float, actual: float) -> float:
    return round(abs(estimate - actual) / actual * 100, 2) if actual > 0 else 0.0


def ratio(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 4) if denominator else 0.0


def pct(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator) * 100, 2) if denominator else 0.0


def quantiles(values: Iterable[float | int | None]) -> dict[str, float | None]:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return dict.fromkeys(("min", "p10", "p25", "p50", "p75", "p90", "p95", "p99", "max"))
    return {
        "min": round(clean[0], 4),
        "p10": round(percentile(clean, 10), 4),
        "p25": round(percentile(clean, 25), 4),
        "p50": round(percentile(clean, 50), 4),
        "p75": round(percentile(clean, 75), 4),
        "p90": round(percentile(clean, 90), 4),
        "p95": round(percentile(clean, 95), 4),
        "p99": round(percentile(clean, 99), 4),
        "max": round(clean[-1], 4),
    }


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


def normalize_comuna(value: str | None) -> str:
    return str(value or "").replace("_", " ").strip().lower()


def _listing_key(listing: Listing) -> str:
    return f"id:{listing.id}" if listing.id is not None else f"fp:{listing.fingerprint}"


def _row_key(row: BenchmarkRow) -> str:
    return f"id:{row.listing_id}" if row.listing_id is not None else f"fp:{row.fingerprint}"


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    return value


async def _latest_uf_rate(session) -> Decimal | None:
    result = await session.execute(select(UFRateORM).order_by(UFRateORM.date.desc()).limit(1))
    row = result.scalar_one_or_none()
    return Decimal(row.value_clp) if row is not None else None


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
