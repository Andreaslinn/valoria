"""Read-only funnel audit for Radar opportunity detection.

The script loads the same active listing universe used by RadarService,
replays the detector logic with extra observability, and writes reports under
reports/radar/. It does not write to the database, call scrapers, refresh data,
or change product behavior.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constants import (  # noqa: E402
    COMPARABLES_MAX_DISTANCE_KM,
    LOW_DATA_THRESHOLD,
    MIN_COMPARABLES,
    MIN_RADAR_DATASET_SIZE,
    MIN_UNDERVALUATION,
    MIN_UNDERVALUATION_LOW_DATA,
)
from core.entities.listing import Listing, Property  # noqa: E402
from core.entities.opportunity import Opportunity  # noqa: E402
from core.exceptions import InsufficientDataError, ValidationError  # noqa: E402
from core.normalization.property_type import normalize_property_type as _property_type  # noqa: E402
from domain.geocoding.quality import normalized_precision_for  # noqa: E402
from domain.radar.beta_safety import assess_radar_safety  # noqa: E402
from domain.radar.filters import apply_quality_filters, top_n  # noqa: E402
from domain.radar.price_basis import (  # noqa: E402
    canonical_discount_pct,
    display_price_uf,
    radar_price_basis,
)
from domain.valuation.comparables import valuate  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402

SUPPORTED_PROPERTY_TYPES = frozenset({"apartment", "house"})
CURRENT_SERVICE_MIN_CONFIDENCE = 0.0
CURRENT_SCORE_THRESHOLD: float | None = None
DEFAULT_RETURN_LIMIT = 20
RANDOM_SEED = 42


@dataclass(frozen=True)
class AuditRow:
    listing_id: int | None
    title: str
    comuna: str
    property_type: str
    source: str
    listing_price_uf: float | None
    listing_price_clp: float
    estimated_value_uf: float | None
    estimated_value_clp: float | None
    discount_pct: float | None
    opportunity_score: float | None
    confidence: float | None
    confidence_label: str | None
    engine_used: str
    comparable_count: int | None
    dispersion: float | None
    geocode_precision: str | None
    price_currency: str | None
    price_uf_source: str | None
    price_data_quality: str | None
    price_basis_used: str | None
    warning_codes: str
    reason_entered_radar: str
    reason_not_rejected: str
    top_score_components: str
    url: str | None
    valuation_status: str


@dataclass(frozen=True)
class EvaluatedRow:
    listing: Listing
    audit: AuditRow
    opportunity: Opportunity | None
    valuation_attempted: bool
    valuation_success: bool
    candidate: bool
    failure_reason: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a read-only Radar funnel audit.")
    parser.add_argument("--uf-rate", type=Decimal, required=True)
    parser.add_argument("--limit", type=int, default=DEFAULT_RETURN_LIMIT)
    parser.add_argument("--output-dir", default="reports/radar")
    parser.add_argument("--sample-size", type=int, default=50)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    timings: dict[str, float] = {}

    load_start = perf_counter()
    async with get_session_factory()() as session:
        repo = SqlAlchemyListingRepository(session)
        listings = list(await repo.list_active())
        db_identity = await _db_identity(session)
    timings["list_active_ms"] = _elapsed_ms(load_start)

    evaluate_start = perf_counter()
    evaluated = evaluate_universe(listings, args.uf_rate)
    timings["audit_evaluation_ms"] = _elapsed_ms(evaluate_start)

    filter_start = perf_counter()
    opportunities = [row.opportunity for row in evaluated if row.opportunity is not None]
    filtered = apply_quality_filters(
        opportunities,
        min_confidence=CURRENT_SERVICE_MIN_CONFIDENCE,
        min_comparables=MIN_COMPARABLES,
    )
    returned = _service_returned_top_n(filtered, args.limit)
    timings["post_detection_filters_ms"] = _elapsed_ms(filter_start)

    report_start = perf_counter()
    report = build_report(
        listings=listings,
        evaluated=evaluated,
        filtered=filtered,
        returned=returned,
        uf_rate=args.uf_rate,
        limit=args.limit,
        timings=timings,
        db_identity=db_identity,
    )
    samples = build_samples(
        evaluated=evaluated,
        filtered=filtered,
        returned=returned,
        sample_size=args.sample_size,
    )
    write_outputs(report, samples, output_dir)
    timings["report_write_ms"] = _elapsed_ms(report_start)

    summary = {
        "active_listings": report["funnel"]["active_listings"]["count"],
        "valuation_attempted": report["funnel"]["valuation_attempted"]["count"],
        "valuation_success": report["funnel"]["valuation_success"]["count"],
        "final_candidates": report["funnel"]["final_candidates"]["count"],
        "returned_top_n": report["funnel"]["returned_top_n"]["count"],
        "markdown": str(output_dir / "radar_funnel_audit_latest.md"),
        "json": str(output_dir / "radar_funnel_audit_latest.json"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def evaluate_universe(listings: Sequence[Listing], uf_rate: Decimal) -> list[EvaluatedRow]:
    active = [listing for listing in listings if listing.is_active]
    processable = [listing for listing in active if _has_valid_area(listing)]
    by_type = _active_by_property_type(processable)
    low_data_by_type = {
        property_type: len(rows) < LOW_DATA_THRESHOLD for property_type, rows in by_type.items()
    }
    any_supported_dataset = any(
        len(rows) >= MIN_RADAR_DATASET_SIZE for rows in by_type.values()
    )
    rows: list[EvaluatedRow] = []
    for listing in active:
        property_type = _property_type(listing)
        listing_price_uf = _safe_display_price_uf(listing, uf_rate)
        basis = radar_price_basis(listing)
        geocode_precision = normalized_precision_for(listing)
        base_audit = _audit_row(
            listing=listing,
            uf_rate=uf_rate,
            listing_price_uf=listing_price_uf,
            geocode_precision=geocode_precision,
            basis=basis,
        )

        if not _has_valid_area(listing):
            rows.append(
                EvaluatedRow(
                    listing=listing,
                    audit=_replace_audit(
                        base_audit,
                        valuation_status="not_attempted",
                        reason_not_rejected="rejected: invalid_or_missing_area",
                    ),
                    opportunity=None,
                    valuation_attempted=False,
                    valuation_success=False,
                    candidate=False,
                    failure_reason="invalid_or_missing_area",
                )
            )
            continue

        same_type_count = len(by_type.get(property_type, ()))
        if not any_supported_dataset or same_type_count < MIN_RADAR_DATASET_SIZE:
            rows.append(
                EvaluatedRow(
                    listing=listing,
                    audit=_replace_audit(
                        base_audit,
                        valuation_status="not_attempted",
                        reason_not_rejected="rejected: property_type_dataset_below_min",
                    ),
                    opportunity=None,
                    valuation_attempted=False,
                    valuation_success=False,
                    candidate=False,
                    failure_reason="property_type_dataset_below_min",
                )
            )
            continue

        min_discount = (
            MIN_UNDERVALUATION_LOW_DATA
            if low_data_by_type.get(property_type, True)
            else MIN_UNDERVALUATION
        )
        try:
            opportunity, audit = _evaluate_listing_for_audit(
                listing=listing,
                processable=processable,
                uf_rate=uf_rate,
                min_discount=min_discount,
                base_audit=base_audit,
            )
        except ValidationError as exc:
            rows.append(
                EvaluatedRow(
                    listing=listing,
                    audit=_replace_audit(
                        base_audit,
                        valuation_status="validation_error",
                        reason_not_rejected=f"rejected: validation_error:{exc}",
                    ),
                    opportunity=None,
                    valuation_attempted=True,
                    valuation_success=False,
                    candidate=False,
                    failure_reason="validation_error",
                )
            )
            continue
        except InsufficientDataError as exc:
            rows.append(
                EvaluatedRow(
                    listing=listing,
                    audit=_replace_audit(
                        base_audit,
                        valuation_status="insufficient_data",
                        reason_not_rejected=f"rejected: insufficient_data:{exc}",
                    ),
                    opportunity=None,
                    valuation_attempted=True,
                    valuation_success=False,
                    candidate=False,
                    failure_reason="insufficient_data",
                )
            )
            continue

        rows.append(
            EvaluatedRow(
                listing=listing,
                audit=audit,
                opportunity=opportunity,
                valuation_attempted=True,
                valuation_success=True,
                candidate=opportunity is not None,
                failure_reason=None if opportunity is not None else audit.reason_not_rejected,
            )
        )
    return rows


def _evaluate_listing_for_audit(
    *,
    listing: Listing,
    processable: Sequence[Listing],
    uf_rate: Decimal,
    min_discount: float,
    base_audit: AuditRow,
) -> tuple[Opportunity | None, AuditRow]:
    candidates = [
        candidate
        for candidate in _exclude_self(listing, processable)
        if _property_type(candidate) == _property_type(listing)
    ]
    valuation = valuate(_listing_as_property(listing), candidates, uf_rate)
    basis = radar_price_basis(listing)
    discount = canonical_discount_pct(
        market_price_clp=valuation.estimated_price.clp,
        listing_basis=basis,
        uf_to_clp=uf_rate,
    )
    estimated_value_uf = float(valuation.estimated_price.clp / uf_rate) if uf_rate > 0 else None
    engine_used = str(valuation.reliability_metrics.get("canonical_price_mode") or "legacy")
    warnings = _dedupe(
        [
            *valuation.reliability_warnings,
            *valuation.comparable_quality_flags,
            *valuation.beta_scope_flags,
        ]
    )
    score = None
    reason_entered = ""
    reason_not_rejected = "not_opportunity"
    opportunity = None
    if discount is None:
        reason_not_rejected = f"rejected: unusable_price_basis:{basis.exclude_reason}"
    elif discount < min_discount:
        reason_not_rejected = (
            f"rejected: discount_below_threshold:{_pct(discount)} < {_pct(min_discount)}"
        )
    else:
        opportunity = Opportunity(
            listing=listing,
            market_price=valuation.estimated_price,
            discount_pct=min(discount, 1.0),
            confidence=valuation.confidence,
            comparables_used=valuation.comparables_used,
            valuation_result=valuation,
            price_currency=basis.price_currency,
            price_uf=basis.price_uf,
            price_clp_snapshot=basis.price_clp_snapshot,
            price_basis_used=basis.price_basis_used,
            price_data_quality=basis.price_data_quality,
        )
        score = opportunity.ranking_score
        reason_entered = (
            f"discount {_pct(discount)} >= threshold {_pct(min_discount)}; "
            f"confidence={valuation.confidence.value:.4f}; comparables={valuation.comparables_used}"
        )
        reason_not_rejected = (
            "not rejected by current service filters: min_confidence=0.0, "
            f"min_comparables={MIN_COMPARABLES}, no score threshold"
        )

    audit = _replace_audit(
        base_audit,
        estimated_value_uf=_round(estimated_value_uf),
        estimated_value_clp=_round(float(valuation.estimated_price.clp)),
        discount_pct=_round(discount * 100) if discount is not None else None,
        opportunity_score=_round(score),
        confidence=_round(valuation.confidence.value),
        confidence_label=_confidence_label(valuation.confidence.value),
        engine_used=engine_used,
        comparable_count=valuation.comparables_used,
        dispersion=_round(_dispersion_from(valuation)),
        warning_codes=";".join(warnings),
        reason_entered_radar=reason_entered,
        reason_not_rejected=reason_not_rejected,
        top_score_components=_score_components(discount, valuation.confidence.value),
        valuation_status="success",
    )
    return opportunity, audit


def build_report(
    *,
    listings: Sequence[Listing],
    evaluated: Sequence[EvaluatedRow],
    filtered: Sequence[Opportunity],
    returned: Sequence[Opportunity],
    uf_rate: Decimal,
    limit: int,
    timings: dict[str, float],
    db_identity: dict[str, str | None],
) -> dict[str, Any]:
    active = [listing for listing in listings if listing.is_active]
    row_by_key = {_key(row.listing): row for row in evaluated}
    returned_keys = {_key(opportunity.listing) for opportunity in returned}
    score_values = [row.audit.opportunity_score for row in evaluated if row.audit.opportunity_score is not None]
    discount_values = [row.audit.discount_pct for row in evaluated if row.audit.discount_pct is not None]
    estimated_to_listing = [
        row.audit.estimated_value_uf / row.audit.listing_price_uf
        for row in evaluated
        if row.audit.estimated_value_uf is not None
        and row.audit.listing_price_uf not in {None, 0}
    ]
    listing_to_estimated = [
        row.audit.listing_price_uf / row.audit.estimated_value_uf
        for row in evaluated
        if row.audit.estimated_value_uf not in {None, 0}
        and row.audit.listing_price_uf is not None
    ]
    confidence_values = [
        row.audit.confidence for row in evaluated if row.audit.confidence is not None
    ]
    comparable_values = [
        row.audit.comparable_count for row in evaluated if row.audit.comparable_count is not None
    ]
    dispersion_values = [
        row.audit.dispersion for row in evaluated if row.audit.dispersion is not None
    ]

    final_candidate_keys = {_key(opportunity.listing) for opportunity in filtered}
    discount_threshold_count = sum(
        1
        for row in evaluated
        if row.audit.discount_pct is not None
        and row.audit.discount_pct / 100 >= _current_discount_threshold(row.listing, active)
    )

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "methodology": {
            "read_only": True,
            "productive_code_modified": False,
            "universe_loader": "RadarService.opportunities() -> listing_repo.list_active() -> SqlAlchemyListingRepository.list_active(status='active')",
            "detector": "domain.radar.detector.detect_opportunities() semantics replayed with per-listing observability",
            "uf_rate_used": str(uf_rate),
            "return_limit": limit,
            "db_identity": db_identity,
        },
        "definitions": {
            "active_universe": "Rows loaded by listing_repo.list_active(); SQL status='active' plus in-memory geocoding guardrails.",
            "technically_evaluable_universe": "Active listings with positive effective area: built_area_m2 or usable_area_m2 or m2.",
            "radar_candidates": "Technically evaluable listings whose normalized property_type has at least MIN_RADAR_DATASET_SIZE processable rows; valuation is attempted.",
            "real_opportunities": "Valuation succeeds, target price basis can produce a discount, and discount is above the active segment threshold.",
            "top_n_results": "Real opportunities sorted by discount * confidence, then truncated by API limit and beta safety display rules.",
        },
        "filter_map": filter_map(),
        "score_and_valuation": score_and_valuation_notes(),
        "thresholds": thresholds(active),
        "funnel": _funnel(evaluated, active, filtered, returned, discount_threshold_count),
        "distributions": {
            "opportunity_score": quantiles(score_values),
            "discount_pct": quantiles(discount_values),
            "estimated_value_uf_over_listing_price_uf": quantiles(estimated_to_listing),
            "listing_price_uf_over_estimated_value_uf": quantiles(listing_to_estimated),
            "confidence": quantiles(confidence_values),
            "comparable_count": quantiles(comparable_values),
            "dispersion": quantiles(dispersion_values),
            "runtime_by_stage_ms": {key: round(value, 2) for key, value in timings.items()},
        },
        "cuts": {
            "property_type": cuts(evaluated, "property_type", final_candidate_keys, returned_keys),
            "comuna": cuts(evaluated, "comuna", final_candidate_keys, returned_keys, limit=30),
            "source": cuts(evaluated, "source", final_candidate_keys, returned_keys),
            "price_currency": cuts(evaluated, "price_currency", final_candidate_keys, returned_keys),
            "price_uf_source": cuts(evaluated, "price_uf_source", final_candidate_keys, returned_keys),
            "price_data_quality": cuts(evaluated, "price_data_quality", final_candidate_keys, returned_keys),
            "engine_used": cuts(evaluated, "engine_used", final_candidate_keys, returned_keys),
            "geocode_precision": cuts(evaluated, "geocode_precision", final_candidate_keys, returned_keys),
            "confidence_bucket": cuts(
                evaluated,
                "confidence_bucket",
                final_candidate_keys,
                returned_keys,
                bucket_fn=lambda row: confidence_bucket(row.audit.confidence),
            ),
            "comparable_count_bucket": cuts(
                evaluated,
                "comparable_count_bucket",
                final_candidate_keys,
                returned_keys,
                bucket_fn=lambda row: comparable_count_bucket(row.audit.comparable_count),
            ),
        },
        "sample_files": {
            "top_20_current_radar": "reports/radar/samples/top_20_current_radar.csv",
            "random_50_radar_candidates": "reports/radar/samples/random_50_radar_candidates.csv",
            "random_50_non_opportunities": "reports/radar/samples/random_50_non_opportunities.csv",
            "top_50_highest_discount": "reports/radar/samples/top_50_highest_discount.csv",
            "top_50_low_confidence_in_radar": "reports/radar/samples/top_50_low_confidence_in_radar.csv",
            "top_50_high_estimated_to_listing_ratio": "reports/radar/samples/top_50_high_estimated_to_listing_ratio.csv",
            "evident_bias_segment_50": "reports/radar/samples/evident_bias_segment_50.csv",
        },
        "conclusions": conclusions(evaluated, filtered, row_by_key),
    }
    return report


def thresholds(active: Sequence[Listing]) -> dict[str, Any]:
    by_type = _active_by_property_type([listing for listing in active if _has_valid_area(listing)])
    return {
        "discount": {
            "normal_dataset": MIN_UNDERVALUATION,
            "normal_dataset_pct": _pct(MIN_UNDERVALUATION),
            "low_data_dataset": MIN_UNDERVALUATION_LOW_DATA,
            "low_data_dataset_pct": _pct(MIN_UNDERVALUATION_LOW_DATA),
            "low_data_threshold_count": LOW_DATA_THRESHOLD,
        },
        "opportunity_score": {
            "current_minimum": CURRENT_SCORE_THRESHOLD,
            "current_behavior": "no explicit score threshold; score only ranks top-N",
        },
        "confidence": {
            "service_filter_min_confidence": CURRENT_SERVICE_MIN_CONFIDENCE,
            "default_filter_min_confidence_if_not_overridden": 0.5,
        },
        "comparables_minimum": MIN_COMPARABLES,
        "geocoding": {
            "target_required": False,
            "distance_filter_only_when_target_and_candidate_precision_are_address": True,
            "max_distance_km": COMPARABLES_MAX_DISTANCE_KM,
        },
        "dispersion": {
            "hard_filter": False,
            "penalty_or_warning": "reliability/comparable_quality warnings only",
        },
        "canonical_price": {
            "radar_target_price_basis_required_for_discount": True,
            "weak_or_missing_UF_excluded_for_strong_opportunity": True,
        },
        "property_type": {
            "explicit_filter": False,
            "conceptually_supported_residential_types": sorted(SUPPORTED_PROPERTY_TYPES),
            "same_type_dataset_minimum": MIN_RADAR_DATASET_SIZE,
            "active_processable_by_type": {key: len(value) for key, value in sorted(by_type.items())},
        },
        "comuna": {
            "explicit_whitelist": False,
            "valuation_requires_non_empty_target_comuna": True,
            "comparables_must_match_exact_comuna": True,
        },
    }


def filter_map() -> dict[str, Any]:
    return {
        "before_detect_opportunities": [
            "RadarService obtains a real UF rate.",
            "RadarService calls listing_repo.list_active().",
            "SqlAlchemyListingRepository.list_active() filters only status='active' and orders by scraped_at desc.",
            "apply_geocoding_guardrails() normalizes/degrades geocode precision in memory; it does not remove rows.",
        ],
        "inside_detect_opportunities": [
            "Keep active listings.",
            "Keep listings with effective area > 0.",
            "Group by normalized property_type.",
            "Skip a property_type only if its processable same-type dataset has fewer than 10 rows.",
            "For each target, value against same-property-type listings excluding self.",
            "Valuation filters comparables by exact comuna, same property_type, active status, area tolerance, positive price, and address-level distance <= 5 km when both sides are precise.",
            "Valuation requires at least 5 eligible comparables.",
            "Target discount uses radar_price_basis(); weak/missing UF target prices cannot become strong opportunities.",
            "Opportunity passes if discount >= 5% in normal-data segments or >= 10% in low-data segments.",
        ],
        "after_detect_opportunities": [
            "RadarService calls apply_quality_filters(result.opportunities, min_confidence=0.0).",
            "The helper still enforces min_comparables=5, which valuation already enforced.",
            "No additional min_discount is passed.",
            "top_n() truncates sorted opportunities to the API limit.",
            "assess_radar_safety() can hide top-N rows with no-data/beta-safety issues, but does not re-rank or backfill.",
        ],
        "practically_no_op_filters": [
            "min_confidence=0.0 in RadarService.",
            "min_comparables after detection, because valuation success already implies at least 5.",
            "opportunity_score threshold, because none exists.",
            "geocoding as a target gate, because missing/non-address geocoding does not reject a target.",
            "dispersion as a hard gate, because it only creates warnings/penalties.",
            "comuna whitelist, because none exists.",
        ],
        "restrictive_filters": [
            "effective area > 0 removes invalid area rows.",
            "same-property-type dataset >= 10 controls whether valuation is attempted.",
            "exact comuna matching and area tolerance control comparable eligibility.",
            "minimum 5 comparables controls valuation success.",
            "target price basis excludes weak or unrecoverable UF prices from becoming opportunities.",
            "discount >= 5% or 10% controls final opportunity status.",
        ],
    }


def score_and_valuation_notes() -> dict[str, Any]:
    return {
        "opportunity_score_formula": "discount_pct * confidence",
        "score_inputs": [
            "discount_pct against point AVM estimate",
            "final confidence after reliability penalties",
        ],
        "discount_formula": "(estimated_market_price - listing_price_basis) / estimated_market_price",
        "valuation_engine_used_by_radar": "domain.valuation.comparables.valuate()",
        "current_engine_mode": _configured_engine_name(),
        "not_used_by_radar": ["consensus", "canonical_outliers"],
        "point_or_range": "Radar uses valuation.estimated_price / market_price; low/high range is computed but not used for opportunity gating.",
        "confidence_penalizes_low_quality": True,
        "few_comparables_handling": "Fewer than 5 comparables fails valuation. Between 5 and LOW_COMPARABLE_COUNT can produce warnings/penalties but still enter.",
        "high_dispersion_handling": "High dispersion produces warnings and confidence penalties; it is not a hard rejection.",
        "property_type_separation": "Targets and comparables must share normalized property_type; houses are not backfilled with apartments.",
        "comparable_overvaluation_risk": "Possible when exact-comuna/same-type comparables are sparse, mixed by microzone, low geocode quality, high dispersion, or affected by weak price provenance.",
    }


def build_samples(
    *,
    evaluated: Sequence[EvaluatedRow],
    filtered: Sequence[Opportunity],
    returned: Sequence[Opportunity],
    sample_size: int,
) -> dict[str, list[AuditRow]]:
    row_by_key = {_key(row.listing): row.audit for row in evaluated}
    candidate_keys = {_key(opportunity.listing) for opportunity in filtered}
    candidates = [row for row in evaluated if _key(row.listing) in candidate_keys]
    non_opportunities = [
        row
        for row in evaluated
        if row.valuation_success
        and _key(row.listing) not in candidate_keys
        and (row.audit.discount_pct is None or row.audit.discount_pct <= 0)
    ]
    rng = random.Random(RANDOM_SEED)
    random_candidates = rng.sample(candidates, min(sample_size, len(candidates))) if candidates else []
    random_non_opportunities = (
        rng.sample(non_opportunities, min(sample_size, len(non_opportunities)))
        if non_opportunities
        else []
    )
    high_discount = sorted(
        [row for row in evaluated if row.audit.discount_pct is not None],
        key=lambda row: row.audit.discount_pct or -999,
        reverse=True,
    )[:sample_size]
    low_confidence_in_radar = sorted(
        candidates,
        key=lambda row: row.audit.confidence if row.audit.confidence is not None else 999,
    )[:sample_size]
    high_ratio = sorted(
        [
            row
            for row in evaluated
            if row.audit.estimated_value_uf is not None
            and row.audit.listing_price_uf not in {None, 0}
        ],
        key=lambda row: (row.audit.estimated_value_uf or 0) / (row.audit.listing_price_uf or 1),
        reverse=True,
    )[:sample_size]
    bias_rows = _bias_sample(candidates, sample_size)
    return {
        "top_20_current_radar": [row_by_key[_key(opportunity.listing)] for opportunity in returned],
        "random_50_radar_candidates": [row.audit for row in random_candidates],
        "random_50_non_opportunities": [row.audit for row in random_non_opportunities],
        "top_50_highest_discount": [row.audit for row in high_discount],
        "top_50_low_confidence_in_radar": [row.audit for row in low_confidence_in_radar],
        "top_50_high_estimated_to_listing_ratio": [row.audit for row in high_ratio],
        "evident_bias_segment_50": [row.audit for row in bias_rows],
    }


def write_outputs(
    report: dict[str, Any],
    samples: dict[str, list[AuditRow]],
    output_dir: Path,
) -> None:
    sample_dir = output_dir / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in samples.items():
        _write_sample_csv(sample_dir / f"{name}.csv", rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_payload = json.dumps(report, ensure_ascii=False, indent=2)
    (output_dir / "radar_funnel_audit_latest.json").write_text(json_payload, encoding="utf-8")
    (output_dir / "radar_funnel_audit_latest.md").write_text(
        markdown_report(report),
        encoding="utf-8",
    )


def markdown_report(report: dict[str, Any]) -> str:
    funnel = report["funnel"]
    conclusions_data = report["conclusions"]
    lines = [
        "# Radar Funnel Audit",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Executive Conclusion",
        "",
        f"- Radar today is: **{conclusions_data['detector_or_ranking']}**.",
        f"- Real minimum opportunity threshold: **{conclusions_data['real_minimum_opportunity_threshold']}**.",
        f"- Main cause of broad entry: **{conclusions_data['main_cause']}**.",
        f"- AVM bias signal: **{conclusions_data['avm_bias_signal']}**.",
        f"- Strongest segment signal: **{conclusions_data['strongest_segment_signal']}**.",
        f"- Minimum conceptual change before performance work: **{conclusions_data['minimum_conceptual_change']}**.",
        f"- Do not touch yet: **{conclusions_data['do_not_touch_yet']}**.",
        "",
        "## Methodology",
        "",
        f"- Universe loader: `{report['methodology']['universe_loader']}`",
        f"- UF rate used: `{report['methodology']['uf_rate_used']}`",
        f"- Productive code modified: `{report['methodology']['productive_code_modified']}`",
        "",
        "## Definitions",
        "",
    ]
    for key, value in report["definitions"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Filter Map",
            "",
            "### Before Detection",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["filter_map"]["before_detect_opportunities"])
    lines.extend(["", "### During Detection", ""])
    lines.extend(f"- {item}" for item in report["filter_map"]["inside_detect_opportunities"])
    lines.extend(["", "### After Detection", ""])
    lines.extend(f"- {item}" for item in report["filter_map"]["after_detect_opportunities"])
    lines.extend(["", "### Restrictive vs No-Op", ""])
    lines.append("Restrictive filters:")
    lines.extend(f"- {item}" for item in report["filter_map"]["restrictive_filters"])
    lines.append("")
    lines.append("Practically no-op filters:")
    lines.extend(f"- {item}" for item in report["filter_map"]["practically_no_op_filters"])
    lines.extend(
        [
            "",
            "## Score And Valuation",
            "",
            f"- Opportunity score formula: `{report['score_and_valuation']['opportunity_score_formula']}`",
            f"- Discount formula: `{report['score_and_valuation']['discount_formula']}`",
            f"- Valuation engine used by Radar: `{report['score_and_valuation']['valuation_engine_used_by_radar']}`",
            f"- Current engine mode: `{report['score_and_valuation']['current_engine_mode']}`",
            f"- Point/range usage: {report['score_and_valuation']['point_or_range']}",
            f"- Confidence penalty behavior: {report['score_and_valuation']['confidence_penalizes_low_quality']}",
            f"- Few comparables: {report['score_and_valuation']['few_comparables_handling']}",
            f"- High dispersion: {report['score_and_valuation']['high_dispersion_handling']}",
            f"- Property type separation: {report['score_and_valuation']['property_type_separation']}",
            f"- Comparable overvaluation risk: {report['score_and_valuation']['comparable_overvaluation_risk']}",
            "",
        ]
    )
    lines.extend(
        [
        "## Funnel",
        "",
        "| Stage | Count | Percent of active |",
        "| --- | ---: | ---: |",
        ]
    )
    for key, row in funnel.items():
        lines.append(f"| `{key}` | {row['count']} | {row['pct_of_active']} |")
    lines.extend(
        [
            "",
            "## Current Thresholds",
            "",
            f"- Discount: {report['thresholds']['discount']['normal_dataset_pct']} normal, "
            f"{report['thresholds']['discount']['low_data_dataset_pct']} low-data.",
            "- Opportunity score: no explicit minimum; it only orders results.",
            "- Confidence: service passes `min_confidence=0.0`; the default helper threshold `0.5` is bypassed.",
            f"- Comparables: valuation requires at least `{report['thresholds']['comparables_minimum']}`.",
            "- Geocoding: no target geocode requirement; distance is enforced only when both sides are address-level.",
            "- Dispersion: warnings/penalties only, no hard rejection.",
            "",
            "## Distributions",
            "",
            "| Metric | min | p10 | p25 | p50 | p75 | p90 | p95 | p99 | max |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for metric, values in report["distributions"].items():
        if metric == "runtime_by_stage_ms":
            continue
        lines.append(
            f"| `{metric}` | {values['min']} | {values['p10']} | {values['p25']} | "
            f"{values['p50']} | {values['p75']} | {values['p90']} | {values['p95']} | "
            f"{values['p99']} | {values['max']} |"
        )
    lines.extend(
        [
            "",
            "## Runtime By Stage",
            "",
            "| Stage | ms |",
            "| --- | ---: |",
        ]
    )
    for key, value in report["distributions"]["runtime_by_stage_ms"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Cuts",
            "",
            "See the JSON report for full cuts by property_type, comuna, source, price currency, price quality, engine, geocoding, confidence bucket, and comparable-count bucket.",
            "",
            "## Sample Files",
            "",
        ]
    )
    for label, path in report["sample_files"].items():
        lines.append(f"- `{label}`: `{path}`")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            conclusions_data["interpretation"],
            "",
            "## Explicit Answers",
            "",
            f"1. Detector or ranking: {conclusions_data['detector_or_ranking']}.",
            f"2. Minimum score threshold exists: {conclusions_data['score_threshold_exists']}.",
            f"3. Almost all enter because filters are lax: {conclusions_data['filters_lax_answer']}.",
            f"4. Almost all enter because AVM is biased: {conclusions_data['avm_biased_answer']}.",
            f"5. Segment/source concentration: {conclusions_data['strongest_segment_signal']}.",
            f"6. Minimum conceptual change: {conclusions_data['minimum_conceptual_change']}.",
            f"7. Do not touch yet: {conclusions_data['do_not_touch_yet']}.",
            "",
        ]
    )
    return "\n".join(lines)


def quantiles(values: Iterable[float | int | None]) -> dict[str, float | None]:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return dict.fromkeys(("min", "p10", "p25", "p50", "p75", "p90", "p95", "p99", "max"))
    return {
        "min": _round(clean[0]),
        "p10": _round(_percentile(clean, 10)),
        "p25": _round(_percentile(clean, 25)),
        "p50": _round(_percentile(clean, 50)),
        "p75": _round(_percentile(clean, 75)),
        "p90": _round(_percentile(clean, 90)),
        "p95": _round(_percentile(clean, 95)),
        "p99": _round(_percentile(clean, 99)),
        "max": _round(clean[-1]),
    }


def cuts(
    evaluated: Sequence[EvaluatedRow],
    field: str,
    final_candidate_keys: set[str],
    returned_keys: set[str],
    *,
    bucket_fn=None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[EvaluatedRow]] = defaultdict(list)
    for row in evaluated:
        value = bucket_fn(row) if bucket_fn is not None else getattr(row.audit, field)
        grouped[str(value or "unknown")].append(row)
    rows = []
    for value, group in grouped.items():
        active = len(group)
        valuation_success = sum(1 for row in group if row.valuation_success)
        final_candidates = sum(1 for row in group if _key(row.listing) in final_candidate_keys)
        returned = sum(1 for row in group if _key(row.listing) in returned_keys)
        discounts = [row.audit.discount_pct for row in group if row.audit.discount_pct is not None]
        rows.append(
            {
                "value": value,
                "active": active,
                "valuation_success": valuation_success,
                "final_candidates": final_candidates,
                "returned_top_n": returned,
                "candidate_share_pct": _pct_value(final_candidates, active),
                "median_discount_pct": quantiles(discounts)["p50"],
            }
        )
    rows.sort(key=lambda item: (item["final_candidates"], item["active"]), reverse=True)
    return rows[:limit] if limit is not None else rows


def confidence_bucket(value: float | None) -> str:
    if value is None:
        return "missing"
    if value < 0.3:
        return "<0.30"
    if value < 0.5:
        return "0.30-0.49"
    if value < 0.75:
        return "0.50-0.74"
    return ">=0.75"


def comparable_count_bucket(value: int | None) -> str:
    if value is None:
        return "missing"
    if value < MIN_COMPARABLES:
        return f"<{MIN_COMPARABLES}"
    if value < 10:
        return "5-9"
    if value < 20:
        return "10-19"
    return ">=20"


def conclusions(
    evaluated: Sequence[EvaluatedRow],
    filtered: Sequence[Opportunity],
    row_by_key: dict[str, EvaluatedRow],
) -> dict[str, str]:
    active = len(evaluated)
    valuation_attempted = sum(1 for row in evaluated if row.valuation_attempted)
    valuation_success = sum(1 for row in evaluated if row.valuation_success)
    final_candidates = len(filtered)
    attempted_share = _pct_value(valuation_attempted, active)
    success_share = _pct_value(valuation_success, active)
    candidate_share = _pct_value(final_candidates, active)
    positive_discount_share = _pct_value(
        sum(1 for row in evaluated if row.audit.discount_pct is not None and row.audit.discount_pct > 0),
        valuation_success,
    )
    segment = _strongest_segment(filtered, row_by_key)
    if candidate_share >= 80:
        main_cause = (
            "filters laxos sobre oportunidades finales; el umbral de descuento no separa "
            "suficiente y no hay umbral de score"
        )
    else:
        main_cause = (
            "el universo entra casi completo al detector porque los pre-filtros son mínimos; "
            "no todos cruzan el umbral de oportunidad final"
        )
    avm_bias_signal = (
        f"{positive_discount_share}% de valuaciones exitosas tienen descuento positivo; "
        "esto es compatible con sobrevaloracion AVM si la mediana/percentiles de descuento son altos"
    )
    return {
        "detector_or_ranking": "ranking with a light discount gate" if final_candidates else "detector with no current candidates",
        "real_minimum_opportunity_threshold": "5% discount in normal segments, 10% in low-data segments; no score threshold",
        "main_cause": main_cause,
        "avm_bias_signal": avm_bias_signal,
        "strongest_segment_signal": segment,
        "minimum_conceptual_change": "define opportunity as discount plus minimum confidence/comparable-quality gates before top-N ranking",
        "do_not_touch_yet": "performance, cache, parallelism, UI behavior, timeouts, or score formula",
        "score_threshold_exists": "no; opportunity_score is discount * confidence and is only used for sorting",
        "filters_lax_answer": (
            f"yes for detector entry: attempted={attempted_share}% and success={success_share}%; "
            f"final opportunities are {candidate_share}% of active"
        ),
        "avm_biased_answer": "plausible when discount distribution is broadly positive; validate with holdout before changing performance",
        "interpretation": (
            f"Radar loaded {active} active listings, attempted valuation for {valuation_attempted} "
            f"and returned {final_candidates} final candidates before top-N. The service-level "
            "confidence filter is configured to 0.0, comparable count is already enforced by the "
            "valuation engine, and score has no acceptance threshold. Therefore broad entry is "
            "explained first by permissive candidate gates; AVM overvaluation remains a likely "
            "upstream amplifier if discounts are positive across most segments."
        ),
    }


def _funnel(
    evaluated: Sequence[EvaluatedRow],
    active: Sequence[Listing],
    filtered: Sequence[Opportunity],
    returned: Sequence[Opportunity],
    discount_threshold_count: int,
) -> dict[str, dict[str, float | int]]:
    active_count = len(active)
    canonical_price_eligible = sum(
        1 for listing in active if radar_price_basis(listing).is_usable_for_strong_opportunity
    )
    property_type_supported = sum(
        1 for listing in active if _property_type(listing) in SUPPORTED_PROPERTY_TYPES
    )
    usable_area_present = sum(1 for listing in active if _has_valid_area(listing))
    comuna_supported = sum(1 for listing in active if bool(listing.comuna))
    valuation_attempted = sum(1 for row in evaluated if row.valuation_attempted)
    valuation_success = sum(1 for row in evaluated if row.valuation_success)
    valuation_failed = valuation_attempted - valuation_success
    confidence_available = sum(1 for row in evaluated if row.audit.confidence is not None)
    confidence_above_threshold = sum(
        1
        for row in evaluated
        if row.audit.confidence is not None and row.audit.confidence >= CURRENT_SERVICE_MIN_CONFIDENCE
    )
    comparable_count_available = sum(1 for row in evaluated if row.audit.comparable_count is not None)
    comparable_count_above_threshold = sum(
        1
        for row in evaluated
        if row.audit.comparable_count is not None and row.audit.comparable_count >= MIN_COMPARABLES
    )
    discount_positive = sum(
        1 for row in evaluated if row.audit.discount_pct is not None and row.audit.discount_pct > 0
    )
    score_positive = sum(
        1
        for row in evaluated
        if row.audit.opportunity_score is not None and row.audit.opportunity_score > 0
    )
    stages = {
        "active_listings": active_count,
        "canonical_price_eligible": canonical_price_eligible,
        "property_type_supported": property_type_supported,
        "usable_area_present": usable_area_present,
        "comuna_supported": comuna_supported,
        "valuation_attempted": valuation_attempted,
        "valuation_success": valuation_success,
        "valuation_failed": valuation_failed,
        "confidence_available": confidence_available,
        "confidence_above_threshold": confidence_above_threshold,
        "comparable_count_available": comparable_count_available,
        "comparable_count_above_threshold": comparable_count_above_threshold,
        "discount_positive": discount_positive,
        "discount_above_5_pct": _discount_above(evaluated, 5),
        "discount_above_10_pct": _discount_above(evaluated, 10),
        "discount_above_15_pct": _discount_above(evaluated, 15),
        "opportunity_score_positive": score_positive,
        "opportunity_score_above_current_threshold": score_positive,
        "final_candidates": len(filtered),
        "returned_top_n": len(returned),
    }
    return {
        key: {"count": value, "pct_of_active": _pct_value(value, active_count)}
        for key, value in stages.items()
    }


def _service_returned_top_n(opportunities: Sequence[Opportunity], limit: int) -> list[Opportunity]:
    returned = []
    for opportunity in top_n(opportunities, limit):
        valuation = opportunity.valuation_result
        warnings = []
        if valuation is not None:
            warnings.extend(valuation.reliability_warnings)
            warnings.extend(valuation.comparable_quality_flags)
        safety = assess_radar_safety(
            beta_scope_status=valuation.beta_scope_status if valuation is not None else None,
            beta_scope_flags=valuation.beta_scope_flags if valuation is not None else (),
            comparable_quality_level=valuation.comparable_quality_level if valuation is not None else None,
            comparable_quality_flags=valuation.comparable_quality_flags if valuation is not None else (),
            warnings=warnings,
        )
        if safety.show:
            returned.append(opportunity)
    return returned


def _audit_row(
    *,
    listing: Listing,
    uf_rate: Decimal,
    listing_price_uf: float | None,
    geocode_precision: str | None,
    basis,
) -> AuditRow:
    return AuditRow(
        listing_id=listing.id,
        title=listing.title,
        comuna=listing.comuna,
        property_type=_property_type(listing),
        source=listing.source,
        listing_price_uf=_round(listing_price_uf),
        listing_price_clp=_round(float(listing.price.clp)),
        estimated_value_uf=None,
        estimated_value_clp=None,
        discount_pct=None,
        opportunity_score=None,
        confidence=None,
        confidence_label=None,
        engine_used=_configured_engine_name(),
        comparable_count=None,
        dispersion=None,
        geocode_precision=geocode_precision,
        price_currency=basis.price_currency,
        price_uf_source=listing.price_uf_source,
        price_data_quality=basis.price_data_quality,
        price_basis_used=basis.price_basis_used,
        warning_codes="",
        reason_entered_radar="",
        reason_not_rejected="not evaluated yet",
        top_score_components="",
        url=listing.url,
        valuation_status="not_attempted",
    )


def _replace_audit(row: AuditRow, **changes) -> AuditRow:
    values = asdict(row)
    values.update(changes)
    return AuditRow(**values)


def _write_sample_csv(path: Path, rows: Sequence[AuditRow]) -> None:
    fieldnames = list(AuditRow.__dataclass_fields__.keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


async def _db_identity(session) -> dict[str, str | None]:
    try:
        result = await session.execute(text("select current_database(), current_user"))
        database, user = result.one()
        return {"database": str(database), "user": str(user)}
    except Exception:
        return {"database": None, "user": None}


def _active_by_property_type(active: Sequence[Listing]) -> dict[str, list[Listing]]:
    by_type: dict[str, list[Listing]] = defaultdict(list)
    for listing in active:
        by_type[_property_type(listing)].append(listing)
    return dict(by_type)


def _current_discount_threshold(listing: Listing, active: Sequence[Listing]) -> float:
    processable = [item for item in active if _has_valid_area(item)]
    same_type_count = sum(1 for item in processable if _property_type(item) == _property_type(listing))
    return MIN_UNDERVALUATION_LOW_DATA if same_type_count < LOW_DATA_THRESHOLD else MIN_UNDERVALUATION


def _exclude_self(target: Listing, universe: Sequence[Listing]) -> list[Listing]:
    if target.id is not None:
        return [listing for listing in universe if listing.id != target.id]
    return [listing for listing in universe if listing.fingerprint != target.fingerprint]


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


def _has_valid_area(listing: Listing) -> bool:
    area = listing.built_area_m2 or listing.usable_area_m2 or listing.m2
    return area is not None and area > 0


def _safe_display_price_uf(listing: Listing, uf_rate: Decimal) -> float | None:
    try:
        return display_price_uf(listing, uf_rate)
    except Exception:
        return None


def _dispersion_from(valuation) -> float | None:
    reliability_value = valuation.reliability_metrics.get("price_m2_iqr_pct")
    quality_value = valuation.comparable_quality_metrics.get("price_per_m2_dispersion")
    value = reliability_value if reliability_value is not None else quality_value
    return float(value) if value is not None else None


def _score_components(discount: float | None, confidence: float | None) -> str:
    if discount is None or confidence is None:
        return ""
    return f"discount_pct={_pct(discount)};confidence={confidence:.4f}"


def _configured_engine_name() -> str:
    if os.getenv("VALORIA_USE_CONSENSUS", "").strip().lower() in {"1", "true", "yes", "on"}:
        return "consensus_flag_enabled_but_radar_uses_comparables"
    if os.getenv("VALUATION_CANONICAL_PRICE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        return "canonical"
    if os.getenv("VALUATION_CANONICAL_PRICE_SEGMENTED", "").strip().lower() in {"1", "true", "yes", "on"}:
        return "canonical_segmented"
    return "legacy"


def _confidence_label(value: float) -> str:
    if value >= 0.75:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


def _discount_above(evaluated: Sequence[EvaluatedRow], threshold_pct: float) -> int:
    return sum(
        1
        for row in evaluated
        if row.audit.discount_pct is not None and row.audit.discount_pct >= threshold_pct
    )


def _bias_sample(candidates: Sequence[EvaluatedRow], sample_size: int) -> list[EvaluatedRow]:
    grouped: dict[tuple[str, str], list[EvaluatedRow]] = defaultdict(list)
    for row in candidates:
        grouped[(row.audit.comuna, row.audit.property_type)].append(row)
    if not grouped:
        return []
    group_key, rows = max(grouped.items(), key=lambda item: len(item[1]))
    if len(rows) < min(10, sample_size):
        return []
    _ = group_key
    return sorted(rows, key=lambda row: row.audit.opportunity_score or 0, reverse=True)[:sample_size]


def _strongest_segment(
    filtered: Sequence[Opportunity],
    row_by_key: dict[str, EvaluatedRow],
) -> str:
    if not filtered:
        return "no candidates"
    counts: Counter[str] = Counter()
    for opportunity in filtered:
        row = row_by_key.get(_key(opportunity.listing))
        if row is None:
            continue
        counts[f"{row.audit.comuna}/{row.audit.property_type}/{row.audit.source}"] += 1
    segment, count = counts.most_common(1)[0]
    return f"{segment}: {count} candidates"


def _key(listing: Listing) -> str:
    return f"id:{listing.id}" if listing.id is not None else f"fp:{listing.fingerprint}"


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        text_value = str(value or "").strip()
        if not text_value or text_value in seen:
            continue
        seen.add(text_value)
        result.append(text_value)
    return result


def _elapsed_ms(start: float) -> float:
    return (perf_counter() - start) * 1000


def _percentile(values: Sequence[float], percentile: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def _round(value: float | None, ndigits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), ndigits)


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _pct_value(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 2)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
