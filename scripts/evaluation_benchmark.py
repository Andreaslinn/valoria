"""Evaluate AVM accuracy with a leave-one-out benchmark.

Usage:
    python scripts/evaluation_benchmark.py --limit 500 --output-dir reports/evaluation_benchmark

The evaluated listing is never allowed to act as its own comparable. Candidates
with the same listing id, fingerprint, source/external id, or property_id are
excluded to reduce leakage from duplicated publications.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean
from typing import Any

from core.entities.listing import Listing, Property
from core.exceptions import InsufficientDataError, ValidationError
from core.normalization.property_type import normalize_property_type as _property_type
from domain.geocoding.quality import apply_geocoding_guardrails, is_poor_geocoding
from domain.valuation.comparables import filter_candidates, valuate
from domain.valuation.price_surface import MATERIAL_DIFF_PCT, lookup_price_surface, maybe_apply_surface_adjustment
from infrastructure.db.database import get_session_factory
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository

DEFAULT_OUTPUT_DIR = Path("reports/evaluation_benchmark")
LOW_DATA_COMPARABLE_THRESHOLD = 8


@dataclass(frozen=True)
class EvaluationRow:
    listing_id: int | None
    fingerprint: str
    comuna: str
    property_type: str
    m2_bucket: str
    actual_clp: float
    estimated_clp: float | None
    actual_uf: float | None
    estimated_uf: float | None
    adjusted_estimated_clp: float | None
    adjusted_estimated_uf: float | None
    absolute_error_clp: float | None
    absolute_error_uf: float | None
    absolute_percentage_error: float | None
    adjusted_model_error_pct: float | None
    adjustment_applied: bool
    adjustment_weight: float
    adjustment_reason: str | None
    comparables_used: int
    eligible_comparables: int
    low_data_mode: bool
    status: str
    reason: str | None
    detail: str | None
    surface_available: bool
    surface_level_used: str
    surface_price_m2: float | None
    surface_dispersion: float | None
    surface_sample_count: int | None
    surface_microzone_token: str | None
    surface_error_pct: float | None
    model_error_pct: float | None
    surface_beats_model: bool | None
    surface_vs_model_diff_pct: float | None
    estimate_differs_from_price_surface: bool | None
    hypothetical_blend_10_pct_error: float | None
    hypothetical_blend_20_pct_error: float | None
    hypothetical_blend_30_pct_error: float | None


@dataclass(frozen=True)
class BenchmarkArtifacts:
    json_path: Path
    csv_path: Path
    comuna_csv_path: Path
    markdown_path: Path


async def main() -> int:
    args = _parse_args()
    listings = await _load_active_listings(limit=args.limit)
    report = run_benchmark(
        listings,
        uf_to_clp=Decimal(str(args.uf_to_clp)),
        min_samples=args.min_samples,
    )
    artifacts = write_report(report, output_dir=Path(args.output_dir))
    print(f"Benchmark JSON: {artifacts.json_path}")
    print(f"Benchmark CSV: {artifacts.csv_path}")
    print(f"Benchmark comuna CSV: {artifacts.comuna_csv_path}")
    print(f"Benchmark Markdown: {artifacts.markdown_path}")
    print(report["summary"]["status"])
    _print_console_summary(report)
    return 0


def run_benchmark(
    listings: Sequence[Listing],
    *,
    uf_to_clp: Decimal | None = None,
    min_samples: int = 5,
) -> dict[str, Any]:
    if uf_to_clp is None:
        raise ValueError("uf_to_clp real requerido; no hay fallback UF operativo")
    active = apply_geocoding_guardrails([listing for listing in listings if listing.is_active])
    unique_active = _deduplicate_eval_targets(active)
    rows = [_evaluate_listing(target, active, uf_to_clp=uf_to_clp) for target in unique_active]

    successful = [row for row in rows if row.status == "ok"]
    status = "ok"
    if len(successful) < min_samples:
        status = "insufficient_data"

    summary = {
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "total_active_listings": len(active),
        "unique_eval_targets": len(unique_active),
        "successful_valuations": len(successful),
        "failed_valuations": len(rows) - len(successful),
        "coverage_pct": _pct(len(successful), len(unique_active)),
        "insufficient_data_rate_pct": _insufficient_data_rate(rows),
        "low_data_mode_rate_pct": _pct(sum(row.low_data_mode for row in rows), len(rows)),
        "surface_available_rate_pct": _pct(sum(row.surface_available for row in rows), len(rows)),
        "surface_level_usage": _surface_level_usage(rows),
        "surface_audit": _surface_audit_metrics(successful),
        "adjusted_mape_pct": _mean_or_none(
            row.adjusted_model_error_pct for row in successful if row.adjusted_model_error_pct is not None
        ),
        "surface_adjustment_applied_rate_pct": _pct(sum(row.adjustment_applied for row in successful), len(successful)),
        "surface_adjustment_improved_cases": sum(
            row.adjustment_applied
            and row.adjusted_model_error_pct is not None
            and row.model_error_pct is not None
            and row.adjusted_model_error_pct < row.model_error_pct
            for row in successful
        ),
        "surface_adjustment_worsened_cases": sum(
            row.adjustment_applied
            and row.adjusted_model_error_pct is not None
            and row.model_error_pct is not None
            and row.adjusted_model_error_pct > row.model_error_pct
            for row in successful
        ),
        "avg_comparables_used": _mean_or_none(row.comparables_used for row in successful),
        "metrics": _accuracy_metrics(successful, uf_to_clp=uf_to_clp) if status == "ok" else None,
        "skip_reasons": dict(Counter(row.reason or row.status for row in rows if row.status != "ok")),
        "note": None,
    }
    if status == "insufficient_data":
        summary["note"] = (
            f"Solo {len(successful)} valuaciones exitosas; se requieren al menos {min_samples}. "
            "No se reportan metricas de accuracy para evitar conclusiones falsas."
        )

    by_comuna = _segment_reports(
        rows,
        key=lambda row: row.comuna,
        active=list(active),
        active_key=lambda listing: listing.comuna,
        uf_to_clp=uf_to_clp,
        min_samples=min_samples,
    )
    by_property_type = _segment_reports(
        rows,
        key=lambda row: row.property_type,
        active=list(active),
        active_key=lambda listing: _property_type(listing.property_type),
        uf_to_clp=uf_to_clp,
        min_samples=min_samples,
    )
    by_m2_bucket = _segment_reports(
        rows,
        key=lambda row: row.m2_bucket,
        active=list(active),
        active_key=_m2_bucket_from_listing,
        uf_to_clp=uf_to_clp,
        min_samples=min_samples,
    )
    by_surface_level = _surface_segment_reports(successful, key=lambda row: row.surface_level_used)
    by_surface_dispersion_bucket = _surface_segment_reports(successful, key=lambda row: _surface_dispersion_bucket(row))
    by_surface_sample_count_bucket = _surface_segment_reports(successful, key=lambda row: _surface_sample_count_bucket(row))

    return {
        "summary": summary,
        "by_comuna": by_comuna,
        "by_property_type": by_property_type,
        "by_m2_bucket": by_m2_bucket,
        "by_surface_level": by_surface_level,
        "by_surface_dispersion_bucket": by_surface_dispersion_bucket,
        "by_surface_sample_count_bucket": by_surface_sample_count_bucket,
        "rankings": _rankings(by_comuna),
        "rows": [asdict(row) for row in rows],
    }


def _evaluate_listing(target_listing: Listing, all_candidates: Sequence[Listing], *, uf_to_clp: Decimal) -> EvaluationRow:
    actual_clp = float(target_listing.price.clp)
    target = _target_from_listing(target_listing)
    target_property_type = _property_type(target_listing.property_type)
    candidates = [
        candidate
        for candidate in _exclude_leakage(target_listing, all_candidates)
        if _property_type(candidate.property_type) == target_property_type
    ]
    eligible = filter_candidates(target, candidates)
    low_data_mode = len(eligible) < LOW_DATA_COMPARABLE_THRESHOLD
    surface = lookup_price_surface(target, candidates)

    if actual_clp <= 0:
        return _failed_row(target_listing, actual_clp, len(eligible), low_data_mode, "missing_price", surface=surface)
    if target.m2 <= 0:
        return _failed_row(target_listing, actual_clp, len(eligible), low_data_mode, "missing_built_area", surface=surface)

    try:
        valuation = valuate(target, candidates, uf_to_clp)
    except InsufficientDataError as exc:
        return _failed_row(
            target_listing,
            actual_clp,
            len(eligible),
            True,
            "insufficient_comparables",
            str(exc),
            surface=surface,
        )
    except ValidationError as exc:
        return _failed_row(
            target_listing,
            actual_clp,
            len(eligible),
            low_data_mode,
            "validation_error",
            str(exc),
            surface=surface,
        )

    estimated_clp = float(valuation.estimated_price.clp)
    absolute_error_clp = abs(estimated_clp - actual_clp)
    absolute_error_uf = absolute_error_clp / float(uf_to_clp)
    audit = _surface_audit_values(
        actual_clp=actual_clp,
        estimated_clp=estimated_clp,
        area_m2=target.m2,
        surface_price_m2=surface.surface_price_m2,
    )
    adjustment = maybe_apply_surface_adjustment(estimated_clp, surface, target)
    adjusted_estimated_clp = adjustment.adjusted_estimate
    adjusted_error_pct = abs(adjusted_estimated_clp - actual_clp) / actual_clp * 100 if actual_clp > 0 else None
    return EvaluationRow(
        listing_id=target_listing.id,
        fingerprint=target_listing.fingerprint,
        comuna=target_listing.comuna,
        property_type=_property_type(target_listing.property_type),
        m2_bucket=_m2_bucket_from_listing(target_listing),
        actual_clp=actual_clp,
        estimated_clp=estimated_clp,
        actual_uf=actual_clp / float(uf_to_clp),
        estimated_uf=estimated_clp / float(uf_to_clp),
        adjusted_estimated_clp=_round(adjusted_estimated_clp),
        adjusted_estimated_uf=adjusted_estimated_clp / float(uf_to_clp),
        absolute_error_clp=absolute_error_clp,
        absolute_error_uf=absolute_error_uf,
        absolute_percentage_error=absolute_error_clp / actual_clp,
        adjusted_model_error_pct=_round(adjusted_error_pct) if adjusted_error_pct is not None else None,
        adjustment_applied=adjustment.adjustment_applied,
        adjustment_weight=adjustment.adjustment_weight,
        adjustment_reason=adjustment.adjustment_reason,
        comparables_used=valuation.comparables_used,
        eligible_comparables=len(eligible),
        low_data_mode=valuation.comparables_used < LOW_DATA_COMPARABLE_THRESHOLD,
        status="ok",
        reason=None,
        detail=None,
        surface_available=surface.available,
        surface_level_used=surface.level_used,
        surface_price_m2=_round(surface.surface_price_m2) if surface.surface_price_m2 is not None else None,
        surface_dispersion=_round(surface.surface_dispersion) if surface.surface_dispersion is not None else None,
        surface_sample_count=surface.stats.sample_count if surface.stats else None,
        surface_microzone_token=surface.microzone_token,
        surface_error_pct=audit["surface_error_pct"],
        model_error_pct=audit["model_error_pct"],
        surface_beats_model=audit["surface_beats_model"],
        surface_vs_model_diff_pct=audit["surface_vs_model_diff_pct"],
        estimate_differs_from_price_surface=audit["estimate_differs_from_price_surface"],
        hypothetical_blend_10_pct_error=audit["hypothetical_blend_10_pct_error"],
        hypothetical_blend_20_pct_error=audit["hypothetical_blend_20_pct_error"],
        hypothetical_blend_30_pct_error=audit["hypothetical_blend_30_pct_error"],
    )


def _target_from_listing(listing: Listing) -> Property:
    built_area = listing.built_area_m2 or listing.usable_area_m2 or listing.m2 or 0
    return Property(
        id=listing.property_id,
        comuna=listing.comuna,
        m2=built_area,
        bedrooms=listing.bedrooms,
        bathrooms=listing.bathrooms,
        parking=listing.parking,
        property_type=_property_type(listing.property_type),
        built_area_m2=built_area,
        land_area_m2=listing.land_area_m2,
        usable_area_m2=listing.usable_area_m2,
        coordinates=listing.coordinates,
        geocode_precision=listing.geocode_precision,
        raw_metadata=listing.raw_metadata,
    )


def _exclude_leakage(target: Listing, candidates: Sequence[Listing]) -> list[Listing]:
    filtered: list[Listing] = []
    seen_fingerprints: set[str] = set()
    for candidate in candidates:
        if candidate.id is not None and target.id == candidate.id:
            continue
        if candidate.fingerprint and candidate.fingerprint == target.fingerprint:
            continue
        if target.property_id is not None and candidate.property_id == target.property_id:
            continue
        if (
            target.source
            and target.external_id
            and candidate.source == target.source
            and candidate.external_id == target.external_id
        ):
            continue
        if candidate.fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(candidate.fingerprint)
        filtered.append(candidate)
    return filtered


def _deduplicate_eval_targets(listings: Sequence[Listing]) -> list[Listing]:
    unique: list[Listing] = []
    seen: set[tuple[str, str]] = set()
    for listing in listings:
        key = (listing.source, listing.external_id or listing.fingerprint)
        if key in seen or listing.fingerprint in {item.fingerprint for item in unique}:
            continue
        seen.add(key)
        unique.append(listing)
    return unique


def _failed_row(
    listing: Listing,
    actual_clp: float,
    eligible_comparables: int,
    low_data_mode: bool,
    reason: str,
    detail: str | None = None,
    surface: Any | None = None,
) -> EvaluationRow:
    return EvaluationRow(
        listing_id=listing.id,
        fingerprint=listing.fingerprint,
        comuna=listing.comuna,
        property_type=_property_type(listing.property_type),
        m2_bucket=_m2_bucket_from_listing(listing),
        actual_clp=actual_clp,
        estimated_clp=None,
        actual_uf=None,
        estimated_uf=None,
        adjusted_estimated_clp=None,
        adjusted_estimated_uf=None,
        absolute_error_clp=None,
        absolute_error_uf=None,
        absolute_percentage_error=None,
        adjusted_model_error_pct=None,
        adjustment_applied=False,
        adjustment_weight=0.0,
        adjustment_reason=None,
        comparables_used=0,
        eligible_comparables=eligible_comparables,
        low_data_mode=low_data_mode,
        status="failed",
        reason=reason,
        detail=detail,
        surface_available=bool(surface and surface.available),
        surface_level_used=surface.level_used if surface else "not_evaluated",
        surface_price_m2=_round(surface.surface_price_m2) if surface and surface.surface_price_m2 is not None else None,
        surface_dispersion=_round(surface.surface_dispersion) if surface and surface.surface_dispersion is not None else None,
        surface_sample_count=surface.stats.sample_count if surface and surface.stats else None,
        surface_microzone_token=surface.microzone_token if surface else None,
        surface_error_pct=None,
        model_error_pct=None,
        surface_beats_model=None,
        surface_vs_model_diff_pct=None,
        estimate_differs_from_price_surface=None,
        hypothetical_blend_10_pct_error=None,
        hypothetical_blend_20_pct_error=None,
        hypothetical_blend_30_pct_error=None,
    )


def _accuracy_metrics(rows: Sequence[EvaluationRow], *, uf_to_clp: Decimal) -> dict[str, Any]:
    abs_pct = [row.absolute_percentage_error for row in rows if row.absolute_percentage_error is not None]
    abs_clp = [row.absolute_error_clp for row in rows if row.absolute_error_clp is not None]
    return {
        "mape_pct": _round(mean(abs_pct) * 100) if abs_pct else None,
        "median_ape_pct": _round(_percentile(abs_pct, 50) * 100) if abs_pct else None,
        "mae_clp": _round(mean(abs_clp)) if abs_clp else None,
        "mae_uf": _round(mean(abs_clp) / float(uf_to_clp)) if abs_clp else None,
        "error_percentiles_pct": {
            "p50": _round(_percentile(abs_pct, 50) * 100) if abs_pct else None,
            "p75": _round(_percentile(abs_pct, 75) * 100) if abs_pct else None,
            "p90": _round(_percentile(abs_pct, 90) * 100) if abs_pct else None,
            "p95": _round(_percentile(abs_pct, 95) * 100) if abs_pct else None,
        },
    }


def _surface_audit_values(
    *,
    actual_clp: float,
    estimated_clp: float,
    area_m2: float | None,
    surface_price_m2: float | None,
) -> dict[str, Any]:
    model_error_pct = abs(estimated_clp - actual_clp) / actual_clp * 100 if actual_clp > 0 else None
    if surface_price_m2 is None or area_m2 is None or area_m2 <= 0 or actual_clp <= 0:
        return {
            "surface_error_pct": None,
            "model_error_pct": _round(model_error_pct) if model_error_pct is not None else None,
            "surface_beats_model": None,
            "surface_vs_model_diff_pct": None,
            "estimate_differs_from_price_surface": None,
            "hypothetical_blend_10_pct_error": None,
            "hypothetical_blend_20_pct_error": None,
            "hypothetical_blend_30_pct_error": None,
        }
    surface_estimated_clp = surface_price_m2 * area_m2
    surface_error_pct = abs(surface_estimated_clp - actual_clp) / actual_clp * 100
    estimated_price_m2 = estimated_clp / area_m2
    surface_vs_model_diff_pct = (
        abs(estimated_price_m2 - surface_price_m2) / surface_price_m2 * 100
        if surface_price_m2 > 0
        else None
    )
    return {
        "surface_error_pct": _round(surface_error_pct),
        "model_error_pct": _round(model_error_pct) if model_error_pct is not None else None,
        "surface_beats_model": surface_error_pct < model_error_pct if model_error_pct is not None else None,
        "surface_vs_model_diff_pct": _round(surface_vs_model_diff_pct) if surface_vs_model_diff_pct is not None else None,
        "estimate_differs_from_price_surface": (
            surface_vs_model_diff_pct >= MATERIAL_DIFF_PCT if surface_vs_model_diff_pct is not None else None
        ),
        "hypothetical_blend_10_pct_error": _blend_error_pct(
            actual_clp=actual_clp,
            estimated_clp=estimated_clp,
            surface_estimated_clp=surface_estimated_clp,
            surface_weight=0.10,
        ),
        "hypothetical_blend_20_pct_error": _blend_error_pct(
            actual_clp=actual_clp,
            estimated_clp=estimated_clp,
            surface_estimated_clp=surface_estimated_clp,
            surface_weight=0.20,
        ),
        "hypothetical_blend_30_pct_error": _blend_error_pct(
            actual_clp=actual_clp,
            estimated_clp=estimated_clp,
            surface_estimated_clp=surface_estimated_clp,
            surface_weight=0.30,
        ),
    }


def _blend_error_pct(
    *,
    actual_clp: float,
    estimated_clp: float,
    surface_estimated_clp: float,
    surface_weight: float,
) -> float | None:
    if actual_clp <= 0:
        return None
    blended = estimated_clp * (1.0 - surface_weight) + surface_estimated_clp * surface_weight
    return _round(abs(blended - actual_clp) / actual_clp * 100)


def _surface_audit_metrics(rows: Sequence[EvaluationRow]) -> dict[str, Any]:
    rows_with_surface = [row for row in rows if row.surface_error_pct is not None]
    return {
        "n": len(rows),
        "surface_available_n": len(rows_with_surface),
        "surface_available_rate_pct": _pct(len(rows_with_surface), len(rows)),
        "model_mape_pct": _mean_or_none(row.model_error_pct for row in rows if row.model_error_pct is not None),
        "adjusted_mape_pct": _mean_or_none(
            row.adjusted_model_error_pct for row in rows if row.adjusted_model_error_pct is not None
        ),
        "adjustment_applied_rate_pct": _pct(sum(row.adjustment_applied for row in rows), len(rows)),
        "avg_adjustment_weight": _mean_or_none(row.adjustment_weight for row in rows if row.adjustment_applied),
        "surface_mape_pct": _mean_or_none(row.surface_error_pct for row in rows_with_surface),
        "surface_beats_model_rate_pct": _pct(
            sum(row.surface_beats_model is True for row in rows_with_surface),
            len(rows_with_surface),
        ),
        "estimate_differs_from_surface_rate_pct": _pct(
            sum(row.estimate_differs_from_price_surface is True for row in rows_with_surface),
            len(rows_with_surface),
        ),
        "avg_surface_vs_model_diff_pct": _mean_or_none(
            row.surface_vs_model_diff_pct for row in rows_with_surface if row.surface_vs_model_diff_pct is not None
        ),
        "blend_10_mape_pct": _mean_or_none(
            row.hypothetical_blend_10_pct_error
            for row in rows_with_surface
            if row.hypothetical_blend_10_pct_error is not None
        ),
        "blend_20_mape_pct": _mean_or_none(
            row.hypothetical_blend_20_pct_error
            for row in rows_with_surface
            if row.hypothetical_blend_20_pct_error is not None
        ),
        "blend_30_mape_pct": _mean_or_none(
            row.hypothetical_blend_30_pct_error
            for row in rows_with_surface
            if row.hypothetical_blend_30_pct_error is not None
        ),
    }


def _group_metrics(
    rows: Sequence[EvaluationRow],
    *,
    key: Any,
    uf_to_clp: Decimal,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[EvaluationRow]] = defaultdict(list)
    for row in rows:
        groups[str(key(row) or "unknown")].append(row)
    return {
        group: {
            "n": len(group_rows),
            "avg_comparables_used": _mean_or_none(row.comparables_used for row in group_rows),
            "low_data_mode_rate_pct": _pct(sum(row.low_data_mode for row in group_rows), len(group_rows)),
            **_accuracy_metrics(group_rows, uf_to_clp=uf_to_clp),
        }
        for group, group_rows in sorted(groups.items())
    }


def _surface_segment_reports(
    rows: Sequence[EvaluationRow],
    *,
    key: Any,
) -> dict[str, dict[str, Any]]:
    grouped_rows: dict[str, list[EvaluationRow]] = defaultdict(list)
    for row in rows:
        grouped_rows[str(key(row) or "unknown")].append(row)
    return {
        segment: _surface_audit_metrics(group_rows)
        for segment, group_rows in sorted(grouped_rows.items())
    }


def _segment_reports(
    rows: Sequence[EvaluationRow],
    *,
    key: Any,
    active: Sequence[Listing],
    active_key: Any,
    uf_to_clp: Decimal,
    min_samples: int,
) -> dict[str, dict[str, Any]]:
    grouped_rows: dict[str, list[EvaluationRow]] = defaultdict(list)
    grouped_active: dict[str, list[Listing]] = defaultdict(list)
    for row in rows:
        grouped_rows[str(key(row) or "unknown")].append(row)
    for listing in active:
        grouped_active[str(active_key(listing) or "unknown")].append(listing)

    segments = sorted(set(grouped_rows) | set(grouped_active))
    return {
        segment: _segment_metrics(
            grouped_rows.get(segment, []),
            grouped_active.get(segment, []),
            uf_to_clp=uf_to_clp,
            min_samples=min_samples,
        )
        for segment in segments
    }


def _segment_metrics(
    rows: Sequence[EvaluationRow],
    active: Sequence[Listing],
    *,
    uf_to_clp: Decimal,
    min_samples: int,
) -> dict[str, Any]:
    successful = [row for row in rows if row.status == "ok"]
    metrics = _accuracy_metrics(successful, uf_to_clp=uf_to_clp) if successful else _empty_accuracy_metrics()
    diagnostics = _segment_diagnostics(rows, active, successful, min_samples=min_samples, uf_to_clp=uf_to_clp)
    return {
        "active_listings": len(active),
        "eval_targets": len(rows),
        "successful_valuations": len(successful),
        "failed_valuations": len(rows) - len(successful),
        "coverage_pct": _pct(len(successful), len(rows)),
        "insufficient_data_rate_pct": _insufficient_data_rate(rows),
        "n": len(successful),
        "avg_comparables_used": _mean_or_none(row.comparables_used for row in successful),
        "avg_eligible_comparables": _mean_or_none(row.eligible_comparables for row in rows),
        "low_data_mode_rate_pct": _pct(sum(row.low_data_mode for row in rows), len(rows)),
        "surface_available_rate_pct": _pct(sum(row.surface_available for row in rows), len(rows)),
        "surface_level_usage": _surface_level_usage(rows),
        "surface_audit": _surface_audit_metrics(successful),
        "low_data_mode": diagnostics["low_data_mode"],
        "geocoding_poor_pct": diagnostics["geocoding_poor_pct"],
        "price_m2_cv_pct": diagnostics["price_m2_cv_pct"],
        "price_m2_p50": diagnostics["price_m2_p50"],
        "reliability_score": diagnostics["reliability_score"],
        "reliability_label": diagnostics["reliability_label"],
        "risk_flags": diagnostics["risk_flags"],
        "skip_reasons": dict(Counter(row.reason or row.status for row in rows if row.status != "ok")),
        **metrics,
    }


def _empty_accuracy_metrics() -> dict[str, Any]:
    return {
        "mape_pct": None,
        "median_ape_pct": None,
        "mae_clp": None,
        "mae_uf": None,
        "error_percentiles_pct": {"p50": None, "p75": None, "p90": None, "p95": None},
    }


def _segment_diagnostics(
    rows: Sequence[EvaluationRow],
    active: Sequence[Listing],
    successful: Sequence[EvaluationRow],
    *,
    min_samples: int,
    uf_to_clp: Decimal,
) -> dict[str, Any]:
    low_data_mode = len(active) < LOW_DATA_COMPARABLE_THRESHOLD or len(successful) < min_samples
    geocoding_poor_pct = _pct(sum(_has_poor_geocoding(listing) for listing in active), len(active))
    price_m2_values = [_price_per_m2(listing) for listing in active]
    price_m2_values = [value for value in price_m2_values if value is not None]
    price_m2_cv_pct = _coefficient_variation_pct(price_m2_values)
    risk_flags: list[str] = []
    if low_data_mode:
        risk_flags.append("poca_data")
    if geocoding_poor_pct is not None and geocoding_poor_pct >= 70:
        risk_flags.append("geocoding_pobre")
    if price_m2_cv_pct is not None and price_m2_cv_pct >= 35:
        risk_flags.append("alta_dispersion_precio_m2")
    coverage = _pct(len(successful), len(rows)) or 0.0
    mape = _accuracy_metrics(successful, uf_to_clp=uf_to_clp)["mape_pct"] if successful else None
    reliability_score = _reliability_score(
        coverage_pct=coverage,
        mape_pct=mape,
        avg_comparables=_mean_or_none(row.comparables_used for row in successful),
        geocoding_poor_pct=geocoding_poor_pct,
        price_m2_cv_pct=price_m2_cv_pct,
        low_data_mode=low_data_mode,
    )
    return {
        "low_data_mode": low_data_mode,
        "geocoding_poor_pct": geocoding_poor_pct,
        "price_m2_cv_pct": price_m2_cv_pct,
        "price_m2_p50": _round(_percentile(price_m2_values, 50)) if price_m2_values else None,
        "reliability_score": reliability_score,
        "reliability_label": _reliability_label(reliability_score, risk_flags),
        "risk_flags": risk_flags,
    }


def _rankings(by_comuna: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rows = [
        {"comuna": comuna, **metrics}
        for comuna, metrics in by_comuna.items()
        if metrics.get("n", 0) > 0
    ]
    reliable_pool = [row for row in rows if row.get("reliability_label") != "no_confiable"]
    best = sorted(
        reliable_pool,
        key=lambda row: (
            -(row.get("reliability_score") or 0),
            row.get("mape_pct") if row.get("mape_pct") is not None else 999,
            -row.get("coverage_pct", 0),
        ),
    )[:5]
    worst = sorted(
        rows,
        key=lambda row: (
            row.get("reliability_score") or 0,
            -(row.get("mape_pct") or 0),
            row.get("coverage_pct") or 0,
        ),
    )[:5]
    unreliable = [
        row for row in sorted(rows, key=lambda item: item.get("reliability_score") or 0)
        if row_is_unreliable(row)
    ][:10]
    return {
        "best_comunas": [_ranking_row(row) for row in best],
        "worst_comunas": [_ranking_row(row) for row in worst],
        "unreliable_comunas": [_ranking_row(row) for row in unreliable],
    }


def row_is_unreliable(row: dict[str, Any]) -> bool:
    return row.get("reliability_label") == "no_confiable" or bool(row.get("risk_flags"))


def _ranking_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "comuna": row["comuna"],
        "n": row.get("n"),
        "mape_pct": row.get("mape_pct"),
        "coverage_pct": row.get("coverage_pct"),
        "avg_comparables_used": row.get("avg_comparables_used"),
        "low_data_mode": row.get("low_data_mode"),
        "geocoding_poor_pct": row.get("geocoding_poor_pct"),
        "price_m2_cv_pct": row.get("price_m2_cv_pct"),
        "reliability_score": row.get("reliability_score"),
        "reliability_label": row.get("reliability_label"),
        "risk_flags": row.get("risk_flags"),
    }


def write_report(report: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> BenchmarkArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"evaluation_benchmark_{stamp}.json"
    csv_path = output_dir / f"evaluation_benchmark_{stamp}.csv"
    comuna_csv_path = output_dir / f"evaluation_benchmark_by_comuna_{stamp}.csv"
    markdown_path = output_dir / f"evaluation_benchmark_{stamp}.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(report["rows"], csv_path)
    _write_comuna_csv(report["by_comuna"], comuna_csv_path)
    markdown_path.write_text(_markdown_summary(report), encoding="utf-8")
    return BenchmarkArtifacts(
        json_path=json_path,
        csv_path=csv_path,
        comuna_csv_path=comuna_csv_path,
        markdown_path=markdown_path,
    )


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fieldnames = list(EvaluationRow.__dataclass_fields__.keys())
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_comuna_csv(groups: dict[str, dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "comuna",
        "active_listings",
        "eval_targets",
        "successful_valuations",
        "coverage_pct",
        "insufficient_data_rate_pct",
        "mape_pct",
        "median_ape_pct",
        "mae_clp",
        "avg_comparables_used",
        "low_data_mode_rate_pct",
        "low_data_mode",
        "surface_available_rate_pct",
        "geocoding_poor_pct",
        "price_m2_cv_pct",
        "reliability_score",
        "reliability_label",
        "risk_flags",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for comuna, metrics in groups.items():
            row = {"comuna": comuna, **metrics}
            row["risk_flags"] = ", ".join(row.get("risk_flags") or [])
            writer.writerow({key: row.get(key) for key in fieldnames})


def _markdown_summary(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# AVM Evaluation Benchmark",
        "",
        "## Resumen Ejecutivo",
        "",
        f"- Status: `{summary['status']}`",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Total active listings: {summary['total_active_listings']}",
        f"- Unique eval targets: {summary['unique_eval_targets']}",
        f"- Successful valuations: {summary['successful_valuations']}",
        f"- Coverage: {summary['coverage_pct']}%",
        f"- Insufficient data rate: {summary['insufficient_data_rate_pct']}%",
        f"- Avg comparables used: {summary['avg_comparables_used']}",
        f"- LOW_DATA_MODE rate: {summary['low_data_mode_rate_pct']}%",
        f"- Price surface available rate: {summary['surface_available_rate_pct']}%",
        f"- Price surface levels: {summary['surface_level_usage']}",
        f"- Price surface audit: {summary['surface_audit']}",
        f"- Adjusted MAPE: {summary['adjusted_mape_pct']}%",
        f"- Surface adjustment applied rate: {summary['surface_adjustment_applied_rate_pct']}%",
        f"- Surface adjustment improved/worsened cases: "
        f"{summary['surface_adjustment_improved_cases']}/{summary['surface_adjustment_worsened_cases']}",
    ]
    if summary["note"]:
        lines.extend(["", f"**Insufficient data:** {summary['note']}"])
        return "\n".join(lines) + "\n"

    metrics = summary["metrics"]
    interpretation = _automatic_interpretation(report)
    lines.extend(
        [
            "",
            "## Accuracy",
            "",
            f"- MAPE: {metrics['mape_pct']}%",
            f"- Median APE: {metrics['median_ape_pct']}%",
            f"- MAE CLP: {metrics['mae_clp']}",
            f"- MAE UF: {metrics['mae_uf']}",
            f"- Error p50/p75/p90/p95: {metrics['error_percentiles_pct']}",
            "",
            "## Interpretación Automática",
            "",
            interpretation,
            "",
            "## Ranking Comunas Más Confiables",
            "",
            _ranking_table(report["rankings"]["best_comunas"]),
            "",
            "## Ranking Comunas Menos Confiables",
            "",
            _ranking_table(report["rankings"]["worst_comunas"]),
            "",
            "## Comunas No Confiables",
            "",
            _ranking_table(report["rankings"]["unreliable_comunas"]),
            "",
            "## Métricas Por Comuna",
            "",
            _markdown_table(report["by_comuna"]),
            "",
            "## Métricas Por Property Type",
            "",
            _markdown_table(report["by_property_type"]),
            "",
            "## Metricas Por Rango M2",
            "",
            _markdown_table(report["by_m2_bucket"]),
            "",
            "## Price Surface Audit By Level",
            "",
            _surface_markdown_table(report["by_surface_level"]),
            "",
            "## Price Surface Audit By Dispersion",
            "",
            _surface_markdown_table(report["by_surface_dispersion_bucket"]),
            "",
            "## Price Surface Audit By Sample Count",
            "",
            _surface_markdown_table(report["by_surface_sample_count_bucket"]),
            "",
            "## Leakage Controls",
            "",
            "- Excludes the evaluated listing id from candidates.",
            "- Excludes matching fingerprints.",
            "- Excludes matching source/external_id.",
            "- Excludes matching property_id when available.",
            "- Deduplicates repeated candidate fingerprints.",
        ]
    )
    return "\n".join(lines) + "\n"


def _markdown_table(groups: dict[str, dict[str, Any]]) -> str:
    if not groups:
        return "_No successful valuations._"
    lines = [
        "| Segment | Active | n | Coverage % | Surface % | Insufficient % | MAPE % | Median APE % | p90 % | Avg comps | LOW_DATA % | Geo pobre % | CV precio/m2 % | Reliability | Flags |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for segment, metrics in groups.items():
        percentiles = metrics.get("error_percentiles_pct") or {}
        lines.append(
            f"| {segment} | {metrics.get('active_listings')} | {metrics['n']} | "
            f"{metrics.get('coverage_pct')} | {metrics.get('surface_available_rate_pct')} | "
            f"{metrics.get('insufficient_data_rate_pct')} | "
            f"{metrics['mape_pct']} | {metrics.get('median_ape_pct')} | {percentiles.get('p90')} | "
            f"{metrics['avg_comparables_used']} | {metrics['low_data_mode_rate_pct']} | "
            f"{metrics.get('geocoding_poor_pct')} | {metrics.get('price_m2_cv_pct')} | "
            f"{metrics.get('reliability_score')} | {', '.join(metrics.get('risk_flags') or [])} |"
        )
    return "\n".join(lines)


def _surface_markdown_table(groups: dict[str, dict[str, Any]]) -> str:
    if not groups:
        return "_No price surface audit rows._"
    lines = [
        "| Segment | n | Surface n | Model MAPE % | Adjusted MAPE % | Applied % | Surface MAPE % | Surface wins % | Differs % | Blend 10 % | Blend 20 % | Blend 30 % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for segment, metrics in groups.items():
        lines.append(
            f"| {segment} | {metrics.get('n')} | {metrics.get('surface_available_n')} | "
            f"{metrics.get('model_mape_pct')} | {metrics.get('adjusted_mape_pct')} | "
            f"{metrics.get('adjustment_applied_rate_pct')} | {metrics.get('surface_mape_pct')} | "
            f"{metrics.get('surface_beats_model_rate_pct')} | "
            f"{metrics.get('estimate_differs_from_surface_rate_pct')} | "
            f"{metrics.get('blend_10_mape_pct')} | {metrics.get('blend_20_mape_pct')} | "
            f"{metrics.get('blend_30_mape_pct')} |"
        )
    return "\n".join(lines)


def _ranking_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_Sin comunas en este grupo._"
    lines = [
        "| Comuna | n | MAPE % | Coverage % | Avg comps | LOW_DATA | Geo pobre % | CV precio/m2 % | Score | Flags |",
        "|---|---:|---:|---:|---:|---|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['comuna']} | {row.get('n')} | {row.get('mape_pct')} | "
            f"{row.get('coverage_pct')} | {row.get('avg_comparables_used')} | "
            f"{row.get('low_data_mode')} | {row.get('geocoding_poor_pct')} | "
            f"{row.get('price_m2_cv_pct')} | {row.get('reliability_score')} | "
            f"{', '.join(row.get('risk_flags') or [])} |"
        )
    return "\n".join(lines)


def _automatic_interpretation(report: dict[str, Any]) -> str:
    summary = report["summary"]
    metrics = summary["metrics"] or {}
    rankings = report["rankings"]
    lines = [
        f"- El benchmark logró {summary['coverage_pct']}% de cobertura real sobre targets únicos.",
        f"- El MAPE global fue {metrics.get('mape_pct')}%; úsalo como métrica direccional, no como garantía comercial.",
    ]
    if rankings["best_comunas"]:
        best = rankings["best_comunas"][0]
        lines.append(
            f"- La comuna con mejor señal relativa fue {best['comuna']} "
            f"(MAPE {best['mape_pct']}%, coverage {best['coverage_pct']}%)."
        )
    if rankings["unreliable_comunas"]:
        names = ", ".join(row["comuna"] for row in rankings["unreliable_comunas"][:5])
        lines.append(f"- Comunas a tratar con cautela: {names}.")
    if summary["low_data_mode_rate_pct"] and summary["low_data_mode_rate_pct"] > 25:
        lines.append("- Hay una proporción relevante de valuaciones en LOW_DATA_MODE; no conviene relajar filtros sin más datos.")
    return "\n".join(lines)


def _print_console_summary(report: dict[str, Any]) -> None:
    summary = report["summary"]
    metrics = summary.get("metrics") or {}
    print("Global metrics")
    print(f"  valid_evaluations: {summary['successful_valuations']}")
    print(f"  coverage_pct: {summary['coverage_pct']}")
    print(f"  insufficient_data_rate_pct: {summary.get('insufficient_data_rate_pct')}")
    print(f"  surface_available_rate_pct: {summary.get('surface_available_rate_pct')}")
    print(f"  surface_level_usage: {summary.get('surface_level_usage')}")
    print(f"  surface_audit: {summary.get('surface_audit')}")
    print(f"  adjusted_mape_pct: {summary.get('adjusted_mape_pct')}")
    print(f"  surface_adjustment_applied_rate_pct: {summary.get('surface_adjustment_applied_rate_pct')}")
    print(f"  surface_adjustment_improved_cases: {summary.get('surface_adjustment_improved_cases')}")
    print(f"  surface_adjustment_worsened_cases: {summary.get('surface_adjustment_worsened_cases')}")
    print(f"  mae_clp: {metrics.get('mae_clp')}")
    print(f"  mape_pct: {metrics.get('mape_pct')}")
    print(f"  median_ape_pct: {metrics.get('median_ape_pct')}")
    print("\nApartment metrics")
    _print_segment_metrics(report["by_property_type"].get("apartment"))
    print("\nHouse metrics")
    _print_segment_metrics(report["by_property_type"].get("house"))
    print("\nMetrics by comuna")
    print("top_5_comunas_mas_confiables:")
    for row in report["rankings"]["best_comunas"][:5]:
        print(
            f"  {row['comuna']}: score={row['reliability_score']} "
            f"mape={row['mape_pct']} coverage={row['coverage_pct']} comps={row['avg_comparables_used']}"
        )
    print("top_5_comunas_menos_confiables:")
    for row in report["rankings"]["worst_comunas"][:5]:
        print(
            f"  {row['comuna']}: score={row['reliability_score']} "
            f"mape={row['mape_pct']} coverage={row['coverage_pct']} flags={','.join(row['risk_flags'] or [])}"
        )
    print("\nMetrics by m2 bucket")
    for bucket, row in report["by_m2_bucket"].items():
        print(
            f"  {bucket}: valid={row['n']} coverage={row['coverage_pct']} "
            f"insufficient={row['insufficient_data_rate_pct']} mape={row['mape_pct']}"
        )
    print("\nInsufficient data summary")
    print(f"  global_insufficient_data_rate_pct: {summary.get('insufficient_data_rate_pct')}")
    print(f"  skip_reasons: {summary.get('skip_reasons')}")
    print("\nPrice surface audit by level")
    for level, metrics in report.get("by_surface_level", {}).items():
        print(
            f"  {level}: n={metrics.get('n')} model_mape={metrics.get('model_mape_pct')} "
            f"adjusted_mape={metrics.get('adjusted_mape_pct')} applied={metrics.get('adjustment_applied_rate_pct')} "
            f"surface_mape={metrics.get('surface_mape_pct')} wins={metrics.get('surface_beats_model_rate_pct')} "
            f"blend10={metrics.get('blend_10_mape_pct')}"
        )


def _print_segment_metrics(metrics: dict[str, Any] | None) -> None:
    if not metrics:
        print("  no_data")
        return
    print(f"  active_listings: {metrics.get('active_listings')}")
    print(f"  valid_evaluations: {metrics.get('n')}")
    print(f"  coverage_pct: {metrics.get('coverage_pct')}")
    print(f"  insufficient_data_rate_pct: {metrics.get('insufficient_data_rate_pct')}")
    print(f"  mae_clp: {metrics.get('mae_clp')}")
    print(f"  mape_pct: {metrics.get('mape_pct')}")
    print(f"  median_ape_pct: {metrics.get('median_ape_pct')}")
    print(f"  avg_comparables_used: {metrics.get('avg_comparables_used')}")
    print(f"  surface_available_rate_pct: {metrics.get('surface_available_rate_pct')}")


def _surface_level_usage(rows: Sequence[EvaluationRow]) -> dict[str, int]:
    return dict(Counter(row.surface_level_used for row in rows))


def _surface_dispersion_bucket(row: EvaluationRow) -> str:
    value = row.surface_dispersion
    if value is None:
        return "unknown"
    if value < 20:
        return "0-19"
    if value < 35:
        return "20-34"
    if value < 50:
        return "35-49"
    if value < 75:
        return "50-74"
    return "75+"


def _surface_sample_count_bucket(row: EvaluationRow) -> str:
    value = row.surface_sample_count
    if value is None:
        return "unknown"
    if value < 5:
        return "0-4"
    if value < 10:
        return "5-9"
    if value < 20:
        return "10-19"
    if value < 50:
        return "20-49"
    return "50+"


async def _load_active_listings(*, limit: int | None) -> list[Listing]:
    async with get_session_factory()() as session:
        repo = SqlAlchemyListingRepository(session)
        return list(await repo.list_active(limit=limit))


def _has_poor_geocoding(listing: Listing) -> bool:
    return is_poor_geocoding(listing)


def _price_per_m2(listing: Listing) -> float | None:
    area = listing.built_area_m2 or listing.usable_area_m2 or listing.m2
    if area is None or area <= 0 or listing.price.clp <= 0:
        return None
    return float(listing.price.clp) / float(area)


def _m2_bucket_from_listing(listing: Listing) -> str:
    area = listing.built_area_m2 or listing.usable_area_m2 or listing.m2
    return _m2_bucket(area)


def _m2_bucket(area: float | None) -> str:
    if area is None or area <= 0:
        return "unknown"
    if area < 40:
        return "0-39"
    if area < 60:
        return "40-59"
    if area < 80:
        return "60-79"
    if area < 120:
        return "80-119"
    if area < 180:
        return "120-179"
    return "180+"


def _insufficient_data_rate(rows: Sequence[EvaluationRow]) -> float | None:
    return _pct(sum(row.reason == "insufficient_comparables" for row in rows), len(rows))


def _coefficient_variation_pct(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = mean(values)
    if avg <= 0:
        return None
    variance = sum((value - avg) ** 2 for value in values) / len(values)
    return _round((variance**0.5 / avg) * 100)


def _reliability_score(
    *,
    coverage_pct: float,
    mape_pct: float | None,
    avg_comparables: float | None,
    geocoding_poor_pct: float | None,
    price_m2_cv_pct: float | None,
    low_data_mode: bool,
) -> float:
    score = 100.0
    score -= max(0.0, 100.0 - coverage_pct) * 0.35
    if mape_pct is not None:
        score -= min(45.0, mape_pct * 0.9)
    else:
        score -= 35.0
    if avg_comparables is not None:
        score += min(10.0, avg_comparables)
    else:
        score -= 10.0
    if geocoding_poor_pct is not None:
        score -= min(20.0, geocoding_poor_pct * 0.2)
    if price_m2_cv_pct is not None:
        score -= min(20.0, max(0.0, price_m2_cv_pct - 20.0) * 0.5)
    if low_data_mode:
        score -= 15.0
    return _round(max(0.0, min(100.0, score)))


def _reliability_label(score: float, risk_flags: Sequence[str]) -> str:
    if score < 45 or "poca_data" in risk_flags:
        return "no_confiable"
    if score < 65 or risk_flags:
        return "cautela"
    return "confiable"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate AVM accuracy and coverage.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum active listings to evaluate.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for JSON/CSV/Markdown reports.")
    parser.add_argument("--uf-to-clp", type=float, required=True, help="Real UF rate for UF metrics.")
    parser.add_argument("--min-samples", type=int, default=5, help="Minimum successful valuations before reporting accuracy.")
    return parser.parse_args()


def _mean_or_none(values: Iterable[int | float]) -> float | None:
    materialized = [float(value) for value in values]
    return _round(mean(materialized)) if materialized else None


def _percentile(values: Sequence[float], percentile: int) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (percentile / 100)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _pct(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return _round((float(numerator) / float(denominator)) * 100)


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
