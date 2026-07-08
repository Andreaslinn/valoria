"""Read-only interpretability audit for comparable similarity calibration."""
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

from config.constants import (  # noqa: E402
    COMPARABLES_MAX_DISTANCE_KM,
    SCORE_WEIGHTS,
    TOP_N_COMPARABLES,
)
from core.entities.listing import Listing, Property  # noqa: E402
from core.normalization.property_type import normalize_property_type as _property_type  # noqa: E402
from core.value_objects.score import Score  # noqa: E402
from domain.geocoding.hierarchical_microzones import (  # noqa: E402
    HierarchicalMicrozoneAssignment,
    assign_hierarchical_microzone,
)
from domain.geocoding.microzones import microzone_similarity_bonus  # noqa: E402
from domain.geocoding.quality import (  # noqa: E402
    apply_geocoding_guardrails,
    has_valid_coordinates,
    normalized_precision_for,
)
from domain.valuation.comparables import filter_candidates  # noqa: E402
from domain.valuation.hierarchical_comparable_diagnostics import (  # noqa: E402
    HierarchicalComparableDiagnostics,
    diagnose_hierarchical_comparable,
)
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402
from scripts.benchmark_hierarchical_comparables import (  # noqa: E402
    build_density_index,
    exclude_leakage,
    listing_as_property,
)

DEFAULT_BENCHMARK_JSON = Path("reports/microzones/hierarchical_comparables_benchmark_latest.json")
DEFAULT_DELTA_JSON = Path("reports/microzones/hierarchical_comparable_delta_audit_latest.json")
OUTPUT_JSON = "comparable_similarity_calibration_latest.json"
OUTPUT_MD = "comparable_similarity_calibration_latest.md"
MIN_LEVEL4_FILTER_COMPARABLES = 5

_NEUTRAL_DISTANCE_SCORE = 0.5
_POOR_DISTANCE_SCORE = 0.35
_PRECISION_DISTANCE_IMPACT = {
    "address": 1.0,
    "street": 0.35,
    "comuna": 0.0,
    "comuna_centroid": 0.0,
    "unknown": 0.0,
}


@dataclass(frozen=True)
class ScoreBreakdown:
    listing_key: str
    total_score: float
    base_score: float
    area_score: float
    distance_score: float
    bedrooms_score: float
    bathrooms_score: float
    parking_score: float
    area_contribution: float
    distance_contribution: float
    bedrooms_contribution: float
    bathrooms_contribution: float
    parking_contribution: float
    legacy_microzone_bonus: float
    hierarchy_score: float
    hierarchy_match_level: int
    hierarchy_density: int
    hierarchy_reasons: tuple[str, ...]
    distance_km: float | None
    geocode_precision: str
    price_m2_uf: float | None


@dataclass(frozen=True)
class VariantConfig:
    name: str
    hierarchy_scale: float = 1.0
    distance_multiplier: float = 1.0
    no_hierarchy: bool = False
    no_comuna_only_hierarchy: bool = False
    level2_tiebreaker_only: bool = False
    level4_filter: bool = False
    level3_min_density: int | None = None


@dataclass(frozen=True)
class VariantResult:
    name: str
    n: int
    coverage_pct: float
    mape_pct: float | None
    median_ape_pct: float | None
    p90_ape_pct: float | None
    avg_changed_top_count: float | None
    avg_top20_overlap_pct: float | None
    avg_hierarchy_score_abs: float | None


@dataclass(frozen=True)
class CaseExplanation:
    listing_id: int | None
    title: str | None
    comuna: str
    baseline_ape: float
    challenger_ape: float
    delta_ape: float
    subject_level: int
    subject_key: str | None
    suspected_issue: str
    changed_in: tuple[dict[str, Any], ...]
    changed_out: tuple[dict[str, Any], ...]
    baseline_top: tuple[dict[str, Any], ...]
    challenger_top: tuple[dict[str, Any], ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit comparable similarity calibration versus hierarchical microzones.")
    parser.add_argument("--benchmark-json", default=str(DEFAULT_BENCHMARK_JSON))
    parser.add_argument("--delta-json", default=str(DEFAULT_DELTA_JSON))
    parser.add_argument("--output-dir", default="reports/microzones")
    parser.add_argument("--case-limit", type=int, default=10)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    start = perf_counter()
    benchmark = json.loads(Path(args.benchmark_json).read_text(encoding="utf-8"))
    delta = json.loads(Path(args.delta_json).read_text(encoding="utf-8"))
    async with get_session_factory()() as session:
        listings = list(await SqlAlchemyListingRepository(session).list_active())

    report = build_report(
        benchmark=benchmark,
        delta=delta,
        listings=listings,
        benchmark_path=Path(args.benchmark_json),
        delta_path=Path(args.delta_json),
        case_limit=args.case_limit,
        runtime_ms=0.0,
    )
    report["summary"]["runtime_ms"] = round((perf_counter() - start) * 1000, 2)
    json_path, md_path = write_outputs(report, Path(args.output_dir))
    best = report["sensitivity"]["best_variant"]
    print(
        json.dumps(
            {
                "paired_rows": report["summary"]["paired_rows"],
                "baseline_mape": report["sensitivity"]["variants"][0]["mape_pct"],
                "best_variant": best["name"],
                "best_mape": best["mape_pct"],
                "dominant_score_component": report["dominance"]["dominant_component"],
                "json": str(json_path),
                "markdown": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_report(
    *,
    benchmark: dict[str, Any],
    delta: dict[str, Any],
    listings: Sequence[Listing],
    benchmark_path: Path,
    delta_path: Path,
    case_limit: int,
    runtime_ms: float,
) -> dict[str, Any]:
    active = apply_geocoding_guardrails([listing for listing in listings if listing.is_active])
    active = [listing for listing in active if _has_valid_area(listing) and listing.price.clp > 0]
    listing_index = _listing_index(active)
    assignments = {_listing_key(listing): assign_hierarchical_microzone(listing) for listing in active}
    density_index = build_density_index(active, assignments)
    rows = [
        row for row in benchmark.get("rows", [])
        if row.get("status") == "ok"
        and row.get("baseline_ape_pct") is not None
        and _row_key(row) in listing_index
    ]
    uf_rate = Decimal(str(benchmark["summary"]["uf_rate_used"]))
    variants = variant_configs()
    variant_results, row_audits = run_sensitivity(
        rows=rows,
        active=active,
        listing_index=listing_index,
        assignments=assignments,
        density_index=density_index,
        uf_rate=uf_rate,
        variants=variants,
    )
    cases = explain_cases(
        delta_rows=delta.get("rows", []),
        active=active,
        listing_index=listing_index,
        assignments=assignments,
        density_index=density_index,
        uf_rate=uf_rate,
        case_limit=case_limit,
    )
    dominance = dominance_analysis(row_audits)
    organization = microzone_organization(active, assignments, density_index)
    engine = comparable_engine_explanation()
    answers_data = answers(organization, engine, variant_results, dominance)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": {
            "read_only": True,
            "productive_code_modified": False,
            "benchmark_path": str(benchmark_path),
            "delta_path": str(delta_path),
            "property_type": benchmark["summary"].get("property_type"),
            "uf_rate_used": str(uf_rate),
            "paired_rows": len(rows),
            "active_listings": len(active),
            "runtime_ms": runtime_ms,
        },
        "microzone_organization": organization,
        "current_comparable_engine": engine,
        "hierarchy_challenger": hierarchy_challenger_explanation(),
        "dominance": dominance,
        "sensitivity": {
            "variants": [asdict(item) for item in variant_results],
            "best_variant": asdict(best_variant(variant_results)),
        },
        "case_analysis": {
            "improved_examples": [asdict(item) for item in cases["improved"]],
            "worsened_examples": [asdict(item) for item in cases["worsened"]],
        },
        "answers": answers_data,
        "recommendation": recommendation(variant_results, dominance, organization),
        "do_not_do_yet": [
            "Do not persist hierarchical assignments.",
            "Do not change productive comparable scoring or Radar scoring from this audit.",
            "Do not hard-filter level_2 or level_3 comparables.",
            "Do not run broad external geocoding.",
            "Do not treat comuna_only or sparse textual level_2 as real microzone evidence.",
        ],
    }


def run_sensitivity(
    *,
    rows: Sequence[dict[str, Any]],
    active: Sequence[Listing],
    listing_index: dict[str, Listing],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    density_index: dict[int, Counter[tuple[str, str, str]]],
    uf_rate: Decimal,
    variants: Sequence[VariantConfig],
) -> tuple[list[VariantResult], list[dict[str, Any]]]:
    errors_by_variant: dict[str, list[float]] = {variant.name: [] for variant in variants}
    changed_by_variant: dict[str, list[int]] = {variant.name: [] for variant in variants}
    overlap_by_variant: dict[str, list[float]] = {variant.name: [] for variant in variants}
    hierarchy_abs_by_variant: dict[str, list[float]] = {variant.name: [] for variant in variants}
    row_audits: list[dict[str, Any]] = []

    for row in rows:
        target_listing = listing_index.get(_row_key(row))
        if target_listing is None:
            continue
        target = listing_as_property(target_listing)
        candidates = [
            listing for listing in exclude_leakage(target_listing, active)
            if _property_type(listing) == _property_type(target_listing)
        ]
        eligible = filter_candidates(target, candidates)
        if len(eligible) < 5:
            continue
        subject_assignment = assignments[_listing_key(target_listing)]
        base_ranked = rank_candidates(
            target=target,
            candidates=eligible,
            subject_assignment=subject_assignment,
            assignments=assignments,
            density_index=density_index,
            uf_rate=uf_rate,
            variant=variants[0],
        )
        base_top_keys = [_listing_key(item[1]) for item in base_ranked[:TOP_N_COMPARABLES]]
        audit_rows = []
        for variant in variants:
            ranked = rank_candidates(
                target=target,
                candidates=eligible,
                subject_assignment=subject_assignment,
                assignments=assignments,
                density_index=density_index,
                uf_rate=uf_rate,
                variant=variant,
            )
            if len(ranked) < 5:
                continue
            selected = ranked[:TOP_N_COMPARABLES]
            estimate = weighted_estimate(target, [(Score.clamped(item[0].total_score), item[1]) for item in selected])
            error = ape_pct(estimate, float(target_listing.price.clp))
            errors_by_variant[variant.name].append(error)
            keys = [_listing_key(item[1]) for item in selected]
            changed = len(set(keys) ^ set(base_top_keys))
            overlap = len(set(keys) & set(base_top_keys)) / len(base_top_keys) if base_top_keys else 0.0
            changed_by_variant[variant.name].append(changed)
            overlap_by_variant[variant.name].append(overlap * 100)
            hierarchy_abs_by_variant[variant.name].append(mean(abs(item[0].hierarchy_score) for item in selected))
            if variant.name == "current_hierarchy_medium":
                audit_rows.append(
                    {
                        "listing_id": row.get("listing_id"),
                        "component_dominance": component_dominance([item[0] for item in selected]),
                        "avg_hierarchy_score_abs": hierarchy_abs_by_variant[variant.name][-1],
                        "changed_top_count": changed,
                        "top20_overlap_pct": overlap * 100,
                    }
                )
        row_audits.extend(audit_rows)

    results = []
    total = len(rows)
    for variant in variants:
        values = errors_by_variant[variant.name]
        results.append(
            VariantResult(
                name=variant.name,
                n=len(values),
                coverage_pct=pct(len(values), total),
                mape_pct=round(mean(values), 4) if values else None,
                median_ape_pct=round(percentile(values, 50), 4) if values else None,
                p90_ape_pct=round(percentile(values, 90), 4) if values else None,
                avg_changed_top_count=round(mean(changed_by_variant[variant.name]), 4) if changed_by_variant[variant.name] else None,
                avg_top20_overlap_pct=round(mean(overlap_by_variant[variant.name]), 4) if overlap_by_variant[variant.name] else None,
                avg_hierarchy_score_abs=round(mean(hierarchy_abs_by_variant[variant.name]), 4) if hierarchy_abs_by_variant[variant.name] else None,
            )
        )
    return results, row_audits


def rank_candidates(
    *,
    target: Property,
    candidates: Sequence[Listing],
    subject_assignment: HierarchicalMicrozoneAssignment,
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    density_index: dict[int, Counter[tuple[str, str, str]]],
    uf_rate: Decimal,
    variant: VariantConfig,
) -> list[tuple[ScoreBreakdown, Listing, HierarchicalComparableDiagnostics]]:
    rows: list[tuple[ScoreBreakdown, Listing, HierarchicalComparableDiagnostics]] = []
    level4_candidates: list[Listing] = []
    if variant.level4_filter and subject_assignment.level_4_key:
        level4_candidates = [
            listing for listing in candidates
            if assignments[_listing_key(listing)].level_4_key == subject_assignment.level_4_key
        ]
        if len(level4_candidates) >= MIN_LEVEL4_FILTER_COMPARABLES:
            candidates = level4_candidates
    for candidate in candidates:
        assignment = assignments[_listing_key(candidate)]
        diagnostics = diagnose_hierarchical_comparable(
            subject_assignment,
            assignment,
            density_index=density_index,
            comparable_comuna=candidate.comuna,
            property_type=_property_type(candidate),
        )
        breakdown = score_breakdown(
            target=target,
            candidate=candidate,
            diagnostics=diagnostics,
            variant=variant,
            uf_rate=uf_rate,
        )
        rows.append((breakdown, candidate, diagnostics))
    rows.sort(
        key=lambda item: (
            item[0].total_score,
            item[2].hierarchy_match_level,
            item[2].hierarchy_density,
            str(item[1].fingerprint),
        ),
        reverse=True,
    )
    return rows


def score_breakdown(
    *,
    target: Property,
    candidate: Listing,
    diagnostics: HierarchicalComparableDiagnostics,
    variant: VariantConfig,
    uf_rate: Decimal,
) -> ScoreBreakdown:
    area = area_score(target, candidate)
    distance = distance_score(target, candidate)
    bedrooms = discrete_score(target.bedrooms, candidate.bedrooms)
    bathrooms = discrete_score(target.bathrooms, candidate.bathrooms)
    parking = discrete_score(target.parking, candidate.parking)
    area_contribution = SCORE_WEIGHTS["m2"] * area
    distance_contribution = SCORE_WEIGHTS["distance"] * distance * variant.distance_multiplier
    bedrooms_contribution = SCORE_WEIGHTS["bedrooms"] * bedrooms
    bathrooms_contribution = SCORE_WEIGHTS["bathrooms"] * bathrooms
    parking_contribution = SCORE_WEIGHTS["parking"] * parking
    legacy_bonus, _ = microzone_similarity_bonus(target, candidate)
    hierarchy_score = hierarchy_score_for(diagnostics, variant)
    base = (
        area_contribution
        + distance_contribution
        + bedrooms_contribution
        + bathrooms_contribution
        + parking_contribution
        + legacy_bonus
    )
    total = max(0.0, min(1.0, base + hierarchy_score))
    return ScoreBreakdown(
        listing_key=_listing_key(candidate),
        total_score=round(total, 6),
        base_score=round(base, 6),
        area_score=round(area, 6),
        distance_score=round(distance, 6),
        bedrooms_score=round(bedrooms, 6),
        bathrooms_score=round(bathrooms, 6),
        parking_score=round(parking, 6),
        area_contribution=round(area_contribution, 6),
        distance_contribution=round(distance_contribution, 6),
        bedrooms_contribution=round(bedrooms_contribution, 6),
        bathrooms_contribution=round(bathrooms_contribution, 6),
        parking_contribution=round(parking_contribution, 6),
        legacy_microzone_bonus=round(legacy_bonus, 6),
        hierarchy_score=round(hierarchy_score, 6),
        hierarchy_match_level=diagnostics.hierarchy_match_level,
        hierarchy_density=diagnostics.hierarchy_density,
        hierarchy_reasons=diagnostics.reasons,
        distance_km=distance_km(target, candidate),
        geocode_precision=normalized_precision_for(candidate),
        price_m2_uf=price_m2_uf(candidate, uf_rate),
    )


def hierarchy_score_for(diagnostics: HierarchicalComparableDiagnostics, variant: VariantConfig) -> float:
    if variant.no_hierarchy:
        return 0.0
    if variant.no_comuna_only_hierarchy and diagnostics.hierarchy_match_level == 0:
        return 0.0
    if variant.level2_tiebreaker_only:
        if diagnostics.hierarchy_match_level == 2:
            return 0.015
        if diagnostics.hierarchy_match_level in {3, 4}:
            return diagnostics.hierarchy_match_score * 0.25
        return 0.0
    if (
        variant.level3_min_density is not None
        and diagnostics.hierarchy_match_level == 3
        and diagnostics.hierarchy_density < variant.level3_min_density
    ):
        return 0.0
    return diagnostics.hierarchy_match_score * variant.hierarchy_scale


def explain_cases(
    *,
    delta_rows: Sequence[dict[str, Any]],
    active: Sequence[Listing],
    listing_index: dict[str, Listing],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    density_index: dict[int, Counter[tuple[str, str, str]]],
    uf_rate: Decimal,
    case_limit: int,
) -> dict[str, list[CaseExplanation]]:
    ok_rows = [row for row in delta_rows if row.get("outcome") in {"improved", "worsened"}]
    improved = sorted([row for row in ok_rows if row["outcome"] == "improved"], key=lambda row: row["delta_ape"])[:case_limit]
    worsened = sorted([row for row in ok_rows if row["outcome"] == "worsened"], key=lambda row: row["delta_ape"], reverse=True)[:case_limit]
    return {
        "improved": [
            explain_case(row, active, listing_index, assignments, density_index, uf_rate)
            for row in improved
            if _row_key(row) in listing_index
        ],
        "worsened": [
            explain_case(row, active, listing_index, assignments, density_index, uf_rate)
            for row in worsened
            if _row_key(row) in listing_index
        ],
    }


def explain_case(
    row: dict[str, Any],
    active: Sequence[Listing],
    listing_index: dict[str, Listing],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    density_index: dict[int, Counter[tuple[str, str, str]]],
    uf_rate: Decimal,
) -> CaseExplanation:
    target_listing = listing_index[_row_key(row)]
    target = listing_as_property(target_listing)
    candidates = [
        listing for listing in exclude_leakage(target_listing, active)
        if _property_type(listing) == _property_type(target_listing)
    ]
    eligible = filter_candidates(target, candidates)
    subject_assignment = assignments[_listing_key(target_listing)]
    baseline = rank_candidates(
        target=target,
        candidates=eligible,
        subject_assignment=subject_assignment,
        assignments=assignments,
        density_index=density_index,
        uf_rate=uf_rate,
        variant=VariantConfig(name="baseline", no_hierarchy=True),
    )[:TOP_N_COMPARABLES]
    challenger = rank_candidates(
        target=target,
        candidates=eligible,
        subject_assignment=subject_assignment,
        assignments=assignments,
        density_index=density_index,
        uf_rate=uf_rate,
        variant=VariantConfig(name="current_hierarchy_medium"),
    )[:TOP_N_COMPARABLES]
    baseline_keys = {_listing_key(item[1]) for item in baseline}
    challenger_keys = {_listing_key(item[1]) for item in challenger}
    entered = [item for item in challenger if _listing_key(item[1]) not in baseline_keys]
    exited = [item for item in baseline if _listing_key(item[1]) not in challenger_keys]
    return CaseExplanation(
        listing_id=row.get("listing_id"),
        title=row.get("title"),
        comuna=normalize_comuna(row.get("comuna")),
        baseline_ape=float(row["baseline_ape"]),
        challenger_ape=float(row["challenger_ape"]),
        delta_ape=float(row["delta_ape"]),
        subject_level=int(row.get("subject_best_available_level") or -1),
        subject_key=row.get("subject_best_available_key"),
        suspected_issue=suspected_issue(row, entered, exited),
        changed_in=tuple(compact_comparable(item, uf_rate) for item in entered[:8]),
        changed_out=tuple(compact_comparable(item, uf_rate) for item in exited[:8]),
        baseline_top=tuple(compact_comparable(item, uf_rate) for item in baseline[:8]),
        challenger_top=tuple(compact_comparable(item, uf_rate) for item in challenger[:8]),
    )


def suspected_issue(
    row: dict[str, Any],
    entered: Sequence[tuple[ScoreBreakdown, Listing, HierarchicalComparableDiagnostics]],
    exited: Sequence[tuple[ScoreBreakdown, Listing, HierarchicalComparableDiagnostics]],
) -> str:
    if row.get("subject_best_available_level") == 0:
        return "no_real_microzone_signal; ranking changed by structural tie-breaks/comuna_only noise"
    if row.get("subject_best_available_level") == 3 and int(row.get("hierarchy_density") or 0) < 3:
        return "sparse_level_3_hint; not enough density"
    if entered and mean(item[0].price_m2_uf or 0 for item in entered) > mean(item[0].price_m2_uf or 0 for item in exited or entered) * 1.2:
        return "entered_comparables_look_price_m2_high"
    if row.get("matched_signal_type") in {"metro", "barrio_sector_textual", "named_area"}:
        return "textual_or_corridor_signal_may_be_too_noisy"
    return "weight_calibration_or_sparse_density"


def compact_comparable(
    item: tuple[ScoreBreakdown, Listing, HierarchicalComparableDiagnostics],
    uf_rate: Decimal,
) -> dict[str, Any]:
    breakdown, listing, diagnostics = item
    return {
        "listing_id": listing.id,
        "title": listing.title,
        "score": breakdown.total_score,
        "base_score": breakdown.base_score,
        "hierarchy_score": breakdown.hierarchy_score,
        "area_contribution": breakdown.area_contribution,
        "distance_contribution": breakdown.distance_contribution,
        "bedrooms_contribution": breakdown.bedrooms_contribution,
        "bathrooms_contribution": breakdown.bathrooms_contribution,
        "parking_contribution": breakdown.parking_contribution,
        "legacy_microzone_bonus": breakdown.legacy_microzone_bonus,
        "match_level": diagnostics.hierarchy_match_level,
        "hierarchy_density": diagnostics.hierarchy_density,
        "distance_km": breakdown.distance_km,
        "geocode_precision": breakdown.geocode_precision,
        "price_m2_uf": price_m2_uf(listing, uf_rate),
    }


def dominance_analysis(row_audits: Sequence[dict[str, Any]]) -> dict[str, Any]:
    counters: Counter[str] = Counter()
    changed = []
    overlaps = []
    hierarchy_abs = []
    for row in row_audits:
        counters[row["component_dominance"]] += 1
        changed.append(float(row["changed_top_count"]))
        overlaps.append(float(row["top20_overlap_pct"]))
        hierarchy_abs.append(float(row["avg_hierarchy_score_abs"]))
    dominant, _ = counters.most_common(1)[0] if counters else ("unknown", 0)
    return {
        "dominant_component": dominant,
        "dominant_component_distribution": dict(counters),
        "avg_changed_top_count": round(mean(changed), 4) if changed else None,
        "avg_top20_overlap_pct": round(mean(overlaps), 4) if overlaps else None,
        "avg_abs_hierarchy_score": round(mean(hierarchy_abs), 4) if hierarchy_abs else None,
        "interpretation": (
            "The hierarchy can change rank order, but most selected sets still overlap heavily with baseline "
            "and core structural components dominate candidate ordering."
        ),
    }


def component_dominance(breakdowns: Sequence[ScoreBreakdown]) -> str:
    totals = {
        "surface_m2": mean(item.area_contribution for item in breakdowns),
        "distance": mean(item.distance_contribution for item in breakdowns),
        "program": mean(item.bedrooms_contribution + item.bathrooms_contribution + item.parking_contribution for item in breakdowns),
        "legacy_microzone": mean(item.legacy_microzone_bonus for item in breakdowns),
        "hierarchical_microzone": mean(abs(item.hierarchy_score) for item in breakdowns),
    }
    return max(totals.items(), key=lambda item: item[1])[0]


def microzone_organization(
    active: Sequence[Listing],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    density_index: dict[int, Counter[tuple[str, str, str]]],
) -> dict[str, Any]:
    level_counts = Counter(f"level_{assignments[_listing_key(listing)].best_available_level}" for listing in active)
    kind_counts = Counter(signal_kind(assignments[_listing_key(listing)]) for listing in active)
    examples = defaultdict(list)
    for listing in active:
        assignment = assignments[_listing_key(listing)]
        level = f"level_{assignment.best_available_level}"
        if len(examples[level]) < 8:
            examples[level].append(
                {
                    "listing_id": listing.id,
                    "title": listing.title,
                    "comuna": listing.comuna,
                    "property_type": _property_type(listing),
                    "best_key": assignment.best_available_key,
                    "kind": signal_kind(assignment),
                    "confidence": assignment.confidence,
                    "warnings": list(assignment.warnings[:4]),
                }
            )
    return {
        "levels": {
            "level_0": "comuna fallback; not a real microzone",
            "level_1": "named macro area/neighborhood when only broad textual area exists",
            "level_2": "corridor/barrio/sector/metro/avenue signal",
            "level_3": "street microzone or intersection from textual/address hints",
            "level_4": "geo_500m cell from real lat/lon with address or street precision",
        },
        "real_microzone_rule": "best_available_level >= 1; level_0 is fallback only",
        "level_counts": dict(level_counts),
        "signal_kind_counts": dict(kind_counts),
        "strength": {
            "strong": ["level_4 geo_500m with real coordinates"],
            "medium": ["dense level_2 metro/avenue corridors", "level_3 only when repeated/dense"],
            "weak": ["sparse level_2", "single street hints", "named_area"],
            "ambiguous": ["comuna_only", "generic metro/sector text", "barrio_sector_textual without density"],
        },
        "density": {
            f"level_{level}": {
                "groups": len(counter),
                "useful_3_plus": sum(1 for count in counter.values() if count >= 3),
                "useful_5_plus": sum(1 for count in counter.values() if count >= 5),
                "useful_10_plus": sum(1 for count in counter.values() if count >= 10),
            }
            for level, counter in density_index.items()
        },
        "examples": dict(examples),
    }


def comparable_engine_explanation() -> dict[str, Any]:
    return {
        "candidate_filters": [
            "same comuna required",
            "same normalized property_type required",
            "active listing required",
            "positive built/usable/m2 area required",
            "area within +/-30%",
            "house land area within +/-30% when both sides have land_area_m2",
            "positive CLP price required",
            "distance >5km excluded only when both target and candidate have address precision coordinates",
        ],
        "score_weights": dict(SCORE_WEIGHTS),
        "score_components": [
            "m2 similarity: 40%",
            "distance: 25%",
            "bedrooms: 15%",
            "bathrooms: 10%",
            "parking: 10%",
            "legacy textual microzone bonus: additive, capped at +0.08",
        ],
        "distance_logic": {
            "address_precision": "full impact",
            "street_precision": "35% impact",
            "comuna/comuna_centroid/unknown": "neutral distance score; no effective distance penalty",
            "max_distance_km": COMPARABLES_MAX_DISTANCE_KM,
        },
        "price_m2_usage": "price/m2 is not a similarity input in legacy comparable ranking; it affects estimate and reliability/dispersion diagnostics after selection",
        "dominance_expectation": "m2 and program dominate when coordinates are weak; distance dominates only for address-level pairs",
        "freshness_usage": "freshness/age is not currently in SCORE_WEIGHTS",
    }


def hierarchy_challenger_explanation() -> dict[str, Any]:
    return {
        "mechanism": "read-only challenger reranks eligible comparables by adding hierarchy_match_score to current structural score; it does not exclude by microzone",
        "same_level_4": "+0.24 strong bonus",
        "same_level_3": "+0.14 if density >=3, else +0.03 hint-only",
        "same_level_2": "+0.16 if density >=5, else +0.08 secondary bonus",
        "same_level_1": "+0.04 light bonus",
        "comuna_only": "-0.03 plus fallback/weak penalties",
        "no_shared_location_signal": "-0.08 plus weak penalties",
        "fallback_penalties": "subject fallback -0.03, comparable fallback -0.04, weak subject/comparable level <2 -0.02 each",
        "can_move_ranking": "yes when structural scores are close; sensitivity reports avg changed top count and overlap",
    }


def answers(
    organization: dict[str, Any],
    engine: dict[str, Any],
    variants: Sequence[VariantResult],
    dominance: dict[str, Any],
) -> dict[str, str]:
    best = best_variant(variants)
    baseline = variants[0]
    best_gain = (
        round((baseline.mape_pct or 0) - (best.mape_pct or 0), 4)
        if baseline.mape_pct is not None and best.mape_pct is not None
        else None
    )
    return {
        "how_microzones_are_organized": (
            "level_0 comuna fallback; level_1 named area; level_2 metro/avenue/named corridor; "
            "level_3 street/intersection; level_4 real geo_500m cell from reliable coordinates."
        ),
        "most_reliable_level": "level_4 is most reliable, but has very low coverage; dense level_2 is usable only as secondary signal.",
        "how_microzone_enters_ranking": "productive ranking has a small legacy textual bonus; hierarchy challenger adds read-only bonus/penalty after normal scoring.",
        "does_microzone_have_enough_weight": (
            f"it can move ranking, avg changed top count {dominance['avg_changed_top_count']}, "
            f"but top20 overlap remains {dominance['avg_top20_overlap_pct']}% and {dominance['dominant_component']} dominates."
        ),
        "is_distance_locality_penalized_well": (
            "only for address-level coordinates; weak geocodes get neutral distance, so locality is often under-penalized."
        ),
        "is_score_dominated_by_other_variable": f"yes: dominant component is {dominance['dominant_component']}.",
        "are_comparables_miscalibrated": (
            "partly; price/m2/outlier quality is diagnosed after selection, not directly used as similarity, and weak geo makes locality calibration soft."
        ),
        "best_weight_variant": (
            f"{best.name} with MAPE {best.mape_pct}; gain vs baseline {best_gain} pts; "
            f"coverage {best.coverage_pct}% and P90 {best.p90_ape_pct}."
        ),
        "adjust_weights_before_geocoding": (
            "only in shadow. Productive weight changes should wait; current location signal is still too weak/noisy."
        ),
        "root_cause": (
            "combination of B/C/D/E: low geo signal quality, hierarchy not consistently predictive, weak distance penalty for non-address geocodes, and outlier comparable prices."
        ),
        "level_counts": str(organization["level_counts"]),
        "engine_weights": str(engine["score_weights"]),
    }


def recommendation(
    variants: Sequence[VariantResult],
    dominance: dict[str, Any],
    organization: dict[str, Any],
) -> dict[str, Any]:
    best = best_variant(variants)
    baseline = variants[0]
    if best.mape_pct is not None and baseline.mape_pct is not None and best.mape_pct < baseline.mape_pct:
        path = "C/D first, then retest stricter hierarchy weights in shadow"
        why = "A weight variant improves MAPE directionally, but signal coverage and locality quality are still uneven."
    else:
        path = "D + extraction cleanup first; keep hierarchy diagnostic"
        why = "Sensitivity did not produce a robust enough gain to justify ranking changes."
    return {
        "recommended_path": path,
        "why": why,
        "next_steps": [
            "Make distance/locality interpretable in holdout dashboards.",
            "Clean level_2 corridor extraction before increasing its weight.",
            "Use targeted geocoding for dense level_2 groups and high-impact regression cases.",
            "Add a shadow variant that ignores comuna_only and sparse level_3 ranking bonuses.",
            "Evaluate outlier filtering/price_m2 calibration jointly with geo signal.",
        ],
        "dominance": dominance["dominant_component"],
        "level_counts": organization["level_counts"],
    }


def variant_configs() -> list[VariantConfig]:
    return [
        VariantConfig(name="baseline_no_hierarchy", no_hierarchy=True),
        VariantConfig(name="microzone_no_effect", no_hierarchy=True),
        VariantConfig(name="microzone_light", hierarchy_scale=0.35),
        VariantConfig(name="current_hierarchy_medium", hierarchy_scale=1.0),
        VariantConfig(name="microzone_strong", hierarchy_scale=1.6),
        VariantConfig(name="geo_penalty_light", hierarchy_scale=1.0, distance_multiplier=0.7),
        VariantConfig(name="geo_penalty_medium", hierarchy_scale=1.0, distance_multiplier=1.0),
        VariantConfig(name="geo_penalty_strong", hierarchy_scale=1.0, distance_multiplier=1.45),
        VariantConfig(name="exclude_comuna_only_bonus", hierarchy_scale=1.0, no_comuna_only_hierarchy=True),
        VariantConfig(name="level_2_tiebreaker_only", level2_tiebreaker_only=True),
        VariantConfig(name="level_4_filter_strong", hierarchy_scale=1.0, level4_filter=True),
        VariantConfig(name="level_3_density_3_plus", hierarchy_scale=1.0, level3_min_density=3),
    ]


def best_variant(variants: Sequence[VariantResult]) -> VariantResult:
    valid = [variant for variant in variants if variant.mape_pct is not None]
    return min(valid, key=lambda item: item.mape_pct)


def write_outputs(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / OUTPUT_JSON
    md_path = output_dir / OUTPUT_MD
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: dict[str, Any]) -> str:
    answers_data = report["answers"]
    lines = [
        "# Comparable Similarity Calibration Audit",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Executive Summary",
        "",
        f"- Paired rows: `{report['summary']['paired_rows']}`",
        f"- Dominant score component: `{report['dominance']['dominant_component']}`",
        f"- Avg changed top count: `{report['dominance']['avg_changed_top_count']}`",
        f"- Avg top20 overlap: `{report['dominance']['avg_top20_overlap_pct']}%`",
        f"- Avg abs hierarchy score: `{report['dominance']['avg_abs_hierarchy_score']}`",
        f"- Best variant: `{report['sensitivity']['best_variant']['name']}` "
        f"MAPE `{report['sensitivity']['best_variant']['mape_pct']}`",
        "",
        "## Microzone Organization",
        "",
        f"- Level counts: `{report['microzone_organization']['level_counts']}`",
        f"- Signal kind counts: `{report['microzone_organization']['signal_kind_counts']}`",
        f"- Real microzone rule: {report['microzone_organization']['real_microzone_rule']}",
        "",
        "## Current Comparable Engine",
        "",
        f"- Score weights: `{report['current_comparable_engine']['score_weights']}`",
        f"- Candidate filters: `{report['current_comparable_engine']['candidate_filters']}`",
        f"- Distance logic: `{report['current_comparable_engine']['distance_logic']}`",
        f"- Price/m2 usage: {report['current_comparable_engine']['price_m2_usage']}",
        "",
        "## Sensitivity",
        "",
        "| Variant | Coverage | MAPE | Median APE | P90 | Changed Top | Top20 Overlap | Abs Hierarchy |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["sensitivity"]["variants"]:
        lines.append(
            f"| `{row['name']}` | {row['coverage_pct']} | {row['mape_pct']} | "
            f"{row['median_ape_pct']} | {row['p90_ape_pct']} | {row['avg_changed_top_count']} | "
            f"{row['avg_top20_overlap_pct']} | {row['avg_hierarchy_score_abs']} |"
        )
    lines.extend(["", "## Explicit Answers", ""])
    for key, value in answers_data.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Case Analysis",
            "",
            f"- Improved examples: `{len(report['case_analysis']['improved_examples'])}`",
            f"- Worsened examples: `{len(report['case_analysis']['worsened_examples'])}`",
            "- See JSON for changed-in/changed-out comparable details and score components.",
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


def area_score(target: Property, candidate: Listing) -> float:
    target_built = target.built_area_m2 or target.m2
    candidate_built = candidate.built_area_m2 or candidate.m2
    if candidate_built is None:
        return 0.0
    built_score = m2_score(target_built, candidate_built)
    if _property_type(target) != "house":
        return built_score
    target_land = target.land_area_m2
    candidate_land = candidate.land_area_m2
    if target_land is None or candidate_land is None:
        return built_score * 0.65
    return 0.55 * built_score + 0.45 * m2_score(target_land, candidate_land)


def m2_score(target_m2: float, candidate_m2: float) -> float:
    if target_m2 <= 0:
        return 0.0
    diff_ratio = abs(target_m2 - candidate_m2) / target_m2
    return max(0.0, 1.0 - diff_ratio)


def distance_score(target: Property, candidate: Listing) -> float:
    if target.coordinates is None or candidate.coordinates is None:
        return _NEUTRAL_DISTANCE_SCORE
    impact = min(distance_impact(target), distance_impact(candidate))
    if impact <= 0.0:
        return _NEUTRAL_DISTANCE_SCORE
    dist = target.coordinates.distance_km(candidate.coordinates)
    precise_score = max(0.0, 1.0 - dist / COMPARABLES_MAX_DISTANCE_KM)
    if impact < 0.5:
        return _POOR_DISTANCE_SCORE + impact * (precise_score - _POOR_DISTANCE_SCORE)
    return _NEUTRAL_DISTANCE_SCORE + impact * (precise_score - _NEUTRAL_DISTANCE_SCORE)


def distance_impact(value: Property | Listing) -> float:
    if not has_valid_coordinates(value):
        return 0.0
    return _PRECISION_DISTANCE_IMPACT.get(normalized_precision_for(value), 0.0)


def discrete_score(target_val: int, candidate_val: int) -> float:
    return 1.0 / (1.0 + abs((target_val or 0) - (candidate_val or 0)))


def distance_km(target: Property, candidate: Listing) -> float | None:
    if target.coordinates is None or candidate.coordinates is None:
        return None
    return round(target.coordinates.distance_km(candidate.coordinates), 4)


def weighted_estimate(target: Property, scored: Sequence[tuple[Score, Listing]]) -> float:
    area = built_area(target)
    total_weight = Decimal("0")
    weighted_ppm2 = Decimal("0")
    for score, listing in scored:
        candidate_area = built_area(listing)
        if candidate_area is None or candidate_area <= 0:
            continue
        weight = Decimal(str(score.value))
        weighted_ppm2 += weight * (listing.price.clp / Decimal(str(candidate_area)))
        total_weight += weight
    if total_weight <= 0 or area is None or area <= 0:
        return 0.0
    return float((weighted_ppm2 / total_weight) * Decimal(str(area)))


def price_m2_uf(listing: Listing, uf_rate: Decimal) -> float | None:
    area = built_area(listing)
    if area is None or area <= 0 or uf_rate <= 0:
        return None
    return round(float((listing.price.clp / Decimal(str(area))) / uf_rate), 4)


def built_area(value: Property | Listing) -> float | None:
    return getattr(value, "built_area_m2", None) or getattr(value, "usable_area_m2", None) or value.m2


def ape_pct(estimate: float, actual: float) -> float:
    return abs(estimate - actual) / actual * 100 if actual > 0 else 0.0


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


def signal_kind(assignment: HierarchicalMicrozoneAssignment) -> str:
    if assignment.best_available_level == 4:
        return "geo_500m"
    if assignment.best_available_level == 3:
        return str(assignment.level_3_kind or "level_3")
    if assignment.best_available_level == 2:
        return str(assignment.level_2_kind or "level_2")
    if assignment.best_available_level == 1:
        return str(assignment.level_1_kind or "level_1")
    return "comuna_fallback"


def _listing_index(listings: Sequence[Listing]) -> dict[str, Listing]:
    result = {}
    for listing in listings:
        if listing.id is not None:
            result[f"id:{listing.id}"] = listing
        if listing.fingerprint:
            result[f"fp:{listing.fingerprint}"] = listing
    return result


def _listing_key(listing: Listing) -> str:
    return f"id:{listing.id}" if listing.id is not None else f"fp:{listing.fingerprint}"


def _row_key(row: dict[str, Any]) -> str:
    if row.get("listing_id") is not None:
        return f"id:{row['listing_id']}"
    return f"fp:{row.get('fingerprint')}"


def _has_valid_area(listing: Listing) -> bool:
    area = built_area(listing)
    return area is not None and area > 0


def normalize_comuna(value: Any) -> str:
    return str(value or "").replace("_", " ").strip().lower()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
