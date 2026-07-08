"""Read-only holdout validation for Comparable Quality v2."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.entities.listing import Listing  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM, PriceHistoryORM, UFRateORM  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402
from scripts.audit_comparable_quality_v2 import (  # noqa: E402
    improvement_class,
    json_safe,
    run_audit,
)

OUTPUT_JSON = "comparable_quality_v2_holdout_validation_latest.json"
OUTPUT_MD = "comparable_quality_v2_holdout_validation_latest.md"
BASELINE = "baseline"
CHALLENGER = "robust_weighted_median"
HASH_SEEDS = (11, 23, 37)
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


@dataclass(frozen=True)
class CohortMetrics:
    name: str
    targets: int
    evaluations: int
    coverage_pct: float
    baseline_mape_pct: float | None
    challenger_mape_pct: float | None
    delta_mape_pct: float | None
    baseline_median_ape_pct: float | None
    challenger_median_ape_pct: float | None
    baseline_p90_ape_pct: float | None
    challenger_p90_ape_pct: float | None
    baseline_p95_ape_pct: float | None
    challenger_p95_ape_pct: float | None
    improved_count: int
    worsened_count: int
    unchanged_count: int
    improved_pct: float
    worsened_pct: float
    mean_delta_pct: float | None
    median_delta_pct: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate CQ v2 robust weighted median on holdout splits.")
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
        uf_rate = args.uf_rate or await latest_uf_rate(session)
        db_temporal = await temporal_db_summary(session)
    if uf_rate is None:
        raise SystemExit("No UF rate provided and no local uf_rates row found. Pass --uf-rate.")

    report = build_validation(
        listings=listings,
        uf_rate=uf_rate,
        property_type=args.property_type,
        limit=args.limit,
        case_limit=args.case_limit,
        db_temporal=db_temporal,
        runtime_ms=0.0,
    )
    report["summary"]["runtime_ms"] = round((perf_counter() - start) * 1000, 2)
    json_path, md_path = write_outputs(report, Path(args.output_dir))
    print(
        json.dumps(
            {
                "evaluations": report["summary"]["successful_evaluations"],
                "baseline_mape": report["summary"]["baseline_mape_pct"],
                "challenger_mape": report["summary"]["challenger_mape_pct"],
                "delta_mape": report["summary"]["delta_mape_pct"],
                "temporal_holdout_delta": report["temporal_split"]["holdout_newer"]["delta_mape_pct"],
                "hash_mean_delta": report["hash_splits"]["mean_delta_mape_pct"],
                "recommendation": report["recommendation"]["decision"],
                "json": str(json_path),
                "markdown": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_validation(
    *,
    listings: Sequence[Listing],
    uf_rate: Decimal,
    property_type: str,
    limit: int | None,
    case_limit: int,
    db_temporal: dict[str, Any],
    runtime_ms: float,
) -> dict[str, Any]:
    source = run_audit(
        listings,
        uf_rate=uf_rate,
        property_type=property_type,
        limit=limit,
        case_limit=case_limit,
        runtime_ms=0.0,
    )
    rows = [row for row in source["rows"] if has_pair(row)]
    listing_index = listing_index_by_key(listings)
    enriched = [attach_temporal(row, listing_index) for row in rows]
    all_metrics = cohort_metrics("all", enriched)
    temporal = temporal_split(enriched)
    hash_report = hash_splits(enriched)
    surface = surface_cohorts(enriched)
    baseline_error = baseline_error_cohorts(enriched)
    quality = comparable_quality_cohorts(enriched)
    by_comuna = comuna_cohorts(enriched)
    regressions = regression_analysis(enriched, case_limit=case_limit)
    production = production_safety()
    recommendation_data = recommendation(all_metrics, temporal, hash_report, by_comuna, quality)
    return json_safe(
        {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "summary": {
                "read_only": True,
                "productive_code_modified": False,
                "property_type": property_type,
                "uf_rate_used": str(uf_rate),
                "active_listings": len(listings),
                "total_targets": source["summary"]["total_targets"],
                "successful_evaluations": len(rows),
                "baseline_mape_pct": all_metrics.baseline_mape_pct,
                "challenger": CHALLENGER,
                "challenger_mape_pct": all_metrics.challenger_mape_pct,
                "delta_mape_pct": all_metrics.delta_mape_pct,
                "improvement_class": improvement_class(all_metrics.delta_mape_pct),
                "baseline_p90_pct": all_metrics.baseline_p90_ape_pct,
                "challenger_p90_pct": all_metrics.challenger_p90_ape_pct,
                "runtime_ms": runtime_ms,
            },
            "available_temporal_fields": temporal_field_summary(listings, db_temporal),
            "production_safety": production,
            "overall": asdict(all_metrics),
            "temporal_split": temporal,
            "hash_splits": hash_report,
            "cohorts": {
                "by_comuna": by_comuna,
                "critical_comunas": [row for row in by_comuna if row["name"] in CRITICAL_COMUNAS],
                "by_surface_m2": surface,
                "by_baseline_error": baseline_error,
                "by_comparable_quality": quality,
            },
            "regressions": regressions,
            "answers": explicit_answers(all_metrics, temporal, hash_report, by_comuna, quality, recommendation_data),
            "recommendation": recommendation_data,
            "do_not_do_yet": [
                "Do not replace productive AVM scoring from this validation alone.",
                "Do not use subject observed price or subject price_m2 in estimation.",
                "Do not enable robust_weighted_median for cohorts with unstable P90 without guardrails.",
                "Do not use listing asking price as its own valuation input in Radar/listing analysis.",
                "Do not run scraper, external geocoding, migrations or backfills from this benchmark.",
            ],
        }
    )


def temporal_split(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    usable = [row for row in rows if row.get("temporal_key") is not None]
    if len(usable) < 20:
        return {
            "status": "insufficient_temporal_data",
            "timestamp_field": "scraped_at",
            "older_train": asdict(cohort_metrics("older_train", [])),
            "holdout_newer": asdict(cohort_metrics("holdout_newer", [])),
        }
    ordered = sorted(usable, key=lambda row: row["temporal_key"])
    cutoff = ordered[len(ordered) // 2]["temporal_key"]
    older = [row for row in usable if row["temporal_key"] <= cutoff]
    newer = [row for row in usable if row["temporal_key"] > cutoff]
    return {
        "status": "ok",
        "timestamp_field": "scraped_at",
        "timestamp_note": "scraped_at is an observation timestamp, not original publication date.",
        "cutoff": cutoff,
        "oldest": ordered[0]["temporal_key"],
        "newest": ordered[-1]["temporal_key"],
        "older_train": asdict(cohort_metrics("older_train", older)),
        "holdout_newer": asdict(cohort_metrics("holdout_newer", newer)),
    }


def hash_splits(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    splits = []
    for seed in HASH_SEEDS:
        train = []
        holdout = []
        for row in rows:
            bucket = stable_hash_bucket(row_key(row), seed)
            if bucket < 70:
                train.append(row)
            else:
                holdout.append(row)
        train_metrics = cohort_metrics(f"hash_seed_{seed}_train70", train)
        holdout_metrics = cohort_metrics(f"hash_seed_{seed}_holdout30", holdout)
        splits.append(
            {
                "seed": seed,
                "train70": asdict(train_metrics),
                "holdout30": asdict(holdout_metrics),
            }
        )
    holdout_deltas = [
        split["holdout30"]["delta_mape_pct"]
        for split in splits
        if split["holdout30"]["delta_mape_pct"] is not None
    ]
    return {
        "seeds": list(HASH_SEEDS),
        "splits": splits,
        "mean_delta_mape_pct": round(mean(holdout_deltas), 4) if holdout_deltas else None,
        "min_delta_mape_pct": round(min(holdout_deltas), 4) if holdout_deltas else None,
        "max_delta_mape_pct": round(max(holdout_deltas), 4) if holdout_deltas else None,
        "delta_stddev_pct": round(pop_stddev(holdout_deltas), 4) if len(holdout_deltas) > 1 else 0.0,
    }


def surface_cohorts(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    values = sorted(row["surface_m2"] for row in rows if row.get("surface_m2") is not None)
    if not values:
        return []
    p33 = percentile(values, 33.33)
    p66 = percentile(values, 66.66)
    cohorts = [
        ("small", lambda row: (row.get("surface_m2") or 0) <= p33),
        ("medium", lambda row: p33 < (row.get("surface_m2") or 0) <= p66),
        ("large", lambda row: (row.get("surface_m2") or 0) > p66),
    ]
    return [
        {
            **asdict(cohort_metrics(name, [row for row in rows if predicate(row)])),
            "bucket_rule": bucket_rule,
        }
        for name, predicate, bucket_rule in [
            (cohorts[0][0], cohorts[0][1], f"surface_m2 <= {round(p33, 2)}"),
            (cohorts[1][0], cohorts[1][1], f"{round(p33, 2)} < surface_m2 <= {round(p66, 2)}"),
            (cohorts[2][0], cohorts[2][1], f"surface_m2 > {round(p66, 2)}"),
        ]
    ]


def baseline_error_cohorts(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    cohorts = [
        ("ape_lte_15", lambda row: baseline_ape(row) <= 15),
        ("ape_15_to_30", lambda row: 15 < baseline_ape(row) <= 30),
        ("ape_gt_30", lambda row: baseline_ape(row) > 30),
        ("ape_gt_50", lambda row: baseline_ape(row) > 50),
    ]
    return [asdict(cohort_metrics(name, [row for row in rows if predicate(row)])) for name, predicate in cohorts]


def comparable_quality_cohorts(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    outlier_counts = [row["baseline_contamination"]["economic_outlier_count"] for row in rows]
    dispersions = [
        row["baseline_contamination"]["price_m2_iqr_pct"]
        for row in rows
        if row["baseline_contamination"]["price_m2_iqr_pct"] is not None
    ]
    dispersion_p75 = percentile(dispersions, 75) if dispersions else 0
    cohorts = [
        ("few_comparables", lambda row: row["variant_results"][BASELINE]["comparable_count"] < 10),
        ("sufficient_comparables", lambda row: 10 <= row["variant_results"][BASELINE]["comparable_count"] < 20),
        ("many_comparables", lambda row: row["variant_results"][BASELINE]["comparable_count"] >= 20),
        ("many_outliers", lambda row: row["baseline_contamination"]["economic_outlier_count"] >= 3),
        ("low_price_m2_dispersion", lambda row: (row["baseline_contamination"]["price_m2_iqr_pct"] or 0) < dispersion_p75),
        ("high_price_m2_dispersion", lambda row: (row["baseline_contamination"]["price_m2_iqr_pct"] or 0) >= dispersion_p75),
    ]
    result = [asdict(cohort_metrics(name, [row for row in rows if predicate(row)])) for name, predicate in cohorts]
    return [
        {
            **item,
            "notes": {
                "outlier_count_p50": round(percentile(outlier_counts, 50), 4) if outlier_counts else None,
                "high_dispersion_threshold_iqr_pct": round(dispersion_p75, 4) if dispersions else None,
            },
        }
        for item in result
    ]


def comuna_cohorts(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("comuna") or "").strip().lower()].append(row)
    result = []
    for comuna, items in sorted(grouped.items()):
        metrics = asdict(cohort_metrics(comuna, items))
        metrics["regression_risk"] = regression_risk(metrics)
        result.append(metrics)
    return result


def regression_analysis(rows: Sequence[dict[str, Any]], *, case_limit: int) -> dict[str, Any]:
    worsened = [
        row for row in rows
        if challenger_ape(row) is not None and baseline_ape(row) is not None
        and challenger_ape(row) > baseline_ape(row)
    ]
    worsened.sort(key=lambda row: challenger_ape(row) - baseline_ape(row), reverse=True)
    cohorts_worse_p90 = []
    for group_name, group_rows in {
        "all": rows,
        **{f"comuna:{row['name']}": [item for item in rows if item.get("comuna") == row["name"]] for row in comuna_cohorts(rows)},
    }.items():
        metrics = cohort_metrics(group_name, group_rows)
        if (
            metrics.baseline_p90_ape_pct is not None
            and metrics.challenger_p90_ape_pct is not None
            and metrics.challenger_p90_ape_pct > metrics.baseline_p90_ape_pct
        ):
            cohorts_worse_p90.append(asdict(metrics))
    return {
        "worsened_count": len(worsened),
        "top_regressions": [regression_case(row) for row in worsened[:case_limit]],
        "cohorts_where_p90_worsens": cohorts_worse_p90,
    }


def cohort_metrics(name: str, rows: Sequence[dict[str, Any]]) -> CohortMetrics:
    baseline_values = [baseline_ape(row) for row in rows if baseline_ape(row) is not None]
    challenger_values = [challenger_ape(row) for row in rows if challenger_ape(row) is not None]
    paired = [row for row in rows if baseline_ape(row) is not None and challenger_ape(row) is not None]
    deltas = [challenger_ape(row) - baseline_ape(row) for row in paired]
    improved = [delta for delta in deltas if delta < -0.0001]
    worsened = [delta for delta in deltas if delta > 0.0001]
    unchanged = [delta for delta in deltas if abs(delta) <= 0.0001]
    baseline_mape = rounded_mean(baseline_values)
    challenger_mape = rounded_mean(challenger_values)
    return CohortMetrics(
        name=name,
        targets=len(rows),
        evaluations=len(paired),
        coverage_pct=pct(len(paired), len(rows)),
        baseline_mape_pct=baseline_mape,
        challenger_mape_pct=challenger_mape,
        delta_mape_pct=round(baseline_mape - challenger_mape, 4)
        if baseline_mape is not None and challenger_mape is not None
        else None,
        baseline_median_ape_pct=rounded_percentile(baseline_values, 50),
        challenger_median_ape_pct=rounded_percentile(challenger_values, 50),
        baseline_p90_ape_pct=rounded_percentile(baseline_values, 90),
        challenger_p90_ape_pct=rounded_percentile(challenger_values, 90),
        baseline_p95_ape_pct=rounded_percentile(baseline_values, 95),
        challenger_p95_ape_pct=rounded_percentile(challenger_values, 95),
        improved_count=len(improved),
        worsened_count=len(worsened),
        unchanged_count=len(unchanged),
        improved_pct=pct(len(improved), len(deltas)),
        worsened_pct=pct(len(worsened), len(deltas)),
        mean_delta_pct=rounded_mean(deltas),
        median_delta_pct=rounded_percentile(deltas, 50),
    )


def regression_case(row: dict[str, Any]) -> dict[str, Any]:
    delta = challenger_ape(row) - baseline_ape(row)
    contamination = row["baseline_contamination"]
    return {
        "listing_id": row.get("listing_id"),
        "title": row.get("title"),
        "comuna": row.get("comuna"),
        "surface_m2": row.get("surface_m2"),
        "baseline_ape_pct": baseline_ape(row),
        "challenger_ape_pct": challenger_ape(row),
        "delta_ape_pct": round(delta, 4),
        "baseline_comparables": row["variant_results"][BASELINE]["comparable_count"],
        "outlier_count": contamination["economic_outlier_count"],
        "price_m2_iqr_pct": contamination["price_m2_iqr_pct"],
        "probable_regression_reason": probable_regression_reason(row),
    }


def probable_regression_reason(row: dict[str, Any]) -> str:
    count = row["variant_results"][BASELINE]["comparable_count"]
    contamination = row["baseline_contamination"]
    outliers = contamination["economic_outlier_count"]
    dispersion = contamination["price_m2_iqr_pct"] or 0
    if count < 10:
        return "few_comparables"
    if outliers <= 1 and dispersion < 18:
        return "homogeneous_comparables_where_weighted_mean_was_useful"
    if outliers >= 3 and challenger_ape(row) > baseline_ape(row):
        return "weighted_median_may_choose_wrong_side_of_skewed_pool"
    if baseline_ape(row) > 50:
        return "subject_or_published_price_may_be_anomalous"
    return "baseline_weight_signal_lost_or_pool_shape_issue"


def explicit_answers(
    all_metrics: CohortMetrics,
    temporal: dict[str, Any],
    hash_report: dict[str, Any],
    by_comuna: Sequence[dict[str, Any]],
    quality: Sequence[dict[str, Any]],
    recommendation_data: dict[str, Any],
) -> dict[str, str]:
    holdout = temporal.get("holdout_newer", {})
    worsened_comunas = [
        row["name"] for row in by_comuna
        if row.get("delta_mape_pct") is not None and row["delta_mape_pct"] < 0
    ]
    p90_worse = [
        row["name"] for row in [*by_comuna, *quality]
        if row.get("baseline_p90_ape_pct") is not None
        and row.get("challenger_p90_ape_pct") is not None
        and row["challenger_p90_ape_pct"] > row["baseline_p90_ape_pct"]
    ]
    bad_cohorts = [
        row["name"] for row in quality
        if row.get("delta_mape_pct") is not None and row["delta_mape_pct"] < 0
    ]
    return {
        "does_17_791_to_17_1549_hold_out_of_sample": (
            f"hash holdouts show mean delta {hash_report['mean_delta_mape_pct']} pts; "
            f"temporal newer holdout delta {holdout.get('delta_mape_pct')} pts."
        ),
        "does_p90_improve_consistently": (
            f"overall P90 improves from {all_metrics.baseline_p90_ape_pct} to {all_metrics.challenger_p90_ape_pct}; "
            f"cohorts with P90 regression: {', '.join(p90_worse) if p90_worse else 'none'}."
        ),
        "which_comunas_worsen_too_much": ", ".join(worsened_comunas) if worsened_comunas else "none by MAPE",
        "cohorts_where_not_recommended": ", ".join(bad_cohorts) if bad_cohorts else "none by MAPE",
        "can_move_to_feature_flag_challenger": recommendation_data["decision"],
        "guardrails_needed": "; ".join(recommendation_data["guardrails"]),
        "production_safety": (
            "confirmed: subject price is used only for post-estimate error measurement; estimator uses comparable price_m2 and baseline score."
        ),
    }


def recommendation(
    all_metrics: CohortMetrics,
    temporal: dict[str, Any],
    hash_report: dict[str, Any],
    by_comuna: Sequence[dict[str, Any]],
    quality: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    holdout_delta = temporal.get("holdout_newer", {}).get("delta_mape_pct")
    hash_delta = hash_report.get("mean_delta_mape_pct")
    p90_ok = (
        all_metrics.baseline_p90_ape_pct is not None
        and all_metrics.challenger_p90_ape_pct is not None
        and all_metrics.challenger_p90_ape_pct <= all_metrics.baseline_p90_ape_pct
    )
    stable_hash = hash_delta is not None and hash_delta > 0.2
    stable_temporal = holdout_delta is not None and holdout_delta > 0.2
    bad_comunas = [
        row["name"] for row in by_comuna
        if row.get("evaluations", 0) >= 30
        and row.get("delta_mape_pct") is not None
        and row["delta_mape_pct"] < -0.3
    ]
    bad_quality = [
        row["name"] for row in quality
        if row.get("delta_mape_pct") is not None
        and row["delta_mape_pct"] < -0.2
    ]
    if stable_hash and stable_temporal and p90_ok and not bad_comunas:
        decision = "A) pass to challenger engine behind feature flag"
    elif stable_hash and p90_ok:
        decision = "B) use as challenger with cohort guardrails"
    elif all_metrics.delta_mape_pct is not None and all_metrics.delta_mape_pct > 0:
        decision = "C) keep as diagnostic/shadow until unstable cohorts are handled"
    else:
        decision = "D) adjust before productizing"
    return {
        "decision": decision,
        "why": (
            f"overall delta={all_metrics.delta_mape_pct}, hash_mean_delta={hash_delta}, "
            f"temporal_holdout_delta={holdout_delta}, p90_ok={p90_ok}, bad_comunas={bad_comunas}."
        ),
        "bad_comunas": bad_comunas,
        "bad_quality_cohorts": bad_quality,
        "guardrails": [
            "feature flag only; no replacement of current engine yet",
            "log baseline and robust estimates side-by-side",
            "fallback to baseline when comparable_count < 5 or weighted median cannot be computed",
            "monitor P90/P95 by comuna before promoting",
            "do not use subject asking price as estimator input",
        ],
    }


def production_safety() -> dict[str, Any]:
    return {
        "uses_actual_price_for_estimation": False,
        "uses_subject_price_m2_for_estimation": False,
        "uses_actual_error_or_ape_for_estimation": False,
        "actual_price_usage": "post-estimate APE calculation only",
        "estimator_inputs": ["comparable price_m2_uf", "baseline similarity score", "subject surface for final total"],
        "candidate_leakage_guard": "exclude_leakage removes the target listing and same source/external/property/fingerprint candidates.",
    }


def temporal_field_summary(listings: Sequence[Listing], db_temporal: dict[str, Any]) -> dict[str, Any]:
    scraped = [as_iso(listing.scraped_at) for listing in listings if listing.scraped_at is not None]
    last_seen = [as_iso(listing.last_seen_at) for listing in listings if listing.last_seen_at is not None]
    return {
        "domain_listing_fields": {
            "scraped_at_coverage_pct": pct(len(scraped), len(listings)),
            "last_seen_at_coverage_pct": pct(len(last_seen), len(listings)),
            "scraped_at_min": min(scraped) if scraped else None,
            "scraped_at_max": max(scraped) if scraped else None,
            "last_seen_at_min": min(last_seen) if last_seen else None,
            "last_seen_at_max": max(last_seen) if last_seen else None,
        },
        "orm_fields_available": db_temporal,
        "chosen_temporal_split_field": "scraped_at",
        "limitations": [
            "created_at/updated_at exist in ORM but are not mapped to core Listing.",
            "first_seen_at is not a Listing field.",
            "scraped_at is capture timestamp, not original publication date.",
        ],
    }


async def temporal_db_summary(session) -> dict[str, Any]:
    listing_totals = await session.execute(
        select(
            func.count(ListingORM.id),
            func.min(ListingORM.created_at),
            func.max(ListingORM.created_at),
            func.min(ListingORM.updated_at),
            func.max(ListingORM.updated_at),
            func.min(ListingORM.scraped_at),
            func.max(ListingORM.scraped_at),
            func.min(ListingORM.last_seen_at),
            func.max(ListingORM.last_seen_at),
        )
    )
    price_history = await session.execute(
        select(
            func.count(PriceHistoryORM.id),
            func.count(func.distinct(PriceHistoryORM.listing_id)),
            func.min(PriceHistoryORM.observed_at),
            func.max(PriceHistoryORM.observed_at),
        )
    )
    lt = listing_totals.one()
    ph = price_history.one()
    return {
        "listing_rows": int(lt[0] or 0),
        "created_at_min": as_iso(lt[1]),
        "created_at_max": as_iso(lt[2]),
        "updated_at_min": as_iso(lt[3]),
        "updated_at_max": as_iso(lt[4]),
        "scraped_at_min": as_iso(lt[5]),
        "scraped_at_max": as_iso(lt[6]),
        "last_seen_at_min": as_iso(lt[7]),
        "last_seen_at_max": as_iso(lt[8]),
        "price_history_rows": int(ph[0] or 0),
        "price_history_listing_count": int(ph[1] or 0),
        "price_history_observed_at_min": as_iso(ph[2]),
        "price_history_observed_at_max": as_iso(ph[3]),
    }


def attach_temporal(row: dict[str, Any], listing_index: dict[str, Listing]) -> dict[str, Any]:
    listing = listing_index.get(row_key(row))
    enriched = dict(row)
    enriched["temporal_key"] = as_iso(listing.scraped_at) if listing is not None else None
    enriched["last_seen_at"] = as_iso(listing.last_seen_at) if listing is not None else None
    return enriched


def listing_index_by_key(listings: Sequence[Listing]) -> dict[str, Listing]:
    result = {}
    for listing in listings:
        if listing.id is not None:
            result[f"id:{listing.id}"] = listing
        if listing.fingerprint:
            result[f"fp:{listing.fingerprint}"] = listing
    return result


def has_pair(row: dict[str, Any]) -> bool:
    return (
        row.get("status") == "ok"
        and row.get("variant_results", {}).get(BASELINE, {}).get("ape_pct") is not None
        and row.get("variant_results", {}).get(CHALLENGER, {}).get("ape_pct") is not None
    )


def baseline_ape(row: dict[str, Any]) -> float | None:
    return row["variant_results"][BASELINE]["ape_pct"]


def challenger_ape(row: dict[str, Any]) -> float | None:
    return row["variant_results"][CHALLENGER]["ape_pct"]


def row_key(row: dict[str, Any]) -> str:
    if row.get("listing_id") is not None:
        return f"id:{row['listing_id']}"
    return f"fp:{row.get('fingerprint')}"


def stable_hash_bucket(value: str, seed: int) -> int:
    digest = hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def rounded_mean(values: Sequence[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return round(mean(clean), 4) if clean else None


def rounded_percentile(values: Sequence[float | None], pct_value: float) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return round(percentile(clean, pct_value), 4) if clean else None


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


def pop_stddev(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    avg = mean(values)
    return (sum((value - avg) ** 2 for value in values) / len(values)) ** 0.5


def pct(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator) * 100, 2) if denominator else 0.0


def regression_risk(metrics: dict[str, Any]) -> str:
    delta = metrics.get("delta_mape_pct")
    p90_base = metrics.get("baseline_p90_ape_pct")
    p90_challenger = metrics.get("challenger_p90_ape_pct")
    if delta is not None and delta < -0.3:
        return "mape_regression"
    if p90_base is not None and p90_challenger is not None and p90_challenger > p90_base + 1.0:
        return "tail_regression"
    return "ok"


def as_iso(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds")


async def latest_uf_rate(session) -> Decimal | None:
    result = await session.execute(select(UFRateORM).order_by(UFRateORM.date.desc()).limit(1))
    row = result.scalar_one_or_none()
    return Decimal(row.value_clp) if row is not None else None


def write_outputs(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / OUTPUT_JSON
    md_path = output_dir / OUTPUT_MD
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    temporal = report["temporal_split"]
    hash_report = report["hash_splits"]
    lines = [
        "# Comparable Quality v2 Holdout Validation",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Executive Summary",
        "",
        f"- Scope: `{summary['property_type']}`",
        f"- Evaluations: `{summary['successful_evaluations']}`",
        f"- Baseline MAPE: `{summary['baseline_mape_pct']}`",
        f"- Challenger: `{summary['challenger']}` MAPE `{summary['challenger_mape_pct']}`",
        f"- Delta MAPE: `{summary['delta_mape_pct']}` pts ({summary['improvement_class']})",
        f"- P90 baseline/challenger: `{summary['baseline_p90_pct']}` / `{summary['challenger_p90_pct']}`",
        f"- Temporal newer holdout delta: `{temporal.get('holdout_newer', {}).get('delta_mape_pct')}`",
        f"- Hash holdout mean delta: `{hash_report['mean_delta_mape_pct']}` "
        f"(std `{hash_report['delta_stddev_pct']}`)",
        f"- Decision: `{report['recommendation']['decision']}`",
        "",
        "## Temporal Fields",
        "",
        f"- Chosen split field: `{report['available_temporal_fields']['chosen_temporal_split_field']}`",
        f"- Domain listing fields: `{report['available_temporal_fields']['domain_listing_fields']}`",
        f"- ORM fields: `{report['available_temporal_fields']['orm_fields_available']}`",
        f"- Limitations: `{report['available_temporal_fields']['limitations']}`",
        "",
        "## Temporal Split",
        "",
        "| Cohort | n | Baseline MAPE | Challenger MAPE | Delta | Baseline P90 | Challenger P90 | Improved | Worsened |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key in ("older_train", "holdout_newer"):
        row = temporal.get(key, {})
        lines.append(
            f"| `{key}` | {row.get('evaluations')} | {row.get('baseline_mape_pct')} | "
            f"{row.get('challenger_mape_pct')} | {row.get('delta_mape_pct')} | "
            f"{row.get('baseline_p90_ape_pct')} | {row.get('challenger_p90_ape_pct')} | "
            f"{row.get('improved_count')} | {row.get('worsened_count')} |"
        )
    lines.extend(
        [
            "",
            "## Hash Splits",
            "",
            "| Seed | Holdout n | Baseline MAPE | Challenger MAPE | Delta | P90 Delta |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for split in hash_report["splits"]:
        row = split["holdout30"]
        p90_delta = None
        if row["baseline_p90_ape_pct"] is not None and row["challenger_p90_ape_pct"] is not None:
            p90_delta = round(row["baseline_p90_ape_pct"] - row["challenger_p90_ape_pct"], 4)
        lines.append(
            f"| {split['seed']} | {row['evaluations']} | {row['baseline_mape_pct']} | "
            f"{row['challenger_mape_pct']} | {row['delta_mape_pct']} | {p90_delta} |"
        )
    lines.extend(["", "## Critical Comunas", ""])
    lines.append("| Comuna | n | Baseline MAPE | Challenger MAPE | Delta | P90 Base | P90 Challenger | Risk |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for row in report["cohorts"]["critical_comunas"]:
        lines.append(
            f"| `{row['name']}` | {row['evaluations']} | {row['baseline_mape_pct']} | "
            f"{row['challenger_mape_pct']} | {row['delta_mape_pct']} | "
            f"{row['baseline_p90_ape_pct']} | {row['challenger_p90_ape_pct']} | `{row['regression_risk']}` |"
        )
    lines.extend(["", "## Cohorts", ""])
    for section, rows in (
        ("Surface", report["cohorts"]["by_surface_m2"]),
        ("Baseline Error", report["cohorts"]["by_baseline_error"]),
        ("Comparable Quality", report["cohorts"]["by_comparable_quality"]),
    ):
        lines.extend([f"### {section}", ""])
        lines.append("| Cohort | n | Baseline MAPE | Challenger MAPE | Delta | Baseline P90 | Challenger P90 |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for row in rows:
            lines.append(
                f"| `{row['name']}` | {row['evaluations']} | {row['baseline_mape_pct']} | "
                f"{row['challenger_mape_pct']} | {row['delta_mape_pct']} | "
                f"{row['baseline_p90_ape_pct']} | {row['challenger_p90_ape_pct']} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Regressions",
            "",
            f"- Worsened cases: `{report['regressions']['worsened_count']}`",
            f"- Top regression cases in JSON: `{len(report['regressions']['top_regressions'])}`",
            f"- Cohorts where P90 worsens: `{[row['name'] for row in report['regressions']['cohorts_where_p90_worsens']]}`",
            "",
            "## Explicit Answers",
            "",
        ]
    )
    for key, value in report["answers"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"- Decision: `{report['recommendation']['decision']}`",
            f"- Why: {report['recommendation']['why']}",
            f"- Guardrails: `{report['recommendation']['guardrails']}`",
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
            f"- `{report['production_safety']}`",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
