"""Read-only strategy audit for future valuation model engines.

This module quantifies whether ML, house-land-building and consensus work is
worth implementing. It deliberately does not train, register or run new engines.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from domain.geocoding.microzones import extract_microzone_signals
from domain.valuation.evaluation.evaluator import EngineEvaluationRow
from domain.valuation.evaluation.hedonic_coverage import AuditRecord, dataset_signature


REDUCTION_SCENARIOS = {
    "conservative_5pct": 0.05,
    "conservative_10pct": 0.10,
    "base_15pct": 0.15,
    "base_20pct": 0.20,
    "aggressive_25pct": 0.25,
    "aggressive_30pct": 0.30,
}

DECISIONS = {"go", "limited_pilot", "defer", "no_go"}


@dataclass(frozen=True)
class LoadedReport:
    name: str
    path: str
    parse_ok: bool
    dataset_signature: str | None = None
    error: str | None = None


def load_json_report(path: Path) -> tuple[LoadedReport, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - exercised through missing/broken files
        return LoadedReport(path.stem, str(path), False, error=str(exc)), {}
    signature = (
        payload.get("metadata", {}).get("dataset_signature")
        or payload.get("preflight", {}).get("dataset_signature")
        or payload.get("ablation", {}).get("dataset_signature")
        or payload.get("benchmark", {}).get("dataset_signature")
    )
    return LoadedReport(path.stem, str(path), True, signature), payload


def evidence_summary(
    *,
    phase0b: Mapping[str, Any],
    phase1: Mapping[str, Any],
    phase2: Mapping[str, Any],
    registry_engines: Sequence[str],
) -> dict[str, Any]:
    phase1_benchmark = phase1.get("benchmark", {})
    phase1_ablation = phase1.get("ablation", {})
    phase2_universe = phase2.get("universe", {})
    return {
        "real_engines": [name for name in registry_engines if name.startswith("comparables_")],
        "future_engines_not_registered": ["hedonic", "ml", "house_land_building", "valoria_consensus"],
        "main_practical_challenger": "comparables_canonical_outliers",
        "phase0b_dataset_signature": phase0b.get("metadata", {}).get("dataset_signature"),
        "phase1_dataset_signature": (
            phase1_benchmark.get("dataset_signature") or phase1_ablation.get("dataset_signature")
        ),
        "phase2_dataset_signature": phase2.get("preflight", {}).get("dataset_signature"),
        "house_baselines": {
            "legacy": phase1_benchmark.get("segments", {}).get("house", {}).get("legacy", {}),
            "canonical_plus_outliers": phase1_ablation.get("variants_house", {}).get("canonical_plus_outliers", {}),
            "canonical_full": phase1_benchmark.get("segments", {}).get("house", {}).get("canonical", {}),
        },
        "apartment_baselines": {
            "legacy": phase1_benchmark.get("segments", {}).get("apartment", {}).get("legacy", {}),
            "canonical_full": phase1_benchmark.get("segments", {}).get("apartment", {}).get("canonical", {}),
        },
        "phase2_universe": phase2_universe,
        "phase2_decision": phase2.get("decision", {}),
    }


def ml_eligibility(records: Sequence[AuditRecord], cases: Sequence[Any]) -> dict[str, Any]:
    case_fingerprints = {case.listing.fingerprint for case in cases}
    predicates: dict[str, Callable[[AuditRecord], bool]] = {
        "ML0_basic": lambda r: _ml0(r),
        "ML1_physical": lambda r: _ml0(r) and r.bedrooms_valid and r.bathrooms_valid and r.parking_present,
        "ML2_geo": lambda r: _ml1(r) and (r.useful_geocode or r.microzone_useful),
        "ML3_house_enriched": lambda r: _house(r) and _ml1(r) and (r.has_land_area or r.product_class_usable),
        "ML4_full": lambda r: _ml1(r)
        and (r.useful_geocode or r.microzone_useful)
        and r.has_land_area
        and r.microzone_useful
        and r.product_class_usable
        and r.scraped_at_valid,
    }
    result: dict[str, Any] = {}
    for level, predicate in predicates.items():
        result[level] = {
            segment: _eligibility_row(
                [r for r in _segment(records, segment) if predicate(r)],
                total=len(_segment(records, segment)),
                case_fingerprints=case_fingerprints,
            )
            for segment in ("global", "apartment", "house", "house_with_land", "house_without_land")
        }
    return result


def ml_dataset_profile(records: Sequence[AuditRecord]) -> dict[str, Any]:
    canonical = [r for r in records if r.canonical_price_usable]
    return {
        "observations_total": len(records),
        "canonical_price_usable": len(canonical),
        "by_property_type": dict(Counter(r.property_type for r in records)),
        "canonical_by_property_type": dict(Counter(r.property_type for r in canonical)),
        "by_comuna_top": _top_counts((r.comuna for r in canonical), limit=20),
        "by_price_range": _price_ranges(canonical),
        "by_surface_range": _surface_ranges(canonical),
        "by_period": _period_counts(canonical),
        "physical_complete": _count(records, lambda r: r.effective_area_valid and r.bedrooms_valid and r.bathrooms_valid and r.parking_present),
        "useful_geography": _count(records, lambda r: r.useful_geocode),
        "microzone": _count(records, lambda r: r.microzone_useful),
        "land_area": _count(records, lambda r: r.has_land_area),
        "product_classification": _count(records, lambda r: r.product_class_usable),
        "reliable_dates": _count(records, lambda r: r.scraped_at_valid),
        "segments": {
            segment: {
                "total": len(_segment(records, segment)),
                "canonical_price_usable": _count(_segment(records, segment), lambda r: r.canonical_price_usable),
                "physical_complete": _count(_segment(records, segment), lambda r: r.effective_area_valid and r.bedrooms_valid and r.bathrooms_valid and r.parking_present),
                "useful_geography": _count(_segment(records, segment), lambda r: r.useful_geocode),
                "microzone": _count(_segment(records, segment), lambda r: r.microzone_useful),
                "land_area": _count(_segment(records, segment), lambda r: r.has_land_area),
            }
            for segment in ("apartment", "house", "house_with_land", "house_without_land")
        },
    }


def ml_feature_groups(records: Sequence[AuditRecord]) -> dict[str, Any]:
    groups: dict[str, dict[str, Callable[[AuditRecord], bool]]] = {
        "basic": {
            "property_type": lambda r: r.property_type in {"apartment", "house"},
            "comuna": lambda r: bool(r.comuna and r.comuna != "unknown"),
            "surface": lambda r: r.effective_area_valid,
            "bedrooms": lambda r: r.bedrooms_valid,
            "bathrooms": lambda r: r.bathrooms_valid,
            "parking": lambda r: r.parking_present,
            "canonical_price_target": lambda r: r.canonical_price_usable,
        },
        "geographic": {
            "lat_lon": lambda r: r.coordinates_valid,
            "geocode_precision": lambda r: r.geocode_precision != "unknown",
            "microzone": lambda r: r.microzone_useful,
            "metro": lambda r: bool(_signals(r).nearby_metro),
            "avenue": lambda r: bool(_signals(r).nearby_avenue),
            "neighborhood": lambda r: bool(_signals(r).neighborhood_hint),
            "intersection": lambda r: bool(_signals(r).intersection_hint),
        },
        "house": {
            "land_area_m2": lambda r: r.has_land_area,
            "land_building_ratio": lambda r: r.land_building_ratio_valid,
            "missing_land_indicator": lambda r: _house(r),
            "product_classification": lambda r: r.product_class_usable,
            "special_product": lambda r: r.product_class not in {"standard_residential", "unknown"},
        },
        "temporal": {
            "scraped_at": lambda r: r.scraped_at_valid,
            "first_seen": lambda r: False,
            "last_seen": lambda r: bool(getattr(r.listing, "last_seen_at", None)),
            "published_at": lambda r: False,
            "market_period": lambda r: r.scraped_at_valid,
            "uf": lambda r: r.price_uf_usable,
        },
        "aggregated_possible": {
            "historical_median_by_comuna": lambda r: r.canonical_price_usable and bool(r.comuna),
            "historical_median_by_microzone": lambda r: r.canonical_price_usable and r.microzone_useful,
            "local_density": lambda r: r.useful_geocode or r.microzone_useful,
            "local_dispersion": lambda r: r.canonical_price_usable and (r.useful_geocode or r.microzone_useful),
            "sample_count": lambda r: bool(r.comuna),
        },
    }
    output: dict[str, Any] = {}
    for group, feature_map in groups.items():
        feature_rows = {
            name: _coverage(records, predicate)
            for name, predicate in feature_map.items()
        }
        output[group] = {
            "features": feature_rows,
            "group_joint_coverage": _coverage(records, lambda r, fmap=feature_map: all(fn(r) for fn in fmap.values())),
            "effective_size": min(row["valid_count"] for row in feature_rows.values()) if feature_rows else 0,
            "cardinality": _group_cardinality(group, records),
            "leakage_risk": _leakage_risk(group),
            "production_calculable": _production_calculable(group),
            "expected_stability": _expected_stability(group),
        }
    return output


def overfitting_risk(records: Sequence[AuditRecord], eligibility: Mapping[str, Any]) -> dict[str, Any]:
    canonical = [r for r in records if r.canonical_price_usable]
    communes = Counter(r.comuna for r in canonical)
    microzones = Counter(token for r in canonical for token in _microzone_tokens(r))
    feature_count_estimate = 8 + len([c for c, n in communes.items() if n >= 5])
    return {
        "canonical_rows": len(canonical),
        "rows_by_type": dict(Counter(r.property_type for r in canonical)),
        "communes": len(communes),
        "communes_lt_5": sum(1 for n in communes.values() if n < 5),
        "communes_lt_10": sum(1 for n in communes.values() if n < 10),
        "microzone_categories": len(microzones),
        "microzones_lt_5": sum(1 for n in microzones.values() if n < 5),
        "high_missingness_features": [
            "lat_lon",
            "microzone",
            "land_area_m2",
            "price_uf_real",
            "first_seen",
            "published_at",
        ],
        "rough_rows_per_feature": round(len(canonical) / feature_count_estimate, 2) if feature_count_estimate else None,
        "risk_level": "high" if len(canonical) < 2000 or sum(1 for n in communes.values() if n < 10) > 0 else "medium",
        "risks": [
            "Small effective sample after canonical target filtering, especially apartments.",
            "Microzone and lat/lon coverage are too sparse for high-cardinality geography.",
            "Zonal aggregate features must be fitted on train only to avoid target leakage.",
            "House land features are too sparse and would mostly learn missingness.",
        ],
        "eligibility_summary": {
            level: values.get("global", {})
            for level, values in eligibility.items()
        },
    }


def split_viability(records: Sequence[AuditRecord]) -> dict[str, Any]:
    canonical = [r for r in records if r.canonical_price_usable]
    months = _period_counts(canonical)
    communes = Counter(r.comuna for r in canonical)
    return {
        "random_reproducible": {
            "viable": len(canonical) >= 300,
            "reason": f"{len(canonical)} canonical rows allow random train/validation/test, but it is optimistic.",
        },
        "temporal": {
            "viable": len(months) >= 3 and len(canonical) >= 500,
            "periods": len(months),
            "reason": "Viable only as a rough active-listing split; not a full historical backtest.",
        },
        "by_comuna_holdout": {
            "viable": sum(1 for n in communes.values() if n >= 30) >= 5,
            "communes_ge_30": sum(1 for n in communes.values() if n >= 30),
            "reason": "Useful stress test, but scarce communes will dominate instability.",
        },
        "train_validation_test": {
            "viable": len(canonical) >= 500,
            "reason": "Viable globally; segment-specific validation remains weak for apartments and land-rich houses.",
        },
    }


def improvement_scenarios(
    rows: Sequence[EngineEvaluationRow],
    records: Sequence[AuditRecord],
    eligibility: Mapping[str, Any],
    predicates: Mapping[str, Callable[[AuditRecord], bool]],
    *,
    reference_engines: Sequence[str],
) -> dict[str, Any]:
    record_by_case = {r.benchmark_case_id: r for r in records if r.benchmark_case_id}
    output: dict[str, Any] = {}
    for engine in reference_engines:
        engine_rows = [
            row for row in rows
            if row.engine_name == engine and row.absolute_percentage_error is not None
        ]
        engine_key: dict[str, Any] = {
            "reference_mape_pct": _mean([row.absolute_percentage_error for row in engine_rows]),
            "successful_cases": len(engine_rows),
            "levels": {},
        }
        for level, predicate in predicates.items():
            eligible_rows = [
                row for row in engine_rows
                if (record := record_by_case.get(row.case_id)) is not None and predicate(record)
            ]
            eligible_case_ids = {row.case_id for row in eligible_rows}
            non_rows = [row for row in engine_rows if row.case_id not in eligible_case_ids]
            engine_key["levels"][level] = _scenario_row(engine_rows, eligible_rows, non_rows)
        output[engine] = engine_key
    return output


def house_land_building_coverage(records: Sequence[AuditRecord], cases: Sequence[Any]) -> dict[str, Any]:
    houses = [r for r in records if _house(r)]
    with_land = [r for r in houses if r.has_land_area]
    case_fingerprints = {case.listing.fingerprint for case in cases}
    by_comuna = Counter(r.comuna for r in with_land)
    with_microzone = [r for r in with_land if r.microzone_useful]
    with_geo = [r for r in with_land if r.useful_geocode]
    return {
        "total_houses": len(houses),
        "houses_with_land": _coverage(houses, lambda r: r.has_land_area),
        "houses_with_land_and_canonical_price": _coverage(houses, lambda r: r.has_land_area and r.canonical_price_usable),
        "houses_with_land_and_built_area": _coverage(houses, lambda r: r.has_land_area and r.effective_area_valid),
        "houses_with_land_and_useful_geo": _coverage(houses, lambda r: r.has_land_area and r.useful_geocode),
        "houses_with_land_and_microzone": _coverage(houses, lambda r: r.has_land_area and r.microzone_useful),
        "houses_with_land_and_product_classification": _coverage(houses, lambda r: r.has_land_area and r.product_class_usable),
        "houses_with_land_and_reliable_date": _coverage(houses, lambda r: r.has_land_area and r.scraped_at_valid),
        "benchmark_eligible_cases": sum(1 for r in with_land if r.listing.fingerprint in case_fingerprints),
        "density_by_comuna": dict(sorted(by_comuna.items(), key=lambda item: (-item[1], item[0]))),
        "communes_ge_5": sum(1 for n in by_comuna.values() if n >= 5),
        "communes_ge_10": sum(1 for n in by_comuna.values() if n >= 10),
        "communes_ge_20": sum(1 for n in by_comuna.values() if n >= 20),
        "communes_ge_30": sum(1 for n in by_comuna.values() if n >= 30),
        "communes_with_microzone": len({r.comuna for r in with_microzone}),
        "communes_with_useful_geo": len({r.comuna for r in with_geo}),
        "component_viability": {
            "land_value": _component_viability(len(with_land), by_comuna, requires_microzone=False),
            "building_value": _component_viability(len(with_land), by_comuna, requires_microzone=False),
            "depreciation": {"viable": False, "reason": "No reliable age/condition variable in Listing entity."},
            "land_building_interaction": {
                "viable": len([r for r in with_land if r.land_building_ratio_valid]) >= 200,
                "observations": len([r for r in with_land if r.land_building_ratio_valid]),
                "reason": "Current ratio sample is far below a stable interaction model.",
            },
            "comuna_effect": {
                "viable": sum(1 for n in by_comuna.values() if n >= 20) >= 3,
                "reason": "Most communes have too few land-rich house rows.",
            },
            "microzone_effect": {
                "viable": len(with_microzone) >= 200,
                "observations": len(with_microzone),
                "reason": "Microzone sample is not enough for land/building separation.",
            },
        },
    }


def house_land_predicates() -> dict[str, Callable[[AuditRecord], bool]]:
    return {
        "HLB0_land_price_area": lambda r: _house(r) and r.canonical_price_usable and r.has_land_area,
        "HLB1_land_built": lambda r: _house(r) and r.canonical_price_usable and r.has_land_area and r.effective_area_valid,
        "HLB2_land_geo": lambda r: _house(r) and r.canonical_price_usable and r.has_land_area and r.effective_area_valid and r.useful_geocode,
        "HLB3_land_microzone": lambda r: _house(r) and r.canonical_price_usable and r.has_land_area and r.effective_area_valid and r.microzone_useful,
    }


def consensus_audit(root: Path, registry_engines: Sequence[str]) -> dict[str, Any]:
    folder = root / "domain" / "valuation" / "engines" / "valoria_consensus"
    files = sorted(folder.glob("*.py")) if folder.exists() else []
    contents = {path.name: path.read_text(encoding="utf-8") for path in files}
    all_text = "\n".join(contents.values())
    registered = "valoria_consensus" in set(registry_engines)
    imports_real_result = "EngineResult" in all_text and "domain.valuation.engines.contracts" in all_text
    imports_real_context = "EngineContext" in all_text and "domain.valuation.engines.contracts" in all_text
    expected = _extract_expected_engines(contents.get("config.py", ""))
    missing_expected = [name for name in expected if name not in registry_engines]
    status = "contract_connected_but_not_operationally_ready"
    if not imports_real_result or not imports_real_context:
        status = "disconnected_from_real_contracts"
    return {
        "folder_exists": folder.exists(),
        "files": [str(path.relative_to(root)) for path in files],
        "registered": registered,
        "imports_real_engine_result": imports_real_result,
        "imports_real_engine_context": imports_real_context,
        "consumes_registry_real": False,
        "expects_engine_results_in_context_metadata": "engine_results" in all_text,
        "expected_engines": expected,
        "missing_expected_engines": missing_expected,
        "duplicates_contracts": "dataclass" in all_text and "class EngineResult" in all_text,
        "invented_result_fields": [],
        "status": status,
        "decision": "defer",
        "diagnosis": (
            "The skeleton uses real contracts, but it is not registered and depends on precomputed "
            "base EngineResult objects plus calibrated weights that do not exist yet. With only legacy "
            "and canonical variants, consensus would be selection logic rather than a real ensemble."
        ),
        "future_rewrite_conditions": [
            "At least two real non-variant engines, ideally three, with comparable benchmarks.",
            "Same dataset signature, target rules, UF rate and split across engines.",
            "Segmented validation metrics and calibrated confidence.",
            "Versioned exclusion rules and disagreement handling.",
            "Evidence that the ensemble beats or stabilizes the best individual motor.",
        ],
    }


def strategic_decisions(
    *,
    ml_scenarios: Mapping[str, Any],
    hlb_coverage: Mapping[str, Any],
    consensus: Mapping[str, Any],
    canonical_reference: str,
) -> dict[str, str]:
    canonical_levels = ml_scenarios.get(canonical_reference, {}).get("levels", {})
    ml1 = canonical_levels.get("ML1_physical", {})
    ml_gain = ml1.get("scenarios", {}).get("base_20pct", {}).get("improvement_pp", 0) or 0
    ml_decision = "limited_pilot" if ml_gain >= 1.0 else "defer"
    land_pct = hlb_coverage.get("houses_with_land", {}).get("valid_pct", 0) or 0
    hlb_decision = "defer" if land_pct < 25 else "limited_pilot"
    consensus_decision = "defer" if consensus.get("decision") == "defer" else "no_go"
    return {
        "ml": ml_decision,
        "house_land_building": hlb_decision,
        "valoria_consensus": consensus_decision,
    }


def roadmap(decisions: Mapping[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "priority": 1,
            "option": "B",
            "name": "Stabilize canonical_plus_outliers as a practical challenger variant",
            "impact": "high",
            "technical_cost": "low",
            "risk": "low",
            "data_dependency": "low",
            "coverage": "high for houses relative to canonical_full",
            "product_value": "high",
        },
        {
            "priority": 2,
            "option": "C",
            "name": "Improve data before heavier new engines: land_area, microzone, geocode, apartment canonical target",
            "impact": "high",
            "technical_cost": "medium",
            "risk": "medium",
            "data_dependency": "core dependency",
            "coverage": "unlocks future engines",
            "product_value": "high",
        },
        {
            "priority": 3,
            "option": "A",
            "name": "Implement hedonic_house_minimal as a limited offline pilot before full ML",
            "impact": "medium",
            "technical_cost": "medium",
            "risk": "medium",
            "data_dependency": "moderate",
            "coverage": "houses H1 only",
            "product_value": "medium",
        },
        {
            "priority": 4,
            "option": "D",
            "name": "Run ML as laboratory only after a clean validation plan",
            "impact": "medium",
            "technical_cost": "high",
            "risk": "high",
            "data_dependency": "medium/high",
            "coverage": "ML1 enough; ML2/ML4 constrained",
            "product_value": "research value now",
        },
        {
            "priority": 5,
            "option": "E",
            "name": "Defer house_land_building",
            "impact": "low now",
            "technical_cost": "high",
            "risk": "high",
            "data_dependency": "very high",
            "coverage": "too low with current land coverage",
            "product_value": "future only",
        },
        {
            "priority": 6,
            "option": "F",
            "name": "Rewrite valoria_consensus after 2-3 real engines exist",
            "impact": "future high",
            "technical_cost": "medium",
            "risk": "medium",
            "data_dependency": "needs comparable engine benchmarks",
            "coverage": "depends on base engines",
            "product_value": "future orchestration",
        },
    ]


def build_report(
    *,
    preflight: Mapping[str, Any],
    loaded_reports: Sequence[LoadedReport],
    evidence: Mapping[str, Any],
    records: Sequence[AuditRecord],
    cases: Sequence[Any],
    rows: Sequence[EngineEvaluationRow],
    consensus: Mapping[str, Any],
    canonical_reference: str,
    tests: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    ml_levels = ml_eligibility(records, cases)
    ml_predicates = {
        "ML0_basic": _ml0,
        "ML1_physical": _ml1,
        "ML2_geo": lambda r: _ml1(r) and (r.useful_geocode or r.microzone_useful),
        "ML3_house_enriched": lambda r: _house(r) and _ml1(r) and (r.has_land_area or r.product_class_usable),
        "ML4_full": lambda r: _ml1(r)
        and (r.useful_geocode or r.microzone_useful)
        and r.has_land_area
        and r.microzone_useful
        and r.product_class_usable
        and r.scraped_at_valid,
    }
    reference_engines = ["comparables_legacy", canonical_reference]
    ml_scenarios = improvement_scenarios(rows, records, ml_levels, ml_predicates, reference_engines=reference_engines)
    hlb_coverage = house_land_building_coverage(records, cases)
    hlb_scenarios = improvement_scenarios(
        rows,
        records,
        {},
        house_land_predicates(),
        reference_engines=reference_engines,
    )
    decisions = strategic_decisions(
        ml_scenarios=ml_scenarios,
        hlb_coverage=hlb_coverage,
        consensus=consensus,
        canonical_reference=canonical_reference,
    )
    return {
        "report": "phase3_model_strategy_latest",
        "date": "2026-06-13",
        "preflight": {
            **dict(preflight),
            "dataset_signature": dataset_signature(records),
            "loaded_reports": [report.__dict__ for report in loaded_reports],
            "real_engines": evidence.get("real_engines", []),
            "future_engines_not_registered": evidence.get("future_engines_not_registered", []),
            "old_consensus_status": consensus.get("status"),
        },
        "evidence": evidence,
        "ml": {
            "dataset_profile": ml_dataset_profile(records),
            "feature_groups": ml_feature_groups(records),
            "eligibility": ml_levels,
            "overfitting_risk": overfitting_risk(records, ml_levels),
            "split_viability": split_viability(records),
            "improvement_scenarios": ml_scenarios,
            "decision": decisions["ml"],
        },
        "house_land_building": {
            "coverage": hlb_coverage,
            "improvement_scenarios": hlb_scenarios,
            "decision": decisions["house_land_building"],
            "methodological_warning": "Current land_area coverage is too sparse to separate land and construction value.",
        },
        "valoria_consensus": {
            **dict(consensus),
            "decision": decisions["valoria_consensus"],
        },
        "roadmap": roadmap(decisions),
        "tests": list(tests or []),
        "guardrails": {
            "db_modified": False,
            "migrations_created_or_executed": False,
            "models_trained": False,
            "model_artifacts_created": False,
            "ml_registered": False,
            "house_land_building_registered": False,
            "valoria_consensus_registered": False,
            "base_engines_modified": False,
            "production_changed": False,
            "remote_configured": False,
            "push_performed": False,
        },
    }


def write_outputs(output_dir: Path, report: Mapping[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "phase3_model_strategy_latest.json"
    md_path = output_dir / "phase3_model_strategy_latest.md"
    ml_csv = output_dir / "phase3_ml_coverage.csv"
    hlb_csv = output_dir / "phase3_house_land_building_coverage.csv"
    scenarios_csv = output_dir / "phase3_strategy_scenarios.csv"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    _write_ml_csv(ml_csv, report["ml"]["eligibility"])
    _write_hlb_csv(hlb_csv, report["house_land_building"]["coverage"])
    _write_scenarios_csv(scenarios_csv, report)
    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "ml_csv": str(ml_csv),
        "house_land_building_csv": str(hlb_csv),
        "scenarios_csv": str(scenarios_csv),
    }


def markdown_report(report: Mapping[str, Any]) -> str:
    preflight = report["preflight"]
    ml = report["ml"]
    hlb = report["house_land_building"]
    consensus = report["valoria_consensus"]
    lines = [
        "# Phase 3 Model Strategy Audit",
        "",
        "## Preflight",
        "",
        f"- Branch: `{preflight.get('branch')}`",
        f"- HEAD: `{preflight.get('head')}`",
        f"- Dataset signature: `{preflight.get('dataset_signature')}`",
        f"- Git status: `{preflight.get('git_status')}`",
        f"- Real engines: `{', '.join(preflight.get('real_engines', []))}`",
        f"- Future engines not registered: `{', '.join(preflight.get('future_engines_not_registered', []))}`",
        f"- Consensus skeleton: `{preflight.get('old_consensus_status')}`",
        "",
        "## Consolidated Evidence",
        "",
        f"- Main practical challenger: `{report['evidence'].get('main_practical_challenger')}`",
        f"- Phase 1 dataset signature: `{report['evidence'].get('phase1_dataset_signature')}`",
        f"- Phase 2 dataset signature: `{report['evidence'].get('phase2_dataset_signature')}`",
        "",
        "## ML Eligibility",
        "",
        "| Level | Global obs | Global coverage | House obs | Apartment obs | Can split |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for level, segments in ml["eligibility"].items():
        global_row = segments["global"]
        house_row = segments["house"]
        apt_row = segments["apartment"]
        lines.append(
            f"| `{level}` | {global_row['observations']} | {global_row['coverage_pct']}% | "
            f"{house_row['observations']} | {apt_row['observations']} | {global_row['can_split_train_validation_test']} |"
        )
    lines.extend([
        "",
        "## ML Improvement Ceiling",
        "",
        "| Reference | Level | Eligible share | Current eligible MAPE | Base 20pp gain | Upper bound gain |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ])
    for engine, data in ml["improvement_scenarios"].items():
        for level, row in data["levels"].items():
            base20 = row["scenarios"]["base_20pct"]["improvement_pp"]
            upper = row["upper_bound_unrealistic"]["improvement_pp"]
            lines.append(
                f"| `{engine}` | `{level}` | {row['eligible_share_pct']}% | "
                f"{row['mape_eligible_pct']} | {base20} | {upper} |"
            )
    lines.extend([
        "",
        "## House Land Building",
        "",
        f"- Houses with land: `{hlb['coverage']['houses_with_land']['valid_count']}` "
        f"({hlb['coverage']['houses_with_land']['valid_pct']}%).",
        f"- Communes with >=10 land observations: `{hlb['coverage']['communes_ge_10']}`.",
        f"- Decision: `{hlb['decision']}`.",
        "",
        "## Consensus",
        "",
        f"- Imports real EngineResult: `{consensus.get('imports_real_engine_result')}`",
        f"- Imports real EngineContext: `{consensus.get('imports_real_engine_context')}`",
        f"- Registered: `{consensus.get('registered')}`",
        f"- Status: `{consensus.get('status')}`",
        f"- Decision: `{consensus.get('decision')}`",
        "",
        "## Decisions",
        "",
        f"- ML: `{ml['decision']}`",
        f"- house_land_building: `{hlb['decision']}`",
        f"- valoria_consensus: `{consensus.get('decision')}`",
        "",
        "## Roadmap",
        "",
    ])
    for item in report["roadmap"]:
        lines.append(f"{item['priority']}. `{item['option']}` {item['name']} - impact `{item['impact']}`, risk `{item['risk']}`.")
    lines.extend([
        "",
        "## Tests",
        "",
        "| Command | Passed | Failed | Errors | Skipped |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for row in report.get("tests", []):
        lines.append(
            f"| `{row.get('command')}` | {row.get('passed', 0)} | {row.get('failed', 0)} | "
            f"{row.get('errors', 0)} | {row.get('skipped', 0)} |"
        )
    lines.extend([
        "",
        "## Guardrails",
        "",
    ])
    for key, value in report["guardrails"].items():
        lines.append(f"- `{key}`: `{value}`")
    return "\n".join(lines) + "\n"


def report_dataset_hash(report: Mapping[str, Any]) -> str:
    raw = json.dumps(report, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def run_git(*args: str) -> str:
    try:
        result = subprocess.run(["git", *args], check=False, capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return "git_unavailable"
    text = (result.stdout or result.stderr).strip()
    return text or "clean"


def _ml0(record: AuditRecord) -> bool:
    return (
        record.canonical_price_usable
        and record.property_type in {"apartment", "house"}
        and bool(record.comuna and record.comuna != "unknown")
        and record.effective_area_valid
    )


def _ml1(record: AuditRecord) -> bool:
    return _ml0(record) and record.bedrooms_valid and record.bathrooms_valid and record.parking_present


def _house(record: AuditRecord) -> bool:
    return record.property_type == "house"


def _segment(records: Sequence[AuditRecord], segment: str) -> list[AuditRecord]:
    if segment == "global":
        return list(records)
    if segment == "house_with_land":
        return [r for r in records if r.property_type == "house" and r.has_land_area]
    if segment == "house_without_land":
        return [r for r in records if r.property_type == "house" and not r.has_land_area]
    return [r for r in records if r.property_type == segment]


def _eligibility_row(records: Sequence[AuditRecord], *, total: int, case_fingerprints: set[str]) -> dict[str, Any]:
    by_comuna = Counter(r.comuna for r in records)
    return {
        "observations": len(records),
        "coverage_pct": _pct(len(records), total),
        "benchmark_coverage_count": sum(1 for r in records if r.listing.fingerprint in case_fingerprints),
        "communes_covered": len(by_comuna),
        "median_observations_per_comuna": _median(list(by_comuna.values())),
        "communes_lt_10": sum(1 for n in by_comuna.values() if n < 10),
        "communes_ge_30": sum(1 for n in by_comuna.values() if n >= 30),
        "can_split_train_validation_test": len(records) >= 100 and sum(1 for n in by_comuna.values() if n >= 20) >= 3,
    }


def _scenario_row(
    all_rows: Sequence[EngineEvaluationRow],
    eligible_rows: Sequence[EngineEvaluationRow],
    non_rows: Sequence[EngineEvaluationRow],
) -> dict[str, Any]:
    all_mape = _mean([row.absolute_percentage_error for row in all_rows if row.absolute_percentage_error is not None])
    eligible_mape = _mean([row.absolute_percentage_error for row in eligible_rows if row.absolute_percentage_error is not None])
    non_mape = _mean([row.absolute_percentage_error for row in non_rows if row.absolute_percentage_error is not None])
    share = len(eligible_rows) / len(all_rows) if all_rows else 0
    non_share = 1 - share
    scenarios = {}
    for name, reduction in REDUCTION_SCENARIOS.items():
        estimated = _weighted_mape(share, eligible_mape, reduction, non_share, non_mape)
        scenarios[name] = {
            "estimated_mape_pct": estimated,
            "improvement_pp": _round((all_mape or 0) - estimated) if estimated is not None else None,
        }
    upper = _round(non_share * (non_mape or 0)) if all_rows else None
    return {
        "eligible_cases": len(eligible_rows),
        "eligible_share_pct": _pct(len(eligible_rows), len(all_rows)),
        "mape_eligible_pct": eligible_mape,
        "mape_non_eligible_pct": non_mape,
        "reference_mape_pct": all_mape,
        "scenarios": scenarios,
        "upper_bound_unrealistic": {
            "estimated_mape_pct": upper,
            "improvement_pp": _round((all_mape or 0) - upper) if upper is not None else None,
        },
    }


def _weighted_mape(
    share: float,
    eligible_mape: float | None,
    reduction: float,
    non_share: float,
    non_mape: float | None,
) -> float | None:
    if eligible_mape is None and non_mape is None:
        return None
    return _round(share * (eligible_mape or 0) * (1 - reduction) + non_share * (non_mape or 0))


def _coverage(records: Sequence[AuditRecord], predicate: Callable[[AuditRecord], bool]) -> dict[str, Any]:
    valid = sum(1 for record in records if predicate(record))
    return {
        "total": len(records),
        "valid_count": valid,
        "valid_pct": _pct(valid, len(records)),
        "missing_count": len(records) - valid,
    }


def _count(records: Sequence[AuditRecord], predicate: Callable[[AuditRecord], bool]) -> int:
    return sum(1 for record in records if predicate(record))


def _pct(part: int, total: int) -> float:
    return round(part / total * 100, 2) if total else 0.0


def _round(value: float | int | None) -> float | None:
    return round(float(value), 2) if value is not None and math.isfinite(float(value)) else None


def _mean(values: Sequence[float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    return _round(sum(clean) / len(clean)) if clean else None


def _median(values: Sequence[int]) -> float | None:
    return _round(median(values)) if values else None


def _top_counts(values: Sequence[str], *, limit: int) -> dict[str, int]:
    return dict(Counter(values).most_common(limit))


def _price_ranges(records: Sequence[AuditRecord]) -> dict[str, int]:
    buckets = Counter()
    for record in records:
        price = float(record.price_clp)
        if price < 100_000_000:
            buckets["lt_100m"] += 1
        elif price < 200_000_000:
            buckets["100m_200m"] += 1
        elif price < 400_000_000:
            buckets["200m_400m"] += 1
        elif price < 800_000_000:
            buckets["400m_800m"] += 1
        else:
            buckets["gte_800m"] += 1
    return dict(buckets)


def _surface_ranges(records: Sequence[AuditRecord]) -> dict[str, int]:
    buckets = Counter()
    for record in records:
        area = record.built_area or 0
        if area < 50:
            buckets["lt_50"] += 1
        elif area < 80:
            buckets["50_80"] += 1
        elif area < 120:
            buckets["80_120"] += 1
        elif area < 200:
            buckets["120_200"] += 1
        else:
            buckets["gte_200"] += 1
    return dict(buckets)


def _period_counts(records: Sequence[AuditRecord]) -> dict[str, int]:
    values = Counter()
    for record in records:
        scraped_at = getattr(record.listing, "scraped_at", None)
        if isinstance(scraped_at, datetime):
            values[f"{scraped_at.year:04d}-{scraped_at.month:02d}"] += 1
    return dict(sorted(values.items()))


def _signals(record: AuditRecord):
    return extract_microzone_signals(title=record.listing.title, raw_metadata=record.listing.raw_metadata)


def _microzone_tokens(record: AuditRecord) -> list[str]:
    signals = _signals(record)
    tokens = []
    for value in (signals.nearby_metro, signals.nearby_avenue, signals.neighborhood_hint, signals.intersection_hint):
        if value:
            tokens.append(value)
    tokens.extend(signals.landmark_tokens)
    return tokens


def _group_cardinality(group: str, records: Sequence[AuditRecord]) -> dict[str, int]:
    if group == "basic":
        return {
            "property_type": len({r.property_type for r in records}),
            "comuna": len({r.comuna for r in records}),
        }
    if group == "geographic":
        return {
            "geocode_precision": len({r.geocode_precision for r in records}),
            "microzone_tokens": len({token for r in records for token in _microzone_tokens(r)}),
        }
    if group == "house":
        return {"product_class": len({r.product_class for r in records})}
    if group == "temporal":
        return {"periods": len(_period_counts(records))}
    return {"zones": len({r.comuna for r in records})}


def _leakage_risk(group: str) -> str:
    return {
        "basic": "low if target price is excluded from features",
        "geographic": "medium because sparse geography can memorize locations",
        "house": "medium because product classification may reflect price-language proxies",
        "temporal": "medium/high if last_seen or future refresh data is used",
        "aggregated_possible": "high unless fitted only on train and cutoff-aware",
    }[group]


def _production_calculable(group: str) -> str:
    return {
        "basic": "yes",
        "geographic": "partially",
        "house": "partially",
        "temporal": "scraped_at yes; publication date mostly no",
        "aggregated_possible": "yes only through versioned offline transformers",
    }[group]


def _expected_stability(group: str) -> str:
    return {
        "basic": "high",
        "geographic": "low/medium with current coverage",
        "house": "low for land features",
        "temporal": "medium",
        "aggregated_possible": "medium if leakage-controlled",
    }[group]


def _component_viability(total: int, by_comuna: Counter[str], *, requires_microzone: bool) -> dict[str, Any]:
    return {
        "viable": total >= 300 and sum(1 for n in by_comuna.values() if n >= 30) >= 3 and not requires_microzone,
        "observations": total,
        "communes_ge_30": sum(1 for n in by_comuna.values() if n >= 30),
        "reason": "Requires hundreds of land-rich houses and multiple dense communes; current sample is too small.",
    }


def _extract_expected_engines(config_text: str) -> list[str]:
    expected = []
    for name in ("comparables_legacy", "comparables_canonical", "hedonic", "ml", "house_land_building"):
        if name in config_text:
            expected.append(name)
    return expected


def _write_ml_csv(path: Path, eligibility: Mapping[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["level", "segment", "observations", "coverage_pct", "benchmark_coverage_count", "can_split_train_validation_test"])
        writer.writeheader()
        for level, segments in eligibility.items():
            for segment, row in segments.items():
                writer.writerow({
                    "level": level,
                    "segment": segment,
                    "observations": row.get("observations"),
                    "coverage_pct": row.get("coverage_pct"),
                    "benchmark_coverage_count": row.get("benchmark_coverage_count"),
                    "can_split_train_validation_test": row.get("can_split_train_validation_test"),
                })


def _write_hlb_csv(path: Path, coverage: Mapping[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "valid_count", "valid_pct", "detail"])
        writer.writeheader()
        for key, value in coverage.items():
            if isinstance(value, Mapping) and "valid_count" in value:
                writer.writerow({"metric": key, "valid_count": value.get("valid_count"), "valid_pct": value.get("valid_pct"), "detail": ""})
        for comuna, count in coverage.get("density_by_comuna", {}).items():
            writer.writerow({"metric": "density_by_comuna", "valid_count": count, "valid_pct": "", "detail": comuna})


def _write_scenarios_csv(path: Path, report: Mapping[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["engine", "family", "level", "scenario", "eligible_share_pct", "reference_mape_pct", "estimated_mape_pct", "improvement_pp"])
        writer.writeheader()
        for family in ("ml", "house_land_building"):
            scenarios = report[family]["improvement_scenarios"]
            for engine, engine_data in scenarios.items():
                for level, row in engine_data.get("levels", {}).items():
                    for scenario, values in row.get("scenarios", {}).items():
                        writer.writerow({
                            "engine": engine,
                            "family": family,
                            "level": level,
                            "scenario": scenario,
                            "eligible_share_pct": row.get("eligible_share_pct"),
                            "reference_mape_pct": row.get("reference_mape_pct"),
                            "estimated_mape_pct": values.get("estimated_mape_pct"),
                            "improvement_pp": values.get("improvement_pp"),
                        })
                    upper = row.get("upper_bound_unrealistic", {})
                    writer.writerow({
                        "engine": engine,
                        "family": family,
                        "level": level,
                        "scenario": "upper_bound_unrealistic",
                        "eligible_share_pct": row.get("eligible_share_pct"),
                        "reference_mape_pct": row.get("reference_mape_pct"),
                        "estimated_mape_pct": upper.get("estimated_mape_pct"),
                        "improvement_pp": upper.get("improvement_pp"),
                    })
