"""Audit hedonic model viability without training a model."""
from __future__ import annotations

import argparse
import asyncio
import subprocess
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from core.ports.uf_service import UFRateInfo
from domain.valuation.engines.registry import default_engine_registry
from domain.valuation.evaluation.dataset import build_evaluation_cases, infer_uf_rate
from domain.valuation.evaluation.evaluator import evaluate_engines
from domain.valuation.evaluation.hedonic_coverage import (
    build_audit_records,
    candidate_specs,
    dataset_signature,
    feature_rows,
    improvement_scenarios,
    individual_feature_coverage,
    joint_eligibility,
    residual_error_by_features,
    scenario_rows,
    segment_rows,
    target_quality,
    write_outputs,
)
from infrastructure.db.database import get_session_factory
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository
from services.uf_rate import validate_real_uf_rate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit hedonic AVM viability without model training")
    parser.add_argument("--reference-engines", default="comparables_legacy,comparables_canonical_outliers,comparables_canonical")
    parser.add_argument("--canonical-variant", default="comparables_canonical_outliers")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--property-type", choices=["apartment", "house", "unknown"], default=None)
    parser.add_argument("--cutoff", default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--uf-rate", default=None)
    parser.add_argument("--min-segment", type=int, default=20)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    cutoff = _parse_cutoff(args.cutoff)
    engine_names = [item.strip() for item in args.reference_engines.split(",") if item.strip()]
    registry = default_engine_registry()
    for engine_name in engine_names:
        registry.get(engine_name)

    async with get_session_factory()() as session:
        repo = SqlAlchemyListingRepository(session)
        listings = list(await repo.list_active(limit=None))

    uf_to_clp = _resolve_uf_rate(args.uf_rate, listings)
    cases = build_evaluation_cases(
        listings,
        limit=args.limit,
        property_type=args.property_type,
        seed=args.seed,
        cutoff=cutoff,
    )
    rows = evaluate_engines(
        cases=cases,
        registry=registry,
        engine_names=engine_names,
        uf_to_clp=uf_to_clp,
    )
    records = build_audit_records(listings, cases, uf_to_clp=uf_to_clp)
    signature = dataset_signature(records)
    feature_coverage = individual_feature_coverage(records)
    joint = joint_eligibility(records, cases)
    residual = residual_error_by_features(rows, records)
    scenarios = improvement_scenarios(rows, records, joint)
    specs = candidate_specs(joint, scenarios)
    quality = target_quality(records)
    report = {
        "report": "phase2_hedonic_coverage_latest",
        "date": "2026-06-13",
        "preflight": {
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "head": _git("rev-parse", "HEAD"),
            "git_status": _git("status", "--short"),
            "remotes": _git("remote", "-v"),
            "engines": [
                {"name": name, "version": getattr(registry.get(name), "version", None)}
                for name in registry.list()
            ],
            "reference_engines": engine_names,
            "canonical_variant": args.canonical_variant,
            "dataset_signature": signature,
            "seed": args.seed,
            "limit": args.limit,
            "cutoff": args.cutoff,
        },
        "universe": _universe(records, cases),
        "target_quality": quality,
        "feature_coverage": feature_coverage,
        "joint_eligibility": joint,
        "residual_error": residual,
        "improvement_scenarios": scenarios,
        "candidate_specs": specs,
        "decision": _decision(joint, scenarios, args.canonical_variant),
        "roadmap": _roadmap(feature_coverage),
        "guardrails": {
            "db_modified": False,
            "migrations_created_or_executed": False,
            "models_trained": False,
            "model_artifacts_created": False,
            "hedonic_engine_registered": False,
            "production_changed": False,
        },
    }
    paths = write_outputs(
        output_dir=Path(args.output_dir),
        report=report,
        feature_rows=feature_rows(feature_coverage),
        segment_rows=segment_rows(joint),
        scenario_rows=scenario_rows(scenarios),
    )
    print(f"Wrote hedonic viability reports: {paths}")
    return 0


def _universe(records, cases) -> dict[str, Any]:
    potential = [
        record for record in records
        if record.canonical_price_usable
        and record.property_type in {"apartment", "house"}
        and record.effective_area_valid
        and record.comuna
    ]
    return {
        "active_listings": len(records),
        "benchmark_cases": len(cases),
        "potential_training_rows_minimal": len(potential),
        "canonical_price_usable": sum(1 for record in records if record.canonical_price_usable),
        "apartment_rows": sum(1 for record in records if record.property_type == "apartment"),
        "house_rows": sum(1 for record in records if record.property_type == "house"),
        "house_with_land_rows": sum(1 for record in records if record.property_type == "house" and record.has_land_area),
        "house_without_land_rows": sum(1 for record in records if record.property_type == "house" and not record.has_land_area),
        "sources": dict(__import__("collections").Counter(record.source for record in records)),
        "property_types": dict(__import__("collections").Counter(record.property_type for record in records)),
    }


def _decision(joint: dict[str, Any], scenarios: dict[str, Any], canonical_variant: str) -> dict[str, str]:
    reference = scenarios.get(canonical_variant, {}).get("specs", {})
    apt = joint.get("apartment_H1_basic", {})
    house = joint.get("house_H1_basic", {})
    house_land = joint.get("house_H2_land", {})
    geo = joint.get("house_H3_land_geo", {})
    apt_base = reference.get("apartment_H1_basic", {}).get("scenarios", {}).get("base_20pct", {}).get("improvement_pp") or 0
    house_base = reference.get("house_H1_basic", {}).get("scenarios", {}).get("base_20pct", {}).get("improvement_pp") or 0
    decisions = {
        "apartments": "limited_pilot" if apt.get("observations", 0) >= 500 and apt_base >= 0.75 else "defer",
        "houses": "limited_pilot" if house.get("observations", 0) >= 500 and house_base >= 0.75 else "defer",
        "geographic": "defer" if geo.get("coverage_pct", 0) < 50 else "limited_pilot",
        "land": "defer" if house_land.get("coverage_pct", 0) < 50 else "limited_pilot",
    }
    return decisions


def _roadmap(feature_coverage: dict[str, Any]) -> list[dict[str, Any]]:
    house = feature_coverage["house"]
    return [
        {
            "item": "house_land_area_m2",
            "current_pct": house["land_area_m2"]["valid_pct"],
            "target_pct": 70.0,
            "gap_pct": max(0.0, round(70.0 - house["land_area_m2"]["valid_pct"], 2)),
            "priority": "high",
            "impact": "Enables strict land-building hedonic variants.",
        },
        {
            "item": "house_microzone",
            "current_pct": house["microzone"]["valid_pct"],
            "target_pct": 50.0,
            "gap_pct": max(0.0, round(50.0 - house["microzone"]["valid_pct"], 2)),
            "priority": "high",
            "impact": "Enables geographic hedonic effects without overusing comuna dummies.",
        },
        {
            "item": "useful_geocode",
            "current_pct": house["useful_geocode"]["valid_pct"],
            "target_pct": 60.0,
            "gap_pct": max(0.0, round(60.0 - house["useful_geocode"]["valid_pct"], 2)),
            "priority": "medium",
            "impact": "Improves local segmentation and residual diagnostics.",
        },
        {
            "item": "product_classification",
            "current_pct": house["product_classification"]["valid_pct"],
            "target_pct": 90.0,
            "gap_pct": max(0.0, round(90.0 - house["product_classification"]["valid_pct"], 2)),
            "priority": "low",
            "impact": "Reduces product mixing in both comparables and future hedonic samples.",
        },
    ]


def _resolve_uf_rate(raw: str | None, listings) -> Decimal:
    if raw:
        try:
            value = Decimal(str(raw))
        except InvalidOperation as exc:
            raise SystemExit(f"Invalid --uf-rate: {raw}") from exc
    else:
        value = infer_uf_rate(listings)
        if value is None:
            raise SystemExit("Could not infer UF rate; pass --uf-rate")
    validate_real_uf_rate(UFRateInfo(rate=value, source="cli_or_local_data", is_fallback=False))
    return value


def _parse_cutoff(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"Invalid --cutoff ISO datetime: {raw}") from exc


def _git(*args: str) -> str:
    try:
        result = subprocess.run(["git", *args], check=False, capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return "git_unavailable"
    return (result.stdout or result.stderr).strip() or "clean"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
