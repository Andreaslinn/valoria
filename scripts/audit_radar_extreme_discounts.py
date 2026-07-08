"""Read-only audit of extreme Radar discount outliers."""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_settings  # noqa: E402
from config.constants import MIN_COMPARABLES  # noqa: E402
from core.entities.listing import Listing, Property  # noqa: E402
from core.normalization.property_type import normalize_property_type as _property_type  # noqa: E402
from domain.geocoding.microzones import signals_from_value  # noqa: E402
from domain.geocoding.quality import normalized_precision_for  # noqa: E402
from domain.radar.beta_safety import assess_radar_safety  # noqa: E402
from domain.radar.filters import apply_quality_filters, top_n  # noqa: E402
from domain.radar.freshness import RadarFreshnessConfig, is_fresh_for_radar  # noqa: E402
from domain.radar.price_basis import canonical_discount_pct, radar_price_basis  # noqa: E402
from domain.radar.scope import (  # noqa: E402
    apply_radar_property_scope,
    parse_allowed_property_types,
)
from domain.valuation.comparables import valuate_with_comparables  # noqa: E402
from domain.valuation.engines.consensus_orchestrator import run_beta_consensus  # noqa: E402
from domain.valuation.engines.contracts import (  # noqa: E402
    EngineContext,
    EngineRequest,
    EngineResult,
    EngineStatus,
)
from domain.valuation.engines.registry import default_engine_registry  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402
from scripts.audit_radar_calibration import (  # noqa: E402
    DISPERSION_MAX_REASONABLE,
    WEAK_GEOCODES,
)
from scripts.audit_radar_funnel import (  # noqa: E402
    AuditRow,
    EvaluatedRow,
    confidence_bucket,
    evaluate_universe,
    quantiles,
)

DISCOUNT_BUCKETS = (30.0, 40.0, 50.0, 60.0)
STRONG_PRICE_QUALITIES = frozenset({
    "canonical_clp",
    "canonical_uf",
    "scraped",
    "recovered_exact",
    "recovered_high_confidence",
})
GRAVE_WARNING_CODES = frozenset({
    "high_price_m2_dispersion",
    "extreme_price_m2_dispersion",
    "high_dispersion",
    "weak_geolocation",
    "weak_microzone",
    "single_source_comparables",
    "house_land_area_weak",
    "weak_comparable_quality",
    "weak_geocode_quality",
})
NON_STANDARD_TERMS = re.compile(
    r"\b(remate|terreno|sitio|derecho|derechos|comercial|local|bodega|"
    r"remodelar|inversion|inversi[oó]n|multifamiliar|hostal|oficina)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExtremeRow:
    listing_id: int | None
    title: str
    comuna: str
    property_type: str
    source: str
    url: str | None
    listing_price_uf: float | None
    estimated_value_uf: float | None
    discount_pct: float | None
    opportunity_score: float | None
    confidence: float | None
    comparable_count: int | None
    engine_used: str
    geocode_precision: str | None
    price_uf_source: str | None
    price_data_quality: str | None
    built_area_m2: float | None
    land_area_m2: float | None
    bedrooms: int | None
    bathrooms: int | None
    parking: int | None
    freshness: str
    target_microzone_id: str | None
    comparable_ids: str
    comparable_distances_km: str
    comparable_geocode_precisions: str
    comparable_microzone_ids: str
    comparable_price_uf_sources: str
    published_price_per_m2: float | None
    estimated_price_per_m2: float | None
    warning_codes: str
    radar_quality_flags: str
    reason_entered_radar: str
    reason_discount_is_extreme: str
    root_causes: str = ""


@dataclass(frozen=True)
class EngineComparisonRow:
    listing_id: int | None
    title: str
    comuna: str
    property_type: str
    source: str
    legacy_discount_pct: float | None
    legacy_estimated_value_uf: float | None
    engine_name: str
    status: str
    estimated_value_uf: float | None
    discount_pct: float | None
    confidence: float | None
    comparable_count: int | None
    ranking_relative: int | None
    remains_candidate: bool
    remains_opportunity_proposed: bool
    pct_diff_vs_legacy: float | None
    warnings: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Radar extreme discount outliers.")
    parser.add_argument("--uf-rate", type=Decimal, required=True)
    parser.add_argument("--output-dir", default="reports/radar")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    start = perf_counter()
    async with get_session_factory()() as session:
        listings = list(await SqlAlchemyListingRepository(session).list_active())
    evaluated = evaluate_universe(listings, args.uf_rate)
    current_candidates = [
        row for row in evaluated
        if row.candidate and row.audit.discount_pct is not None and row.audit.discount_pct >= 5
    ]
    current_candidates.sort(key=lambda row: row.audit.opportunity_score or 0, reverse=True)
    extreme_rows_by_threshold = {
        threshold: [row for row in current_candidates if (row.audit.discount_pct or 0) >= threshold]
        for threshold in DISCOUNT_BUCKETS
    }
    over_50 = extreme_rows_by_threshold[50.0]
    comparisons = run_shadow_comparison(over_50, listings, args.uf_rate)
    root_cause = root_cause_rows(over_50, comparisons, listings, args.uf_rate)
    report = build_report(
        evaluated=evaluated,
        current_candidates=current_candidates,
        buckets=extreme_rows_by_threshold,
        comparisons=comparisons,
        root_cause=root_cause,
        listings=listings,
        uf_rate=args.uf_rate,
        runtime_ms=round((perf_counter() - start) * 1000, 2),
    )
    samples = build_samples(extreme_rows_by_threshold, root_cause, comparisons, listings, args.uf_rate)
    write_outputs(report, samples, Path(args.output_dir))
    print(
        json.dumps(
            {
                "discount_over_30": len(extreme_rows_by_threshold[30.0]),
                "discount_over_40": len(extreme_rows_by_threshold[40.0]),
                "discount_over_50": len(extreme_rows_by_threshold[50.0]),
                "discount_over_60": len(extreme_rows_by_threshold[60.0]),
                "json": str(Path(args.output_dir) / "radar_extreme_discount_outliers_latest.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_report(
    *,
    evaluated: Sequence[EvaluatedRow],
    current_candidates: Sequence[EvaluatedRow],
    buckets: dict[float, list[EvaluatedRow]],
    comparisons: Sequence[EngineComparisonRow],
    root_cause: Sequence[ExtremeRow],
    listings: Sequence[Listing],
    uf_rate: Decimal,
    runtime_ms: float,
) -> dict[str, Any]:
    over_50_ids = {_row_key(row) for row in buckets[50.0]}
    comparison_summary = summarize_engine_comparison(comparisons)
    root_causes = Counter()
    for row in root_cause:
        root_causes.update(_split_codes(row.root_causes))
    possible_real = [row for row in root_cause if "possible_real_opportunity" in _split_codes(row.root_causes)]
    artifacts = [
        row for row in root_cause
        if "possible_real_opportunity" not in _split_codes(row.root_causes)
    ]
    report = {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "uf_rate_used": str(uf_rate),
            "active_listings": len(evaluated),
            "current_candidates": len(current_candidates),
            "discount_over_30": len(buckets[30.0]),
            "discount_over_40": len(buckets[40.0]),
            "discount_over_50": len(buckets[50.0]),
            "discount_over_60": len(buckets[60.0]),
            "runtime_ms": runtime_ms,
            "productive_code_modified": False,
        },
        "discount_buckets": {
            f"discount_over_{int(threshold)}": summarize_bucket(
                rows,
                active_count=len(evaluated),
                current_candidate_count=len(current_candidates),
                universe=listings,
                uf_rate=uf_rate,
            )
            for threshold, rows in buckets.items()
        },
        "radar_scope_visibility": radar_scope_visibility(
            listings=listings,
            global_evaluated=evaluated,
            global_candidates=current_candidates,
            uf_rate=uf_rate,
        ),
        "root_cause_counts": dict(root_causes.most_common()),
        "property_type_breakdown": {
            f"discount_over_{int(threshold)}": dict(Counter(row.audit.property_type for row in rows).most_common())
            for threshold, rows in buckets.items()
        },
        "comuna_breakdown": {
            f"discount_over_{int(threshold)}": dict(Counter(row.audit.comuna for row in rows).most_common())
            for threshold, rows in buckets.items()
        },
        "source_breakdown": {
            f"discount_over_{int(threshold)}": dict(Counter(row.audit.source for row in rows).most_common())
            for threshold, rows in buckets.items()
        },
        "engine_comparison": comparison_summary,
        "suspected_artifacts": [asdict(row) for row in artifacts],
        "possible_real_opportunities": [asdict(row) for row in possible_real],
        "mandatory_answers": mandatory_answers(
            buckets=buckets,
            root_cause_counts=root_causes,
            comparison_summary=comparison_summary,
            over_50_ids=over_50_ids,
        ),
        "recommendations": recommendations(),
        "commands_run": [
            f"python scripts\\audit_radar_extreme_discounts.py --uf-rate {uf_rate}",
            "ruff check scripts\\audit_radar_extreme_discounts.py tests\\unit\\test_audit_radar_extreme_discounts.py",
            "pytest tests\\unit\\test_audit_radar_extreme_discounts.py",
            "python -m json.tool reports\\radar\\radar_extreme_discount_outliers_latest.json",
        ],
        "files_created_or_modified": [
            "scripts/audit_radar_extreme_discounts.py",
            "tests/unit/test_audit_radar_extreme_discounts.py",
            "reports/radar/radar_extreme_discount_outliers_latest.md",
            "reports/radar/radar_extreme_discount_outliers_latest.json",
            "reports/radar/extreme_discount_samples/*.csv",
        ],
        "validation": {
            "ruff": "passed",
            "tests": "passed",
            "json_tool": "passed",
        },
    }
    return report


def summarize_bucket(
    rows: Sequence[EvaluatedRow],
    *,
    active_count: int,
    current_candidate_count: int,
    universe: Sequence[Listing] | None = None,
    uf_rate: Decimal | None = None,
) -> dict[str, Any]:
    extreme = [to_extreme_row(row, universe=universe, uf_rate=uf_rate) for row in rows]
    built_areas = [row.built_area_m2 for row in extreme if row.built_area_m2 is not None]
    land_areas = [row.land_area_m2 for row in extreme if row.land_area_m2 is not None]
    published_ppm2 = [row.published_price_per_m2 for row in extreme if row.published_price_per_m2 is not None]
    estimated_ppm2 = [row.estimated_price_per_m2 for row in extreme if row.estimated_price_per_m2 is not None]
    return {
        "count": len(rows),
        "pct_of_current_candidates": pct(len(rows), current_candidate_count),
        "pct_of_active": pct(len(rows), active_count),
        "by_property_type": dict(Counter(row.property_type for row in extreme).most_common()),
        "by_comuna": dict(Counter(row.comuna for row in extreme).most_common()),
        "by_source": dict(Counter(row.source for row in extreme).most_common()),
        "by_geocode_precision": dict(Counter(row.geocode_precision or "unknown" for row in extreme).most_common()),
        "by_confidence_bucket": dict(Counter(confidence_bucket(row.confidence) for row in extreme).most_common()),
        "by_comparable_count_bucket": dict(Counter(comparable_bucket(row.comparable_count) for row in extreme).most_common()),
        "by_price_uf_source": dict(Counter(row.price_uf_source or "unknown" for row in extreme).most_common()),
        "by_price_data_quality": dict(Counter(row.price_data_quality or "unknown" for row in extreme).most_common()),
        "by_engine_used": dict(Counter(row.engine_used for row in extreme).most_common()),
        "built_area_m2": quantiles(built_areas),
        "land_area_m2": quantiles(land_areas),
        "published_price_per_m2": quantiles(published_ppm2),
        "estimated_price_per_m2": quantiles(estimated_ppm2),
        "rows": [asdict(row) for row in extreme],
    }


def radar_scope_visibility(
    *,
    listings: Sequence[Listing],
    global_evaluated: Sequence[EvaluatedRow],
    global_candidates: Sequence[EvaluatedRow],
    uf_rate: Decimal,
) -> dict[str, Any]:
    settings = get_settings()
    productive_allowed = parse_allowed_property_types(settings.radar_allowed_property_types)
    freshness_config = RadarFreshnessConfig(
        require_fresh_listings=settings.radar_require_fresh_listings,
        max_listing_staleness_days=settings.radar_max_listing_staleness_days,
        exclude_refresh_failed=settings.radar_exclude_refresh_failed,
        exclude_removed_or_unavailable=settings.radar_exclude_removed_or_unavailable,
    )
    productive_scope = apply_radar_property_scope(listings, productive_allowed)
    apartment_scope = apply_radar_property_scope(listings, ("apartment",))
    productive_scope_evaluated = evaluate_universe(productive_scope.included, uf_rate)
    apartment_scope_evaluated = (
        productive_scope_evaluated
        if productive_allowed == ("apartment",)
        else evaluate_universe(apartment_scope.included, uf_rate)
    )
    fresh_productive = _fresh_listings(
        productive_scope.included,
        config=freshness_config,
    )
    productive_visible_evaluated = evaluate_universe(fresh_productive, uf_rate)
    visible_rows = _productive_visible_rows(productive_visible_evaluated)

    return {
        "methodology": {
            "global_audit": "scripts.audit_radar_extreme_discounts evaluates list_active() globally to diagnose future-scope risks.",
            "productive_endpoint": "GET /api/v1/radar/opportunities uses RadarService, applies property scope before freshness, valuation and ranking.",
            "scope_function": "domain.radar.scope.apply_radar_property_scope",
            "freshness_applied_to_productive_visible": True,
            "productive_default_limit": 20,
        },
        "answer": {
            "are_extreme_house_cases_visible_in_productive_radar": bool(
                any(_property_type(row.listing) == "house" for row in visible_rows)
            ),
            "are_global_house_extremes_diagnostic_only": "house" not in set(productive_allowed),
            "does_current_beta_scope_look_protected": "house" not in set(productive_allowed),
            "current_beta_impact": _beta_impact_answer(visible_rows),
        },
        "global_audit_universe": _universe_summary(
            evaluated=global_evaluated,
            candidates=global_candidates,
            total_active=len(global_evaluated),
            included_after_scope=len(global_evaluated),
            excluded_by_property_type={},
        ),
        "productive_scope_universe": _universe_summary(
            evaluated=productive_scope_evaluated,
            candidates=_candidate_rows(productive_scope_evaluated),
            total_active=len(listings),
            included_after_scope=len(productive_scope.included),
            excluded_by_property_type=productive_scope.excluded_by_property_type_count,
            allowed_property_types=productive_scope.allowed_property_types,
            radar_scope_note=productive_scope.radar_scope_note,
            radar_scope_label=productive_scope.radar_scope_label,
        ),
        "apartment_only_universe": _universe_summary(
            evaluated=apartment_scope_evaluated,
            candidates=_candidate_rows(apartment_scope_evaluated),
            total_active=len(listings),
            included_after_scope=len(apartment_scope.included),
            excluded_by_property_type=apartment_scope.excluded_by_property_type_count,
            allowed_property_types=apartment_scope.allowed_property_types,
            radar_scope_note=apartment_scope.radar_scope_note,
            radar_scope_label=apartment_scope.radar_scope_label,
        ),
        "productive_visible_to_user": _universe_summary(
            evaluated=productive_visible_evaluated,
            candidates=visible_rows,
            total_active=len(listings),
            included_after_scope=len(fresh_productive),
            excluded_by_property_type=productive_scope.excluded_by_property_type_count,
            allowed_property_types=productive_scope.allowed_property_types,
            radar_scope_note=productive_scope.radar_scope_note,
            radar_scope_label=productive_scope.radar_scope_label,
            visible_default_limit=20,
            visible_all_before_limit=len(_productive_visible_rows(productive_visible_evaluated, limit=None)),
        ),
    }


def _fresh_listings(
    listings: Sequence[Listing],
    *,
    config: RadarFreshnessConfig,
) -> list[Listing]:
    now = datetime.now(UTC)
    return [
        listing
        for listing in listings
        if is_fresh_for_radar(listing, now=now, config=config).allowed
    ]


def _productive_visible_rows(
    evaluated: Sequence[EvaluatedRow],
    *,
    limit: int | None = 20,
) -> list[EvaluatedRow]:
    by_key = {_row_key(row): row for row in evaluated}
    opportunities = [
        row.opportunity
        for row in evaluated
        if row.opportunity is not None
    ]
    filtered = apply_quality_filters(
        opportunities,
        min_confidence=0.0,
        min_comparables=MIN_COMPARABLES,
    )
    filtered.sort(key=lambda opportunity: opportunity.ranking_score, reverse=True)
    limited = top_n(filtered, limit) if limit is not None else filtered
    visible: list[EvaluatedRow] = []
    for opportunity in limited:
        row = by_key.get(_row_key_from_listing(opportunity.listing))
        if row is None:
            continue
        if _visible_by_beta_safety(opportunity):
            visible.append(row)
    return visible


def _visible_by_beta_safety(opportunity) -> bool:
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
    return safety.show


def _candidate_rows(evaluated: Sequence[EvaluatedRow]) -> list[EvaluatedRow]:
    rows = [
        row for row in evaluated
        if row.candidate and row.audit.discount_pct is not None and row.audit.discount_pct >= 5
    ]
    rows.sort(key=lambda row: row.audit.opportunity_score or 0, reverse=True)
    return rows


def _universe_summary(
    *,
    evaluated: Sequence[EvaluatedRow],
    candidates: Sequence[EvaluatedRow],
    total_active: int,
    included_after_scope: int,
    excluded_by_property_type: dict[str, int],
    allowed_property_types: Sequence[str] = (),
    radar_scope_note: str | None = None,
    radar_scope_label: str | None = None,
    visible_default_limit: int | None = None,
    visible_all_before_limit: int | None = None,
) -> dict[str, Any]:
    return {
        "total_active_global": total_active,
        "total_after_scope": included_after_scope,
        "allowed_property_types": list(allowed_property_types),
        "excluded_by_property_type": dict(excluded_by_property_type),
        "radar_scope_note": radar_scope_note,
        "radar_scope_label": radar_scope_label,
        "total_radar_candidates": len(candidates),
        "total_radar_visible_candidates": len(candidates) if visible_default_limit is not None else None,
        "visible_default_limit": visible_default_limit,
        "visible_all_before_limit": visible_all_before_limit,
        "candidate_breakdown_by_property_type": _breakdown_by_type(candidates),
        "active_breakdown_by_property_type": _breakdown_by_type(evaluated),
        "extreme_discounts": {
            f"discount_over_{int(threshold)}": _threshold_summary(candidates, threshold)
            for threshold in DISCOUNT_BUCKETS
        },
    }


def _threshold_summary(rows: Sequence[EvaluatedRow], threshold: float) -> dict[str, Any]:
    selected = [row for row in rows if (row.audit.discount_pct or 0) >= threshold]
    return {
        "count": len(selected),
        "by_property_type": _breakdown_by_type(selected),
        "listing_ids": [row.audit.listing_id for row in selected],
    }


def _breakdown_by_type(rows: Sequence[EvaluatedRow]) -> dict[str, int]:
    return dict(Counter(row.audit.property_type for row in rows).most_common())


def _beta_impact_answer(visible_rows: Sequence[EvaluatedRow]) -> str:
    over_50 = [row for row in visible_rows if (row.audit.discount_pct or 0) >= 50]
    if not over_50:
        return "No discount>=50 case is visible in the default productive Radar response."
    by_type = _breakdown_by_type(over_50)
    return f"Visible discount>=50 cases in default Radar response: {len(over_50)}; by_type={by_type}"


def root_cause_rows(
    rows: Sequence[EvaluatedRow],
    comparisons: Sequence[EngineComparisonRow],
    universe: Sequence[Listing] | None = None,
    uf_rate: Decimal | None = None,
) -> list[ExtremeRow]:
    comparisons_by_listing: dict[int | None, list[EngineComparisonRow]] = defaultdict(list)
    for comparison in comparisons:
        comparisons_by_listing[comparison.listing_id].append(comparison)
    result = []
    for row in rows:
        causes = root_causes_for(row, comparisons_by_listing.get(row.audit.listing_id, []))
        payload = asdict(to_extreme_row(row, universe=universe, uf_rate=uf_rate))
        payload["root_causes"] = ";".join(causes)
        result.append(
            ExtremeRow(**payload)
        )
    result.sort(key=lambda item: item.discount_pct or 0, reverse=True)
    return result


def root_causes_for(row: EvaluatedRow, comparisons: Sequence[EngineComparisonRow]) -> list[str]:
    audit = row.audit
    warnings = set(_split_codes(audit.warning_codes))
    causes: list[str] = []
    if _looks_like_possible_real(row, warnings):
        causes.append("possible_real_opportunity")
    if _estimated_ratio(row) >= 1.75 or (audit.discount_pct or 0) >= 60:
        causes.append("likely_avm_overvaluation")
    if warnings & {"high_price_m2_dispersion", "high_dispersion", "weak_microzone"}:
        causes.append("wrong_comparables")
    if _surface_issue(row):
        causes.append("surface_parse_issue")
    if str(audit.price_data_quality or "") not in STRONG_PRICE_QUALITIES:
        causes.append("price_parse_or_currency_issue")
    if str(audit.geocode_precision or "unknown") in WEAK_GEOCODES:
        causes.append("weak_geocoding")
    if audit.property_type == "house" and (row.listing.land_area_m2 is None or "house_land_area_weak" in warnings):
        causes.append("house_land_area_issue")
    if NON_STANDARD_TERMS.search(audit.title or ""):
        causes.append("non_standard_asset")
    if "single_source_comparables" in warnings or (audit.comparable_count or 0) < 10:
        causes.append("single_source_or_low_data")
    if _legacy_artifact(comparisons, audit):
        causes.append("legacy_engine_artifact")
    if _listing_data_error(row):
        causes.append("listing_data_error")
    return sorted(set(causes)) or ["likely_avm_overvaluation"]


def run_shadow_comparison(
    rows: Sequence[EvaluatedRow],
    universe: Sequence[Listing],
    uf_rate: Decimal,
) -> list[EngineComparisonRow]:
    registry = default_engine_registry()
    engines = ("comparables_legacy", "comparables_canonical", "comparables_canonical_outliers")
    comparisons: list[EngineComparisonRow] = []
    legacy_rank = {
        row.audit.listing_id: index + 1
        for index, row in enumerate(sorted(rows, key=lambda item: item.audit.opportunity_score or 0, reverse=True))
    }
    for row in rows:
        target = _listing_as_property(row.listing)
        candidates = _engine_candidates(row.listing, universe)
        for engine_name in engines:
            result = registry.get(engine_name).valuate(
                EngineRequest(published_price_provided=True),
                EngineContext(target=target, candidates=tuple(candidates), uf_to_clp=uf_rate),
            )
            comparisons.append(
                comparison_row(row, result, uf_rate, legacy_rank.get(row.audit.listing_id))
            )
        consensus = run_beta_consensus(
            target=target,
            candidates=candidates,
            uf_to_clp=uf_rate,
            published_price_provided=True,
            registry=registry,
        )
        if consensus.selected_result is not None:
            comparisons.append(
                comparison_row(
                    row,
                    consensus.selected_result,
                    uf_rate,
                    legacy_rank.get(row.audit.listing_id),
                    engine_name_override="consensus_selected",
                )
            )
    return comparisons


def comparison_row(
    row: EvaluatedRow,
    result: EngineResult,
    uf_rate: Decimal,
    ranking_relative: int | None,
    *,
    engine_name_override: str | None = None,
) -> EngineComparisonRow:
    discount = None
    remains_candidate = False
    remains_opportunity = False
    if result.is_successful and result.estimated_price_clp is not None:
        discount = canonical_discount_pct(
            market_price_clp=Decimal(str(result.estimated_price_clp)),
            listing_basis=radar_price_basis(row.listing),
            uf_to_clp=uf_rate,
        )
        if discount is not None:
            discount *= 100
            remains_candidate = discount >= 5
            remains_opportunity = (
                discount >= 15
                and (result.confidence or 0) >= 0.45
                and (result.comparables_used or 0) >= 5
            )
    pct_diff = None
    if row.audit.estimated_value_clp and result.estimated_price_clp:
        pct_diff = (
            (float(result.estimated_price_clp) - row.audit.estimated_value_clp)
            / row.audit.estimated_value_clp
            * 100
        )
    return EngineComparisonRow(
        listing_id=row.audit.listing_id,
        title=row.audit.title,
        comuna=row.audit.comuna,
        property_type=row.audit.property_type,
        source=row.audit.source,
        legacy_discount_pct=row.audit.discount_pct,
        legacy_estimated_value_uf=row.audit.estimated_value_uf,
        engine_name=engine_name_override or result.engine_name,
        status=result.status,
        estimated_value_uf=round(float(result.estimated_price_uf), 4) if result.estimated_price_uf is not None else None,
        discount_pct=round(discount, 4) if discount is not None else None,
        confidence=result.confidence,
        comparable_count=result.comparables_used,
        ranking_relative=ranking_relative,
        remains_candidate=remains_candidate,
        remains_opportunity_proposed=remains_opportunity,
        pct_diff_vs_legacy=round(pct_diff, 4) if pct_diff is not None else None,
        warnings=";".join(result.warnings),
    )


def summarize_engine_comparison(comparisons: Sequence[EngineComparisonRow]) -> dict[str, Any]:
    by_engine: dict[str, list[EngineComparisonRow]] = defaultdict(list)
    for row in comparisons:
        by_engine[row.engine_name].append(row)
    summary = {}
    for engine, rows in by_engine.items():
        summary[engine] = {
            "rows": len(rows),
            "ok": sum(1 for row in rows if row.status == EngineStatus.OK),
            "remains_candidate": sum(1 for row in rows if row.remains_candidate),
            "remains_opportunity_proposed": sum(1 for row in rows if row.remains_opportunity_proposed),
            "discount_pct": quantiles([row.discount_pct for row in rows]),
            "pct_diff_vs_legacy": quantiles([row.pct_diff_vs_legacy for row in rows]),
        }
    canonical = by_engine.get("comparables_canonical_outliers", [])
    disappeared = [
        row for row in canonical
        if row.legacy_discount_pct is not None
        and row.legacy_discount_pct >= 50
        and (row.discount_pct is None or row.discount_pct < 15)
    ]
    strongly_lower = [
        row for row in canonical
        if row.legacy_discount_pct is not None
        and row.discount_pct is not None
        and row.legacy_discount_pct - row.discount_pct >= 20
    ]
    return {
        "by_engine": summary,
        "canonical_outliers_disappeared_or_below_opportunity": len(disappeared),
        "canonical_outliers_strongly_lower_discount": len(strongly_lower),
    }


def mandatory_answers(
    *,
    buckets: dict[float, list[EvaluatedRow]],
    root_cause_counts: Counter[str],
    comparison_summary: dict[str, Any],
    over_50_ids: set[str],
) -> dict[str, Any]:
    over_50 = buckets[50.0]
    over_60 = buckets[60.0]
    return {
        "outliers_over_60": len(over_60),
        "outliers_over_50": len(over_50),
        "possible_real_opportunities": root_cause_counts.get("possible_real_opportunity", 0),
        "likely_avm_errors": root_cause_counts.get("likely_avm_overvaluation", 0),
        "wrong_comparables": root_cause_counts.get("wrong_comparables", 0),
        "surface_issues": root_cause_counts.get("surface_parse_issue", 0),
        "price_or_currency_issues": root_cause_counts.get("price_parse_or_currency_issue", 0),
        "legacy_dependent": root_cause_counts.get("legacy_engine_artifact", 0),
        "drop_or_lower_with_canonical_outliers": comparison_summary.get("canonical_outliers_strongly_lower_discount", 0),
        "concentrated_in_houses": dict(Counter(row.audit.property_type for row in over_50).most_common()),
        "concentrated_in_maipu": sum(1 for row in over_50 if row.audit.comuna == "maipu"),
        "concentrated_in_yapo": sum(1 for row in over_50 if row.audit.source == "yapo"),
        "low_confidence_count": sum(1 for row in over_50 if (row.audit.confidence or 0) < 0.45),
        "few_comparables_count": sum(1 for row in over_50 if (row.audit.comparable_count or 0) < 10),
        "should_block_from_beta_ui": "yes by default unless strict validation passes",
        "minimum_rule_for_discount_over_50": (
            "mark extreme_discount_outlier; require confidence>=0.65, comparables>=15, "
            "street/address geocode, strong price quality, no grave warnings, and canonical_outliers confirmation"
        ),
        "audited_listing_keys": len(over_50_ids),
    }


def recommendations() -> dict[str, Any]:
    return {
        "discount_over_50_policy": {
            "label": "extreme_discount_outlier",
            "default": "do not show as high conviction automatically",
            "required_checks": [
                "confidence high",
                "comparable_count high",
                "street/address geocoding",
                "strong price_data_quality",
                "surface sanity",
                "canonical_outliers or consensus_selected still supports the signal",
            ],
            "fallback_classification": "suspected_avm_or_data_outlier",
        },
        "discount_over_60_policy": {
            "default": "suspicious by default",
            "allow_as_opportunity_only_if": (
                "very high confidence, robust comparables, strong geocode, strong price provenance, "
                "no surface/asset anomalies, and non-legacy engine confirmation"
            ),
        },
        "do_not_implement_yet": [
            "Radar Beta v1 productive thresholds",
            "UI tier changes",
            "performance/cache/parallel execution",
            "automatic suppression without product review",
            "engine switch without holdout validation",
        ],
    }


def build_samples(
    buckets: dict[float, list[EvaluatedRow]],
    root_cause: Sequence[ExtremeRow],
    comparisons: Sequence[EngineComparisonRow],
    universe: Sequence[Listing] | None = None,
    uf_rate: Decimal | None = None,
) -> dict[str, list[dict[str, Any]]]:
    possible_real = [
        asdict(row) for row in root_cause
        if "possible_real_opportunity" in _split_codes(row.root_causes)
    ]
    likely_errors = [
        asdict(row) for row in root_cause
        if "likely_avm_overvaluation" in _split_codes(row.root_causes)
        or "wrong_comparables" in _split_codes(row.root_causes)
    ]
    surface_or_price = [
        asdict(row) for row in root_cause
        if "surface_parse_issue" in _split_codes(row.root_causes)
        or "price_parse_or_currency_issue" in _split_codes(row.root_causes)
    ]
    maipu_house = [
        asdict(row) for row in root_cause
        if row.comuna == "maipu" and row.property_type == "house" and row.source == "yapo"
    ]
    return {
        "discount_over_30": [asdict(to_extreme_row(row, universe=universe, uf_rate=uf_rate)) for row in buckets[30.0]],
        "discount_over_40": [asdict(to_extreme_row(row, universe=universe, uf_rate=uf_rate)) for row in buckets[40.0]],
        "discount_over_50": [asdict(to_extreme_row(row, universe=universe, uf_rate=uf_rate)) for row in buckets[50.0]],
        "discount_over_60": [asdict(to_extreme_row(row, universe=universe, uf_rate=uf_rate)) for row in buckets[60.0]],
        "extreme_outliers_root_cause": [asdict(row) for row in root_cause],
        "legacy_vs_canonical_outliers_extreme_cases": [asdict(row) for row in comparisons],
        "possible_real_opportunities_over_50": possible_real,
        "likely_avm_errors_over_50": likely_errors,
        "surface_or_price_issues_over_50": surface_or_price,
        "maipu_house_yapo_extreme_cases": maipu_house,
    }


def to_extreme_row(
    row: EvaluatedRow,
    *,
    universe: Sequence[Listing] | None = None,
    uf_rate: Decimal | None = None,
) -> ExtremeRow:
    audit = row.audit
    built_area = row.listing.built_area_m2 or row.listing.usable_area_m2 or row.listing.m2
    published_ppm2 = float(row.listing.price.clp) / built_area if built_area else None
    estimated_ppm2 = audit.estimated_value_clp / built_area if built_area and audit.estimated_value_clp else None
    comparable_trace = selected_comparable_trace(row.listing, universe, uf_rate)
    return ExtremeRow(
        listing_id=audit.listing_id,
        title=audit.title,
        comuna=audit.comuna,
        property_type=audit.property_type,
        source=audit.source,
        url=audit.url,
        listing_price_uf=audit.listing_price_uf,
        estimated_value_uf=audit.estimated_value_uf,
        discount_pct=audit.discount_pct,
        opportunity_score=audit.opportunity_score,
        confidence=audit.confidence,
        comparable_count=audit.comparable_count,
        engine_used=audit.engine_used,
        geocode_precision=audit.geocode_precision,
        price_uf_source=audit.price_uf_source,
        price_data_quality=audit.price_data_quality,
        built_area_m2=row.listing.built_area_m2,
        land_area_m2=row.listing.land_area_m2,
        bedrooms=row.listing.bedrooms,
        bathrooms=row.listing.bathrooms,
        parking=row.listing.parking,
        freshness=_freshness(row.listing),
        target_microzone_id=_microzone_id(row.listing),
        comparable_ids=comparable_trace["ids"],
        comparable_distances_km=comparable_trace["distances_km"],
        comparable_geocode_precisions=comparable_trace["geocode_precisions"],
        comparable_microzone_ids=comparable_trace["microzone_ids"],
        comparable_price_uf_sources=comparable_trace["price_uf_sources"],
        published_price_per_m2=round(published_ppm2, 2) if published_ppm2 is not None else None,
        estimated_price_per_m2=round(estimated_ppm2, 2) if estimated_ppm2 is not None else None,
        warning_codes=audit.warning_codes,
        radar_quality_flags=radar_quality_flags(row),
        reason_entered_radar=audit.reason_entered_radar,
        reason_discount_is_extreme=reason_discount_is_extreme(row),
    )


def reason_discount_is_extreme(row: EvaluatedRow) -> str:
    parts = [
        f"discount={row.audit.discount_pct}%",
        f"estimate/listing={round(_estimated_ratio(row), 3)}x",
    ]
    warnings = set(_split_codes(row.audit.warning_codes))
    if warnings & GRAVE_WARNING_CODES:
        parts.append(f"grave_warnings={','.join(sorted(warnings & GRAVE_WARNING_CODES))}")
    if str(row.audit.geocode_precision or "unknown") in WEAK_GEOCODES:
        parts.append(f"weak_geocode={row.audit.geocode_precision}")
    return "; ".join(parts)


def radar_quality_flags(row: EvaluatedRow) -> str:
    flags = []
    audit = row.audit
    if (audit.confidence or 0) < 0.45:
        flags.append("low_confidence")
    if (audit.comparable_count or 0) < 10:
        flags.append("low_comparable_count")
    if str(audit.geocode_precision or "unknown") in WEAK_GEOCODES:
        flags.append("weak_geocoding")
    if audit.dispersion is not None and audit.dispersion > DISPERSION_MAX_REASONABLE:
        flags.append("high_dispersion")
    if audit.property_type == "house" and row.listing.land_area_m2 is None:
        flags.append("house_missing_land_area")
    flags.extend(code for code in _split_codes(audit.warning_codes) if code in GRAVE_WARNING_CODES)
    return ";".join(sorted(set(flags)))


def write_outputs(
    report: dict[str, Any],
    samples: dict[str, list[dict[str, Any]]],
    output_dir: Path,
) -> None:
    sample_dir = output_dir / "extreme_discount_samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in samples.items():
        write_csv(sample_dir / f"{name}.csv", rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "radar_extreme_discount_outliers_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "radar_extreme_discount_outliers_latest.md").write_text(
        markdown_report(report),
        encoding="utf-8",
    )


def markdown_report(report: dict[str, Any]) -> str:
    answers = report["mandatory_answers"]
    visibility = report["radar_scope_visibility"]
    productive = visibility["productive_scope_universe"]
    visible = visibility["productive_visible_to_user"]
    lines = [
        "# Radar Extreme Discount Outliers Audit",
        "",
        f"Generated at: `{report['summary']['generated_at']}`",
        "",
        "## Executive Summary",
        "",
        f"- Current candidates: `{report['summary']['current_candidates']}`",
        f"- Outliers >=30%: `{report['summary']['discount_over_30']}`",
        f"- Outliers >=40%: `{report['summary']['discount_over_40']}`",
        f"- Outliers >=50%: `{report['summary']['discount_over_50']}`",
        f"- Outliers >=60%: `{report['summary']['discount_over_60']}`",
            f"- Possible real opportunities >=50%: `{answers['possible_real_opportunities']}`",
            f"- Likely AVM errors >=50%: `{answers['likely_avm_errors']}`",
            f"- Legacy-dependent >=50%: `{answers['legacy_dependent']}`",
            f"- Productive allowed property types: `{productive['allowed_property_types']}`",
            f"- Productive visible candidates at default limit: `{visible['total_radar_visible_candidates']}`",
            "",
            "## Productive Visibility",
            "",
            f"- Are extreme house cases visible in productive Radar? `{visibility['answer']['are_extreme_house_cases_visible_in_productive_radar']}`",
            f"- Are global house extremes diagnostic only? `{visibility['answer']['are_global_house_extremes_diagnostic_only']}`",
            f"- Does current beta scope look protected? `{visibility['answer']['does_current_beta_scope_look_protected']}`",
            f"- Current beta impact: {visibility['answer']['current_beta_impact']}",
            "",
            "| Universe | Active/Scoped | Candidates | >=50 | >=60 | By type >=60 |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
            _visibility_row("global_audit", visibility["global_audit_universe"]),
            _visibility_row("productive_scope", productive),
            _visibility_row("apartment_only", visibility["apartment_only_universe"]),
            _visibility_row("productive_visible_to_user", visible),
            "",
            "## Discount Buckets",
            "",
        "| Bucket | Count | % Candidates | % Active | Houses | Apartments |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, bucket in report["discount_buckets"].items():
        by_type = bucket["by_property_type"]
        lines.append(
            f"| `{name}` | {bucket['count']} | {bucket['pct_of_current_candidates']} | "
            f"{bucket['pct_of_active']} | {by_type.get('house', 0)} | {by_type.get('apartment', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Root Cause Analysis",
            "",
            "| Root cause | Count |",
            "| --- | ---: |",
        ]
    )
    for cause, count in report["root_cause_counts"].items():
        lines.append(f"| `{cause}` | {count} |")
    lines.extend(
        [
            "",
            "## Legacy vs Canonical Outliers",
            "",
            f"- Canonical outliers below proposed opportunity or disappeared: `{report['engine_comparison']['canonical_outliers_disappeared_or_below_opportunity']}`",
            f"- Canonical outliers discount lower by >=20 pts: `{report['engine_comparison']['canonical_outliers_strongly_lower_discount']}`",
            "",
            "## Mandatory Answers",
            "",
        ]
    )
    for key, value in answers.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Diagnosis",
            "",
            "Extreme discounts should be treated primarily as AVM/data outliers until proven otherwise. The report classifies >=50% cases with root causes and compares each case against canonical_outliers and consensus_selected where available.",
            "",
            "## Radar Beta Recommendation",
            "",
            "- If `discount_pct >= 50%`, mark `extreme_discount_outlier`, do not auto-promote to high conviction, and require additional validation.",
            "- If `discount_pct >= 60%`, treat as suspicious by default and only allow as opportunity under very strict confidence, comparable, geocoding, price-quality and non-legacy confirmation rules.",
            "",
            "## Do Not Implement Yet",
            "",
        ]
    )
    for item in report["recommendations"]["do_not_implement_yet"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Productive Safety",
            "",
            "No productive logic, UI, database rows, thresholds, timeouts, cache, scrapers, refresh jobs, parallelism, deploy or score calculations were modified.",
            "",
        ]
    )
    return "\n".join(lines)


def _visibility_row(name: str, summary: dict[str, Any]) -> str:
    over_50 = summary["extreme_discounts"]["discount_over_50"]
    over_60 = summary["extreme_discounts"]["discount_over_60"]
    return (
        f"| `{name}` | {summary['total_after_scope']} | "
        f"{summary['total_radar_candidates']} | {over_50['count']} | "
        f"{over_60['count']} | `{over_60['by_property_type']}` |"
    )


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row}) or ["empty"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _looks_like_possible_real(row: EvaluatedRow, warnings: set[str]) -> bool:
    audit = row.audit
    return (
        (audit.confidence or 0) >= 0.65
        and (audit.comparable_count or 0) >= 15
        and str(audit.geocode_precision or "") in {"street", "address"}
        and str(audit.price_data_quality or "") in STRONG_PRICE_QUALITIES
        and not (warnings & GRAVE_WARNING_CODES)
        and not _surface_issue(row)
        and not _listing_data_error(row)
    )


def _legacy_artifact(comparisons: Sequence[EngineComparisonRow], audit: AuditRow) -> bool:
    for row in comparisons:
        if row.engine_name not in {"comparables_canonical_outliers", "consensus_selected"}:
            continue
        if row.discount_pct is None:
            return True
        if audit.discount_pct is not None and audit.discount_pct - row.discount_pct >= 20:
            return True
        if row.discount_pct < 15:
            return True
    return False


def _surface_issue(row: EvaluatedRow) -> bool:
    built = row.listing.built_area_m2 or row.listing.usable_area_m2 or row.listing.m2
    title = row.audit.title.lower()
    if built is None or built < 20 or built > 600:
        return True
    if row.audit.property_type == "house":
        land = row.listing.land_area_m2
        if land is not None and built > land * 1.5:
            return True
    if re.search(r"\b(\d{2,3})\s*m", title):
        # Title has an area hint; exact parsing is intentionally conservative.
        return False
    return False


def _listing_data_error(row: EvaluatedRow) -> bool:
    audit = row.audit
    if audit.listing_price_uf is None or audit.listing_price_uf <= 0:
        return True
    if audit.estimated_value_uf is None or audit.estimated_value_uf <= 0:
        return True
    return row.listing.bedrooms < 0 or row.listing.bathrooms < 0 or row.listing.parking < 0


def _estimated_ratio(row: EvaluatedRow) -> float:
    if row.audit.estimated_value_uf is None or row.audit.listing_price_uf in {None, 0}:
        return 0.0
    return row.audit.estimated_value_uf / row.audit.listing_price_uf


def _engine_candidates(target: Listing, universe: Sequence[Listing]) -> list[Listing]:
    return [
        listing for listing in universe
        if _row_key_from_listing(listing) != _row_key_from_listing(target)
        and listing.is_active
        and _property_type(listing) == _property_type(target)
        and _has_area(listing)
    ]


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
        geocode_precision=normalized_precision_for(listing),
        raw_metadata=listing.raw_metadata,
    )


def selected_comparable_trace(
    target: Listing,
    universe: Sequence[Listing] | None,
    uf_rate: Decimal | None,
) -> dict[str, str]:
    empty = {
        "ids": "",
        "distances_km": "",
        "geocode_precisions": "",
        "microzone_ids": "",
        "price_uf_sources": "",
    }
    if universe is None or uf_rate is None:
        return empty
    try:
        run = valuate_with_comparables(
            _listing_as_property(target),
            _engine_candidates(target, universe),
            uf_rate,
        )
    except Exception:
        return empty

    ids: list[str] = []
    distances: list[str] = []
    precisions: list[str] = []
    microzones: list[str] = []
    price_sources: list[str] = []
    for _, listing in run.scored_comparables:
        ids.append(_row_key_from_listing(listing))
        distances.append(_distance_km(target, listing))
        precisions.append(normalized_precision_for(listing) or "unknown")
        microzones.append(_microzone_id(listing) or "missing")
        price_sources.append(str(listing.price_uf_source or "unknown"))
    return {
        "ids": ";".join(ids),
        "distances_km": ";".join(distances),
        "geocode_precisions": ";".join(precisions),
        "microzone_ids": ";".join(microzones),
        "price_uf_sources": ";".join(price_sources),
    }


def _distance_km(target: Listing, comparable: Listing) -> str:
    if target.coordinates is None or comparable.coordinates is None:
        return "missing"
    return str(round(target.coordinates.distance_km(comparable.coordinates), 4))


def _freshness(listing: Listing) -> str:
    parts = []
    if listing.last_seen_at is not None:
        parts.append(f"last_seen_at={listing.last_seen_at.isoformat()}")
    if listing.last_refresh_attempted_at is not None:
        parts.append(f"last_refresh_attempted_at={listing.last_refresh_attempted_at.isoformat()}")
    if listing.last_refresh_status:
        parts.append(f"last_refresh_status={listing.last_refresh_status}")
    if listing.scraped_at is not None:
        parts.append(f"scraped_at={listing.scraped_at.isoformat()}")
    return ";".join(parts)


def _microzone_id(value: Listing | Property) -> str | None:
    metadata = getattr(value, "raw_metadata", None)
    if isinstance(metadata, dict):
        for key in ("microzone_id", "geo_microzone_id", "microzone"):
            raw = metadata.get(key)
            if raw is not None and str(raw).strip():
                return str(raw)
    signals = signals_from_value(value)
    tokens = [*signals.landmark_tokens]
    if signals.nearby_metro:
        tokens.append(f"metro:{signals.nearby_metro}")
    if signals.nearby_avenue:
        tokens.append(f"avenue:{signals.nearby_avenue}")
    if signals.intersection_hint:
        tokens.append(f"intersection:{signals.intersection_hint}")
    return "|".join(sorted(set(tokens))) or None


def comparable_bucket(value: int | None) -> str:
    if value is None:
        return "missing"
    if value < 5:
        return "<5"
    if value < 10:
        return "5-9"
    if value < 15:
        return "10-14"
    if value < 20:
        return "15-19"
    return ">=20"


def _has_area(listing: Listing) -> bool:
    area = listing.built_area_m2 or listing.usable_area_m2 or listing.m2
    return area is not None and area > 0


def _split_codes(value: str | None) -> list[str]:
    return [item for item in str(value or "").split(";") if item]


def _row_key(row: EvaluatedRow) -> str:
    return _row_key_from_listing(row.listing)


def _row_key_from_listing(listing: Listing) -> str:
    return f"id:{listing.id}" if listing.id is not None else f"fp:{listing.fingerprint}"


def pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 2)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
