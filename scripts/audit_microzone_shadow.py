"""Read-only microzone shadow audit for Radar and comparables."""
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
from domain.geocoding.microzone_shadow import (  # noqa: E402
    WEAK_GEOCODE_PRECISIONS,
    ShadowMicrozoneAssignment,
    assign_shadow_microzone,
)
from domain.valuation.comparables import valuate_with_comparables  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import UFRateORM  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402
from scripts.audit_radar_funnel import EvaluatedRow, evaluate_universe, quantiles  # noqa: E402

CRITICAL_COMUNAS = (
    "santiago",
    "las condes",
    "providencia",
    "nunoa",
    "vitacura",
    "estacion central",
    "san miguel",
    "la florida",
    "macul",
    "independencia",
)
MIN_SAME_MICROZONE_COMPARABLES = 5


@dataclass(frozen=True)
class ComparableShadowRow:
    listing_id: int | None
    comuna: str
    property_type: str
    microzone_kind: str
    microzone_key: str | None
    comparables_used: int
    same_real_microzone_ratio: float
    same_textual_microzone_ratio: float
    comuna_only_ratio: float
    weak_geo_comparable_ratio: float
    current_comparable_mix_warning: bool
    microzone_aware_bucket: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate read-only shadow microzone audit.")
    parser.add_argument("--uf-rate", type=Decimal)
    parser.add_argument("--output-dir", default="reports/microzones")
    parser.add_argument("--comparable-sample-size", type=int, default=120)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    start = perf_counter()
    async with get_session_factory()() as session:
        listings = list(await SqlAlchemyListingRepository(session).list_active())
        uf_rate = args.uf_rate or await _latest_uf_rate(session)
    if uf_rate is None:
        raise SystemExit("No UF rate provided and no local uf_rates row found. Pass --uf-rate.")

    assignments = {id(listing): assign_shadow_microzone(listing) for listing in listings}
    evaluated = evaluate_universe(listings, uf_rate)
    radar = radar_shadow_diagnostics(evaluated, assignments)
    comparable_rows = comparable_shadow_diagnostics(
        evaluated=evaluated,
        listings=listings,
        uf_rate=uf_rate,
        sample_size=args.comparable_sample_size,
    )
    report = build_report(
        listings=listings,
        assignments=assignments,
        evaluated=evaluated,
        radar=radar,
        comparable_rows=comparable_rows,
        uf_rate=uf_rate,
        runtime_ms=round((perf_counter() - start) * 1000, 2),
    )
    write_outputs(report, Path(args.output_dir))
    print(
        json.dumps(
            {
                "active_listings": report["summary"]["active_listings"],
                "radar_candidates": report["radar_extremes"]["radar_opportunities"],
                "discount_over_60": report["radar_extremes"]["discount_over_60"],
                "discount_over_60_without_real_microzone_pct": report["radar_extremes"]["pct_over_60_without_real_microzone"],
                "json": str(Path(args.output_dir) / "microzone_shadow_audit_latest.json"),
                "markdown": str(Path(args.output_dir) / "microzone_shadow_audit_latest.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_report(
    *,
    listings: Sequence[Listing],
    assignments: dict[int, ShadowMicrozoneAssignment],
    evaluated: Sequence[EvaluatedRow],
    radar: dict[str, Any],
    comparable_rows: Sequence[ComparableShadowRow],
    uf_rate: Decimal,
    runtime_ms: float,
) -> dict[str, Any]:
    active = [listing for listing in listings if listing.is_active]
    coverage = coverage_summary(active, assignments)
    comparable_summary = summarize_comparables(comparable_rows)
    priorities = priority_comunas(coverage, radar, comparable_rows)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": {
            "active_listings": len(active),
            "active_apartments": sum(1 for listing in active if _property_type(listing) == "apartment"),
            "active_houses": sum(1 for listing in active if _property_type(listing) == "house"),
            "uf_rate_used": str(uf_rate),
            "runtime_ms": runtime_ms,
            "read_only": True,
            "productive_code_modified": False,
        },
        "coverage": coverage,
        "radar_extremes": radar,
        "comparables_shadow": comparable_summary,
        "priority_comunas": priorities,
        "recommendation": recommendation(radar, comparable_summary),
        "do_not_do_yet": [
            "Do not create a persisted microzones table.",
            "Do not hard-filter productive comparables by microzone.",
            "Do not backfill historical coordinates or call external geocoding.",
            "Do not suppress Radar opportunities automatically.",
            "Do not change frontend labels or AVM scoring from this audit alone.",
        ],
        "sample_rows": {
            "radar_extreme_over_60": radar["extreme_rows"][:50],
            "comparable_shadow": [asdict(row) for row in comparable_rows[:100]],
        },
        "commands_run": [
            "python scripts/audit_microzone_shadow.py",
            "python -m ruff check domain/geocoding/microzone_shadow.py scripts/audit_microzone_shadow.py tests/unit/test_microzone_shadow.py",
            "pytest tests/unit/test_microzone_shadow.py",
        ],
    }


def coverage_summary(
    active: Sequence[Listing],
    assignments: dict[int, ShadowMicrozoneAssignment],
) -> dict[str, Any]:
    by_kind = Counter(assignments[id(listing)].microzone_kind for listing in active)
    by_confidence = Counter(assignments[id(listing)].confidence for listing in active)
    real_count = sum(1 for listing in active if assignments[id(listing)].is_real_microzone)
    return {
        "total_active": len(active),
        "geo_microzone_500m": by_kind["geo_500m"],
        "geo_microzone_500m_pct": pct(by_kind["geo_500m"], len(active)),
        "textual_microzone": by_kind["textual"],
        "textual_microzone_pct": pct(by_kind["textual"], len(active)),
        "comuna_fallback": by_kind["comuna_fallback"],
        "comuna_fallback_pct": pct(by_kind["comuna_fallback"], len(active)),
        "none": by_kind["none"],
        "none_pct": pct(by_kind["none"], len(active)),
        "real_microzone": real_count,
        "real_microzone_pct": pct(real_count, len(active)),
        "by_confidence": counter_dict(by_confidence),
        "by_comuna": grouped_coverage(active, assignments, "comuna"),
        "by_geocode_precision": grouped_coverage(active, assignments, "geocode_precision"),
        "by_property_type": grouped_coverage(active, assignments, "property_type"),
    }


def grouped_coverage(
    listings: Sequence[Listing],
    assignments: dict[int, ShadowMicrozoneAssignment],
    field: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[Listing]] = defaultdict(list)
    for listing in listings:
        value = _property_type(listing) if field == "property_type" else getattr(listing, field, None)
        groups[str(value or "unknown").strip().lower()].append(listing)
    rows = []
    for value, group in groups.items():
        kinds = Counter(assignments[id(listing)].microzone_kind for listing in group)
        real = sum(1 for listing in group if assignments[id(listing)].is_real_microzone)
        rows.append(
            {
                "value": value,
                "active": len(group),
                "geo_500m": kinds["geo_500m"],
                "textual": kinds["textual"],
                "comuna_fallback": kinds["comuna_fallback"],
                "none": kinds["none"],
                "real_microzone_pct": pct(real, len(group)),
            }
        )
    return sorted(rows, key=lambda row: (-row["active"], row["value"]))


def radar_shadow_diagnostics(
    evaluated: Sequence[EvaluatedRow],
    assignments: dict[int, ShadowMicrozoneAssignment],
) -> dict[str, Any]:
    opportunities = [row for row in evaluated if row.candidate]
    over_60 = [row for row in opportunities if (row.audit.discount_pct or 0) > 60]
    without_real = [row for row in over_60 if not assignments[id(row.listing)].is_real_microzone]
    weak_geo = [
        row for row in over_60
        if str(row.audit.geocode_precision or "unknown") in WEAK_GEOCODE_PRECISIONS
    ]
    warning_counts: Counter[str] = Counter()
    for row in over_60:
        warning_counts.update(_split_codes(row.audit.warning_codes))
        warning_counts.update(assignments[id(row.listing)].warnings)
    return {
        "radar_opportunities": len(opportunities),
        "discount_over_60": len(over_60),
        "pct_over_60_without_real_microzone": pct(len(without_real), len(over_60)),
        "pct_over_60_weak_geocode": pct(len(weak_geo), len(over_60)),
        "suspicious_extreme_if_microzone_rule": len({_listing_key(row.listing) for row in without_real + weak_geo}),
        "top_comunas_over_60": counter_dict(Counter(row.audit.comuna for row in over_60), limit=20),
        "top_property_types_over_60": counter_dict(Counter(row.audit.property_type for row in over_60)),
        "top_microzone_kinds_over_60": counter_dict(Counter(assignments[id(row.listing)].microzone_kind for row in over_60)),
        "top_warnings_over_60": counter_dict(warning_counts, limit=30),
        "extreme_rows": [radar_row(row, assignments[id(row.listing)]) for row in over_60],
    }


def radar_row(row: EvaluatedRow, assignment: ShadowMicrozoneAssignment) -> dict[str, Any]:
    return {
        "listing_id": row.audit.listing_id,
        "comuna": row.audit.comuna,
        "property_type": row.audit.property_type,
        "price_uf": row.audit.listing_price_uf,
        "surface_m2": _built_area(row.listing),
        "discount_pct": row.audit.discount_pct,
        "geocode_precision": row.audit.geocode_precision,
        "microzone_kind": assignment.microzone_kind,
        "microzone_key": assignment.microzone_key,
        "confidence": assignment.confidence,
        "without_real_microzone": not assignment.is_real_microzone,
        "weak_geocode": str(row.audit.geocode_precision or "unknown") in WEAK_GEOCODE_PRECISIONS,
        "warnings": sorted({*_split_codes(row.audit.warning_codes), *assignment.warnings}),
        "title": row.audit.title,
        "url": row.audit.url,
    }


def comparable_shadow_diagnostics(
    *,
    evaluated: Sequence[EvaluatedRow],
    listings: Sequence[Listing],
    uf_rate: Decimal,
    sample_size: int,
) -> list[ComparableShadowRow]:
    sample = comparable_sample(evaluated, sample_size)
    processable = [listing for listing in listings if listing.is_active and _built_area(listing)]
    rows: list[ComparableShadowRow] = []
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
        rows.append(comparable_shadow_row(row.listing, comparables))
    return rows


def comparable_sample(evaluated: Sequence[EvaluatedRow], sample_size: int) -> list[EvaluatedRow]:
    successful = [row for row in evaluated if row.valuation_success]
    critical = [
        row for row in successful
        if _normalize_comuna(row.audit.comuna) in {_normalize_comuna(value) for value in CRITICAL_COMUNAS}
    ]
    extreme = [row for row in successful if (row.audit.discount_pct or 0) > 60]
    selected: dict[str, EvaluatedRow] = {}
    for row in sorted(extreme, key=lambda item: item.audit.discount_pct or 0, reverse=True):
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


def comparable_shadow_row(subject: Listing, comparables: Sequence[Listing]) -> ComparableShadowRow:
    subject_assignment = assign_shadow_microzone(subject)
    comparable_assignments = [assign_shadow_microzone(listing) for listing in comparables]
    same_real = sum(
        1 for assignment in comparable_assignments
        if (
            subject_assignment.is_real_microzone
            and assignment.is_real_microzone
            and assignment.microzone_kind == subject_assignment.microzone_kind
            and assignment.microzone_key == subject_assignment.microzone_key
        )
    )
    same_textual = sum(
        1 for assignment in comparable_assignments
        if (
            subject_assignment.microzone_kind == "textual"
            and assignment.microzone_kind == "textual"
            and assignment.microzone_key == subject_assignment.microzone_key
        )
    )
    comuna_only = sum(1 for assignment in comparable_assignments if assignment.microzone_kind == "comuna_fallback")
    weak_geo = sum(1 for listing in comparables if str(listing.geocode_precision or "unknown") in WEAK_GEOCODE_PRECISIONS)
    total = len(comparables)
    microzone_aware_bucket = simulate_microzone_aware_bucket(subject_assignment, comparable_assignments)
    return ComparableShadowRow(
        listing_id=subject.id,
        comuna=subject.comuna,
        property_type=_property_type(subject),
        microzone_kind=subject_assignment.microzone_kind,
        microzone_key=subject_assignment.microzone_key,
        comparables_used=total,
        same_real_microzone_ratio=ratio(same_real, total),
        same_textual_microzone_ratio=ratio(same_textual, total),
        comuna_only_ratio=ratio(comuna_only, total),
        weak_geo_comparable_ratio=ratio(weak_geo, total),
        current_comparable_mix_warning=same_real < MIN_SAME_MICROZONE_COMPARABLES and subject_assignment.is_real_microzone,
        microzone_aware_bucket=microzone_aware_bucket,
    )


def simulate_microzone_aware_bucket(
    subject: ShadowMicrozoneAssignment,
    comparables: Sequence[ShadowMicrozoneAssignment],
) -> str:
    if subject.microzone_kind == "geo_500m" and subject.confidence == "high":
        same_geo = sum(
            1 for item in comparables
            if item.microzone_kind == "geo_500m" and item.microzone_key == subject.microzone_key
        )
        if same_geo >= MIN_SAME_MICROZONE_COMPARABLES:
            return "prefer_same_geo_microzone"
        same_textual = sum(1 for item in comparables if item.microzone_kind == "textual")
        if same_textual >= MIN_SAME_MICROZONE_COMPARABLES:
            return "fallback_to_textual_microzone"
        return "fallback_to_comuna_with_penalty"
    if subject.microzone_kind == "textual":
        same_textual = sum(
            1 for item in comparables
            if item.microzone_kind == "textual" and item.microzone_key == subject.microzone_key
        )
        if same_textual >= MIN_SAME_MICROZONE_COMPARABLES:
            return "prefer_same_textual_microzone"
        return "fallback_to_comuna_with_penalty"
    if subject.microzone_kind == "comuna_fallback":
        return "valuation_low_confidence_comuna_only"
    return "valuation_low_confidence_no_microzone"


def summarize_comparables(rows: Sequence[ComparableShadowRow]) -> dict[str, Any]:
    return {
        "sample_size": len(rows),
        "same_real_microzone_ratio": quantiles(row.same_real_microzone_ratio for row in rows),
        "same_textual_microzone_ratio": quantiles(row.same_textual_microzone_ratio for row in rows),
        "comuna_only_ratio": quantiles(row.comuna_only_ratio for row in rows),
        "weak_geo_comparable_ratio": quantiles(row.weak_geo_comparable_ratio for row in rows),
        "mix_warning_count": sum(row.current_comparable_mix_warning for row in rows),
        "mix_warning_pct": pct(sum(row.current_comparable_mix_warning for row in rows), len(rows)),
        "microzone_aware_buckets": counter_dict(Counter(row.microzone_aware_bucket for row in rows)),
        "by_critical_comuna": comparable_by_comuna(rows),
    }


def comparable_by_comuna(rows: Sequence[ComparableShadowRow]) -> list[dict[str, Any]]:
    grouped: dict[str, list[ComparableShadowRow]] = defaultdict(list)
    critical = {_normalize_comuna(value) for value in CRITICAL_COMUNAS}
    for row in rows:
        if _normalize_comuna(row.comuna) in critical:
            grouped[_normalize_comuna(row.comuna)].append(row)
    result = []
    for comuna, items in grouped.items():
        result.append(
            {
                "comuna": comuna,
                "sample_size": len(items),
                "same_real_microzone_p50": quantiles(item.same_real_microzone_ratio for item in items)["p50"],
                "comuna_only_p50": quantiles(item.comuna_only_ratio for item in items)["p50"],
                "weak_geo_comparable_p50": quantiles(item.weak_geo_comparable_ratio for item in items)["p50"],
                "mix_warning_pct": pct(sum(item.current_comparable_mix_warning for item in items), len(items)),
            }
        )
    return sorted(result, key=lambda row: (-row["mix_warning_pct"], -row["sample_size"], row["comuna"]))


def priority_comunas(
    coverage: dict[str, Any],
    radar: dict[str, Any],
    comparable_rows: Sequence[ComparableShadowRow],
) -> list[dict[str, Any]]:
    coverage_by_comuna = {row["value"]: row for row in coverage["by_comuna"]}
    extreme_counts = Counter(row["comuna"] for row in radar["extreme_rows"])
    mix_counts = Counter(_normalize_comuna(row.comuna) for row in comparable_rows if row.current_comparable_mix_warning)
    scores = []
    for comuna, coverage_row in coverage_by_comuna.items():
        score = extreme_counts[comuna] * 5 + mix_counts[_normalize_comuna(comuna)] * 2
        score += max(0.0, 50.0 - float(coverage_row["real_microzone_pct"])) / 10.0
        if _normalize_comuna(comuna) in {_normalize_comuna(value) for value in CRITICAL_COMUNAS}:
            score += 2
        if score <= 0:
            continue
        scores.append(
            {
                "comuna": comuna,
                "priority_score": round(score, 2),
                "active": coverage_row["active"],
                "real_microzone_pct": coverage_row["real_microzone_pct"],
                "discount_over_60_count": extreme_counts[comuna],
                "comparable_mix_warning_count": mix_counts[_normalize_comuna(comuna)],
            }
        )
    return sorted(scores, key=lambda row: (-row["priority_score"], -row["discount_over_60_count"], row["comuna"]))[:20]


def recommendation(radar: dict[str, Any], comparable_summary: dict[str, Any]) -> dict[str, Any]:
    over_60 = radar["discount_over_60"]
    weak_extreme_pct = max(
        radar["pct_over_60_without_real_microzone"],
        radar["pct_over_60_weak_geocode"],
    )
    mix_warning_pct = comparable_summary["mix_warning_pct"]
    if over_60 and weak_extreme_pct >= 50:
        path = "A + gradual D"
        reason = "Start with warning/confidence penalty for Radar extremes and prioritize forward geocoding only for high-impact comunas."
    elif mix_warning_pct >= 40:
        path = "A then B"
        reason = "Comparable mixing is visible, but coverage should be measured longer before a hard filter."
    else:
        path = "A"
        reason = "Use microzones as audit warnings first; current coverage is not enough for a persisted table or hard filter."
    return {
        "recommended_path": path,
        "interpretation": reason,
        "options": {
            "A_warning_penalty": "recommended now",
            "B_strong_comparable_filter": "not yet; simulate longer and require coverage thresholds",
            "C_persisted_table": "not yet",
            "D_forward_geocoding_pipeline": "targeted later for priority comunas, not broad backfill",
        },
    }


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "microzone_shadow_audit_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "microzone_shadow_audit_latest.md").write_text(
        markdown_report(report),
        encoding="utf-8",
    )


def markdown_report(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    radar = report["radar_extremes"]
    comparable = report["comparables_shadow"]
    rec = report["recommendation"]
    lines = [
        "# Microzone Shadow Audit",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Executive Summary",
        "",
        f"- Active listings: `{report['summary']['active_listings']}`",
        f"- Active apartments: `{report['summary']['active_apartments']}`",
        f"- Active houses: `{report['summary']['active_houses']}`",
        f"- Real shadow microzone coverage: `{coverage['real_microzone_pct']}%`",
        f"- Geo 500m coverage: `{coverage['geo_microzone_500m_pct']}%`",
        f"- Textual microzone coverage: `{coverage['textual_microzone_pct']}%`",
        f"- Radar opportunities: `{radar['radar_opportunities']}`",
        f"- Radar discount >60%: `{radar['discount_over_60']}`",
        f"- >60% without real microzone: `{radar['pct_over_60_without_real_microzone']}%`",
        f"- >60% with weak geocode: `{radar['pct_over_60_weak_geocode']}%`",
        f"- Recommendation: `{rec['recommended_path']}`",
        "",
        "## Coverage",
        "",
        "| Kind | Count | % Active |",
        "| --- | ---: | ---: |",
        f"| `geo_500m` | {coverage['geo_microzone_500m']} | {coverage['geo_microzone_500m_pct']} |",
        f"| `textual` | {coverage['textual_microzone']} | {coverage['textual_microzone_pct']} |",
        f"| `comuna_fallback` | {coverage['comuna_fallback']} | {coverage['comuna_fallback_pct']} |",
        f"| `none` | {coverage['none']} | {coverage['none_pct']} |",
        "",
        "## Radar Extremes >60%",
        "",
        f"- Suspicious if applying shadow rule: `{radar['suspicious_extreme_if_microzone_rule']}`",
        f"- Top comunas: `{radar['top_comunas_over_60']}`",
        f"- Top warnings: `{radar['top_warnings_over_60']}`",
        "",
        "## Comparables Shadow",
        "",
        f"- Sample size: `{comparable['sample_size']}`",
        f"- Same real microzone p50: `{comparable['same_real_microzone_ratio']['p50']}`",
        f"- Same textual microzone p50: `{comparable['same_textual_microzone_ratio']['p50']}`",
        f"- Comuna-only p50: `{comparable['comuna_only_ratio']['p50']}`",
        f"- Weak geo comparable p50: `{comparable['weak_geo_comparable_ratio']['p50']}`",
        f"- Comparable mix warning: `{comparable['mix_warning_count']}` (`{comparable['mix_warning_pct']}%`)",
        "",
        "## Priority Comunas",
        "",
        "| Comuna | Score | Active | Real Microzone % | >60% | Mix Warnings |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["priority_comunas"][:15]:
        lines.append(
            f"| `{row['comuna']}` | {row['priority_score']} | {row['active']} | "
            f"{row['real_microzone_pct']} | {row['discount_over_60_count']} | "
            f"{row['comparable_mix_warning_count']} |"
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            rec["interpretation"],
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
            "This audit is read-only. It does not write DB rows, create migrations, change Radar scoring, change AVM, touch frontend, run scraping, or use external geocoding.",
            "",
        ]
    )
    return "\n".join(lines)


async def _latest_uf_rate(session) -> Decimal | None:
    result = await session.execute(select(UFRateORM).order_by(UFRateORM.date.desc()).limit(1))
    row = result.scalar_one_or_none()
    return Decimal(row.value_clp) if row is not None else None


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


def counter_dict(counter: Counter[str], *, limit: int | None = None) -> dict[str, int]:
    return dict(counter.most_common(limit))


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def pct(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator) * 100, 2) if denominator else 0.0


def _split_codes(value: str | None) -> list[str]:
    return [item for item in str(value or "").split(";") if item]


def _built_area(listing: Listing) -> float | None:
    return listing.built_area_m2 or listing.usable_area_m2 or listing.m2


def _listing_key(listing: Listing) -> str:
    return f"id:{listing.id}" if listing.id is not None else f"fp:{listing.fingerprint}"


def _normalize_comuna(value: str | None) -> str:
    return str(value or "").strip().lower().replace("_", " ")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
