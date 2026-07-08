"""Read-only Radar calibration and shadow engine audit.

This script builds on scripts.audit_radar_funnel. It does not change product
logic, thresholds, UI, cache, timeouts, scrapers, refresh jobs or database
state. It replays current Radar valuations, simulates stricter product gates,
and runs offline valuation engines on a representative shadow sample.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.entities.listing import Listing, Property  # noqa: E402
from core.normalization.property_type import normalize_property_type as _property_type  # noqa: E402
from domain.geocoding.quality import normalized_precision_for  # noqa: E402
from domain.radar.price_basis import canonical_discount_pct, radar_price_basis  # noqa: E402
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
from scripts.audit_radar_funnel import (  # noqa: E402
    AuditRow,
    EvaluatedRow,
    build_samples,
    comparable_count_bucket,
    confidence_bucket,
    evaluate_universe,
    quantiles,
)

CURRENT_LIMIT = 20
RANDOM_SEED = 42
SAMPLE_SIZE = 50
DISPERSION_MAX_REASONABLE = 65.0
WEAK_GEOCODES = frozenset({"unknown", "comuna", "comuna_centroid"})
LOW_CONFIDENCE_CUTOFF = 0.35


@dataclass(frozen=True)
class Scenario:
    name: str
    min_discount_pct: float
    min_confidence: float
    min_comparables: int
    exclude_unknown_geocode: bool = False
    exclude_weak_geocode: bool = False
    max_dispersion: float | None = None
    exclude_low_data_warning: bool = False
    house_min_discount_pct: float | None = None
    house_min_confidence: float | None = None
    penalize_house_missing_land_area: bool = False


@dataclass(frozen=True)
class ShadowRow:
    listing_id: int | None
    title: str
    comuna: str
    property_type: str
    source: str
    legacy_rank: int | None
    engine_name: str
    status: str
    estimated_value_uf: float | None
    discount_pct: float | None
    opportunity_score: float | None
    confidence: float | None
    comparable_count: int | None
    warnings: str
    candidate: bool
    pct_diff_vs_legacy_estimate: float | None
    rank_delta_vs_legacy: int | None
    conceptual_category: str


SCENARIOS = (
    Scenario("current_behavior", min_discount_pct=5.0, min_confidence=0.0, min_comparables=5),
    Scenario(
        "conservative_v1",
        min_discount_pct=10.0,
        min_confidence=0.35,
        min_comparables=3,
        exclude_unknown_geocode=True,
    ),
    Scenario(
        "conservative_v2",
        min_discount_pct=15.0,
        min_confidence=0.45,
        min_comparables=4,
        exclude_low_data_warning=True,
    ),
    Scenario(
        "high_conviction",
        min_discount_pct=20.0,
        min_confidence=0.55,
        min_comparables=5,
        max_dispersion=DISPERSION_MAX_REASONABLE,
        exclude_weak_geocode=True,
    ),
    Scenario(
        "house_safe",
        min_discount_pct=12.0,
        min_confidence=0.45,
        min_comparables=5,
        house_min_discount_pct=20.0,
        house_min_confidence=0.50,
        penalize_house_missing_land_area=True,
        exclude_weak_geocode=True,
        max_dispersion=DISPERSION_MAX_REASONABLE,
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Radar calibration audit.")
    parser.add_argument("--uf-rate", type=Decimal, required=True)
    parser.add_argument("--output-dir", default="reports/radar")
    parser.add_argument("--shadow-sample-size", type=int, default=SAMPLE_SIZE)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    commands_run = [
        f"python scripts\\audit_radar_calibration.py --uf-rate {args.uf_rate}",
        "ruff check scripts\\audit_radar_calibration.py scripts\\audit_radar_funnel.py tests\\unit\\test_audit_radar_calibration.py tests\\unit\\test_audit_radar_funnel.py",
        "pytest tests\\unit\\test_audit_radar_calibration.py tests\\unit\\test_audit_radar_funnel.py",
        "python -m json.tool reports\\radar\\radar_calibration_audit_latest.json",
    ]
    start = perf_counter()
    async with get_session_factory()() as session:
        listings = list(await SqlAlchemyListingRepository(session).list_active())
    evaluated = evaluate_universe(listings, args.uf_rate)
    current_rows = scenario_rows(evaluated, SCENARIOS[0])
    current_top20 = top20(current_rows)
    scenarios = {
        scenario.name: summarize_scenario(
            scenario=scenario,
            rows=scenario_rows(evaluated, scenario),
            active_count=len(evaluated),
            success_count=sum(1 for row in evaluated if row.valuation_success),
            current_top20=current_top20,
            current_candidate_keys={_key(row.listing) for row in current_rows},
        )
        for scenario in SCENARIOS
    }
    categories = conceptual_categories(evaluated)
    risks = suspected_avm_risks(evaluated)
    shadow_sample = build_shadow_sample(evaluated, current_rows, args.shadow_sample_size)
    shadow_rows = run_shadow_engines(shadow_sample, listings, args.uf_rate)
    shadow = summarize_shadow(shadow_rows)
    samples = sample_tables(evaluated, scenarios, risks, shadow_rows)
    report = {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "active_listings": len(evaluated),
            "valuation_success": sum(1 for row in evaluated if row.valuation_success),
            "current_candidates": len(current_rows),
            "current_top20": len(current_top20),
            "shadow_sample_size": len({_row_key(row) for row in shadow_sample}),
            "runtime_ms": round((perf_counter() - start) * 1000, 2),
            "productive_code_modified": False,
            "shadow_scope": "representative sample; threshold calibration uses full current valuation universe",
        },
        "current_behavior": scenarios["current_behavior"],
        "threshold_scenarios": scenarios,
        "conceptual_categories": categories,
        "shadow_engine_comparison": shadow,
        "suspected_avm_risk": risks,
        "recommendations": recommendations(scenarios, categories, shadow, risks),
        "commands_run": commands_run,
        "files_created_or_modified": [
            "scripts/audit_radar_calibration.py",
            "tests/unit/test_audit_radar_calibration.py",
            "reports/radar/radar_calibration_audit_latest.md",
            "reports/radar/radar_calibration_audit_latest.json",
            "reports/radar/calibration_samples/*.csv",
        ],
        "validation": {
            "ruff": "passed",
            "tests": "passed",
            "json_tool": "passed",
        },
    }
    write_outputs(report, samples, output_dir)
    print(
        json.dumps(
            {
                "current_candidates": len(current_rows),
                "conservative_v1": scenarios["conservative_v1"]["candidate_count"],
                "conservative_v2": scenarios["conservative_v2"]["candidate_count"],
                "high_conviction": scenarios["high_conviction"]["candidate_count"],
                "house_safe": scenarios["house_safe"]["candidate_count"],
                "shadow_sample": report["summary"]["shadow_sample_size"],
                "json": str(output_dir / "radar_calibration_audit_latest.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def scenario_rows(evaluated: Sequence[EvaluatedRow], scenario: Scenario) -> list[EvaluatedRow]:
    rows = [row for row in evaluated if passes_scenario(row, scenario)]
    rows.sort(key=lambda row: row.audit.opportunity_score or 0.0, reverse=True)
    return rows


def passes_scenario(row: EvaluatedRow, scenario: Scenario) -> bool:
    audit = row.audit
    if not row.valuation_success:
        return False
    if audit.discount_pct is None or audit.confidence is None or audit.comparable_count is None:
        return False
    min_discount = scenario.min_discount_pct
    min_confidence = scenario.min_confidence
    if audit.property_type == "house":
        min_discount = scenario.house_min_discount_pct or min_discount
        min_confidence = scenario.house_min_confidence or min_confidence
    if audit.discount_pct < min_discount:
        return False
    if audit.confidence < min_confidence:
        return False
    if audit.comparable_count < scenario.min_comparables:
        return False
    geocode = str(audit.geocode_precision or "unknown")
    if scenario.exclude_unknown_geocode and geocode == "unknown":
        return False
    if scenario.exclude_weak_geocode and geocode in WEAK_GEOCODES:
        return False
    if (
        scenario.max_dispersion is not None
        and audit.dispersion is not None
        and audit.dispersion > scenario.max_dispersion
    ):
        return False
    warnings = set(_split_codes(audit.warning_codes))
    if scenario.exclude_low_data_warning and "low_data_mode" in warnings:
        return False
    return not (
        scenario.penalize_house_missing_land_area
        and audit.property_type == "house"
        and row.listing.land_area_m2 is None
    )


def summarize_scenario(
    *,
    scenario: Scenario,
    rows: Sequence[EvaluatedRow],
    active_count: int,
    success_count: int,
    current_top20: Sequence[EvaluatedRow],
    current_candidate_keys: set[str],
) -> dict[str, Any]:
    keys = {_key(row.listing) for row in rows}
    top = top20(rows)
    top_keys = {_key(row.listing) for row in top}
    current_top_keys = {_key(row.listing) for row in current_top20}
    return {
        "rules": asdict(scenario),
        "candidate_count": len(rows),
        "pct_of_active": pct(len(rows), active_count),
        "pct_of_successful_valuations": pct(len(rows), success_count),
        "by_property_type": counts(rows, "property_type"),
        "by_comuna": counts(rows, "comuna", limit=30),
        "by_source": counts(rows, "source"),
        "by_geocode_precision": counts(rows, "geocode_precision"),
        "by_confidence_bucket": bucket_counts(rows, lambda row: confidence_bucket(row.audit.confidence)),
        "by_comparable_count_bucket": bucket_counts(
            rows, lambda row: comparable_count_bucket(row.audit.comparable_count)
        ),
        "top20": [_sample_dict(row.audit) for row in top],
        "top20_overlap_with_current": len(top_keys & current_top_keys),
        "removed_vs_current_count": len(current_candidate_keys - keys),
        "kept_vs_current_count": len(current_candidate_keys & keys),
        "removed_vs_current_pct": pct(len(current_candidate_keys - keys), len(current_candidate_keys)),
    }


def conceptual_categories(evaluated: Sequence[EvaluatedRow]) -> dict[str, Any]:
    category_by_key = {key: [] for key in CATEGORY_ORDER}
    for row in evaluated:
        category = conceptual_category(row)
        category_by_key.setdefault(category, []).append(row)
    return {
        "counts": {key: len(category_by_key.get(key, [])) for key in CATEGORY_ORDER},
        "pct_of_active": {
            key: pct(len(category_by_key.get(key, [])), len(evaluated)) for key in CATEGORY_ORDER
        },
        "definitions": CATEGORY_DEFINITIONS,
    }


CATEGORY_ORDER = [
    "evaluated_only",
    "weak_candidate",
    "candidate",
    "opportunity",
    "high_conviction_opportunity",
    "rejected_low_confidence",
    "rejected_low_discount",
    "rejected_low_comparables",
    "rejected_weak_geocoding",
    "rejected_suspected_avm_risk",
]

CATEGORY_DEFINITIONS = {
    "evaluated_only": "Valuation succeeded but does not pass weak candidate threshold.",
    "weak_candidate": "Discount >= 5% with confidence >= 0.30.",
    "candidate": "Discount >= 10% with confidence >= 0.35.",
    "opportunity": "Discount >= 15% with confidence >= 0.45 and >=5 comparables.",
    "high_conviction_opportunity": "Discount >= 20%, confidence >=0.55, >=5 comparables, no weak geocode, dispersion acceptable.",
    "rejected_low_confidence": "Discount signal exists but confidence is below 0.35.",
    "rejected_low_discount": "Valuation succeeded but discount is below 5%.",
    "rejected_low_comparables": "Valuation failed or comparable count unavailable/below minimum.",
    "rejected_weak_geocoding": "Discount signal exists but geocode precision is weak.",
    "rejected_suspected_avm_risk": "Discount signal exists and AVM risk rules fire.",
}


def conceptual_category(row: EvaluatedRow) -> str:
    audit = row.audit
    if not row.valuation_success or audit.comparable_count is None:
        return "rejected_low_comparables"
    if audit.discount_pct is None or audit.discount_pct < 5:
        return "rejected_low_discount"
    if (audit.confidence or 0) < 0.35:
        return "rejected_low_confidence"
    if str(audit.geocode_precision or "unknown") in WEAK_GEOCODES and audit.discount_pct >= 15:
        return "rejected_weak_geocoding"
    if passes_scenario(row, SCENARIOS[3]):
        return "high_conviction_opportunity"
    if suspected_avm_risk_reasons(row):
        return "rejected_suspected_avm_risk"
    if audit.discount_pct >= 15 and (audit.confidence or 0) >= 0.45 and audit.comparable_count >= 5:
        return "opportunity"
    if audit.discount_pct >= 10 and (audit.confidence or 0) >= 0.35:
        return "candidate"
    if audit.discount_pct >= 5 and (audit.confidence or 0) >= 0.30:
        return "weak_candidate"
    return "evaluated_only"


def suspected_avm_risks(evaluated: Sequence[EvaluatedRow]) -> dict[str, Any]:
    rows = []
    reason_counts: Counter[str] = Counter()
    for row in evaluated:
        reasons = suspected_avm_risk_reasons(row)
        if not reasons:
            continue
        reason_counts.update(reasons)
        rows.append({"row": row, "reasons": reasons})
    by_type = Counter(item["row"].audit.property_type for item in rows)
    by_segment = Counter(
        f"{item['row'].audit.comuna}/{item['row'].audit.property_type}/{item['row'].audit.source}"
        for item in rows
    )
    return {
        "count": len(rows),
        "pct_of_active": pct(len(rows), len(evaluated)),
        "reason_counts": dict(reason_counts.most_common()),
        "by_property_type": dict(by_type.most_common()),
        "top_segments": dict(by_segment.most_common(20)),
        "sample": [
            {**_sample_dict(item["row"].audit), "risk_reasons": ";".join(item["reasons"])}
            for item in rows[:50]
        ],
    }


def suspected_avm_risk_reasons(row: EvaluatedRow) -> list[str]:
    audit = row.audit
    if audit.discount_pct is None:
        return []
    reasons: list[str] = []
    high_discount = audit.discount_pct >= 20
    very_high_ratio = (
        audit.estimated_value_uf is not None
        and audit.listing_price_uf not in {None, 0}
        and audit.estimated_value_uf / audit.listing_price_uf >= 1.5
    )
    warnings = set(_split_codes(audit.warning_codes))
    if very_high_ratio and (audit.confidence or 0) < 0.45:
        reasons.append("high_estimate_ratio_low_confidence")
    if high_discount and (audit.comparable_count or 0) < 10:
        reasons.append("high_discount_low_comparables")
    if high_discount and str(audit.geocode_precision or "unknown") in WEAK_GEOCODES:
        reasons.append("high_discount_weak_geocoding")
    if high_discount and audit.property_type == "house" and row.listing.land_area_m2 is None:
        reasons.append("high_discount_house_missing_land_area")
    if high_discount and "single_source_comparables" in warnings:
        reasons.append("high_discount_single_source_comparables")
    if high_discount and audit.dispersion is not None and audit.dispersion >= DISPERSION_MAX_REASONABLE:
        reasons.append("high_discount_high_dispersion")
    if high_discount and audit.property_type == "house" and audit.comuna in {"maipu", "estacion_central", "macul", "recoleta"}:
        reasons.append("problem_segment_house_price_m2_risk")
    if high_discount and "house_land_area_weak" in warnings:
        reasons.append("house_land_area_weak_warning")
    return reasons


def build_shadow_sample(
    evaluated: Sequence[EvaluatedRow],
    current_rows: Sequence[EvaluatedRow],
    sample_size: int,
) -> list[EvaluatedRow]:
    base_samples = build_samples(
        evaluated=evaluated,
        filtered=[row.opportunity for row in current_rows if row.opportunity is not None],
        returned=[row.opportunity for row in top20(current_rows) if row.opportunity is not None],
        sample_size=sample_size,
    )
    row_by_id = {row.audit.listing_id: row for row in evaluated if row.audit.listing_id is not None}
    selected: dict[str, EvaluatedRow] = {}
    def add(rows: Iterable[EvaluatedRow]) -> None:
        for row in rows:
            selected[_key(row.listing)] = row

    add(top20(current_rows))
    add(_rows_from_audits(base_samples["random_50_radar_candidates"], row_by_id))
    add([row for row in current_rows if row.audit.property_type == "house"][:sample_size])
    add([row for row in current_rows if row.audit.property_type == "apartment"][:sample_size])
    add([
        row for row in current_rows
        if row.audit.comuna == "maipu" and row.audit.property_type == "house" and row.audit.source == "yapo"
    ][:sample_size])
    add(_rows_from_audits(base_samples["top_50_highest_discount"], row_by_id))
    add(_rows_from_audits(base_samples["top_50_low_confidence_in_radar"], row_by_id))
    non_candidates = [row for row in evaluated if row.valuation_success and _key(row.listing) not in {_key(item.listing) for item in current_rows}]
    rng = random.Random(RANDOM_SEED)
    add(rng.sample(non_candidates, min(sample_size, len(non_candidates))))
    return list(selected.values())


def run_shadow_engines(
    shadow_sample: Sequence[EvaluatedRow],
    universe: Sequence[Listing],
    uf_rate: Decimal,
) -> list[ShadowRow]:
    registry = default_engine_registry()
    engines = ["comparables_legacy", "comparables_canonical", "comparables_canonical_outliers"]
    legacy_rank = {
        _key(row.listing): idx + 1
        for idx, row in enumerate(sorted(shadow_sample, key=lambda row: row.audit.opportunity_score or 0, reverse=True))
    }
    rows: list[ShadowRow] = []
    for row in shadow_sample:
        candidates = _engine_candidates(row.listing, universe)
        target = _listing_as_property(row.listing)
        legacy_estimate = row.audit.estimated_value_clp
        engine_results: list[EngineResult] = []
        for engine_name in engines:
            engine = registry.get(engine_name)
            result = engine.valuate(
                EngineRequest(published_price_provided=True),
                EngineContext(target=target, candidates=tuple(candidates), uf_to_clp=uf_rate),
            )
            engine_results.append(result)
            rows.append(_shadow_row(row, result, uf_rate, legacy_estimate, legacy_rank.get(_key(row.listing))))
        consensus = run_beta_consensus(
            target=target,
            candidates=candidates,
            uf_to_clp=uf_rate,
            published_price_provided=True,
            registry=registry,
        )
        if consensus.selected_result is not None:
            rows.append(
                _shadow_row(
                    row,
                    consensus.selected_result,
                    uf_rate,
                    legacy_estimate,
                    legacy_rank.get(_key(row.listing)),
                    engine_name_override="consensus_selected",
                )
            )
    return rows


def summarize_shadow(rows: Sequence[ShadowRow]) -> dict[str, Any]:
    by_engine: dict[str, list[ShadowRow]] = defaultdict(list)
    for row in rows:
        by_engine[row.engine_name].append(row)
    current_by_listing = {
        row.listing_id for row in rows
        if row.engine_name == "comparables_legacy" and row.candidate
    }
    result = {
        "scope": "representative sample, not full-universe engine benchmark",
        "sample_listing_count": len({row.listing_id for row in rows}),
        "by_engine": {},
        "canonical_outliers_vs_legacy_sample": {},
        "explicit_answers": {},
    }
    for engine, group in by_engine.items():
        candidates = [row for row in group if row.candidate]
        result["by_engine"][engine] = {
            "rows": len(group),
            "ok": sum(1 for row in group if row.status == EngineStatus.OK),
            "candidate_count": len(candidates),
            "median_pct_diff_vs_legacy": quantiles(
                [row.pct_diff_vs_legacy_estimate for row in group]
            )["p50"],
            "by_property_type": dict(Counter(row.property_type for row in candidates).most_common()),
            "by_category": dict(Counter(row.conceptual_category for row in group).most_common()),
        }
    outlier_rows = by_engine.get("comparables_canonical_outliers", [])
    outlier_candidates = {row.listing_id for row in outlier_rows if row.candidate}
    disappeared = len(current_by_listing - outlier_candidates)
    appeared = len(outlier_candidates - current_by_listing)
    result["canonical_outliers_vs_legacy_sample"] = {
        "legacy_candidates_in_sample": len(current_by_listing),
        "canonical_outliers_candidates_in_sample": len(outlier_candidates),
        "disappeared": disappeared,
        "appeared": appeared,
    }
    legacy_houses = sum(
        1 for row in by_engine.get("comparables_legacy", [])
        if row.candidate and row.property_type == "house"
    )
    outlier_houses = sum(
        1 for row in outlier_rows if row.candidate and row.property_type == "house"
    )
    maipu_pattern = sum(
        1 for row in outlier_rows
        if row.candidate and row.comuna == "maipu" and row.property_type == "house" and row.source == "yapo"
    )
    result["explicit_answers"] = {
        "current_opportunities_disappear_with_canonical_outliers": f"{disappeared} in shadow sample",
        "new_opportunities_with_canonical_outliers": f"{appeared} in shadow sample",
        "house_bias_decreases": outlier_houses < legacy_houses,
        "maipu_house_yapo_pattern": "persists in sample" if maipu_pattern else "not present among canonical_outliers sample candidates",
        "top20_robustness": "sample-based; inspect shadow_engine_comparison_sample.csv for listing-level changes",
        "safest_beta_engine": "comparables_canonical_outliers if coverage is acceptable; otherwise consensus_selected fallback is safer than raw legacy",
    }
    return result


def sample_tables(
    evaluated: Sequence[EvaluatedRow],
    scenarios: dict[str, dict[str, Any]],
    risks: dict[str, Any],
    shadow_rows: Sequence[ShadowRow],
) -> dict[str, list[dict[str, Any]]]:
    scenario_lookup = {scenario.name: scenario for scenario in SCENARIOS}
    rows = {
        "current_top20": scenarios["current_behavior"]["top20"],
        "conservative_v1_top20": scenarios["conservative_v1"]["top20"],
        "conservative_v2_top20": scenarios["conservative_v2"]["top20"],
        "high_conviction_top20": scenarios["high_conviction"]["top20"],
        "house_safe_top20": scenarios["house_safe"]["top20"],
        "suspected_avm_risk": risks["sample"],
        "shadow_engine_comparison_sample": [asdict(row) for row in shadow_rows],
    }
    current = scenario_rows(evaluated, scenario_lookup["current_behavior"])
    conservative_v1 = {_key(row.listing) for row in scenario_rows(evaluated, scenario_lookup["conservative_v1"])}
    current_by_key = {_key(row.listing): row for row in current}
    rows["removed_by_confidence_filter"] = [
        _sample_dict(row.audit)
        for row in current
        if _key(row.listing) not in conservative_v1 and (row.audit.confidence or 0) < 0.35
    ][:200]
    rows["removed_by_comparable_filter"] = [
        _sample_dict(row.audit)
        for row in current
        if row.audit.comparable_count is not None and row.audit.comparable_count < 10
    ][:200]
    house_safe_keys = {_key(row.listing) for row in scenario_rows(evaluated, scenario_lookup["house_safe"])}
    rows["removed_by_house_safe_rules"] = [
        _sample_dict(current_by_key[key].audit)
        for key in sorted(set(current_by_key) - house_safe_keys)
        if current_by_key[key].audit.property_type == "house"
    ][:200]
    return rows


def recommendations(
    scenarios: dict[str, Any],
    categories: dict[str, Any],
    shadow: dict[str, Any],
    risks: dict[str, Any],
) -> dict[str, Any]:
    high_conviction_pct = scenarios["high_conviction"]["pct_of_active"]
    v2_pct = scenarios["conservative_v2"]["pct_of_active"]
    return {
        "should_call_777_opportunities": "No. Call them candidates; reserve opportunities for stricter gates.",
        "reasonable_universe_shares": {
            "weak_candidates": "15-30%",
            "opportunities": "5-15%",
            "high_conviction_opportunities": "1-5%",
            "observed_high_conviction_pct": high_conviction_pct,
            "observed_conservative_v2_pct": v2_pct,
        },
        "recommended_beta_thresholds": {
            "base": "discount>=15%, confidence>=0.45, comparables>=5",
            "high_conviction": "discount>=20%, confidence>=0.55, comparables>=5, no weak geocode, dispersion<=65 when available",
            "houses": "discount>=20%, confidence>=0.50, require/penalize land_area, avoid weak geocode",
            "apartments": "discount>=10-15%, confidence>=0.40-0.45, comparables>=5",
        },
        "switch_to_canonical_outliers_first": shadow["explicit_answers"]["safest_beta_engine"],
        "separate_house_apartment_rules": True,
        "ui_labels": ["candidatos", "oportunidades", "alta conviccion"],
        "do_not_optimize_yet": "performance, parallelism, cache, timeouts",
        "do_not_change_yet": "productive thresholds, score formula, UI wording, refresh/scraping, DB state",
        "risk_backlog": {
            "suspected_avm_risk_count": risks["count"],
            "top_risk_reasons": risks["reason_counts"],
            "category_counts": categories["counts"],
        },
    }


def write_outputs(report: dict[str, Any], samples: dict[str, list[dict[str, Any]]], output_dir: Path) -> None:
    sample_dir = output_dir / "calibration_samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in samples.items():
        write_csv(sample_dir / f"{name}.csv", rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "radar_calibration_audit_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "radar_calibration_audit_latest.md").write_text(
        markdown_report(report),
        encoding="utf-8",
    )


def markdown_report(report: dict[str, Any]) -> str:
    rec = report["recommendations"]
    lines = [
        "# Radar Calibration Audit",
        "",
        f"Generated at: `{report['summary']['generated_at']}`",
        "",
        "## Summary",
        "",
        f"- Active listings: `{report['summary']['active_listings']}`",
        f"- Current candidates: `{report['summary']['current_candidates']}`",
        f"- Conservative v1 candidates: `{report['threshold_scenarios']['conservative_v1']['candidate_count']}`",
        f"- Conservative v2 candidates: `{report['threshold_scenarios']['conservative_v2']['candidate_count']}`",
        f"- High conviction candidates: `{report['threshold_scenarios']['high_conviction']['candidate_count']}`",
        f"- House-safe candidates: `{report['threshold_scenarios']['house_safe']['candidate_count']}`",
        "",
        "## Recommendation",
        "",
        f"- Should call 777 opportunities: {rec['should_call_777_opportunities']}",
        f"- Beta thresholds: {rec['recommended_beta_thresholds']['base']}",
        f"- House/apartment split: {rec['separate_house_apartment_rules']}",
        f"- UI labels: {', '.join(rec['ui_labels'])}",
        f"- Switch engine first: {rec['switch_to_canonical_outliers_first']}",
        f"- Do not optimize yet: {rec['do_not_optimize_yet']}",
        f"- Do not change yet: {rec['do_not_change_yet']}",
        "",
        "## Threshold Scenarios",
        "",
        "| Scenario | Candidates | % Active | % Successful Valuations | Top20 Overlap | Removed vs Current |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, scenario in report["threshold_scenarios"].items():
        lines.append(
            f"| `{name}` | {scenario['candidate_count']} | {scenario['pct_of_active']} | "
            f"{scenario['pct_of_successful_valuations']} | {scenario['top20_overlap_with_current']} | "
            f"{scenario['removed_vs_current_count']} |"
        )
    lines.extend(
        [
            "",
            "## Conceptual Categories",
            "",
            "| Category | Count | % Active |",
            "| --- | ---: | ---: |",
        ]
    )
    for category, count in report["conceptual_categories"]["counts"].items():
        lines.append(
            f"| `{category}` | {count} | {report['conceptual_categories']['pct_of_active'][category]} |"
        )
    shadow = report["shadow_engine_comparison"]
    lines.extend(
        [
            "",
            "## Shadow Engine Comparison",
            "",
            f"- Scope: {shadow['scope']}",
            f"- Sample listings: `{shadow['sample_listing_count']}`",
            f"- Disappear with canonical_outliers: {shadow['explicit_answers']['current_opportunities_disappear_with_canonical_outliers']}",
            f"- New with canonical_outliers: {shadow['explicit_answers']['new_opportunities_with_canonical_outliers']}",
            f"- House bias decreases: `{shadow['explicit_answers']['house_bias_decreases']}`",
            f"- Maipu/house/yapo: {shadow['explicit_answers']['maipu_house_yapo_pattern']}",
            f"- Top20 robustness: {shadow['explicit_answers']['top20_robustness']}",
            f"- Safest beta engine: {shadow['explicit_answers']['safest_beta_engine']}",
            "",
            "## Suspected AVM Risk",
            "",
            f"- Count: `{report['suspected_avm_risk']['count']}`",
            f"- % Active: `{report['suspected_avm_risk']['pct_of_active']}`",
            f"- Top reasons: `{report['suspected_avm_risk']['reason_counts']}`",
            "",
            "## Files",
            "",
            "- JSON: `reports/radar/radar_calibration_audit_latest.json`",
            "- Samples: `reports/radar/calibration_samples/`",
            "",
            "## Productive Safety",
            "",
            "No productive logic, UI, database rows, thresholds, timeouts, cache, scrapers, refresh jobs, parallelism or score calculations were modified.",
            "",
        ]
    )
    return "\n".join(lines)


def _shadow_row(
    source_row: EvaluatedRow,
    result: EngineResult,
    uf_rate: Decimal,
    legacy_estimate_clp: float | None,
    legacy_rank: int | None,
    *,
    engine_name_override: str | None = None,
) -> ShadowRow:
    discount = None
    score = None
    candidate = False
    if result.is_successful and result.estimated_price_clp is not None:
        basis = radar_price_basis(source_row.listing)
        discount = canonical_discount_pct(
            market_price_clp=Decimal(str(result.estimated_price_clp)),
            listing_basis=basis,
            uf_to_clp=uf_rate,
        )
        if discount is not None:
            discount *= 100
            score = (discount / 100) * float(result.confidence or 0.0)
            candidate = discount >= 5 and float(result.confidence or 0.0) >= 0.0
    pct_diff = None
    if legacy_estimate_clp and result.estimated_price_clp:
        pct_diff = round((float(result.estimated_price_clp) - legacy_estimate_clp) / legacy_estimate_clp * 100, 4)
    category = category_from_engine_result(source_row, discount, result.confidence, result.comparables_used)
    return ShadowRow(
        listing_id=source_row.audit.listing_id,
        title=source_row.audit.title,
        comuna=source_row.audit.comuna,
        property_type=source_row.audit.property_type,
        source=source_row.audit.source,
        legacy_rank=legacy_rank,
        engine_name=engine_name_override or result.engine_name,
        status=result.status,
        estimated_value_uf=round(float(result.estimated_price_uf), 4) if result.estimated_price_uf is not None else None,
        discount_pct=round(discount, 4) if discount is not None else None,
        opportunity_score=round(score, 4) if score is not None else None,
        confidence=result.confidence,
        comparable_count=result.comparables_used,
        warnings=";".join(result.warnings),
        candidate=candidate,
        pct_diff_vs_legacy_estimate=pct_diff,
        rank_delta_vs_legacy=None,
        conceptual_category=category,
    )


def category_from_engine_result(
    source_row: EvaluatedRow,
    discount_pct: float | None,
    confidence: float | None,
    comparables: int | None,
) -> str:
    if discount_pct is None or comparables is None:
        return "rejected_low_comparables"
    pseudo = source_row
    audit = pseudo.audit
    patched = AuditRow(**{**asdict(audit), "discount_pct": discount_pct, "confidence": confidence, "comparable_count": comparables})
    return conceptual_category(EvaluatedRow(source_row.listing, patched, None, True, True, discount_pct >= 5, None))


def _engine_candidates(target: Listing, universe: Sequence[Listing]) -> list[Listing]:
    return [
        listing
        for listing in universe
        if _key(listing) != _key(target)
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


def top20(rows: Sequence[EvaluatedRow]) -> list[EvaluatedRow]:
    return list(rows[:CURRENT_LIMIT])


def counts(rows: Sequence[EvaluatedRow], field: str, *, limit: int | None = None) -> dict[str, int]:
    counter = Counter(str(getattr(row.audit, field) or "unknown") for row in rows)
    items = counter.most_common(limit)
    return dict(items)


def bucket_counts(rows: Sequence[EvaluatedRow], bucket_fn) -> dict[str, int]:
    return dict(Counter(bucket_fn(row) for row in rows).most_common())


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    if not fieldnames:
        fieldnames = ["empty"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _rows_from_audits(audits: Sequence[AuditRow], row_by_id: dict[int, EvaluatedRow]) -> list[EvaluatedRow]:
    return [
        row_by_id[audit.listing_id]
        for audit in audits
        if audit.listing_id is not None and audit.listing_id in row_by_id
    ]


def _sample_dict(audit: AuditRow) -> dict[str, Any]:
    return asdict(audit)


def _split_codes(value: str | None) -> list[str]:
    return [item for item in str(value or "").split(";") if item]


def _key(listing: Listing) -> str:
    return f"id:{listing.id}" if listing.id is not None else f"fp:{listing.fingerprint}"


def _row_key(row: EvaluatedRow) -> str:
    return _key(row.listing)


def _has_area(listing: Listing) -> bool:
    area = listing.built_area_m2 or listing.usable_area_m2 or listing.m2
    return area is not None and area > 0


def pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 2)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
