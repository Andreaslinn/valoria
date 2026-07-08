"""Read-only coverage diagnostics for the experimental consensus lab."""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from core.entities.listing import Listing
from core.normalization.property_type import normalize_property_type
from core.ports.uf_service import UFRateInfo
from domain.valuation.engines.contracts import EngineContext
from domain.valuation.engines.experimental_lab import (
    DEFAULT_LAB_ENGINE_NAMES,
    run_experimental_engine_lab,
)
from domain.valuation.evaluation.dataset import build_evaluation_cases, infer_uf_rate
from infrastructure.db.database import get_session_factory
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository
from services.uf_rate import validate_real_uf_rate

OUTPUT_DIR = Path("reports/valuation_engine_benchmark/experimental_consensus_lab")
JSON_REPORT = OUTPUT_DIR / "experimental_consensus_coverage_diagnostic_latest.json"
MD_REPORT = OUTPUT_DIR / "experimental_consensus_coverage_diagnostic_latest.md"
ASKING_PRICE_WARNING = (
    "This diagnostic uses active listings and asking prices; it is not a closed-sale or bank-appraisal benchmark."
)
RECENT_WINDOW_DAYS = 60
PREVIOUS_WINDOW_DAYS = 120
MIN_TREND_WINDOW_COUNT = 3
MIN_LAND_CANDIDATES = 5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit experimental consensus lab coverage")
    parser.add_argument("--uf-rate", default=None)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    async with get_session_factory()() as session:
        repo = SqlAlchemyListingRepository(session)
        listings = list(await repo.list_active(limit=None))

    uf_to_clp = _resolve_uf_rate(args.uf_rate, listings)
    cases_all = build_evaluation_cases(listings, limit=args.limit, seed=args.seed)
    cases_apartment = build_evaluation_cases(listings, limit=args.limit, property_type="apartment", seed=args.seed)
    cases_house = build_evaluation_cases(listings, limit=args.limit, property_type="house", seed=args.seed)
    land_target_cases = _build_land_target_cases(listings, limit=args.limit)

    report = {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "dataset_active_listings": len(listings),
            "uf_to_clp": float(uf_to_clp),
            "uf_rate_source": "cli" if args.uf_rate else "local_listing_price_uf_median",
            "warning": ASKING_PRICE_WARNING,
            "read_only": True,
        },
        "engine_context_mapping": _context_mapping_diagnostic(cases_all[: min(25, len(cases_all))]),
        "land_building_diagnostic": _land_building_diagnostic(listings, cases_house, uf_to_clp),
        "market_trends_diagnostic": _market_trends_diagnostic(listings, cases_all, uf_to_clp),
        "benchmark_segments": {
            "apartment_100": _benchmark_segment(cases_apartment, uf_to_clp),
            "house_100": _benchmark_segment(cases_house, uf_to_clp),
            "houses_with_land_area_targeted": _benchmark_segment(land_target_cases, uf_to_clp),
        },
        "conclusion": {},
    }
    report["conclusion"] = _conclusion(report)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / JSON_REPORT.name
    md_path = output_dir / MD_REPORT.name
    json_path.write_text(json.dumps(_json_safe(report), indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    print(f"Wrote reports: {json_path}, {md_path}")
    return 0


def _context_mapping_diagnostic(cases) -> dict[str, Any]:
    counters = Counter()
    mismatches: list[dict[str, Any]] = []
    for case in cases:
        listing = case.listing
        target = case.target
        fields = {
            "property_type": target.property_type == normalize_property_type(listing),
            "comuna": target.comuna == listing.comuna,
            "built_area_m2": target.built_area_m2 == (listing.built_area_m2 or listing.usable_area_m2 or listing.m2),
            "land_area_m2": target.land_area_m2 == listing.land_area_m2,
            "geocode_precision": target.geocode_precision == listing.geocode_precision,
            "target_has_title_metadata": bool(target.raw_metadata.get("title")),
            "candidate_keeps_price_uf": any(candidate.price_uf is not None for candidate in case.candidates),
            "candidate_keeps_provenance": any(candidate.price_uf_source for candidate in case.candidates),
            "candidate_keeps_dates": any(_observed_at(candidate) is not None for candidate in case.candidates),
        }
        for key, ok in fields.items():
            counters[f"{key}:{ok}"] += 1
        failed = [key for key, ok in fields.items() if not ok and key != "land_area_m2"]
        if failed:
            mismatches.append({"target_id": case.target_id, "failed": failed})
    return {
        "sample_cases": len(cases),
        "field_checks": dict(counters),
        "mismatches": mismatches[:10],
        "interpretation": "EngineContext preserves target/candidate fields required by experimental engines unless mismatches are listed.",
    }


def _land_building_diagnostic(listings: list[Listing], cases, uf_to_clp: Decimal) -> dict[str, Any]:
    houses = [listing for listing in listings if listing.is_active and normalize_property_type(listing) == "house"]
    same_comuna_land_counts = {
        listing.id or idx: _same_comuna_land_candidate_count(listing, listings)
        for idx, listing in enumerate(houses)
    }
    context_counts = Counter()
    reasons = Counter()
    diagnostics = []
    for case in cases:
        run = run_experimental_engine_lab(
            EngineContext(target=case.target, candidates=case.candidates, uf_to_clp=uf_to_clp, metadata=case.metadata),
            engine_names=("land_building_v1",),
            include_consensus=False,
        )
        result = run.engine_results[0]
        reasons[result.error_code or result.status] += 1
        context_counts["cases"] += 1
        if case.target.land_area_m2 and case.target.land_area_m2 > 0:
            context_counts["target_land_area_present"] += 1
        diagnostics.append({
            "target_id": case.target_id,
            "status": result.status,
            "reason": result.error_code,
            "target_land_area_m2": case.target.land_area_m2,
            "candidate_with_land_area_count": result.diagnostics.get("candidates_with_land_area_count"),
            "candidate_without_land_area_count": result.diagnostics.get("candidates_without_land_area_count"),
        })
    return {
        "active_houses_total": len(houses),
        "houses_with_built_area": sum(1 for listing in houses if _positive(listing.built_area_m2 or listing.usable_area_m2 or listing.m2)),
        "houses_with_land_area": sum(1 for listing in houses if _positive(listing.land_area_m2)),
        "houses_with_price_uf": sum(1 for listing in houses if _positive(listing.price_uf)),
        "houses_with_same_comuna_land_candidates_min5": sum(1 for count in same_comuna_land_counts.values() if count >= MIN_LAND_CANDIDATES),
        "engine_context_cases": dict(context_counts),
        "abstention_reasons": dict(reasons),
        "sample_case_diagnostics": diagnostics[:20],
    }


def _market_trends_diagnostic(listings: list[Listing], cases, uf_to_clp: Decimal) -> dict[str, Any]:
    clean = [_trend_clean_listing(listing) for listing in listings if listing.is_active]
    clean = [item for item in clean if item is not None]
    dates = [item["observed_at"] for item in clean]
    reasons = Counter()
    window_counts = Counter()
    sample = []
    for case in cases:
        recent, previous = _trend_windows_for_case(case, clean, by_microzone=False)
        mz_recent, mz_previous = _trend_windows_for_case(case, clean, by_microzone=True)
        if len(recent) >= MIN_TREND_WINDOW_COUNT and len(previous) >= MIN_TREND_WINDOW_COUNT:
            window_counts["comuna_two_windows"] += 1
        if len(mz_recent) >= MIN_TREND_WINDOW_COUNT and len(mz_previous) >= MIN_TREND_WINDOW_COUNT:
            window_counts["microzone_two_windows"] += 1
        run = run_experimental_engine_lab(
            EngineContext(target=case.target, candidates=case.candidates, uf_to_clp=uf_to_clp, metadata=case.metadata),
            engine_names=("market_trends_v1",),
            include_consensus=False,
        )
        result = run.engine_results[0]
        reasons[result.error_code or result.status] += 1
        sample.append({
            "target_id": case.target_id,
            "status": result.status,
            "reason": result.error_code,
            "recent_count": result.diagnostics.get("recent_count"),
            "previous_count": result.diagnostics.get("previous_count"),
            "clean_candidates_count": result.diagnostics.get("clean_candidates_count"),
        })
    return {
        "active_with_usable_date": sum(1 for listing in listings if listing.is_active and _observed_at(listing) is not None),
        "active_with_price_area_date": len(clean),
        "date_min": min(dates).isoformat() if dates else None,
        "date_max": max(dates).isoformat() if dates else None,
        "date_age_buckets": _date_age_buckets(dates),
        "cases_with_two_windows": dict(window_counts),
        "abstention_reasons": dict(reasons),
        "sample_case_diagnostics": sample[:20],
    }


def _benchmark_segment(cases, uf_to_clp: Decimal) -> dict[str, Any]:
    rows = []
    for idx, case in enumerate(cases):
        run = run_experimental_engine_lab(
            EngineContext(target=case.target, candidates=case.candidates, uf_to_clp=uf_to_clp, metadata=case.metadata),
            engine_names=DEFAULT_LAB_ENGINE_NAMES,
            include_consensus=True,
        )
        for result in [*run.engine_results, *([run.consensus_result] if run.consensus_result else [])]:
            signed = _signed_pct_error(result.estimated_price_clp, case.actual_price_clp)
            rows.append({
                "case_id": f"case-{idx}",
                "engine_name": result.engine_name,
                "status": result.status,
                "ape": abs(signed) if signed is not None else None,
                "reason": result.error_code,
            })
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["engine_name"]].append(row)
    return {engine: _summary(group_rows) for engine, group_rows in sorted(grouped.items())}


def _build_land_target_cases(listings: list[Listing], *, limit: int):
    land_ids = {
        listing.id
        for listing in listings
        if listing.is_active
        and normalize_property_type(listing) == "house"
        and _positive(listing.built_area_m2 or listing.usable_area_m2 or listing.m2)
        and _positive(listing.land_area_m2)
        and _positive(listing.price.clp)
    }
    cases = build_evaluation_cases(listings, property_type="house", limit=None, seed=42)
    selected = [case for case in cases if case.listing.id in land_ids]
    return selected[:limit]


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    apes = [float(row["ape"]) for row in rows if row["ape"] is not None]
    statuses = Counter(str(row["status"]) for row in rows)
    return {
        "cases": len(rows),
        "success": len(apes),
        "coverage_pct": round(len(apes) / len(rows) * 100, 2) if rows else 0.0,
        "mape_pct": round(sum(apes) / len(apes), 2) if apes else None,
        "median_ape_pct": round(sorted(apes)[len(apes) // 2], 2) if apes else None,
        "abstained": sum(statuses[status] for status in ("abstained", "insufficient_data", "not_applicable")),
        "failed": sum(statuses[status] for status in ("failed", "error", "validation_error")),
        "top_reasons": dict(Counter(str(row["reason"] or row["status"]) for row in rows if row["ape"] is None).most_common(5)),
    }


def _conclusion(report: dict[str, Any]) -> dict[str, Any]:
    land = report["land_building_diagnostic"]
    trends = report["market_trends_diagnostic"]
    return {
        "land_building_coverage_zero_cause": (
            "data_gap_land_area"
            if land["houses_with_land_area"] == 0
            else "insufficient_same_comuna_land_candidates_or_filters"
        ),
        "market_trends_coverage_zero_cause": (
            "insufficient_two_window_temporal_depth"
            if not trends["cases_with_two_windows"]
            else "engine_context_or_filter_mismatch_possible"
        ),
        "before_weight_calibration": [
            "Do not calibrate consensus weights until land_area coverage and temporal windows are addressed.",
            "Treat current asking-price benchmark as relative signal QA only.",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    land = report["land_building_diagnostic"]
    trends = report["market_trends_diagnostic"]
    conclusion = report["conclusion"]
    return "\n".join([
        "# Experimental Consensus Coverage Diagnostic",
        "",
        f"> **Warning:** {ASKING_PRICE_WARNING}",
        "",
        "## Executive Summary",
        "",
        f"- Active listings: `{report['metadata']['dataset_active_listings']}`.",
        f"- Land/building cause: `{conclusion['land_building_coverage_zero_cause']}`.",
        f"- Market trends cause: `{conclusion['market_trends_coverage_zero_cause']}`.",
        "",
        "## EngineContext Mapping",
        "",
        f"- Sample cases checked: `{report['engine_context_mapping']['sample_cases']}`.",
        f"- Mismatches: `{len(report['engine_context_mapping']['mismatches'])}`.",
        "",
        "## land_building_v1",
        "",
        f"- Active houses: `{land['active_houses_total']}`.",
        f"- Houses with built area: `{land['houses_with_built_area']}`.",
        f"- Houses with land area: `{land['houses_with_land_area']}`.",
        f"- Houses with price UF: `{land['houses_with_price_uf']}`.",
        f"- Houses with >=5 same-comuna land candidates: `{land['houses_with_same_comuna_land_candidates_min5']}`.",
        f"- Abstention reasons: `{land['abstention_reasons']}`.",
        "",
        "## market_trends_v1",
        "",
        f"- Active with usable date: `{trends['active_with_usable_date']}`.",
        f"- Active with price + area + date: `{trends['active_with_price_area_date']}`.",
        f"- Date range: `{trends['date_min']}` to `{trends['date_max']}`.",
        f"- Cases with two windows: `{trends['cases_with_two_windows']}`.",
        f"- Abstention reasons: `{trends['abstention_reasons']}`.",
        "",
        "## Recommendation",
        "",
        "- Do not calibrate weights yet.",
        "- Fix/ingest land_area for houses before expecting land_building_v1 coverage.",
        "- Add historical/temporal depth or price history before expecting market_trends_v1 coverage.",
        "- EngineContext mapping does not appear to be the primary blocker if mismatches are zero/low.",
        "",
    ])


def _trend_clean_listing(listing: Listing) -> dict[str, Any] | None:
    observed_at = _observed_at(listing)
    area = listing.built_area_m2 or listing.usable_area_m2 or listing.m2
    if observed_at is None or not _positive(listing.price_uf) or not _positive(area):
        return None
    return {
        "listing": listing,
        "observed_at": observed_at,
        "property_type": normalize_property_type(listing),
        "comuna": listing.comuna,
        "microzone_id": _microzone_id(listing),
    }


def _trend_windows_for_case(case, clean: list[dict[str, Any]], *, by_microzone: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target_microzone = _microzone_id(case.target)
    candidates = [
        item
        for item in clean
        if item["property_type"] == case.target.property_type
        and item["comuna"] == case.target.comuna
        and (not by_microzone or (target_microzone and item["microzone_id"] == target_microzone))
    ]
    if not candidates:
        return [], []
    anchor = max(item["observed_at"] for item in candidates)
    recent_cutoff = anchor - timedelta(days=60)
    previous_cutoff = recent_cutoff - timedelta(days=120)
    recent = [item for item in candidates if item["observed_at"] >= recent_cutoff]
    previous = [item for item in candidates if previous_cutoff <= item["observed_at"] < recent_cutoff]
    return recent, previous


def _same_comuna_land_candidate_count(target: Listing, listings: list[Listing]) -> int:
    return sum(
        1
        for candidate in listings
        if candidate.is_active
        and candidate is not target
        and normalize_property_type(candidate) == "house"
        and candidate.comuna == target.comuna
        and _positive(candidate.land_area_m2)
        and _positive(candidate.built_area_m2 or candidate.usable_area_m2 or candidate.m2)
        and _positive(candidate.price_uf)
        and candidate.price_uf_source != "legacy_unrecoverable"
    )


def _observed_at(listing: Listing) -> datetime | None:
    for value in (
        getattr(listing, "last_seen_at", None),
        getattr(listing, "scraped_at", None),
        (getattr(listing, "raw_metadata", None) or {}).get("observed_at"),
        (getattr(listing, "raw_metadata", None) or {}).get("created_at"),
        (getattr(listing, "raw_metadata", None) or {}).get("updated_at"),
    ):
        parsed = _datetime_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _date_age_buckets(dates: list[datetime]) -> dict[str, int]:
    if not dates:
        return {}
    anchor = max(dates)
    return {
        "0_30_days": sum(1 for item in dates if (anchor - item).days <= 30),
        "31_60_days": sum(1 for item in dates if 30 < (anchor - item).days <= 60),
        "61_180_days": sum(1 for item in dates if 60 < (anchor - item).days <= 180),
        "older": sum(1 for item in dates if (anchor - item).days > 180),
    }


def _microzone_id(value: object | None) -> str | None:
    metadata = getattr(value, "raw_metadata", None) or {}
    if isinstance(metadata, dict):
        for key in ("microzone_id", "microzone", "microzone_key", "subcomuna", "neighborhood"):
            if metadata.get(key):
                return str(metadata[key])
    return None


def _positive(value: Any) -> bool:
    try:
        return value is not None and Decimal(str(value)) > 0
    except Exception:
        return False


def _signed_pct_error(estimate: Decimal | None, actual: Decimal) -> float | None:
    if estimate is None or actual <= 0:
        return None
    return float((estimate - actual) / actual * Decimal("100"))


def _resolve_uf_rate(raw: str | None, listings) -> Decimal:
    if raw:
        try:
            value = Decimal(str(raw))
        except InvalidOperation as exc:
            raise SystemExit(f"Invalid --uf-rate: {raw}") from exc
    else:
        value = infer_uf_rate(listings)
        if value is None:
            raise SystemExit("Could not infer UF rate from local listings; pass --uf-rate")
    validate_real_uf_rate(UFRateInfo(rate=value, source="cli_or_local_data", is_fallback=False))
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
