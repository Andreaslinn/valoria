"""Compare production CLP/m2 valuation with an experimental canonical UF/m2 path.

This script is intentionally read-only. It does not change the production
valuation engine, endpoints, comparable scoring, or persisted data.
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
from typing import Any

import httpx
from redis.asyncio import Redis

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_settings  # noqa: E402
from config.constants import MIN_COMPARABLES, TOP_N_COMPARABLES  # noqa: E402
from config.valuation_flags import canonical_price_enabled_for_segment, canonical_price_segment_key  # noqa: E402
from core.entities.listing import Listing, Property  # noqa: E402
from core.exceptions import InsufficientDataError, UFServiceError, ValidationError  # noqa: E402
from core.ports.uf_service import UFRateInfo  # noqa: E402
from core.normalization.property_type import normalize_property_type as _property_type  # noqa: E402
from domain.geocoding.quality import apply_geocoding_guardrails  # noqa: E402
from domain.valuation.canonical_price import valuation_price_basis  # noqa: E402
from domain.valuation.comparables import filter_candidates, score_and_rank, valuate, valuate_with_comparables  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402
from infrastructure.external.uf_client import UFClient  # noqa: E402
from services.uf_rate import require_real_uf_rate  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("reports/valuation_canonical_price")


@dataclass(frozen=True)
class AuditRow:
    listing_id: int | None
    external_id: str | None
    fingerprint: str
    comuna: str
    property_type: str
    target_price_currency: str | None
    target_price_basis_used: str
    target_price_quality: str
    target_usable_for_valuation: bool
    current_estimated_uf: float | None
    experimental_estimated_uf: float | None
    current_estimated_clp: float | None
    experimental_estimated_clp_display: float | None
    estimate_delta_pct: float | None
    actual_uf: float | None
    current_error_pct: float | None
    experimental_error_pct: float | None
    current_comparables_used: int
    experimental_comparables_used: int
    eligible_comparables: int
    canonical_price_coverage_pct: float | None
    weak_price_share_pct: float | None
    mixed_currency_share_pct: float | None
    excluded_by_legacy: int
    excluded_by_estimated_or_low: int
    excluded_by_fallback: int
    excluded_by_unknown: int
    segmented_policy_mode: str
    status: str
    reason: str | None
    detail: str | None


@dataclass(frozen=True)
class ExperimentalResult:
    estimated_uf: Decimal
    estimated_clp_display: Decimal
    comparables_used: int
    current_top_stats: dict[str, Any]
    selected_currency_counts: dict[str, int]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit valuation impact of canonical UF price basis.")
    parser.add_argument("--limit", type=int, default=None, help="Max active listings to load.")
    parser.add_argument("--examples", type=int, default=20, help="Rows to include in top-delta tables.")
    parser.add_argument("--min-samples", type=int, default=5)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


async def main() -> int:
    args = parse_args()
    try:
        uf_info = await _resolve_real_uf_rate()
    except UFServiceError as exc:
        print(f"ERROR: UF real no disponible para benchmark canonico: {exc}", file=sys.stderr)
        return 2
    listings = await _load_active_listings(limit=args.limit)
    report = run_audit(
        listings,
        uf_to_clp=uf_info.rate,
        uf_info=uf_info,
        min_samples=args.min_samples,
        examples=args.examples,
    )
    artifacts = write_report(report, Path(args.output_dir))
    print(f"Valuation canonical price JSON: {artifacts['json_path']}")
    print(f"Valuation canonical price Markdown: {artifacts['markdown_path']}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


async def _load_active_listings(*, limit: int | None) -> Sequence[Listing]:
    async with get_session_factory()() as session:
        repo = SqlAlchemyListingRepository(session)
        return await repo.list_active(limit=limit)


async def _resolve_real_uf_rate() -> UFRateInfo:
    settings = get_settings()
    async with httpx.AsyncClient() as http:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            client = UFClient(api_url=settings.uf_api_url, http_client=http, redis=redis)
            return await require_real_uf_rate(client)
        finally:
            await redis.aclose()


def run_audit(
    listings: Sequence[Listing],
    *,
    uf_to_clp: Decimal,
    uf_info: UFRateInfo | None = None,
    min_samples: int = 5,
    examples: int = 20,
) -> dict[str, Any]:
    active = apply_geocoding_guardrails([listing for listing in listings if listing.is_active])
    targets = _deduplicate_targets(active)
    rows = [_evaluate_listing(target, active, uf_to_clp=uf_to_clp) for target in targets]
    both_success = [row for row in rows if row.status == "ok" and row.estimate_delta_pct is not None]
    current_success = [row for row in rows if row.current_estimated_uf is not None]
    experimental_success = [row for row in rows if row.experimental_estimated_uf is not None]
    segmented_policy = _segmented_policy_report(rows)
    status = "ok" if len(both_success) >= min_samples else "insufficient_data"

    top_deltas = sorted(
        both_success,
        key=lambda row: abs(row.estimate_delta_pct or 0),
        reverse=True,
    )[:examples]

    summary = {
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "uf_rate_used": str(uf_to_clp),
        "uf_rate_source": uf_info.source if uf_info else "provided",
        "uf_rate_cache_hit": uf_info.cache_hit if uf_info else None,
        "uf_rate_is_fallback": uf_info.is_fallback if uf_info else None,
        "uf_rate_observed_at": datetime.now(UTC).isoformat(),
        "active_listings": len(active),
        "evaluated_targets": len(targets),
        "current_successful_valuations": len(current_success),
        "experimental_successful_valuations": len(experimental_success),
        "both_successful_valuations": len(both_success),
        "failed_valuations": len(rows) - len(both_success),
        "avg_estimate_delta_pct": _mean_or_none(row.estimate_delta_pct for row in both_success),
        "median_estimate_delta_pct": _median_or_none(row.estimate_delta_pct for row in both_success),
        "p90_abs_estimate_delta_pct": _percentile_or_none(
            [abs(row.estimate_delta_pct or 0) for row in both_success],
            90,
        ),
        "max_abs_estimate_delta_pct": _max_or_none(abs(row.estimate_delta_pct or 0) for row in both_success),
        "avg_current_error_pct": _mean_or_none(row.current_error_pct for row in both_success),
        "avg_experimental_error_pct": _mean_or_none(row.experimental_error_pct for row in both_success),
        "canonical_price_coverage_pct": _mean_or_none(row.canonical_price_coverage_pct for row in rows),
        "weak_price_share_pct": _mean_or_none(row.weak_price_share_pct for row in rows),
        "mixed_currency_share_pct": _mean_or_none(row.mixed_currency_share_pct for row in rows),
        "comparables_excluded_by_legacy": sum(row.excluded_by_legacy for row in rows),
        "comparables_excluded_by_estimated_or_low": sum(row.excluded_by_estimated_or_low for row in rows),
        "comparables_excluded_by_fallback": sum(row.excluded_by_fallback for row in rows),
        "comparables_excluded_by_unknown": sum(row.excluded_by_unknown for row in rows),
        "segmented_policy_evaluated_canonical": segmented_policy["summary"]["evaluated_canonical"],
        "segmented_policy_evaluated_legacy": segmented_policy["summary"]["evaluated_legacy"],
        "segmented_policy_successful_canonical": segmented_policy["summary"]["successful_canonical"],
        "segmented_policy_successful_legacy": segmented_policy["summary"]["successful_legacy"],
        "skip_reasons": dict(Counter(row.reason or row.status for row in rows if row.status != "ok")),
        "note": None,
    }
    if status == "insufficient_data":
        summary["note"] = (
            f"Solo {len(both_success)} tasaciones comparables exitosas; "
            f"se requieren al menos {min_samples} para una conclusion robusta."
        )

    return {
        "summary": summary,
        "by_comuna": _segment(rows, key=lambda row: row.comuna, min_samples=min_samples),
        "by_property_type": _segment(rows, key=lambda row: row.property_type, min_samples=min_samples),
        "segmented_policy": segmented_policy,
        "top_20_largest_deltas": [asdict(row) for row in top_deltas],
        "rows": [asdict(row) for row in rows],
    }


def _evaluate_listing(target_listing: Listing, all_candidates: Sequence[Listing], *, uf_to_clp: Decimal) -> AuditRow:
    target = _target_from_listing(target_listing)
    target_property_type = _property_type(target_listing.property_type)
    candidates = [
        candidate
        for candidate in _exclude_leakage(target_listing, all_candidates)
        if _property_type(candidate.property_type) == target_property_type
    ]
    target_basis = valuation_price_basis(target_listing, uf_to_clp)
    segmented_policy_mode = _segmented_policy_mode(target_listing.comuna, target_property_type)

    try:
        eligible = filter_candidates(target, candidates)
        current = valuate(target, candidates, uf_to_clp, canonical_price_enabled=False)
        experimental = valuate_with_comparables(
            target,
            candidates,
            uf_to_clp,
            canonical_price_enabled=True,
        )
    except InsufficientDataError as exc:
        return _failed_row(target_listing, target_basis, "insufficient_comparables", str(exc), candidates, target, uf_to_clp)
    except ValidationError as exc:
        return _failed_row(target_listing, target_basis, "validation_error", str(exc), candidates, target, uf_to_clp)

    current_estimated_clp = Decimal(current.estimated_price.clp)
    current_estimated_uf = current_estimated_clp / uf_to_clp if uf_to_clp > 0 else None
    estimate_delta_pct = None
    experimental_estimated_clp = Decimal(experimental.result.estimated_price.clp)
    experimental_estimated_uf = experimental_estimated_clp / uf_to_clp if uf_to_clp > 0 else None
    if current_estimated_uf is not None and current_estimated_uf > 0 and experimental_estimated_uf is not None:
        estimate_delta_pct = _pct_decimal(experimental_estimated_uf - current_estimated_uf, current_estimated_uf)

    actual_uf = target_basis.amount_uf if target_basis.is_usable_for_valuation else None
    current_error_pct = _absolute_error_pct(current_estimated_uf, actual_uf)
    experimental_error_pct = _absolute_error_pct(experimental_estimated_uf, actual_uf)
    stats = experimental.result.reliability_metrics
    excluded_counts = stats.get("excluded_price_quality_count") or {}
    return AuditRow(
        listing_id=target_listing.id,
        external_id=target_listing.external_id,
        fingerprint=target_listing.fingerprint,
        comuna=target_listing.comuna,
        property_type=target_property_type,
        target_price_currency=target_basis.price_unit,
        target_price_basis_used=target_basis.basis_used,
        target_price_quality=target_basis.quality,
        target_usable_for_valuation=target_basis.is_usable_for_valuation,
        current_estimated_uf=_round(current_estimated_uf),
        experimental_estimated_uf=_round(experimental_estimated_uf),
        current_estimated_clp=_round(current_estimated_clp),
        experimental_estimated_clp_display=_round(experimental_estimated_clp),
        estimate_delta_pct=_round(estimate_delta_pct),
        actual_uf=_round(actual_uf),
        current_error_pct=_round(current_error_pct),
        experimental_error_pct=_round(experimental_error_pct),
        current_comparables_used=current.comparables_used,
        experimental_comparables_used=experimental.result.comparables_used,
        eligible_comparables=len(eligible),
        canonical_price_coverage_pct=stats.get("canonical_price_coverage_pct"),
        weak_price_share_pct=None,
        mixed_currency_share_pct=stats.get("mixed_currency_share_pct"),
        excluded_by_legacy=int(excluded_counts.get("legacy", 0)),
        excluded_by_estimated_or_low=int(excluded_counts.get("estimated_or_low", 0)),
        excluded_by_fallback=int(excluded_counts.get("fallback", 0)),
        excluded_by_unknown=int(excluded_counts.get("unknown_currency", 0)),
        segmented_policy_mode=segmented_policy_mode,
        status="ok",
        reason=None,
        detail=None,
    )


def _experimental_uf_valuation(
    target: Property,
    eligible: Sequence[Listing],
    *,
    uf_to_clp: Decimal,
) -> ExperimentalResult:
    scored_all = score_and_rank(target, eligible)
    current_top = scored_all[:TOP_N_COMPARABLES]
    current_top_stats = _top_price_stats(current_top, uf_to_clp)
    selected: list[tuple[Decimal, Listing, Decimal]] = []
    currency_counts: Counter[str] = Counter()

    for score, listing in scored_all:
        area = _built_area(listing)
        basis = valuation_price_basis(listing, uf_to_clp)
        if area is None or area <= 0 or not basis.is_usable_for_valuation or basis.amount_uf is None:
            continue
        weight = Decimal(str(score.value)) * basis.weight_factor
        if weight <= 0:
            continue
        selected.append((weight, listing, basis.amount_uf / Decimal(str(area))))
        currency_counts[basis.price_unit or "unknown"] += 1
        if len(selected) >= TOP_N_COMPARABLES:
            break

    if len(selected) < MIN_COMPARABLES:
        raise InsufficientDataError(
            f"Solo {len(selected)} comparables con precio canonico usable; "
            f"se requieren al menos {MIN_COMPARABLES}."
        )

    total_weight = sum(weight for weight, _, _ in selected)
    if total_weight <= 0:
        raise InsufficientDataError("Pesos de comparables canonicos suman 0")
    weighted_ppm2_uf = sum(weight * price_per_m2_uf for weight, _, price_per_m2_uf in selected) / total_weight
    target_area = _built_area(target)
    if target_area is None or target_area <= 0:
        raise ValidationError(f"target.built_area_m2 debe ser positivo, recibido {target_area}")
    estimated_uf = weighted_ppm2_uf * Decimal(str(target_area))
    return ExperimentalResult(
        estimated_uf=estimated_uf,
        estimated_clp_display=estimated_uf * uf_to_clp,
        comparables_used=len(selected),
        current_top_stats=current_top_stats,
        selected_currency_counts=dict(currency_counts),
    )


def _top_price_stats(scored: Sequence[tuple[Any, Listing]], uf_to_clp: Decimal) -> dict[str, Any]:
    if not scored:
        return {
            "canonical_price_coverage_pct": None,
            "weak_price_share_pct": None,
            "excluded_by_legacy": 0,
            "excluded_by_estimated_or_low": 0,
            "excluded_by_fallback": 0,
            "excluded_by_unknown": 0,
        }
    usable = 0
    weak = 0
    legacy = 0
    fallback = 0
    unknown = 0
    for _, listing in scored:
        basis = valuation_price_basis(listing, uf_to_clp)
        if basis.is_usable_for_valuation:
            usable += 1
            continue
        reason = basis.exclusion_reason or basis.quality
        if reason in {"legacy_uf_missing_price_uf", "legacy_unrecoverable"}:
            legacy += 1
        elif reason in {"estimated_uf_not_strong", "low_confidence_uf_not_strong"}:
            weak += 1
        elif reason == "uf_fallback_not_canonical":
            fallback += 1
        else:
            unknown += 1
    total = len(scored)
    return {
        "canonical_price_coverage_pct": _pct(usable, total),
        "weak_price_share_pct": _pct(weak, total),
        "excluded_by_legacy": legacy,
        "excluded_by_estimated_or_low": weak,
        "excluded_by_fallback": fallback,
        "excluded_by_unknown": unknown,
    }


def _failed_row(
    target_listing: Listing,
    target_basis,
    reason: str,
    detail: str,
    candidates: Sequence[Listing],
    target: Property,
    uf_to_clp: Decimal,
) -> AuditRow:
    eligible_count = 0
    stats = {
        "canonical_price_coverage_pct": None,
        "weak_price_share_pct": None,
        "excluded_by_legacy": 0,
        "excluded_by_estimated_or_low": 0,
        "excluded_by_fallback": 0,
        "excluded_by_unknown": 0,
    }
    try:
        eligible = filter_candidates(target, candidates)
        eligible_count = len(eligible)
        stats = _top_price_stats(score_and_rank(target, eligible)[:TOP_N_COMPARABLES], uf_to_clp)
    except Exception:
        pass
    return AuditRow(
        listing_id=target_listing.id,
        external_id=target_listing.external_id,
        fingerprint=target_listing.fingerprint,
        comuna=target_listing.comuna,
        property_type=_property_type(target_listing.property_type),
        target_price_currency=target_basis.price_unit,
        target_price_basis_used=target_basis.basis_used,
        target_price_quality=target_basis.quality,
        target_usable_for_valuation=target_basis.is_usable_for_valuation,
        current_estimated_uf=None,
        experimental_estimated_uf=None,
        current_estimated_clp=None,
        experimental_estimated_clp_display=None,
        estimate_delta_pct=None,
        actual_uf=_round(target_basis.amount_uf) if target_basis.is_usable_for_valuation else None,
        current_error_pct=None,
        experimental_error_pct=None,
        current_comparables_used=0,
        experimental_comparables_used=0,
        eligible_comparables=eligible_count,
        canonical_price_coverage_pct=stats["canonical_price_coverage_pct"],
        weak_price_share_pct=stats["weak_price_share_pct"],
        mixed_currency_share_pct=None,
        excluded_by_legacy=stats["excluded_by_legacy"],
        excluded_by_estimated_or_low=stats["excluded_by_estimated_or_low"],
        excluded_by_fallback=stats["excluded_by_fallback"],
        excluded_by_unknown=stats["excluded_by_unknown"],
        segmented_policy_mode=_segmented_policy_mode(target_listing.comuna, _property_type(target_listing.property_type)),
        status="failed",
        reason=reason,
        detail=detail,
    )


def _target_from_listing(listing: Listing) -> Property:
    built_area = _built_area(listing) or 0
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


def _deduplicate_targets(listings: Sequence[Listing]) -> list[Listing]:
    unique: list[Listing] = []
    seen: set[tuple[str, str]] = set()
    seen_fingerprints: set[str] = set()
    for listing in listings:
        key = (listing.source, listing.external_id or listing.fingerprint)
        if key in seen or listing.fingerprint in seen_fingerprints:
            continue
        seen.add(key)
        seen_fingerprints.add(listing.fingerprint)
        unique.append(listing)
    return unique


def _segment(
    rows: Sequence[AuditRow],
    *,
    key,
    min_samples: int,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[AuditRow]] = defaultdict(list)
    for row in rows:
        grouped[str(key(row) or "unknown")].append(row)
    report: dict[str, dict[str, Any]] = {}
    for label, items in sorted(grouped.items()):
        successful = [row for row in items if row.status == "ok" and row.estimate_delta_pct is not None]
        report[label] = {
            "samples": len(items),
            "successful": len(successful),
            "status": "ok" if len(successful) >= min_samples else "insufficient_data",
            "avg_estimate_delta_pct": _mean_or_none(row.estimate_delta_pct for row in successful),
            "median_estimate_delta_pct": _median_or_none(row.estimate_delta_pct for row in successful),
            "max_abs_estimate_delta_pct": _max_or_none(abs(row.estimate_delta_pct or 0) for row in successful),
            "canonical_price_coverage_pct": _mean_or_none(row.canonical_price_coverage_pct for row in items),
            "weak_price_share_pct": _mean_or_none(row.weak_price_share_pct for row in items),
            "mixed_currency_share_pct": _mean_or_none(row.mixed_currency_share_pct for row in successful),
            "comparables_excluded_by_legacy": sum(row.excluded_by_legacy for row in items),
        }
    return report


def _segmented_policy_mode(comuna: str | None, property_type: str | None) -> str:
    return "canonical" if canonical_price_enabled_for_segment(comuna, property_type) else "legacy"


def _segmented_policy_report(rows: Sequence[AuditRow]) -> dict[str, Any]:
    by_segment: dict[str, dict[str, Any]] = {}
    evaluated_counts = Counter(row.segmented_policy_mode for row in rows)
    successful_counts = Counter(
        row.segmented_policy_mode for row in rows
        if row.status == "ok" and row.estimate_delta_pct is not None
    )
    for row in rows:
        segment = canonical_price_segment_key(row.comuna, row.property_type)
        entry = by_segment.setdefault(
            segment,
            {
                "comuna": row.comuna,
                "property_type": row.property_type,
                "mode": row.segmented_policy_mode,
                "evaluated": 0,
                "successful": 0,
                "avg_delta_pct": None,
                "canonical_price_coverage_pct": None,
                "mixed_currency_share_pct": None,
                "legacy_excluded": 0,
            },
        )
        entry["evaluated"] += 1
        entry["legacy_excluded"] += row.excluded_by_legacy
    for segment, entry in by_segment.items():
        segment_rows = [
            row for row in rows
            if canonical_price_segment_key(row.comuna, row.property_type) == segment
        ]
        successful = [row for row in segment_rows if row.status == "ok" and row.estimate_delta_pct is not None]
        entry["successful"] = len(successful)
        entry["avg_delta_pct"] = _mean_or_none(row.estimate_delta_pct for row in successful)
        entry["canonical_price_coverage_pct"] = _mean_or_none(row.canonical_price_coverage_pct for row in segment_rows)
        entry["mixed_currency_share_pct"] = _mean_or_none(row.mixed_currency_share_pct for row in successful)
    return {
        "summary": {
            "evaluated_canonical": int(evaluated_counts.get("canonical", 0)),
            "evaluated_legacy": int(evaluated_counts.get("legacy", 0)),
            "successful_canonical": int(successful_counts.get("canonical", 0)),
            "successful_legacy": int(successful_counts.get("legacy", 0)),
        },
        "by_segment": dict(sorted(by_segment.items())),
    }


def write_report(report: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"valuation_canonical_price_{stamp}"
    json_payload = json.dumps(report, ensure_ascii=False, indent=2)
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(json_payload, encoding="utf-8")
    (output_dir / "valuation_canonical_price_latest.json").write_text(json_payload, encoding="utf-8")
    markdown = _markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    (output_dir / "valuation_canonical_price_latest.md").write_text(markdown, encoding="utf-8")
    return {"json_path": json_path, "markdown_path": markdown_path}


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Valuation Canonical Price Audit",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- UF rate used: {summary['uf_rate_used']}",
        f"- UF rate source: {summary.get('uf_rate_source')}",
        f"- UF rate cache hit: {summary.get('uf_rate_cache_hit')}",
        f"- UF rate observed at: {summary.get('uf_rate_observed_at')}",
        f"- Active listings: {summary['active_listings']}",
        f"- Evaluated targets: {summary['evaluated_targets']}",
        f"- Both successful valuations: {summary['both_successful_valuations']}",
        f"- Avg estimate delta: {_fmt(summary['avg_estimate_delta_pct'])}%",
        f"- Median estimate delta: {_fmt(summary['median_estimate_delta_pct'])}%",
        f"- P90 absolute delta: {_fmt(summary['p90_abs_estimate_delta_pct'])}%",
        f"- Canonical price coverage: {_fmt(summary['canonical_price_coverage_pct'])}%",
        f"- Weak price share: {_fmt(summary['weak_price_share_pct'])}%",
        f"- Mixed currency share: {_fmt(summary['mixed_currency_share_pct'])}%",
        f"- Comparables excluded by legacy: {summary['comparables_excluded_by_legacy']}",
        f"- Comparables excluded by estimated/low: {summary['comparables_excluded_by_estimated_or_low']}",
        f"- Comparables excluded by fallback: {summary['comparables_excluded_by_fallback']}",
        f"- Segmented policy canonical evaluated: {summary['segmented_policy_evaluated_canonical']}",
        f"- Segmented policy legacy evaluated: {summary['segmented_policy_evaluated_legacy']}",
        f"- Segmented policy canonical successful: {summary['segmented_policy_successful_canonical']}",
        f"- Segmented policy legacy successful: {summary['segmented_policy_successful_legacy']}",
        "",
        "## Top 20 Largest Deltas",
        "",
        "| listing_id | comuna | type | current UF | experimental UF | delta % | current comps | experimental comps | coverage % |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["top_20_largest_deltas"]:
        lines.append(
            f"| {row['listing_id']} | {row['comuna']} | {row['property_type']} | "
            f"{_fmt(row['current_estimated_uf'])} | {_fmt(row['experimental_estimated_uf'])} | "
            f"{_fmt(row['estimate_delta_pct'])} | {row['current_comparables_used']} | "
            f"{row['experimental_comparables_used']} | {_fmt(row['canonical_price_coverage_pct'])} |"
        )
    lines.extend([
        "",
        "## By Property Type",
        "",
        "| type | samples | successful | avg delta % | coverage % | legacy excluded |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for label, data in report["by_property_type"].items():
        lines.append(
            f"| {label} | {data['samples']} | {data['successful']} | "
            f"{_fmt(data['avg_estimate_delta_pct'])} | {_fmt(data['canonical_price_coverage_pct'])} | "
            f"{data['comparables_excluded_by_legacy']} |"
        )
    lines.extend([
        "",
        "## By Comuna",
        "",
        "| comuna | samples | successful | avg delta % | coverage % | legacy excluded |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for label, data in sorted(report["by_comuna"].items(), key=lambda item: item[1]["samples"], reverse=True):
        lines.append(
            f"| {label} | {data['samples']} | {data['successful']} | "
            f"{_fmt(data['avg_estimate_delta_pct'])} | {_fmt(data['canonical_price_coverage_pct'])} | "
            f"{data['comparables_excluded_by_legacy']} |"
        )
    lines.extend([
        "",
        "## Segmented Policy",
        "",
        "| segment | mode | evaluated | successful | coverage % | mixed % | legacy excluded |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for segment, data in sorted(report["segmented_policy"]["by_segment"].items()):
        lines.append(
            f"| {segment} | {data['mode']} | {data['evaluated']} | {data['successful']} | "
            f"{_fmt(data['canonical_price_coverage_pct'])} | {_fmt(data['mixed_currency_share_pct'])} | "
            f"{data['legacy_excluded']} |"
        )
    return "\n".join(lines) + "\n"


def _built_area(value: Property | Listing) -> float | None:
    return getattr(value, "built_area_m2", None) or getattr(value, "usable_area_m2", None) or value.m2


def _mixed_currency_share(currency_counts: dict[str, int]) -> float | None:
    total = sum(currency_counts.values())
    if total == 0:
        return None
    if len([count for count in currency_counts.values() if count > 0]) <= 1:
        return 0.0
    dominant = max(currency_counts.values())
    return round((total - dominant) / total * 100, 2)


def _absolute_error_pct(estimated: Decimal | None, actual: Decimal | None) -> float | None:
    if estimated is None or actual is None or actual <= 0:
        return None
    return _round(abs(estimated - actual) / actual * Decimal("100"))


def _pct_decimal(numerator: Decimal, denominator: Decimal) -> float | None:
    if denominator == 0:
        return None
    return float(numerator / denominator * Decimal("100"))


def _pct(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return round(float(numerator) / float(denominator) * 100, 2)


def _round(value: Decimal | float | int | None, ndigits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), ndigits)


def _mean_or_none(values: Iterable[int | float | None]) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    return round(mean(numeric), 2) if numeric else None


def _median_or_none(values: Iterable[int | float | None]) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    return round(median(numeric), 2) if numeric else None


def _max_or_none(values: Iterable[int | float | None]) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    return round(max(numeric), 2) if numeric else None


def _percentile_or_none(values: Sequence[int | float], percentile: int) -> float | None:
    numeric = sorted(float(value) for value in values if value is not None)
    if not numeric:
        return None
    index = min(len(numeric) - 1, max(0, round((percentile / 100) * (len(numeric) - 1))))
    return round(numeric[index], 2)


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
