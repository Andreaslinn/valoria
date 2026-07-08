"""Read-only audit for hierarchical shadow microzones."""
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
from time import perf_counter
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.entities.listing import Listing, Property  # noqa: E402
from core.exceptions import InsufficientDataError, ValidationError  # noqa: E402
from core.normalization.property_type import normalize_property_type as _property_type  # noqa: E402
from domain.geocoding.hierarchical_microzones import (  # noqa: E402
    HierarchicalMicrozoneAssignment,
    assign_hierarchical_microzone,
)
from domain.geocoding.microzone_shadow import assign_shadow_microzone  # noqa: E402
from domain.valuation.comparables import valuate_with_comparables  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import UFRateORM  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402
from scripts.audit_microzone_eligibility import ListingEligibility, classify_listing  # noqa: E402
from scripts.audit_radar_funnel import EvaluatedRow, evaluate_universe, quantiles  # noqa: E402

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
USEFUL_THRESHOLDS = {
    1: (3, 5, 10, 20),
    2: (3, 5, 10),
    3: (3, 5, 10),
    4: (3, 5),
}
COMPARABLE_SAMPLE_SIZE = 120


@dataclass(frozen=True)
class ComparableHierarchyRow:
    listing_id: int | None
    comuna: str
    property_type: str
    subject_level: int
    comparables_used: int
    same_level_4_ratio: float
    same_level_3_ratio: float
    same_level_2_ratio: float
    same_level_1_ratio: float
    comuna_only_ratio: float
    no_shared_location_signal_ratio: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate hierarchical microzones audit.")
    parser.add_argument("--uf-rate", type=Decimal)
    parser.add_argument("--output-dir", default="reports/microzones")
    parser.add_argument("--comparable-sample-size", type=int, default=COMPARABLE_SAMPLE_SIZE)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    start = perf_counter()
    async with get_session_factory()() as session:
        listings = list(await SqlAlchemyListingRepository(session).list_active())
        uf_rate = args.uf_rate or await _latest_uf_rate(session)
    if uf_rate is None:
        raise SystemExit("No UF rate provided and no local uf_rates row found. Pass --uf-rate.")

    active = [listing for listing in listings if listing.is_active]
    hierarchical = {_listing_key(listing): assign_hierarchical_microzone(listing) for listing in active}
    shadow = {_listing_key(listing): assign_shadow_microzone(listing) for listing in active}
    eligibility = {_listing_key(listing): classify_listing(listing) for listing in active}
    group_index = build_group_index(active, hierarchical)
    evaluated = evaluate_universe(active, uf_rate)
    comparable_rows = comparable_diagnostics(
        evaluated=evaluated,
        listings=active,
        assignments=hierarchical,
        uf_rate=uf_rate,
        sample_size=args.comparable_sample_size,
    )
    report = build_report(
        listings=active,
        hierarchical=hierarchical,
        shadow=shadow,
        eligibility=eligibility,
        group_index=group_index,
        evaluated=evaluated,
        comparable_rows=comparable_rows,
        uf_rate=uf_rate,
        runtime_ms=round((perf_counter() - start) * 1000, 2),
    )
    write_outputs(report, Path(args.output_dir))
    print(
        json.dumps(
            {
                "active_listings": report["summary"]["active_listings"],
                "hierarchical_real_microzone_pct": report["coverage"]["hierarchical_real_microzone_pct"],
                "level_distribution": report["coverage"]["best_available_level_counts"],
                "radar_discount_over_60": report["radar_diagnostics"]["discount_over_60"],
                "json": str(Path(args.output_dir) / "hierarchical_microzones_audit_latest.json"),
                "markdown": str(Path(args.output_dir) / "hierarchical_microzones_audit_latest.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_report(
    *,
    listings: Sequence[Listing],
    hierarchical: dict[str, HierarchicalMicrozoneAssignment],
    shadow: dict[str, Any],
    eligibility: dict[str, ListingEligibility],
    group_index: dict[int, Counter[tuple[str, str, str]]],
    evaluated: Sequence[EvaluatedRow],
    comparable_rows: Sequence[ComparableHierarchyRow],
    uf_rate: Decimal,
    runtime_ms: float,
) -> dict[str, Any]:
    coverage = coverage_summary(listings, hierarchical, shadow, eligibility, group_index)
    groups = group_summary(group_index)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": {
            "active_listings": len(listings),
            "active_apartments": sum(1 for listing in listings if _property_type(listing) == "apartment"),
            "active_houses": sum(1 for listing in listings if _property_type(listing) == "house"),
            "uf_rate_used": str(uf_rate),
            "runtime_ms": runtime_ms,
            "read_only": True,
            "productive_code_modified": False,
        },
        "coverage": coverage,
        "density_by_level": groups,
        "comunas": comuna_summary(listings, hierarchical, shadow, group_index),
        "apartment_focus": apartment_summary(listings, hierarchical, shadow, group_index),
        "comparables_diagnostics": summarize_comparables(comparable_rows),
        "radar_diagnostics": radar_diagnostics(evaluated, hierarchical, group_index),
        "explicit_answers": explicit_answers(coverage, groups),
        "recommendation": recommendation(coverage, groups),
        "do_not_do_yet": [
            "Do not persist assignments yet.",
            "Do not change Radar or AVM scoring.",
            "Do not hard-filter comparables using level_2 or level_3 before holdout validation.",
            "Do not run broad external geocoding or historical backfills.",
            "Do not create a large manual catalog until the shadow hierarchy stabilizes.",
        ],
        "examples": examples(listings, hierarchical, eligibility),
    }


def coverage_summary(
    listings: Sequence[Listing],
    hierarchical: dict[str, HierarchicalMicrozoneAssignment],
    shadow: dict[str, Any],
    eligibility: dict[str, ListingEligibility],
    group_index: dict[int, Counter[tuple[str, str, str]]],
) -> dict[str, Any]:
    total = len(listings)
    shadow_real = sum(shadow[_listing_key(listing)].is_real_microzone for listing in listings)
    hierarchy_real = sum(hierarchical[_listing_key(listing)].is_real_microzone for listing in listings)
    shadow_fallback = sum(shadow[_listing_key(listing)].microzone_kind == "comuna_fallback" for listing in listings)
    hierarchy_fallback = sum(hierarchical[_listing_key(listing)].is_fallback_only for listing in listings)
    level_counts = Counter(f"level_{hierarchical[_listing_key(listing)].best_available_level}" for listing in listings)
    street_reference = [row for row in eligibility.values() if row.street_used_only_as_reference]
    strong_street = [row for row in eligibility.values() if row.street_microzone_candidate]
    street_reference_to_level = Counter(
        f"level_{hierarchical[_eligibility_key(row)].best_available_level}"
        for row in street_reference
        if _eligibility_key(row) in hierarchical and hierarchical[_eligibility_key(row)].is_real_microzone
    )
    street_reference_with_any = sum(
        1 for row in street_reference
        if _eligibility_key(row) in hierarchical and hierarchical[_eligibility_key(row)].is_real_microzone
    )
    strong_street_useful = strong_street_useful_counts(strong_street, hierarchical, group_index)
    current_weak_to_real = sum(
        1
        for listing in listings
        if (
            not shadow[_listing_key(listing)].is_real_microzone
            or (
                shadow[_listing_key(listing)].microzone_kind == "textual"
                and shadow[_listing_key(listing)].confidence == "low"
            )
        )
        and hierarchical[_listing_key(listing)].is_real_microzone
    )
    warnings = Counter(warning for assignment in hierarchical.values() for warning in assignment.warnings)
    return {
        "shadow_real_microzone_count": shadow_real,
        "shadow_real_microzone_pct": pct(shadow_real, total),
        "hierarchical_real_microzone_count": hierarchy_real,
        "hierarchical_real_microzone_pct": pct(hierarchy_real, total),
        "shadow_comuna_fallback_count": shadow_fallback,
        "shadow_comuna_fallback_pct": pct(shadow_fallback, total),
        "hierarchical_comuna_fallback_count": hierarchy_fallback,
        "hierarchical_comuna_fallback_pct": pct(hierarchy_fallback, total),
        "coverage_gain_count": hierarchy_real - shadow_real,
        "coverage_gain_pct_points": round(pct(hierarchy_real, total) - pct(shadow_real, total), 2),
        "best_available_level_counts": counter_dict(level_counts),
        "confidence_distribution": counter_dict(Counter(item.confidence for item in hierarchical.values())),
        "street_reference_to_any_hierarchical_level": street_reference_with_any,
        "street_reference_to_level_counts": counter_dict(street_reference_to_level),
        "current_fallback_or_weak_textual_to_real": current_weak_to_real,
        "strong_street_candidates": len(strong_street),
        "strong_street_candidates_useful_groups": strong_street_useful,
        "top_warnings": counter_dict(warnings, limit=30),
    }


def strong_street_useful_counts(
    rows: Sequence[ListingEligibility],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    group_index: dict[int, Counter[tuple[str, str, str]]],
) -> dict[str, int]:
    counts = {"useful_3_plus": 0, "useful_5_plus": 0, "useful_10_plus": 0}
    for row in rows:
        key = _eligibility_key(row)
        assignment = assignments.get(key)
        if assignment is None or not assignment.level_3_key:
            continue
        group_count = group_index[3][(assignment.level_3_key, row.comuna, row.property_type)]
        if group_count >= 3:
            counts["useful_3_plus"] += 1
        if group_count >= 5:
            counts["useful_5_plus"] += 1
        if group_count >= 10:
            counts["useful_10_plus"] += 1
    return counts


def build_group_index(
    listings: Sequence[Listing],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
) -> dict[int, Counter[tuple[str, str, str]]]:
    group_index = {level: Counter() for level in (1, 2, 3, 4)}
    for listing in listings:
        assignment = assignments[_listing_key(listing)]
        for level in (1, 2, 3, 4):
            key = getattr(assignment, f"level_{level}_key")
            if not key:
                continue
            group_index[level][(key, listing.comuna, _property_type(listing))] += 1
    return group_index


def group_summary(group_index: dict[int, Counter[tuple[str, str, str]]]) -> dict[str, Any]:
    result = {}
    for level, counter in group_index.items():
        values = list(counter.values())
        thresholds = USEFUL_THRESHOLDS[level]
        result[f"level_{level}"] = {
            "group_count": len(counter),
            "listing_memberships": sum(values),
            "useful_groups": {
                f"useful_{threshold}_plus": sum(1 for count in values if count >= threshold)
                for threshold in thresholds
            },
            "listings_in_useful_groups": {
                f"useful_{threshold}_plus": sum(count for count in values if count >= threshold)
                for threshold in thresholds
            },
            "group_size_quantiles": quantiles(values),
            "top_groups": top_groups(counter),
        }
    return result


def comuna_summary(
    listings: Sequence[Listing],
    hierarchical: dict[str, HierarchicalMicrozoneAssignment],
    shadow: dict[str, Any],
    group_index: dict[int, Counter[tuple[str, str, str]]],
) -> list[dict[str, Any]]:
    critical = {_normalize_comuna(value) for value in CRITICAL_COMUNAS}
    grouped: dict[str, list[Listing]] = defaultdict(list)
    for listing in listings:
        normalized = _normalize_comuna(listing.comuna)
        if normalized in critical:
            grouped[normalized].append(listing)
    rows = []
    for comuna in sorted(critical):
        items = grouped.get(comuna, [])
        rows.append(comuna_row(comuna, items, hierarchical, shadow, group_index))
    return rows


def comuna_row(
    comuna: str,
    items: Sequence[Listing],
    hierarchical: dict[str, HierarchicalMicrozoneAssignment],
    shadow: dict[str, Any],
    group_index: dict[int, Counter[tuple[str, str, str]]],
) -> dict[str, Any]:
    keys = [_listing_key(listing) for listing in items]
    shadow_real = sum(shadow[key].is_real_microzone for key in keys)
    hier_real = sum(hierarchical[key].is_real_microzone for key in keys)
    level_counts = Counter(f"level_{hierarchical[key].best_available_level}" for key in keys)
    return {
        "comuna": comuna,
        "active": len(items),
        "active_apartments": sum(1 for listing in items if _property_type(listing) == "apartment"),
        "shadow_coverage_pct": pct(shadow_real, len(items)),
        "hierarchical_coverage_pct": pct(hier_real, len(items)),
        "level_distribution": counter_dict(level_counts),
        "useful_groups": useful_groups_for_comuna(comuna, group_index),
        "top_level_1_groups": top_groups_for_comuna(comuna, group_index[1]),
        "top_level_2_groups": top_groups_for_comuna(comuna, group_index[2]),
        "top_level_3_groups": top_groups_for_comuna(comuna, group_index[3]),
        "good_examples": [
            listing_example(listing, hierarchical[_listing_key(listing)])
            for listing in items
            if hierarchical[_listing_key(listing)].best_available_level >= 2
        ][:5],
        "ambiguous_examples": [
            listing_example(listing, hierarchical[_listing_key(listing)])
            for listing in items
            if hierarchical[_listing_key(listing)].confidence == "low"
            and hierarchical[_listing_key(listing)].is_real_microzone
        ][:5],
        "rejected_examples": [
            listing_example(listing, hierarchical[_listing_key(listing)])
            for listing in items
            if hierarchical[_listing_key(listing)].is_fallback_only
        ][:5],
    }


def useful_groups_for_comuna(comuna: str, group_index: dict[int, Counter[tuple[str, str, str]]]) -> dict[str, Any]:
    result = {}
    for level, counter in group_index.items():
        values = [count for (_, group_comuna, _), count in counter.items() if _normalize_comuna(group_comuna) == comuna]
        result[f"level_{level}"] = {
            f"useful_{threshold}_plus": sum(1 for count in values if count >= threshold)
            for threshold in USEFUL_THRESHOLDS[level]
        }
    return result


def apartment_summary(
    listings: Sequence[Listing],
    hierarchical: dict[str, HierarchicalMicrozoneAssignment],
    shadow: dict[str, Any],
    group_index: dict[int, Counter[tuple[str, str, str]]],
) -> dict[str, Any]:
    apartments = [listing for listing in listings if _property_type(listing) == "apartment"]
    keys = [_listing_key(listing) for listing in apartments]
    shadow_real = sum(shadow[key].is_real_microzone for key in keys)
    hier_real = sum(hierarchical[key].is_real_microzone for key in keys)
    return {
        "active_apartments": len(apartments),
        "shadow_coverage_pct": pct(shadow_real, len(apartments)),
        "hierarchical_coverage_pct": pct(hier_real, len(apartments)),
        "best_available_level_counts": counter_dict(Counter(f"level_{hierarchical[key].best_available_level}" for key in keys)),
        "density_by_level_apartments": group_summary(_property_type_group_index(group_index, "apartment")),
    }


def _property_type_group_index(
    group_index: dict[int, Counter[tuple[str, str, str]]],
    property_type: str,
) -> dict[int, Counter[tuple[str, str, str]]]:
    return {
        level: Counter({key: count for key, count in counter.items() if key[2] == property_type})
        for level, counter in group_index.items()
    }


def comparable_diagnostics(
    *,
    evaluated: Sequence[EvaluatedRow],
    listings: Sequence[Listing],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    uf_rate: Decimal,
    sample_size: int,
) -> list[ComparableHierarchyRow]:
    sample = comparable_sample(evaluated, sample_size)
    processable = [listing for listing in listings if listing.is_active and _built_area(listing)]
    rows = []
    for row in sample:
        target = _listing_as_property(row.listing)
        candidates = [
            listing for listing in processable
            if _listing_key(listing) != _listing_key(row.listing)
            and _property_type(listing) == _property_type(row.listing)
        ]
        try:
            valuation_run = valuate_with_comparables(target, candidates, uf_rate)
        except (InsufficientDataError, ValidationError):
            continue
        comparables = [listing for _, listing in valuation_run.scored_comparables]
        rows.append(comparable_row(row.listing, comparables, assignments))
    return rows


def comparable_sample(evaluated: Sequence[EvaluatedRow], sample_size: int) -> list[EvaluatedRow]:
    successful = [row for row in evaluated if row.valuation_success]
    critical = [
        row for row in successful
        if _normalize_comuna(row.audit.comuna) in {_normalize_comuna(value) for value in CRITICAL_COMUNAS}
    ]
    extremes = [row for row in successful if (row.audit.discount_pct or 0) > 60]
    selected: dict[str, EvaluatedRow] = {}
    for row in sorted(extremes, key=lambda item: item.audit.discount_pct or 0, reverse=True):
        selected[_listing_key(row.listing)] = row
    for row in sorted(critical, key=lambda item: item.audit.opportunity_score or 0, reverse=True):
        selected.setdefault(_listing_key(row.listing), row)
        if len(selected) >= sample_size:
            break
    for row in successful:
        selected.setdefault(_listing_key(row.listing), row)
        if len(selected) >= sample_size:
            break
    return list(selected.values())[:sample_size]


def comparable_row(
    subject: Listing,
    comparables: Sequence[Listing],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
) -> ComparableHierarchyRow:
    subject_assignment = assignments[_listing_key(subject)]
    comparable_assignments = [assignments[_listing_key(listing)] for listing in comparables]
    shared_any = [
        _shared_level(subject_assignment, assignment)
        for assignment in comparable_assignments
    ]
    total = len(comparables)
    comuna_only = sum(level == 0 for level in shared_any)
    no_shared = sum(level == -1 for level in shared_any)
    return ComparableHierarchyRow(
        listing_id=subject.id,
        comuna=subject.comuna,
        property_type=_property_type(subject),
        subject_level=subject_assignment.best_available_level,
        comparables_used=total,
        same_level_4_ratio=ratio(sum(_same_level(subject_assignment, item, 4) for item in comparable_assignments), total),
        same_level_3_ratio=ratio(sum(_same_level(subject_assignment, item, 3) for item in comparable_assignments), total),
        same_level_2_ratio=ratio(sum(_same_level(subject_assignment, item, 2) for item in comparable_assignments), total),
        same_level_1_ratio=ratio(sum(_same_level(subject_assignment, item, 1) for item in comparable_assignments), total),
        comuna_only_ratio=ratio(comuna_only, total),
        no_shared_location_signal_ratio=ratio(no_shared, total),
    )


def summarize_comparables(rows: Sequence[ComparableHierarchyRow]) -> dict[str, Any]:
    return {
        "sample_size": len(rows),
        "same_level_4_ratio": quantiles(row.same_level_4_ratio for row in rows),
        "same_level_3_ratio": quantiles(row.same_level_3_ratio for row in rows),
        "same_level_2_ratio": quantiles(row.same_level_2_ratio for row in rows),
        "same_level_1_ratio": quantiles(row.same_level_1_ratio for row in rows),
        "comuna_only_ratio": quantiles(row.comuna_only_ratio for row in rows),
        "no_shared_location_signal_ratio": quantiles(row.no_shared_location_signal_ratio for row in rows),
        "by_subject_level": counter_dict(Counter(f"level_{row.subject_level}" for row in rows)),
        "examples": [asdict(row) for row in rows[:30]],
    }


def radar_diagnostics(
    evaluated: Sequence[EvaluatedRow],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    group_index: dict[int, Counter[tuple[str, str, str]]],
) -> dict[str, Any]:
    opportunities = [row for row in evaluated if row.candidate]
    over_60 = [row for row in opportunities if (row.audit.discount_pct or 0) > 60]
    opportunity_levels = Counter(f"level_{assignments[_listing_key(row.listing)].best_available_level}" for row in opportunities)
    over_60_levels = Counter(f"level_{assignments[_listing_key(row.listing)].best_available_level}" for row in over_60)
    over_60_sufficient = [
        row for row in over_60
        if _assignment_has_sufficient_density(row.listing, assignments[_listing_key(row.listing)], group_index)
    ]
    return {
        "radar_opportunities": len(opportunities),
        "opportunity_level_distribution": counter_dict(opportunity_levels),
        "discount_over_60": len(over_60),
        "discount_over_60_level_distribution": counter_dict(over_60_levels),
        "discount_over_60_only_level_0": sum(assignments[_listing_key(row.listing)].best_available_level == 0 for row in over_60),
        "discount_over_60_level_1_to_3": sum(1 <= assignments[_listing_key(row.listing)].best_available_level <= 3 for row in over_60),
        "discount_over_60_sufficient_density_3_plus": len(over_60_sufficient),
        "top_comunas_over_60": counter_dict(Counter(row.audit.comuna for row in over_60), limit=20),
        "examples_over_60": [
            {
                "listing_id": row.audit.listing_id,
                "comuna": row.audit.comuna,
                "property_type": row.audit.property_type,
                "discount_pct": row.audit.discount_pct,
                "best_level": assignments[_listing_key(row.listing)].best_available_level,
                "best_key": assignments[_listing_key(row.listing)].best_available_key,
                "confidence": assignments[_listing_key(row.listing)].confidence,
                "sufficient_density_3_plus": _assignment_has_sufficient_density(
                    row.listing,
                    assignments[_listing_key(row.listing)],
                    group_index,
                ),
                "title": row.audit.title,
                "url": row.audit.url,
            }
            for row in over_60[:50]
        ],
    }


def explicit_answers(coverage: dict[str, Any], groups: dict[str, Any]) -> dict[str, str]:
    level3_useful = groups["level_3"]["useful_groups"].get("useful_5_plus", 0)
    level2_useful = groups["level_2"]["useful_groups"].get("useful_5_plus", 0)
    return {
        "should_implement_hierarchical_microzones": (
            "yes as a reusable read-only/shadow layer; not as productive scoring yet"
            if coverage["coverage_gain_count"] > 0 else "not yet"
        ),
        "strong_filter_level": "level_4 only today; level_3 needs holdout validation and density thresholds",
        "secondary_signal_level": "level_2 and dense level_3 groups",
        "street_microzone_value": (
            "real shadow microzone when source is specific and groups have density; otherwise hint/diagnostic"
            if level3_useful else "mostly hint until density improves"
        ),
        "persist_assignments_now": "no; run at least one more stability audit and version the taxonomy first",
        "external_geocoding_now": "no broad geocoding; improve extraction and use targeted forward geocoding later",
        "level_2_useful_groups_5_plus": str(level2_useful),
        "level_3_useful_groups_5_plus": str(level3_useful),
    }


def recommendation(coverage: dict[str, Any], groups: dict[str, Any]) -> dict[str, Any]:
    level3_useful = groups["level_3"]["useful_groups"].get("useful_3_plus", 0)
    if coverage["coverage_gain_count"] > 0 and level3_useful:
        path = "A + C, then D targeted, postpone B"
        reason = (
            "Hierarchical microzones materially improve shadow coverage and level_3 forms useful groups, "
            "but persistence and productive filtering need stability/holdout validation."
        )
    else:
        path = "C first"
        reason = "The hierarchy should stay diagnostic until extraction creates enough dense groups."
    return {
        "recommended_path": path,
        "why": reason,
        "next_actions": [
            "Keep hierarchical_microzones as read-only reusable layer.",
            "Improve street/corridor extraction and normalize ambiguous street_hint values.",
            "Run a stability audit comparing current and next refresh snapshots.",
            "Use targeted forward geocoding only for high-value dense corridors.",
        ],
        "defer": [
            "persisted assignments",
            "hard comparable filter",
            "Radar score changes",
            "large manual catalog",
        ],
    }


def examples(
    listings: Sequence[Listing],
    assignments: dict[str, HierarchicalMicrozoneAssignment],
    eligibility: dict[str, ListingEligibility],
) -> dict[str, list[dict[str, Any]]]:
    rows = sorted(
        listings,
        key=lambda listing: assignments[_listing_key(listing)].best_available_level,
        reverse=True,
    )
    return {
        "good": [listing_example(listing, assignments[_listing_key(listing)]) for listing in rows if assignments[_listing_key(listing)].best_available_level >= 3][:20],
        "ambiguous": [
            listing_example(listing, assignments[_listing_key(listing)])
            for listing in rows
            if assignments[_listing_key(listing)].confidence == "low"
            and assignments[_listing_key(listing)].is_real_microzone
        ][:20],
        "rejected_or_fallback": [
            {
                **listing_example(listing, assignments[_listing_key(listing)]),
                "eligibility_bucket": eligibility[_listing_key(listing)].bucket,
            }
            for listing in listings
            if assignments[_listing_key(listing)].is_fallback_only
        ][:20],
    }


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "hierarchical_microzones_audit_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "hierarchical_microzones_audit_latest.md").write_text(
        markdown_report(report),
        encoding="utf-8",
    )


def markdown_report(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    answers = report["explicit_answers"]
    radar = report["radar_diagnostics"]
    comp = report["comparables_diagnostics"]
    lines = [
        "# Hierarchical Microzones Audit",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Executive Summary",
        "",
        f"- Active listings: `{report['summary']['active_listings']}`",
        f"- Active apartments: `{report['summary']['active_apartments']}`",
        f"- Current shadow real coverage: `{coverage['shadow_real_microzone_pct']}%`",
        f"- Hierarchical real coverage: `{coverage['hierarchical_real_microzone_pct']}%`",
        f"- Coverage gain: `{coverage['coverage_gain_count']}` listings (`{coverage['coverage_gain_pct_points']}` pts)",
        f"- Best level distribution: `{coverage['best_available_level_counts']}`",
        f"- Street/reference now with hierarchy: `{coverage['street_reference_to_any_hierarchical_level']}`",
        f"- Radar >60%: `{radar['discount_over_60']}`; sufficient density: `{radar['discount_over_60_sufficient_density_3_plus']}`",
        "",
        "## Why Geo 500m Is Small",
        "",
        "Level 4 still requires real coordinates plus address/street geocode precision. Comuna centroid, unknown precision, title text and street_hint alone cannot create a geo cell.",
        "",
        "## Density By Level",
        "",
        "| Level | Groups | Useful 3+ | Useful 5+ | Useful 10+ | Useful 20+ |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for level_name, data in report["density_by_level"].items():
        useful = data["useful_groups"]
        lines.append(
            f"| `{level_name}` | {data['group_count']} | {useful.get('useful_3_plus', '')} | "
            f"{useful.get('useful_5_plus', '')} | {useful.get('useful_10_plus', '')} | "
            f"{useful.get('useful_20_plus', '')} |"
        )
    lines.extend(
        [
            "",
            "## Comunas",
            "",
            "| Comuna | Active | Apartments | Shadow % | Hierarchical % | Levels |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report["comunas"]:
        lines.append(
            f"| `{row['comuna']}` | {row['active']} | {row['active_apartments']} | "
            f"{row['shadow_coverage_pct']} | {row['hierarchical_coverage_pct']} | "
            f"`{row['level_distribution']}` |"
        )
    lines.extend(
        [
            "",
            "## Comparables",
            "",
            f"- Sample size: `{comp['sample_size']}`",
            f"- Same level 4 p50: `{comp['same_level_4_ratio']['p50']}`",
            f"- Same level 3 p50: `{comp['same_level_3_ratio']['p50']}`",
            f"- Same level 2 p50: `{comp['same_level_2_ratio']['p50']}`",
            f"- Same level 1 p50: `{comp['same_level_1_ratio']['p50']}`",
            f"- Comuna-only p50: `{comp['comuna_only_ratio']['p50']}`",
            "",
            "## Radar >60%",
            "",
            f"- Level distribution: `{radar['discount_over_60_level_distribution']}`",
            f"- Only level 0: `{radar['discount_over_60_only_level_0']}`",
            f"- Level 1-3: `{radar['discount_over_60_level_1_to_3']}`",
            f"- In groups with density 3+: `{radar['discount_over_60_sufficient_density_3_plus']}`",
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
            "No DB writes, migrations, Radar/AVM/frontend changes, scrapers, external geocoding, backfills or scoring changes were made.",
            "",
        ]
    )
    return "\n".join(lines)


def top_groups(counter: Counter[tuple[str, str, str]], *, limit: int = 20) -> list[dict[str, Any]]:
    return [
        {"key": key, "comuna": comuna, "property_type": property_type, "count": count}
        for (key, comuna, property_type), count in counter.most_common(limit)
    ]


def top_groups_for_comuna(comuna: str, counter: Counter[tuple[str, str, str]], *, limit: int = 10) -> list[dict[str, Any]]:
    rows = [
        ((key, group_comuna, property_type), count)
        for (key, group_comuna, property_type), count in counter.items()
        if _normalize_comuna(group_comuna) == comuna
    ]
    rows.sort(key=lambda item: item[1], reverse=True)
    return [
        {"key": key, "property_type": property_type, "count": count}
        for (key, _, property_type), count in rows[:limit]
    ]


def listing_example(listing: Listing, assignment: HierarchicalMicrozoneAssignment) -> dict[str, Any]:
    return {
        "listing_id": listing.id,
        "title": listing.title,
        "comuna": listing.comuna,
        "property_type": _property_type(listing),
        "best_level": assignment.best_available_level,
        "best_key": assignment.best_available_key,
        "confidence": assignment.confidence,
        "source_fields": list(assignment.source_fields),
        "warnings": list(assignment.warnings[:5]),
    }


def _same_level(left: HierarchicalMicrozoneAssignment, right: HierarchicalMicrozoneAssignment, level: int) -> bool:
    key = getattr(left, f"level_{level}_key")
    return bool(key and key == getattr(right, f"level_{level}_key"))


def _shared_level(left: HierarchicalMicrozoneAssignment, right: HierarchicalMicrozoneAssignment) -> int:
    for level in (4, 3, 2, 1):
        if _same_level(left, right, level):
            return level
    if left.level_0_key and left.level_0_key == right.level_0_key:
        return 0
    return -1


def _assignment_has_sufficient_density(
    listing: Listing,
    assignment: HierarchicalMicrozoneAssignment,
    group_index: dict[int, Counter[tuple[str, str, str]]],
    *,
    threshold: int = 3,
) -> bool:
    level = assignment.best_available_level
    if level < 1:
        return False
    key = getattr(assignment, f"level_{level}_key")
    if not key:
        return False
    return group_index[level][(key, listing.comuna, _property_type(listing))] >= threshold


def ratio(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 4) if denominator else 0.0


def pct(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator) * 100, 2) if denominator else 0.0


def counter_dict(counter: Counter[str], *, limit: int | None = None) -> dict[str, int]:
    return dict(counter.most_common(limit))


def _listing_key(listing: Listing) -> str:
    return f"id:{listing.id}" if listing.id is not None else f"fp:{listing.fingerprint}"


def _eligibility_key(row: ListingEligibility) -> str:
    return f"id:{row.listing_id}" if row.listing_id is not None else f"title:{row.title}"


def _normalize_comuna(value: str | None) -> str:
    return str(value or "").replace("_", " ").strip().lower()


def _built_area(listing: Listing) -> float | None:
    return listing.built_area_m2 or listing.usable_area_m2 or listing.m2


def _listing_as_property(listing: Listing) -> Property:
    return Property(
        id=listing.property_id,
        comuna=listing.comuna,
        m2=float(listing.m2 or 0),
        property_type=listing.property_type,
        built_area_m2=listing.built_area_m2,
        land_area_m2=listing.land_area_m2,
        usable_area_m2=listing.usable_area_m2,
        bedrooms=listing.bedrooms,
        bathrooms=listing.bathrooms,
        parking=listing.parking,
        coordinates=listing.coordinates,
        geocode_precision=listing.geocode_precision,
        raw_metadata=listing.raw_metadata,
    )


async def _latest_uf_rate(session) -> Decimal | None:
    result = await session.execute(select(UFRateORM).order_by(UFRateORM.date.desc()).limit(1))
    row = result.scalar_one_or_none()
    return Decimal(row.value_clp) if row is not None else None


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
