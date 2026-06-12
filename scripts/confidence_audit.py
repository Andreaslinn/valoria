"""Audit whether current AVM confidence correlates with real holdout error.

This script is diagnostic only: it does not change the confidence formula.
"""
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
from statistics import mean, median
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.entities.listing import Listing  # noqa: E402
from core.exceptions import InsufficientDataError, ValidationError  # noqa: E402
from core.normalization.property_type import normalize_property_type  # noqa: E402
from domain.geocoding.quality import apply_geocoding_guardrails  # noqa: E402
from domain.valuation.comparables import filter_candidates, valuate  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402
from scripts.evaluation_benchmark import _deduplicate_eval_targets, _exclude_leakage, _m2_bucket_from_listing, _target_from_listing  # noqa: E402
from scripts.holdout_benchmark import (  # noqa: E402
    DEFAULT_HOLDOUT_FRACTION,
    DEFAULT_HOLDOUT_PATH,
    DEFAULT_MIN_SEGMENT_SIZE,
    DEFAULT_SEED,
    generate_stratified_holdout,
    load_holdout,
    save_holdout,
)

DEFAULT_OUTPUT_DIR = Path("reports/confidence")
DEFAULT_MIN_SAMPLES = 5
CONFIDENCE_BUCKETS = (
    (0.0, 0.2),
    (0.2, 0.4),
    (0.4, 0.6),
    (0.6, 0.8),
    (0.8, 1.0),
)


@dataclass(frozen=True)
class ConfidenceAuditRow:
    listing_id: int | None
    fingerprint: str
    comuna: str
    property_type: str
    m2_bucket: str
    actual_clp: float
    estimated_clp: float | None
    confidence: float | None
    confidence_bucket: str
    absolute_error_clp: float | None
    ape_pct: float | None
    comparable_quality_level: str | None
    coverage_metrics: dict[str, Any]
    status: str
    reason: str | None
    detail: str | None


async def main() -> int:
    args = _parse_args()
    listings = await _load_active_listings(limit=args.limit)
    report = run_confidence_audit(
        listings,
        output_dir=Path(args.output_dir),
        holdout_path=Path(args.holdout_path),
        holdout_fraction=args.holdout_fraction,
        min_segment_size=args.min_segment_size,
        min_samples=args.min_samples,
        seed=args.seed,
        force_regenerate=args.force_regenerate,
        uf_to_clp=Decimal(str(args.uf_to_clp)),
    )
    md_path, json_path = write_confidence_audit_report(report, output_dir=Path(args.output_dir))
    print("== AVM Confidence Audit ==")
    print(f"status\t{report['summary']['status']}")
    print(f"conclusion\t{report['summary']['conclusion']}")
    print(f"holdout_targets\t{report['summary']['holdout_targets']}")
    print(f"evaluated\t{report['summary']['n_evaluated']}")
    print(f"confidence_vs_ape_pearson\t{report['correlations']['confidence_vs_ape_pearson']}")
    print(f"confidence_vs_absolute_error_pearson\t{report['correlations']['confidence_vs_absolute_error_pearson']}")
    print(f"markdown\t{md_path}")
    print(f"json\t{json_path}")
    return 0 if report["summary"]["status"] != "insufficient_data" else 2


def run_confidence_audit(
    listings: Sequence[Listing],
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    holdout_path: Path = DEFAULT_HOLDOUT_PATH,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    min_segment_size: int = DEFAULT_MIN_SEGMENT_SIZE,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    seed: int = DEFAULT_SEED,
    force_regenerate: bool = False,
    uf_to_clp: Decimal | None = None,
) -> dict[str, Any]:
    if uf_to_clp is None:
        raise ValueError("uf_to_clp real requerido; no hay fallback UF operativo")
    active = _active_unique(listings)
    if force_regenerate or not holdout_path.exists():
        holdout = generate_stratified_holdout(
            active,
            fraction=holdout_fraction,
            min_segment_size=min_segment_size,
            seed=seed,
        )
        save_holdout(holdout, holdout_path=holdout_path, output_dir=output_dir)
    else:
        holdout = load_holdout(holdout_path)

    active_ids = {_listing_id(listing) for listing in active}
    configured_holdout_ids = {int(item) for item in holdout["listing_ids"]}
    holdout_ids = configured_holdout_ids & active_ids
    training = [listing for listing in active if _listing_id(listing) not in holdout_ids]
    holdout_targets = [listing for listing in active if _listing_id(listing) in holdout_ids]

    rows = evaluate_confidence_holdout(holdout_targets, training, uf_to_clp=uf_to_clp)
    report = summarize_confidence_rows(
        rows,
        holdout=holdout,
        total_active=len(active),
        training_count=len(training),
        holdout_count=len(holdout_targets),
        stale_holdout_ids=len(configured_holdout_ids - active_ids),
        holdout_path=holdout_path,
        min_samples=min_samples,
    )
    return report


def evaluate_confidence_holdout(
    holdout_targets: Sequence[Listing],
    training_pool: Sequence[Listing],
    *,
    uf_to_clp: Decimal | None = None,
) -> list[ConfidenceAuditRow]:
    if uf_to_clp is None:
        raise ValueError("uf_to_clp real requerido; no hay fallback UF operativo")
    training_ids = {_listing_id(listing) for listing in training_pool}
    holdout_ids = {_listing_id(listing) for listing in holdout_targets}
    overlap = training_ids & holdout_ids
    if overlap:
        raise ValueError(f"holdout leakage into training pool: {sorted(overlap)[:10]}")
    return [_evaluate_confidence_listing(target, training_pool, uf_to_clp=uf_to_clp) for target in holdout_targets]


def summarize_confidence_rows(
    rows: Sequence[ConfidenceAuditRow],
    *,
    holdout: dict[str, Any],
    total_active: int,
    training_count: int,
    holdout_count: int,
    stale_holdout_ids: int,
    holdout_path: Path,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> dict[str, Any]:
    successful = [row for row in rows if row.status == "ok" and row.confidence is not None and row.ape_pct is not None]
    status = "ok" if len(successful) >= min_samples else "insufficient_data"
    correlations = {
        "confidence_vs_ape_pearson": _round(_pearson(
            [row.confidence for row in successful],
            [row.ape_pct for row in successful],
        )),
        "confidence_vs_absolute_error_pearson": _round(_pearson(
            [row.confidence for row in successful],
            [row.absolute_error_clp for row in successful],
        )),
    }
    bucket_report = _bucket_report(successful)
    conclusion = _conclusion(correlations["confidence_vs_ape_pearson"], bucket_report, len(successful))
    return {
        "summary": {
            "status": status,
            "generated_at": datetime.now(UTC).isoformat(),
            "conclusion": conclusion,
            "total_active_listings": total_active,
            "training_listings": training_count,
            "holdout_targets": holdout_count,
            "n_evaluated": len(successful),
            "coverage_pct": _pct(len(successful), len(rows)),
            "insufficient_data_rate_pct": _pct(sum(row.status != "ok" for row in rows), len(rows)),
            "holdout_path": str(holdout_path),
            "stale_holdout_ids_not_active": stale_holdout_ids,
            "min_samples": min_samples,
            "note": "Diagnostic only. Current confidence formula was not changed.",
        },
        "holdout_definition": holdout,
        "correlations": correlations,
        "by_confidence_bucket": bucket_report,
        "by_property_type": _segment_report(successful, key=lambda row: row.property_type),
        "by_comuna": _segment_report(successful, key=lambda row: row.comuna),
        "by_comparable_quality_level": _segment_report(
            successful,
            key=lambda row: row.comparable_quality_level or "unknown",
        ),
        "skip_reasons": dict(Counter(row.reason or row.status for row in rows if row.status != "ok")),
        "rows": [asdict(row) for row in rows],
    }


def write_confidence_audit_report(report: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "confidence_audit.json"
    md_path = output_dir / "confidence_audit.md"
    json_path.write_text(json.dumps(_json_safe(report), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    return md_path, json_path


def _evaluate_confidence_listing(
    target_listing: Listing,
    training_pool: Sequence[Listing],
    *,
    uf_to_clp: Decimal,
) -> ConfidenceAuditRow:
    actual_clp = float(target_listing.price.clp)
    target = _target_from_listing(target_listing)
    property_type = normalize_property_type(target_listing.property_type)
    candidates = [
        candidate
        for candidate in _exclude_leakage(target_listing, training_pool)
        if normalize_property_type(candidate.property_type) == property_type
    ]
    eligible = filter_candidates(target, candidates)
    base_coverage = {
        "eligible_comparables": len(eligible),
        "comparables_used": 0,
        "low_data_mode": len(eligible) < 8,
    }

    if actual_clp <= 0:
        return _failed_row(target_listing, actual_clp, base_coverage, "missing_price")
    if target.m2 <= 0:
        return _failed_row(target_listing, actual_clp, base_coverage, "missing_built_area")

    try:
        valuation = valuate(target, candidates, uf_to_clp)
    except InsufficientDataError as exc:
        return _failed_row(
            target_listing,
            actual_clp,
            base_coverage,
            "insufficient_comparables",
            str(exc),
        )
    except ValidationError as exc:
        return _failed_row(target_listing, actual_clp, base_coverage, "validation_error", str(exc))

    estimated_clp = float(valuation.estimated_price.clp)
    absolute_error_clp = abs(estimated_clp - actual_clp)
    ape_pct = (absolute_error_clp / actual_clp) * 100.0 if actual_clp > 0 else None
    coverage_metrics = dict(valuation.comparable_quality_metrics)
    coverage_metrics.update(
        {
            "eligible_comparables": len(eligible),
            "comparables_used": valuation.comparables_used,
            "low_data_mode": valuation.comparables_used < 8,
        }
    )
    confidence = round(float(valuation.confidence.value), 4)
    return ConfidenceAuditRow(
        listing_id=target_listing.id,
        fingerprint=target_listing.fingerprint,
        comuna=target_listing.comuna,
        property_type=property_type,
        m2_bucket=_m2_bucket_from_listing(target_listing),
        actual_clp=actual_clp,
        estimated_clp=estimated_clp,
        confidence=confidence,
        confidence_bucket=_confidence_bucket(confidence),
        absolute_error_clp=absolute_error_clp,
        ape_pct=_round(ape_pct),
        comparable_quality_level=valuation.comparable_quality_level,
        coverage_metrics=coverage_metrics,
        status="ok",
        reason=None,
        detail=None,
    )


def _failed_row(
    listing: Listing,
    actual_clp: float,
    coverage_metrics: dict[str, Any],
    reason: str,
    detail: str | None = None,
) -> ConfidenceAuditRow:
    return ConfidenceAuditRow(
        listing_id=listing.id,
        fingerprint=listing.fingerprint,
        comuna=listing.comuna,
        property_type=normalize_property_type(listing.property_type),
        m2_bucket=_m2_bucket_from_listing(listing),
        actual_clp=actual_clp,
        estimated_clp=None,
        confidence=None,
        confidence_bucket="not_evaluated",
        absolute_error_clp=None,
        ape_pct=None,
        comparable_quality_level=None,
        coverage_metrics=coverage_metrics,
        status="failed",
        reason=reason,
        detail=detail,
    )


def _bucket_report(rows: Sequence[ConfidenceAuditRow]) -> dict[str, Any]:
    grouped: dict[str, list[ConfidenceAuditRow]] = defaultdict(list)
    for row in rows:
        grouped[row.confidence_bucket].append(row)
    return {label: _row_metrics(grouped.get(label, [])) for label in _bucket_labels()}


def _segment_report(rows: Sequence[ConfidenceAuditRow], *, key) -> dict[str, Any]:
    grouped: dict[str, list[ConfidenceAuditRow]] = defaultdict(list)
    for row in rows:
        grouped[str(key(row) or "unknown")].append(row)
    return {label: _row_metrics(segment_rows) for label, segment_rows in sorted(grouped.items())}


def _row_metrics(rows: Sequence[ConfidenceAuditRow]) -> dict[str, Any]:
    apes = [float(row.ape_pct) for row in rows if row.ape_pct is not None]
    abs_errors = [float(row.absolute_error_clp) for row in rows if row.absolute_error_clp is not None]
    confidences = [float(row.confidence) for row in rows if row.confidence is not None]
    quality_counts = Counter(row.comparable_quality_level or "unknown" for row in rows)
    coverage_keys = (
        "address_level_geo_ratio",
        "same_microzone_ratio",
        "m2_bucket_coverage",
        "property_type_consistency",
        "price_per_m2_dispersion",
    )
    return {
        "n": len(rows),
        "avg_confidence": _round(mean(confidences)) if confidences else None,
        "mae_clp": _round(mean(abs_errors)) if abs_errors else None,
        "mape_pct": _round(mean(apes)) if apes else None,
        "median_ape_pct": _round(median(apes)) if apes else None,
        "quality_level_counts": dict(quality_counts),
        "avg_coverage_metrics": {
            metric: _round(mean(values)) if (values := [
                float(row.coverage_metrics[metric])
                for row in rows
                if row.coverage_metrics.get(metric) is not None
            ]) else None
            for metric in coverage_keys
        },
    }


def _conclusion(confidence_ape_correlation: float | None, bucket_report: dict[str, Any], n: int) -> str:
    if n < DEFAULT_MIN_SAMPLES or confidence_ape_correlation is None:
        return "insufficient_data"
    bucket_mapes = [
        metrics["mape_pct"]
        for metrics in bucket_report.values()
        if metrics["n"] > 0 and metrics["mape_pct"] is not None
    ]
    has_monotonic_signal = len(bucket_mapes) >= 3 and bucket_mapes[-1] <= bucket_mapes[0]
    if confidence_ape_correlation <= -0.30 and has_monotonic_signal:
        return "serves"
    if confidence_ape_correlation <= -0.10 or has_monotonic_signal:
        return "serves_partially"
    return "weak_or_not_validated"


def _confidence_bucket(confidence: float | None) -> str:
    if confidence is None:
        return "not_evaluated"
    value = max(0.0, min(1.0, float(confidence)))
    for low, high in CONFIDENCE_BUCKETS:
        if low <= value < high or (high == 1.0 and value <= high):
            return f"{low:.1f}-{high:.1f}"
    return "not_evaluated"


def _bucket_labels() -> list[str]:
    return [f"{low:.1f}-{high:.1f}" for low, high in CONFIDENCE_BUCKETS]


def _pearson(xs: Sequence[float | None], ys: Sequence[float | None]) -> float | None:
    pairs = [(float(x), float(y)) for x, y in zip(xs, ys, strict=False) if x is not None and y is not None]
    if len(pairs) < 2:
        return None
    x_values = [x for x, _ in pairs]
    y_values = [y for _, y in pairs]
    x_mean = mean(x_values)
    y_mean = mean(y_values)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in pairs)
    x_denominator = sum((x - x_mean) ** 2 for x in x_values) ** 0.5
    y_denominator = sum((y - y_mean) ** 2 for y in y_values) ** 0.5
    if x_denominator == 0 or y_denominator == 0:
        return None
    return numerator / (x_denominator * y_denominator)


def _active_unique(listings: Sequence[Listing]) -> list[Listing]:
    active = apply_geocoding_guardrails([listing for listing in listings if listing.is_active and listing.id is not None])
    return _deduplicate_eval_targets(active)


def _listing_id(listing: Listing) -> int:
    if listing.id is None:
        raise ValueError("confidence audit listing requires persisted id")
    return int(listing.id)


def _pct(part: int | float, total: int | float) -> float:
    if not total:
        return 0.0
    return round(float(part) / float(total) * 100, 2)


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    correlations = report["correlations"]
    lines = [
        "# AVM Confidence Audit",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Status: `{summary['status']}`",
        f"- Conclusion: `{summary['conclusion']}`",
        f"- Holdout targets: {summary['holdout_targets']}",
        f"- Evaluated: {summary['n_evaluated']}",
        f"- Coverage: {summary['coverage_pct']}%",
        f"- Confidence vs APE Pearson: {correlations['confidence_vs_ape_pearson']}",
        f"- Confidence vs absolute error Pearson: {correlations['confidence_vs_absolute_error_pearson']}",
        "",
        "## Interpretation",
        "",
        _interpretation(summary["conclusion"]),
        "",
        "## Confidence Buckets",
        "",
        _markdown_table(_dict_rows(report["by_confidence_bucket"], "confidence_bucket")),
        "",
        "## By Property Type",
        "",
        _markdown_table(_dict_rows(report["by_property_type"], "property_type")),
        "",
        "## By Comparable Quality Level",
        "",
        _markdown_table(_dict_rows(report["by_comparable_quality_level"], "quality_level")),
    ]
    return "\n".join(lines) + "\n"


def _interpretation(conclusion: str) -> str:
    if conclusion == "serves":
        return "Confidence currently has a meaningful inverse relationship with holdout error."
    if conclusion == "serves_partially":
        return "Confidence has some signal, but it is not strong enough to treat as calibrated probability."
    if conclusion == "weak_or_not_validated":
        return "Confidence is weakly validated at best; keep it as a heuristic until recalibrated."
    return "There is not enough evaluated holdout data to validate confidence."


def _dict_rows(values: dict[str, Any], key_name: str) -> list[dict[str, Any]]:
    rows = []
    for key, value in values.items():
        row = {key_name: key}
        row.update(value)
        rows.append(row)
    return rows


def _markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No data._"
    columns = list(rows[0])
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


async def _load_active_listings(limit: int | None) -> list[Listing]:
    async with get_session_factory()() as session:
        repo = SqlAlchemyListingRepository(session)
        return list(await repo.list_active(limit=limit))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit current AVM confidence against holdout error.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--holdout-path", default=str(DEFAULT_HOLDOUT_PATH))
    parser.add_argument("--holdout-fraction", type=float, default=DEFAULT_HOLDOUT_FRACTION)
    parser.add_argument("--min-segment-size", type=int, default=DEFAULT_MIN_SEGMENT_SIZE)
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--uf-to-clp", type=float, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force-regenerate", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
