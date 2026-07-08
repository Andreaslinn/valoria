"""Read-only Comparable Quality v2 audit.

This benchmark measures whether AVM accuracy is more sensitive to economic
outliers, robust estimators, surface rebalancing, and light microzone signal
than to the current hierarchy-aware comparable reranking.
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
from statistics import mean, median
from time import perf_counter
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constants import (  # noqa: E402
    COMPARABLES_MAX_DISTANCE_KM,
    MIN_COMPARABLES,
    SCORE_WEIGHTS,
    TOP_N_COMPARABLES,
)
from core.entities.listing import Listing, Property  # noqa: E402
from core.normalization.property_type import normalize_property_type as _property_type  # noqa: E402
from domain.geocoding.hierarchical_microzones import (  # noqa: E402
    HierarchicalMicrozoneAssignment,
    assign_hierarchical_microzone,
)
from domain.geocoding.quality import (  # noqa: E402
    apply_geocoding_guardrails,
    has_valid_coordinates,
    normalized_precision_for,
)
from domain.valuation.comparable_quality_v2 import (  # noqa: E402
    ComparableQualityFlags,
    QualityThresholds,
    build_price_m2_reference,
    built_area,
    comparable_quality_flags,
    economic_similarity,
    filter_by_quality,
    median_estimator,
    safe_price_m2_uf,
    surface_similarity,
    trimmed_mean_estimator,
    weighted_mean,
    weighted_median,
    winsorized_mean_estimator,
)
from domain.valuation.comparables import filter_candidates, score_and_rank  # noqa: E402
from domain.valuation.hierarchical_comparable_diagnostics import (  # noqa: E402
    diagnose_hierarchical_comparable,
)
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import UFRateORM  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402
from scripts.benchmark_hierarchical_comparables import (  # noqa: E402
    build_density_index,
    exclude_leakage,
    listing_as_property,
)

OUTPUT_JSON = "comparable_quality_v2_audit_latest.json"
OUTPUT_MD = "comparable_quality_v2_audit_latest.md"
CRITICAL_COMUNAS = (
    "nunoa",
    "santiago",
    "las condes",
    "providencia",
    "vitacura",
    "san miguel",
    "macul",
    "estacion central",
    "la florida",
    "independencia",
)
WEAK_LOCATION_PRECISIONS = {"", "unknown", "comuna", "comuna_centroid"}
NEUTRAL_DISTANCE_SCORE = 0.5
POOR_DISTANCE_SCORE = 0.35
PRECISION_DISTANCE_IMPACT = {
    "address": 1.0,
    "street": 0.35,
    "comuna": 0.0,
    "comuna_centroid": 0.0,
    "unknown": 0.0,
}


@dataclass(frozen=True)
class VariantConfig:
    name: str
    kind: str
    description: str


@dataclass(frozen=True)
class VariantOutcome:
    estimate_clp: float | None
    ape_pct: float | None
    comparable_count: int
    filtered_count: int
    penalized_count: int


@dataclass(frozen=True)
class VariantSummary:
    name: str
    evaluations: int
    coverage_pct: float
    mape_pct: float | None
    median_ape_pct: float | None
    p90_ape_pct: float | None
    p95_ape_pct: float | None
    improved_count: int
    worsened_count: int
    unchanged_count: int
    improved_pct: float
    worsened_pct: float
    mean_delta_pct: float | None
    median_delta_pct: float | None
    avg_comparables_used: float | None
    filtered_or_penalized_pct: float | None
    mape_ape_gt_30_baseline: float | None
    mape_ape_gt_50_baseline: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Comparable Quality v2 read-only benchmark.")
    parser.add_argument("--output-dir", default="reports/valuation")
    parser.add_argument("--property-type", default="apartment", choices=["apartment", "house"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--uf-rate", type=Decimal)
    parser.add_argument("--case-limit", type=int, default=20)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    start = perf_counter()
    async with get_session_factory()() as session:
        listings = list(await SqlAlchemyListingRepository(session).list_active())
        uf_rate = args.uf_rate or await _latest_uf_rate(session)
    if uf_rate is None:
        raise SystemExit("No UF rate provided and no local uf_rates row found. Pass --uf-rate.")

    report = run_audit(
        listings,
        uf_rate=uf_rate,
        property_type=args.property_type,
        limit=args.limit,
        case_limit=args.case_limit,
        runtime_ms=0.0,
    )
    report["summary"]["runtime_ms"] = round((perf_counter() - start) * 1000, 2)
    json_path, md_path = write_outputs(report, Path(args.output_dir))
    print(
        json.dumps(
            {
                "targets": report["summary"]["total_targets"],
                "evaluations": report["summary"]["successful_evaluations"],
                "baseline_mape": report["variant_summaries"][0]["mape_pct"],
                "best_variant": report["summary"]["best_variant"],
                "best_mape": report["summary"]["best_variant_mape_pct"],
                "improvement_class": report["summary"]["best_improvement_class"],
                "json": str(json_path),
                "markdown": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def run_audit(
    listings: Sequence[Listing],
    *,
    uf_rate: Decimal,
    property_type: str,
    limit: int | None,
    case_limit: int,
    runtime_ms: float,
) -> dict[str, Any]:
    thresholds = QualityThresholds()
    active = apply_geocoding_guardrails([listing for listing in listings if listing.is_active])
    active = [listing for listing in active if built_area(listing) is not None and listing.price.clp > 0]
    assignments = {_listing_key(listing): assign_hierarchical_microzone(listing) for listing in active}
    density_index = build_density_index(active, assignments)
    comuna_refs = comuna_references(active, uf_rate)

    targets = [
        listing
        for listing in deduplicate_targets(active)
        if _property_type(listing) == property_type
        and safe_price_m2_uf(listing, uf_rate) is not None
    ]
    targets.sort(key=lambda item: int(item.id or 0))
    if limit is not None:
        targets = targets[:limit]

    variants = variant_configs()
    rows = [
        evaluate_target(
            target_listing=target,
            active=active,
            assignments=assignments,
            density_index=density_index,
            comuna_refs=comuna_refs,
            uf_rate=uf_rate,
            thresholds=thresholds,
            variants=variants,
        )
        for target in targets
    ]
    successful = [row for row in rows if row["status"] == "ok"]
    variant_summaries = summarize_variants(successful, variants)
    best = best_variant(variant_summaries)
    baseline = variant_summaries[0]
    contamination = contamination_analysis(successful)
    by_comuna = comuna_metrics(successful, variants)
    top_cases = top_error_cases(successful, best.name, case_limit=case_limit)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": {
            "read_only": True,
            "productive_code_modified": False,
            "property_type": property_type,
            "uf_rate_used": str(uf_rate),
            "active_listings": len(active),
            "active_in_scope": sum(1 for listing in active if _property_type(listing) == property_type),
            "total_targets": len(targets),
            "successful_evaluations": len(successful),
            "coverage_baseline_pct": pct(len(successful), len(targets)),
            "best_variant": best.name,
            "best_variant_mape_pct": best.mape_pct,
            "baseline_mape_pct": baseline.mape_pct,
            "best_gain_vs_baseline_pct_points": improvement_points(baseline, best),
            "best_improvement_class": improvement_class(improvement_points(baseline, best)),
            "runtime_ms": runtime_ms,
        },
        "methodology": methodology(thresholds, variants),
        "current_engine_documentation": current_engine_documentation(),
        "thresholds": thresholds.as_dict(),
        "variant_summaries": [asdict(item) for item in variant_summaries],
        "contamination": contamination,
        "by_comuna": by_comuna,
        "critical_comunas": [row for row in by_comuna if row["comuna"] in CRITICAL_COMUNAS],
        "top_baseline_error_cases": top_cases,
        "answers": explicit_answers(
            baseline=baseline,
            best=best,
            contamination=contamination,
            by_comuna=by_comuna,
        ),
        "recommendation": recommendation(baseline, best, contamination),
        "do_not_do_yet": [
            "Do not change productive comparable scoring from this audit alone.",
            "Do not use subject observed price as a production filtering signal.",
            "Do not hard-filter by level_2/level_3 microzone.",
            "Do not persist any benchmark-only flags to DB.",
            "Do not run broad external geocoding or scraper jobs.",
            "Do not deploy strict outlier filters if coverage or P90 regresses.",
        ],
        "rows": successful,
        "failed_rows": [row for row in rows if row["status"] != "ok"],
    }
    return json_safe(report)


def evaluate_target(
    *,
    target_listing: Listing,
    active: Sequence[Listing],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    density_index: dict[int, Counter[tuple[str, str, str]]],
    comuna_refs: dict[tuple[str, str], dict[str, Any]],
    uf_rate: Decimal,
    thresholds: QualityThresholds,
    variants: Sequence[VariantConfig],
) -> dict[str, Any]:
    target = listing_as_property(target_listing)
    candidates = [
        listing for listing in exclude_leakage(target_listing, active)
        if _property_type(listing) == _property_type(target_listing)
    ]
    eligible = filter_candidates(target, candidates)
    base = base_row(target_listing, len(eligible), uf_rate)
    if len(eligible) < MIN_COMPARABLES:
        return {**base, "status": "failed", "reason": "insufficient_comparables"}

    base_scored = [(score.value, listing) for score, listing in score_and_rank(target, eligible)]
    selected = base_scored[:TOP_N_COMPARABLES]
    if len(selected) < MIN_COMPARABLES:
        return {**base, "status": "failed", "reason": "insufficient_top_comparables"}

    subject_ppm2 = safe_price_m2_uf(target_listing, uf_rate)
    if subject_ppm2 is None:
        return {**base, "status": "failed", "reason": "invalid_subject_price_m2"}

    pool_ref = build_price_m2_reference([safe_price_m2_uf(listing, uf_rate) for listing in eligible])
    comuna_ref = comuna_refs.get((normalize_comuna(target_listing.comuna), _property_type(target_listing)), {})
    comuna_median = comuna_ref.get("reference", {}).get("median")

    diagnostic_flags = flags_for_candidates(
        target=target,
        candidates=eligible,
        assignments=assignments,
        uf_rate=uf_rate,
        thresholds=thresholds,
        subject_price_m2_uf=subject_ppm2,
        comuna_median_price_m2_uf=comuna_median,
        pool_median_price_m2_uf=pool_ref.median,
    )
    action_flags = flags_for_candidates(
        target=target,
        candidates=eligible,
        assignments=assignments,
        uf_rate=uf_rate,
        thresholds=thresholds,
        subject_price_m2_uf=None,
        comuna_median_price_m2_uf=comuna_median,
        pool_median_price_m2_uf=pool_ref.median,
    )

    variant_outcomes = {
        variant.name: evaluate_variant(
            variant,
            target=target,
            actual_clp=float(target_listing.price.clp),
            eligible=base_scored,
            baseline_selected=selected,
            action_flags=action_flags,
            assignments=assignments,
            subject_assignment=assignments[_listing_key(target_listing)],
            density_index=density_index,
            uf_rate=uf_rate,
            thresholds=thresholds,
        )
        for variant in variants
    }
    baseline_outcome = variant_outcomes["baseline"]
    if baseline_outcome.ape_pct is None:
        return {**base, "status": "failed", "reason": "baseline_estimation_failed"}

    baseline_comp_details = [
        comparable_detail(
            target=target,
            listing=listing,
            score=score,
            flags=diagnostic_flags[_listing_key(listing)],
            assignment=assignments[_listing_key(listing)],
            subject_assignment=assignments[_listing_key(target_listing)],
            density_index=density_index,
            uf_rate=uf_rate,
        )
        for score, listing in selected
    ]
    outlier_count = sum(1 for item in baseline_comp_details if item["economic_outlier"])
    strict_outlier_count = sum(1 for item in baseline_comp_details if item["strict_economic_outlier"])
    dispersion = price_m2_dispersion([item["price_m2_uf"] for item in baseline_comp_details])
    avg_surface_diff = safe_mean([item["surface_diff_pct"] for item in baseline_comp_details])
    weak_location_count = sum(1 for item in baseline_comp_details if item["weak_location"])

    return {
        **base,
        "status": "ok",
        "reason": None,
        "subject_price_m2_uf": round(subject_ppm2, 4),
        "subject_microzone": assignments[_listing_key(target_listing)].as_dict(),
        "eligible_comparables": len(eligible),
        "pool_price_m2_reference": pool_ref.as_dict(),
        "comuna_price_m2_reference": comuna_ref.get("reference"),
        "baseline_contamination": {
            "economic_outlier_count": outlier_count,
            "strict_economic_outlier_count": strict_outlier_count,
            "economic_outlier_ratio": ratio(outlier_count, len(selected)),
            "weak_location_count": weak_location_count,
            "weak_location_ratio": ratio(weak_location_count, len(selected)),
            "price_m2_iqr_pct": dispersion,
            "avg_surface_diff_pct": round(avg_surface_diff, 4) if avg_surface_diff is not None else None,
        },
        "variant_results": {
            name: asdict(outcome)
            for name, outcome in variant_outcomes.items()
        },
        "baseline_comparables": baseline_comp_details,
        "probable_cause": probable_cause(
            outlier_count=outlier_count,
            weak_location_count=weak_location_count,
            avg_surface_diff=avg_surface_diff,
            dispersion=dispersion,
            baseline_ape=baseline_outcome.ape_pct,
        ),
    }


def evaluate_variant(
    variant: VariantConfig,
    *,
    target: Property,
    actual_clp: float,
    eligible: Sequence[tuple[float, Listing]],
    baseline_selected: Sequence[tuple[float, Listing]],
    action_flags: dict[str, ComparableQualityFlags],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    subject_assignment: HierarchicalMicrozoneAssignment,
    density_index: dict[int, Counter[tuple[str, str, str]]],
    uf_rate: Decimal,
    thresholds: QualityThresholds,
) -> VariantOutcome:
    selected = list(baseline_selected)
    filtered_count = 0
    penalized_count = 0

    if variant.kind == "baseline":
        ppm2 = weighted_mean_price_m2(selected, uf_rate=uf_rate)
    elif variant.kind == "outlier_filter_mild":
        filtered = filter_by_quality(
            selected,
            action_flags,
            mode="mild",
            key_fn=_listing_key,
            min_comparables=thresholds.min_comparables_after_filter,
        )
        filtered_count = len(selected) - len(filtered)
        ppm2 = weighted_mean_price_m2(filtered, uf_rate=uf_rate)
        selected = filtered
    elif variant.kind == "outlier_filter_strict":
        filtered = filter_by_quality(
            selected,
            action_flags,
            mode="strict",
            key_fn=_listing_key,
            min_comparables=thresholds.min_comparables_after_filter,
        )
        filtered_count = len(selected) - len(filtered)
        ppm2 = weighted_mean_price_m2(filtered, uf_rate=uf_rate)
        selected = filtered
    elif variant.kind == "economic_similarity_bonus":
        ranked = rerank_economic(eligible, action_flags=action_flags, uf_rate=uf_rate)
        selected = ranked[:TOP_N_COMPARABLES]
        penalized_count = sum(1 for _, listing in selected if action_flags[_listing_key(listing)].economic_outlier)
        ppm2 = weighted_mean_price_m2(selected, uf_rate=uf_rate)
    elif variant.kind == "surface_rebalanced":
        ranked = rerank_surface_rebalanced(
            target=target,
            eligible=eligible,
            action_flags=action_flags,
            assignments=assignments,
            subject_assignment=subject_assignment,
            density_index=density_index,
            uf_rate=uf_rate,
            microzone_scale=0.0,
        )
        selected = ranked[:TOP_N_COMPARABLES]
        ppm2 = weighted_mean_price_m2(selected, uf_rate=uf_rate)
    elif variant.kind == "robust_median":
        ppm2 = median_estimator(ppm2_values(selected, uf_rate=uf_rate))
    elif variant.kind == "robust_trimmed_mean":
        ppm2 = trimmed_mean_estimator(ppm2_values(selected, uf_rate=uf_rate), trim_ratio=thresholds.trim_ratio)
    elif variant.kind == "robust_winsorized_mean":
        ppm2 = winsorized_mean_estimator(
            ppm2_values(selected, uf_rate=uf_rate),
            winsor_ratio=thresholds.winsor_ratio,
        )
    elif variant.kind == "robust_weighted_median":
        ppm2 = weighted_median(
            [
                (safe_price_m2_uf(listing, uf_rate), score)
                for score, listing in selected
            ]
        )
    elif variant.kind == "quality_weighted_estimator":
        ppm2, penalized_count = quality_weighted_price_m2(selected, action_flags, uf_rate=uf_rate)
    elif variant.kind == "combined_v2":
        ranked = rerank_surface_rebalanced(
            target=target,
            eligible=eligible,
            action_flags=action_flags,
            assignments=assignments,
            subject_assignment=subject_assignment,
            density_index=density_index,
            uf_rate=uf_rate,
            microzone_scale=0.25,
        )
        selected = filter_by_quality(
            ranked[:TOP_N_COMPARABLES],
            action_flags,
            mode="mild",
            key_fn=_listing_key,
            min_comparables=thresholds.min_comparables_after_filter,
        )
        filtered_count = TOP_N_COMPARABLES - len(selected)
        ppm2, penalized_count = quality_weighted_price_m2(selected, action_flags, uf_rate=uf_rate)
    else:
        raise ValueError(f"unknown variant kind: {variant.kind}")

    estimate = total_estimate(target, ppm2, uf_rate)
    ape = ape_pct(estimate, actual_clp) if estimate is not None and actual_clp > 0 else None
    return VariantOutcome(
        estimate_clp=round(estimate, 2) if estimate is not None else None,
        ape_pct=round(ape, 4) if ape is not None else None,
        comparable_count=len(selected),
        filtered_count=max(filtered_count, 0),
        penalized_count=penalized_count,
    )


def flags_for_candidates(
    *,
    target: Property,
    candidates: Sequence[Listing],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    uf_rate: Decimal,
    thresholds: QualityThresholds,
    subject_price_m2_uf: float | None,
    comuna_median_price_m2_uf: float | None,
    pool_median_price_m2_uf: float | None,
) -> dict[str, ComparableQualityFlags]:
    return {
        _listing_key(listing): comparable_quality_flags(
            listing,
            subject=target,
            subject_price_m2_uf=subject_price_m2_uf,
            comuna_median_price_m2_uf=comuna_median_price_m2_uf,
            pool_median_price_m2_uf=pool_median_price_m2_uf,
            microzone_level=assignments[_listing_key(listing)].best_available_level,
            uf_rate=uf_rate,
            thresholds=thresholds,
        )
        for listing in candidates
    }


def comparable_detail(
    *,
    target: Property,
    listing: Listing,
    score: float,
    flags: ComparableQualityFlags,
    assignment: HierarchicalMicrozoneAssignment,
    subject_assignment: HierarchicalMicrozoneAssignment,
    density_index: dict[int, Counter[tuple[str, str, str]]],
    uf_rate: Decimal,
) -> dict[str, Any]:
    diagnostics = diagnose_hierarchical_comparable(
        subject_assignment,
        assignment,
        density_index=density_index,
        comparable_comuna=listing.comuna,
        property_type=_property_type(listing),
    )
    price_uf = safe_price_uf_local(listing, uf_rate)
    return {
        "listing_id": listing.id,
        "fingerprint": listing.fingerprint,
        "title": listing.title,
        "comuna": listing.comuna,
        "property_type": _property_type(listing),
        "surface_m2": built_area(listing),
        "price_uf": round(price_uf, 4) if price_uf is not None else None,
        "price_clp": float(listing.price.clp),
        "price_m2_uf": flags.price_m2_uf,
        "surface_diff_pct": flags.surface_diff_pct,
        "score": round(score, 6),
        "current_similarity_score": round(score, 6),
        "geocode_precision": normalized_precision_for(listing),
        "distance_km": distance_km(target, listing),
        "hierarchical_microzone_level": assignment.best_available_level,
        "hierarchical_microzone_key": assignment.best_available_key,
        "hierarchical_match_level": diagnostics.hierarchy_match_level,
        "hierarchical_match_score": diagnostics.hierarchy_match_score,
        "hierarchical_density": diagnostics.hierarchy_density,
        "flags": list(flags.flags),
        "economic_outlier": flags.economic_outlier,
        "strict_economic_outlier": flags.strict_economic_outlier,
        "weak_location": "weak_location" in flags.flags,
        "comuna_only_location": "comuna_only_location" in flags.flags,
        "subject_ratio": flags.subject_ratio,
        "comuna_ratio": flags.comuna_ratio,
        "pool_ratio": flags.pool_ratio,
    }


def summarize_variants(rows: Sequence[dict[str, Any]], variants: Sequence[VariantConfig]) -> list[VariantSummary]:
    baseline_errors = {
        row["listing_id"]: row["variant_results"]["baseline"]["ape_pct"]
        for row in rows
        if row["variant_results"]["baseline"]["ape_pct"] is not None
    }
    result = []
    total = len(rows)
    for variant in variants:
        outcomes = [row["variant_results"][variant.name] for row in rows]
        values = [item["ape_pct"] for item in outcomes if item["ape_pct"] is not None]
        deltas = []
        high30 = []
        high50 = []
        improved = worsened = unchanged = 0
        filtered_or_penalized = 0
        total_selected = 0
        comps_used = []
        for row in rows:
            outcome = row["variant_results"][variant.name]
            ape = outcome["ape_pct"]
            base = baseline_errors.get(row["listing_id"])
            if ape is None or base is None:
                continue
            delta = ape - base
            deltas.append(delta)
            if delta < -0.0001:
                improved += 1
            elif delta > 0.0001:
                worsened += 1
            else:
                unchanged += 1
            if base > 30:
                high30.append(ape)
            if base > 50:
                high50.append(ape)
            filtered_or_penalized += outcome["filtered_count"] + outcome["penalized_count"]
            total_selected += max(outcome["comparable_count"], 0)
            comps_used.append(outcome["comparable_count"])
        result.append(
            VariantSummary(
                name=variant.name,
                evaluations=len(values),
                coverage_pct=pct(len(values), total),
                mape_pct=round(mean(values), 4) if values else None,
                median_ape_pct=round(percentile(values, 50), 4) if values else None,
                p90_ape_pct=round(percentile(values, 90), 4) if values else None,
                p95_ape_pct=round(percentile(values, 95), 4) if values else None,
                improved_count=improved,
                worsened_count=worsened,
                unchanged_count=unchanged,
                improved_pct=pct(improved, len(deltas)),
                worsened_pct=pct(worsened, len(deltas)),
                mean_delta_pct=round(mean(deltas), 4) if deltas else None,
                median_delta_pct=round(percentile(deltas, 50), 4) if deltas else None,
                avg_comparables_used=round(mean(comps_used), 4) if comps_used else None,
                filtered_or_penalized_pct=pct(filtered_or_penalized, total_selected),
                mape_ape_gt_30_baseline=round(mean(high30), 4) if high30 else None,
                mape_ape_gt_50_baseline=round(mean(high50), 4) if high50 else None,
            )
        )
    return result


def contamination_analysis(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    with_any = [row for row in rows if row["baseline_contamination"]["economic_outlier_count"] >= 1]
    with_3 = [row for row in rows if row["baseline_contamination"]["economic_outlier_count"] >= 3]
    comp_total = sum(len(row["baseline_comparables"]) for row in rows)
    comp_outliers = sum(row["baseline_contamination"]["economic_outlier_count"] for row in rows)
    strict_outliers = sum(row["baseline_contamination"]["strict_economic_outlier_count"] for row in rows)
    by_comuna_counter: dict[str, Counter[str]] = defaultdict(Counter)
    by_geo_counter: dict[str, Counter[str]] = defaultdict(Counter)
    flag_counter: Counter[str] = Counter()
    for row in rows:
        comuna = normalize_comuna(row["comuna"])
        by_comuna_counter[comuna]["targets"] += 1
        if row["baseline_contamination"]["economic_outlier_count"] >= 1:
            by_comuna_counter[comuna]["targets_with_outlier"] += 1
        for comp in row["baseline_comparables"]:
            by_comuna_counter[comuna]["comparables"] += 1
            by_geo_counter[comp["geocode_precision"]]["comparables"] += 1
            for flag in comp["flags"]:
                flag_counter[flag] += 1
            if comp["economic_outlier"]:
                by_comuna_counter[comuna]["outliers"] += 1
                by_geo_counter[comp["geocode_precision"]]["outliers"] += 1

    ape_high = [row for row in rows if row["variant_results"]["baseline"]["ape_pct"] > 30]
    ape_low = [row for row in rows if row["variant_results"]["baseline"]["ape_pct"] <= 30]
    dispersion_values = [
        row["baseline_contamination"]["price_m2_iqr_pct"]
        for row in rows
        if row["baseline_contamination"]["price_m2_iqr_pct"] is not None
    ]
    return {
        "targets": total,
        "targets_with_any_outlier_pct": pct(len(with_any), total),
        "targets_with_3plus_outliers_pct": pct(len(with_3), total),
        "global_comparable_outlier_pct": pct(comp_outliers, comp_total),
        "global_strict_comparable_outlier_pct": pct(strict_outliers, comp_total),
        "top_flags": dict(flag_counter.most_common(20)),
        "by_comuna": [
            {
                "comuna": comuna,
                "targets": counts["targets"],
                "targets_with_outlier_pct": pct(counts["targets_with_outlier"], counts["targets"]),
                "comparables": counts["comparables"],
                "outlier_pct": pct(counts["outliers"], counts["comparables"]),
            }
            for comuna, counts in sorted(
                by_comuna_counter.items(),
                key=lambda item: pct(item[1]["outliers"], item[1]["comparables"]),
                reverse=True,
            )
        ],
        "by_geocode_precision": [
            {
                "geocode_precision": precision,
                "comparables": counts["comparables"],
                "outlier_pct": pct(counts["outliers"], counts["comparables"]),
            }
            for precision, counts in sorted(by_geo_counter.items())
        ],
        "error_relation": {
            "avg_outliers_when_baseline_ape_gt_30": avg_contamination_count(ape_high),
            "avg_outliers_when_baseline_ape_lte_30": avg_contamination_count(ape_low),
            "avg_dispersion_when_baseline_ape_gt_30": avg_dispersion(ape_high),
            "avg_dispersion_when_baseline_ape_lte_30": avg_dispersion(ape_low),
            "baseline_ape_gt_30_count": len(ape_high),
            "baseline_ape_gt_50_count": sum(row["variant_results"]["baseline"]["ape_pct"] > 50 for row in rows),
            "dispersion_price_m2_iqr_pct_quantiles": quantiles(dispersion_values),
        },
        "surface_dominance_relation": {
            "avg_surface_diff_pct_when_baseline_ape_gt_30": avg_surface_diff(ape_high),
            "avg_surface_diff_pct_when_baseline_ape_lte_30": avg_surface_diff(ape_low),
            "note": "surface_m2 dominates current ranking via 40% score weight and hard +/-30% filter; this reports residual surface mismatch among selected comparables.",
        },
    }


def comuna_metrics(rows: Sequence[dict[str, Any]], variants: Sequence[VariantConfig]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[normalize_comuna(row["comuna"])].append(row)
    result = []
    for comuna, items in sorted(grouped.items()):
        summaries = summarize_variants(items, variants)
        best = best_variant(summaries)
        worst = max([item for item in summaries if item.mape_pct is not None], key=lambda item: item.mape_pct)
        baseline = summaries[0]
        improved = sorted(
            (
                row for row in items
                if row["variant_results"][best.name]["ape_pct"] is not None
                and row["variant_results"][best.name]["ape_pct"]
                < row["variant_results"]["baseline"]["ape_pct"]
            ),
            key=lambda row: row["variant_results"][best.name]["ape_pct"] - row["variant_results"]["baseline"]["ape_pct"],
        )[:5]
        worsened = sorted(
            (
                row for row in items
                if row["variant_results"][best.name]["ape_pct"] is not None
                and row["variant_results"][best.name]["ape_pct"]
                > row["variant_results"]["baseline"]["ape_pct"]
            ),
            key=lambda row: row["variant_results"][best.name]["ape_pct"] - row["variant_results"]["baseline"]["ape_pct"],
            reverse=True,
        )[:5]
        result.append(
            {
                "comuna": comuna,
                "evaluables": len(items),
                "baseline_mape_pct": baseline.mape_pct,
                "baseline_median_ape_pct": baseline.median_ape_pct,
                "baseline_p90_pct": baseline.p90_ape_pct,
                "contamination_rate_pct": pct(
                    sum(row["baseline_contamination"]["economic_outlier_count"] >= 1 for row in items),
                    len(items),
                ),
                "best_variant": best.name,
                "best_variant_mape_pct": best.mape_pct,
                "worst_variant": worst.name,
                "worst_variant_mape_pct": worst.mape_pct,
                "variant_metrics": [asdict(item) for item in summaries],
                "examples_improved": [small_example(row, best.name) for row in improved],
                "examples_worsened": [small_example(row, best.name) for row in worsened],
            }
        )
    return result


def top_error_cases(rows: Sequence[dict[str, Any]], best_variant_name: str, *, case_limit: int) -> list[dict[str, Any]]:
    top = sorted(
        rows,
        key=lambda row: row["variant_results"]["baseline"]["ape_pct"] or 0,
        reverse=True,
    )[:case_limit]
    result = []
    for row in top:
        baseline = row["variant_results"]["baseline"]
        best = row["variant_results"][best_variant_name]
        result.append(
            {
                "subject": {
                    "listing_id": row["listing_id"],
                    "title": row["title"],
                    "comuna": row["comuna"],
                    "property_type": row["property_type"],
                    "surface_m2": row["surface_m2"],
                    "price_uf": row["price_uf"],
                    "price_m2_uf": row["subject_price_m2_uf"],
                },
                "baseline_estimate_clp": baseline["estimate_clp"],
                "best_variant": best_variant_name,
                "best_variant_estimate_clp": best["estimate_clp"],
                "observed_clp": row["actual_clp"],
                "baseline_ape_pct": baseline["ape_pct"],
                "best_variant_ape_pct": best["ape_pct"],
                "delta_ape_pct": (
                    round(best["ape_pct"] - baseline["ape_pct"], 4)
                    if best["ape_pct"] is not None and baseline["ape_pct"] is not None
                    else None
                ),
                "baseline_contamination": row["baseline_contamination"],
                "probable_cause": row["probable_cause"],
                "comparables_used": row["baseline_comparables"],
            }
        )
    return result


def variant_configs() -> list[VariantConfig]:
    return [
        VariantConfig("baseline", "baseline", "Current eligible pool, score ranking and weighted mean price/m2."),
        VariantConfig("outlier_filter_mild", "outlier_filter_mild", "Remove only strict economic outliers if >=5 comps remain."),
        VariantConfig("outlier_filter_strict", "outlier_filter_strict", "Remove any economic outlier if >=5 comps remain."),
        VariantConfig("economic_similarity_bonus", "economic_similarity_bonus", "Rerank by current score times pool/comuna economic similarity."),
        VariantConfig("surface_rebalanced", "surface_rebalanced", "Reduce surface dominance and add economic similarity."),
        VariantConfig("robust_median", "robust_median", "Keep baseline comparables, estimate with median UF/m2."),
        VariantConfig("robust_trimmed_mean", "robust_trimmed_mean", "Keep baseline comparables, estimate with trimmed mean UF/m2."),
        VariantConfig("robust_winsorized_mean", "robust_winsorized_mean", "Keep baseline comparables, estimate with winsorized mean UF/m2."),
        VariantConfig("robust_weighted_median", "robust_weighted_median", "Keep baseline comparables, estimate with weighted median UF/m2."),
        VariantConfig("quality_weighted_estimator", "quality_weighted_estimator", "Keep baseline comparables, downweight weak economic/location quality."),
        VariantConfig("combined_v2", "combined_v2", "Mild outlier handling, rebalanced ranking, robust quality weights, microzone light."),
    ]


def current_engine_documentation() -> dict[str, Any]:
    return {
        "selection": [
            "same comuna",
            "same normalized property_type",
            "active listings only",
            "positive built/usable/m2 area",
            "surface within +/-30%",
            "houses also check land area +/-30% when both sides have land_area_m2",
            "positive CLP price",
            "distance >5km only excluded when both subject and comparable have address-level coordinates",
        ],
        "score_weights": dict(SCORE_WEIGHTS),
        "surface_m2": "hard filter +/-30% plus 40% of similarity score; for apartments it is the dominant structural signal.",
        "price_m2": "not used as comparable similarity input in legacy ranking; used after selection to compute weighted mean price/m2 and diagnostics.",
        "outlier_handling": "existing comparable_quality reports dispersion/outlier pressure; productive valuation does not filter selected comps by UF/m2 outliers.",
        "final_estimate": "weighted mean of selected comparable price/m2 by similarity score times subject surface.",
        "robust_price_m2_existing": "domain/valuation/robust_price_m2.py exists for canonical experiments, but it is not the legacy comparable estimator used here.",
    }


def methodology(thresholds: QualityThresholds, variants: Sequence[VariantConfig]) -> dict[str, Any]:
    return {
        "read_only": True,
        "scope": "active evaluable apartments by default; houses can be run separately with --property-type house.",
        "holdout": "each active listing is treated as subject and excluded from its candidate pool.",
        "no_subject_price_leakage_in_challengers": (
            "diagnostic flags include subject observed price/m2, but challenger filters/rankers use only pool/comuna "
            "references available without knowing the subject price."
        ),
        "thresholds": thresholds.as_dict(),
        "variants": [asdict(variant) for variant in variants],
    }


def explicit_answers(
    *,
    baseline: VariantSummary,
    best: VariantSummary,
    contamination: dict[str, Any],
    by_comuna: Sequence[dict[str, Any]],
) -> dict[str, str]:
    gain = improvement_points(baseline, best)
    benefiting = sorted(
        [row for row in by_comuna if row["best_variant_mape_pct"] is not None],
        key=lambda row: row["best_variant_mape_pct"] - row["baseline_mape_pct"],
    )[:5]
    worsening = sorted(
        [row for row in by_comuna if row["best_variant_mape_pct"] is not None],
        key=lambda row: row["best_variant_mape_pct"] - row["baseline_mape_pct"],
        reverse=True,
    )[:5]
    robust_variants = {
        "robust_median",
        "robust_trimmed_mean",
        "robust_winsorized_mean",
        "robust_weighted_median",
        "quality_weighted_estimator",
    }
    robust_won = best.name in robust_variants
    return {
        "is_mape_affected_by_price_m2_outliers": (
            f"yes diagnostically: {contamination['targets_with_any_outlier_pct']}% of evaluated subjects "
            f"have at least one economic outlier in baseline top comparables; "
            f"{contamination['global_comparable_outlier_pct']}% of baseline comparables are flagged."
        ),
        "does_surface_m2_dominate_too_much": (
            "surface_m2 is structurally dominant today: hard +/-30% filter plus 40% score weight. "
            "The audit compares this against surface_rebalanced and economic variants."
        ),
        "do_economically_rare_comparables_explain_high_errors": (
            f"partly: avg outliers for baseline APE>30 is "
            f"{contamination['error_relation']['avg_outliers_when_baseline_ape_gt_30']} vs "
            f"{contamination['error_relation']['avg_outliers_when_baseline_ape_lte_30']} for APE<=30."
        ),
        "does_robust_estimator_improve_more_than_microzones": (
            f"{'yes' if robust_won else 'not globally in this run'}; best variant is {best.name} "
            f"with MAPE {best.mape_pct} vs baseline {baseline.mape_pct}."
        ),
        "which_variant_lowers_mape_without_breaking_coverage_p90": (
            f"{best.name}: coverage {best.coverage_pct}%, MAPE {best.mape_pct}, P90 {best.p90_ape_pct}."
        ),
        "is_improvement_substantial_or_marginal": (
            f"{improvement_class(gain)} improvement ({gain} MAPE points)."
        ),
        "which_comunas_benefit": ", ".join(row["comuna"] for row in benefiting) if benefiting else "insufficient data",
        "which_comunas_worsen": ", ".join(row["comuna"] for row in worsening) if worsening else "insufficient data",
        "should_microzone_remain_secondary": "yes; this audit keeps microzone as light secondary signal only in combined_v2.",
        "should_touch_comparable_scoring": (
            "only if gain is relevant and P90/coverage are stable; otherwise keep changes in shadow."
        ),
        "should_do_targeted_geocoding_first": (
            "yes for high-impact errors and dense level_2 groups, because weak location remains a contamination amplifier."
        ),
        "what_not_to_do_yet": "do not hard-filter microzones, do not deploy strict filters blindly, do not use observed subject price as production input.",
    }


def recommendation(baseline: VariantSummary, best: VariantSummary, contamination: dict[str, Any]) -> dict[str, Any]:
    gain = improvement_points(baseline, best)
    p90_ok = best.p90_ape_pct is not None and baseline.p90_ape_pct is not None and best.p90_ape_pct <= baseline.p90_ape_pct
    coverage_ok = best.coverage_pct >= baseline.coverage_pct - 1.0
    if gain >= 0.5 and p90_ok and coverage_ok:
        path = "promote best quality variant to a larger shadow benchmark before product changes"
    elif gain >= 0.2:
        path = "continue shadow tuning around outliers/economic similarity; no production change yet"
    else:
        path = "focus on data quality/geocoding targeted and outlier diagnostics before scoring changes"
    return {
        "recommended_path": path,
        "why": (
            f"Best gain is {gain} MAPE points ({improvement_class(gain)}); "
            f"P90 stable={p90_ok}, coverage stable={coverage_ok}, "
            f"baseline outlier target rate={contamination['targets_with_any_outlier_pct']}%."
        ),
        "next_steps": [
            "Review top baseline error cases and remove data errors from the benchmark if published price looks anomalous.",
            "Retest best robust/economic variant on a temporally separated holdout.",
            "Add targeted geocoding for high-impact weak-location cases before increasing location weights.",
            "Keep microzone_light as secondary tie-breaker, not as filter.",
        ],
    }


def rerank_economic(
    eligible: Sequence[tuple[float, Listing]],
    *,
    action_flags: dict[str, ComparableQualityFlags],
    uf_rate: Decimal,
) -> list[tuple[float, Listing]]:
    ranked = []
    for score, listing in eligible:
        flags = action_flags[_listing_key(listing)]
        reference = _economic_reference(flags)
        econ = economic_similarity(safe_price_m2_uf(listing, uf_rate), reference)
        penalty = 0.75 + 0.25 * econ
        if flags.economic_outlier:
            penalty *= 0.88
        ranked.append((score * penalty, listing))
    ranked.sort(key=lambda item: (item[0], str(item[1].fingerprint)), reverse=True)
    return ranked


def rerank_surface_rebalanced(
    *,
    target: Property,
    eligible: Sequence[tuple[float, Listing]],
    action_flags: dict[str, ComparableQualityFlags],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    subject_assignment: HierarchicalMicrozoneAssignment,
    density_index: dict[int, Counter[tuple[str, str, str]]],
    uf_rate: Decimal,
    microzone_scale: float,
) -> list[tuple[float, Listing]]:
    ranked = []
    for base_score, listing in eligible:
        flags = action_flags[_listing_key(listing)]
        econ = economic_similarity(safe_price_m2_uf(listing, uf_rate), _economic_reference(flags))
        program = (
            discrete_score(target.bedrooms, listing.bedrooms) * 0.45
            + discrete_score(target.bathrooms, listing.bathrooms) * 0.35
            + discrete_score(target.parking, listing.parking) * 0.20
        )
        location = distance_score(target, listing)
        hierarchy = 0.0
        if microzone_scale > 0:
            diagnostics = diagnose_hierarchical_comparable(
                subject_assignment,
                assignments[_listing_key(listing)],
                density_index=density_index,
                comparable_comuna=listing.comuna,
                property_type=_property_type(listing),
            )
            hierarchy = diagnostics.hierarchy_match_score * microzone_scale
        score = (
            0.25 * surface_similarity(target, listing)
            + 0.25 * econ
            + 0.25 * location
            + 0.20 * program
            + 0.05 * base_score
            + hierarchy
        )
        if flags.economic_outlier:
            score -= 0.04
        ranked.append((max(0.0, min(1.0, score)), listing))
    ranked.sort(key=lambda item: (item[0], str(item[1].fingerprint)), reverse=True)
    return ranked


def quality_weighted_price_m2(
    selected: Sequence[tuple[float, Listing]],
    action_flags: dict[str, ComparableQualityFlags],
    *,
    uf_rate: Decimal,
) -> tuple[float | None, int]:
    weighted = []
    penalized = 0
    for score, listing in selected:
        flags = action_flags[_listing_key(listing)]
        weight = score
        econ = economic_similarity(safe_price_m2_uf(listing, uf_rate), _economic_reference(flags))
        weight *= 0.60 + 0.40 * econ
        if flags.economic_outlier:
            weight *= 0.70
            penalized += 1
        if "weak_location" in flags.flags:
            weight *= 0.92
            penalized += 1
        weighted.append((safe_price_m2_uf(listing, uf_rate), weight))
    return weighted_mean(weighted), penalized


def weighted_mean_price_m2(selected: Sequence[tuple[float, Listing]], *, uf_rate: Decimal) -> float | None:
    return weighted_mean([(safe_price_m2_uf(listing, uf_rate), score) for score, listing in selected])


def ppm2_values(selected: Sequence[tuple[float, Listing]], *, uf_rate: Decimal) -> list[float | None]:
    return [safe_price_m2_uf(listing, uf_rate) for _, listing in selected]


def total_estimate(target: Property, price_m2_uf: float | None, uf_rate: Decimal) -> float | None:
    area = built_area(target)
    if area is None or price_m2_uf is None:
        return None
    return float(Decimal(str(price_m2_uf)) * Decimal(str(area)) * uf_rate)


def base_row(target: Listing, eligible: int, uf_rate: Decimal) -> dict[str, Any]:
    area = built_area(target)
    price_uf = safe_price_uf_local(target, uf_rate)
    return {
        "listing_id": target.id,
        "fingerprint": target.fingerprint,
        "title": target.title,
        "comuna": normalize_comuna(target.comuna),
        "property_type": _property_type(target),
        "surface_m2": area,
        "actual_clp": float(target.price.clp),
        "price_uf": round(price_uf, 4) if price_uf is not None else None,
        "eligible_comparables": eligible,
    }


def comuna_references(listings: Sequence[Listing], uf_rate: Decimal) -> dict[tuple[str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str], list[float | None]] = defaultdict(list)
    for listing in listings:
        grouped[(normalize_comuna(listing.comuna), _property_type(listing))].append(
            safe_price_m2_uf(listing, uf_rate)
        )
    return {
        key: {"reference": build_price_m2_reference(values).as_dict()}
        for key, values in grouped.items()
    }


def price_m2_dispersion(values: Sequence[float | None]) -> float | None:
    clean = sorted(float(value) for value in values if value is not None and value > 0)
    if len(clean) < 4:
        return None
    med = median(clean)
    if med <= 0:
        return None
    iqr = percentile(clean, 75) - percentile(clean, 25)
    return round(iqr / med * 100, 4)


def probable_cause(
    *,
    outlier_count: int,
    weak_location_count: int,
    avg_surface_diff: float | None,
    dispersion: float | None,
    baseline_ape: float | None,
) -> str:
    if baseline_ape is None or baseline_ape < 30:
        return "baseline_error_not_extreme"
    if outlier_count >= 3 or (dispersion is not None and dispersion >= 45):
        return "comparable_uf_m2_outliers_or_high_dispersion"
    if weak_location_count >= 10:
        return "weak_location"
    if avg_surface_diff is not None and avg_surface_diff >= 20:
        return "surface_match_still_far_inside_30pct_filter"
    return "subject_or_published_price_may_be_anomalous"


def best_variant(summaries: Sequence[VariantSummary]) -> VariantSummary:
    valid = [item for item in summaries if item.mape_pct is not None]
    return min(valid, key=lambda item: item.mape_pct)


def improvement_points(baseline: VariantSummary, best: VariantSummary) -> float | None:
    if baseline.mape_pct is None or best.mape_pct is None:
        return None
    return round(baseline.mape_pct - best.mape_pct, 4)


def improvement_class(gain: float | None) -> str:
    if gain is None:
        return "insufficient_data"
    if gain < 0:
        return "regression"
    if gain < 0.2:
        return "irrelevant"
    if gain < 0.5:
        return "small"
    if gain < 1.5:
        return "relevant"
    return "strong"


def small_example(row: dict[str, Any], variant: str) -> dict[str, Any]:
    base = row["variant_results"]["baseline"]
    challenger = row["variant_results"][variant]
    return {
        "listing_id": row["listing_id"],
        "title": row["title"],
        "baseline_ape_pct": base["ape_pct"],
        "variant_ape_pct": challenger["ape_pct"],
        "delta_ape_pct": round(challenger["ape_pct"] - base["ape_pct"], 4),
        "outlier_count": row["baseline_contamination"]["economic_outlier_count"],
        "probable_cause": row["probable_cause"],
    }


def distance_score(target: Property, candidate: Listing) -> float:
    if target.coordinates is None or candidate.coordinates is None:
        return NEUTRAL_DISTANCE_SCORE
    impact = min(distance_impact(target), distance_impact(candidate))
    if impact <= 0.0:
        return NEUTRAL_DISTANCE_SCORE
    dist = target.coordinates.distance_km(candidate.coordinates)
    precise_score = max(0.0, 1.0 - dist / COMPARABLES_MAX_DISTANCE_KM)
    if impact < 0.5:
        return POOR_DISTANCE_SCORE + impact * (precise_score - POOR_DISTANCE_SCORE)
    return NEUTRAL_DISTANCE_SCORE + impact * (precise_score - NEUTRAL_DISTANCE_SCORE)


def distance_impact(value: Property | Listing) -> float:
    if not has_valid_coordinates(value):
        return 0.0
    return PRECISION_DISTANCE_IMPACT.get(normalized_precision_for(value), 0.0)


def distance_km(target: Property, candidate: Listing) -> float | None:
    if target.coordinates is None or candidate.coordinates is None:
        return None
    return round(target.coordinates.distance_km(candidate.coordinates), 4)


def discrete_score(target_val: int | None, candidate_val: int | None) -> float:
    return 1.0 / (1.0 + abs((target_val or 0) - (candidate_val or 0)))


def safe_price_uf_local(value: Listing, uf_rate: Decimal) -> float | None:
    price_m2 = safe_price_m2_uf(value, uf_rate)
    area = built_area(value)
    if price_m2 is None or area is None:
        return None
    return price_m2 * area


def ape_pct(estimate: float | None, actual: float) -> float | None:
    if estimate is None or actual <= 0:
        return None
    return abs(estimate - actual) / actual * 100


def avg_contamination_count(rows: Sequence[dict[str, Any]]) -> float | None:
    values = [row["baseline_contamination"]["economic_outlier_count"] for row in rows]
    return round(mean(values), 4) if values else None


def avg_dispersion(rows: Sequence[dict[str, Any]]) -> float | None:
    values = [
        row["baseline_contamination"]["price_m2_iqr_pct"]
        for row in rows
        if row["baseline_contamination"]["price_m2_iqr_pct"] is not None
    ]
    return round(mean(values), 4) if values else None


def avg_surface_diff(rows: Sequence[dict[str, Any]]) -> float | None:
    values = [
        row["baseline_contamination"]["avg_surface_diff_pct"]
        for row in rows
        if row["baseline_contamination"]["avg_surface_diff_pct"] is not None
    ]
    return round(mean(values), 4) if values else None


def _economic_reference(flags: ComparableQualityFlags) -> float | None:
    values = []
    if flags.comuna_ratio is not None and flags.price_m2_uf is not None:
        values.append(flags.price_m2_uf / flags.comuna_ratio)
    if flags.pool_ratio is not None and flags.price_m2_uf is not None:
        values.append(flags.price_m2_uf / flags.pool_ratio)
    return median(values) if values else None


def deduplicate_targets(listings: Sequence[Listing]) -> list[Listing]:
    result = []
    seen: set[tuple[str, str]] = set()
    seen_fingerprints: set[str] = set()
    for listing in listings:
        key = (listing.source, listing.external_id or listing.fingerprint)
        if key in seen or listing.fingerprint in seen_fingerprints:
            continue
        seen.add(key)
        seen_fingerprints.add(listing.fingerprint)
        result.append(listing)
    return result


def write_outputs(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / OUTPUT_JSON
    md_path = output_dir / OUTPUT_MD
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    contamination = report["contamination"]
    lines = [
        "# Comparable Quality v2 Audit",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Executive Summary",
        "",
        f"- Scope: `{summary['property_type']}`",
        f"- Targets/evaluations: `{summary['total_targets']}` / `{summary['successful_evaluations']}`",
        f"- Baseline MAPE: `{summary['baseline_mape_pct']}`",
        f"- Best variant: `{summary['best_variant']}` MAPE `{summary['best_variant_mape_pct']}`",
        f"- Gain vs baseline: `{summary['best_gain_vs_baseline_pct_points']}` pts "
        f"({summary['best_improvement_class']})",
        f"- Targets with any economic outlier: `{contamination['targets_with_any_outlier_pct']}%`",
        f"- Global comparable outlier rate: `{contamination['global_comparable_outlier_pct']}%`",
        "",
        "## Current Engine",
        "",
        f"- Selection: `{report['current_engine_documentation']['selection']}`",
        f"- Score weights: `{report['current_engine_documentation']['score_weights']}`",
        f"- Surface: {report['current_engine_documentation']['surface_m2']}",
        f"- Price/m2: {report['current_engine_documentation']['price_m2']}",
        f"- Final estimate: {report['current_engine_documentation']['final_estimate']}",
        "",
        "## Variants",
        "",
        "| Variant | Coverage | MAPE | Median | P90 | P95 | Improved | Worsened | Mean Delta | Avg Comps | Filter/Penalize % |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["variant_summaries"]:
        lines.append(
            f"| `{row['name']}` | {row['coverage_pct']} | {row['mape_pct']} | "
            f"{row['median_ape_pct']} | {row['p90_ape_pct']} | {row['p95_ape_pct']} | "
            f"{row['improved_count']} | {row['worsened_count']} | {row['mean_delta_pct']} | "
            f"{row['avg_comparables_used']} | {row['filtered_or_penalized_pct']} |"
        )
    lines.extend(
        [
            "",
            "## Contamination",
            "",
            f"- Evaluations with >=1 outlier: `{contamination['targets_with_any_outlier_pct']}%`",
            f"- Evaluations with >=3 outliers: `{contamination['targets_with_3plus_outliers_pct']}%`",
            f"- Strict comparable outliers: `{contamination['global_strict_comparable_outlier_pct']}%`",
            f"- Top flags: `{contamination['top_flags']}`",
            f"- Error relation: `{contamination['error_relation']}`",
            "",
            "## Critical Comunas",
            "",
            "| Comuna | n | Baseline MAPE | Best Variant | Best MAPE | Contamination | Worst Variant |",
            "| --- | ---: | ---: | --- | ---: | ---: | --- |",
        ]
    )
    for row in report["critical_comunas"]:
        lines.append(
            f"| `{row['comuna']}` | {row['evaluables']} | {row['baseline_mape_pct']} | "
            f"`{row['best_variant']}` | {row['best_variant_mape_pct']} | "
            f"{row['contamination_rate_pct']} | `{row['worst_variant']}` |"
        )
    lines.extend(["", "## Explicit Answers", ""])
    for key, value in report["answers"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Top Error Cases",
            "",
            f"- Cases included in JSON: `{len(report['top_baseline_error_cases'])}`",
            "- JSON contains subject, observed price, baseline estimate, best variant estimate, comparables, UF/m2 and flags.",
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


def normalize_comuna(value: Any) -> str:
    return str(value or "").replace("_", " ").strip().lower()


def _listing_key(listing: Listing | Property) -> str:
    if getattr(listing, "id", None) is not None:
        return f"id:{listing.id}"
    return f"fp:{getattr(listing, 'fingerprint', id(listing))}"


def safe_mean(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return mean(clean) if clean else None


def ratio(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 4) if denominator else 0.0


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


def quantiles(values: Sequence[float]) -> dict[str, float | None]:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return dict.fromkeys(("p10", "p25", "p50", "p75", "p90", "p95"))
    return {
        "p10": round(percentile(clean, 10), 4),
        "p25": round(percentile(clean, 25), 4),
        "p50": round(percentile(clean, 50), 4),
        "p75": round(percentile(clean, 75), 4),
        "p90": round(percentile(clean, 90), 4),
        "p95": round(percentile(clean, 95), 4),
    }


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
