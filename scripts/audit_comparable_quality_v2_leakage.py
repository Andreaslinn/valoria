"""Read-only leakage audit for Comparable Quality v2 variants."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_SOURCE_REPORT = Path("reports/valuation/comparable_quality_v2_audit_latest.json")
OUTPUT_JSON = "comparable_quality_v2_leakage_audit_latest.json"
OUTPUT_MD = "comparable_quality_v2_leakage_audit_latest.md"


@dataclass(frozen=True)
class VariantLeakageAudit:
    name: str
    production_safe: bool
    uses_subject_price: bool
    uses_subject_price_m2: bool
    uses_actual_error_or_ape: bool
    deployable_as_avm_engine: bool
    deployable_only_for_diagnostics: bool
    input_classes: dict[str, list[str]]
    explanation: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit target leakage in Comparable Quality v2.")
    parser.add_argument("--source-report", default=str(DEFAULT_SOURCE_REPORT))
    parser.add_argument("--output-dir", default="reports/valuation")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = Path(args.source_report)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    report = build_report(source, source_path=source_path)
    json_path, md_path = write_outputs(report, Path(args.output_dir))
    print(
        json.dumps(
            {
                "source_report": str(source_path),
                "best_variant_original": report["source_metrics"]["best_variant"],
                "best_variant_production_safe": report["answers"]["best_production_safe_variant"],
                "original_gain_valid_for_production": report["answers"]["is_17_791_to_17_1549_valid_for_production"],
                "json": str(json_path),
                "markdown": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_report(source: dict[str, Any], *, source_path: Path) -> dict[str, Any]:
    audits = variant_audits()
    source_metrics = source_metric_summary(source)
    safe_variants = [item for item in audits if item.production_safe]
    deployable = [item for item in audits if item.deployable_as_avm_engine]
    best_safe = best_safe_variant(source, deployable)
    robust = next(item for item in audits if item.name == "robust_weighted_median")
    has_leaky_winner = not robust.production_safe
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": {
            "read_only": True,
            "productive_code_modified": False,
            "source_report": str(source_path),
            "leakage_found_in_best_variant": has_leaky_winner,
            "rerun_benchmark_without_leakage_required": has_leaky_winner,
            "new_safe_variant_created": False,
            "reason_no_safe_variant_created": (
                "robust_weighted_median already uses only comparable price_m2 and baseline similarity weights; "
                "observed subject price is used only after estimation to compute APE."
            ),
        },
        "source_metrics": source_metrics,
        "data_lineage": data_lineage(),
        "variant_audits": [asdict(item) for item in audits],
        "production_safe_variants": [item.name for item in safe_variants],
        "deployable_as_avm_engine_variants": [item.name for item in deployable],
        "diagnostic_only_fields": diagnostic_only_fields(),
        "answers": answers(source_metrics, best_safe, robust),
        "recommendation": recommendation(best_safe),
        "do_not_do_yet": [
            "Do not use observed subject price or subject price_m2 in AVM estimation.",
            "Do not productivize diagnostic outlier_vs_subject flags.",
            "Do not use APE/delta/error to choose comparables or weights.",
            "Do not use a listing's own asking price as an input when estimating that same listing.",
            "Do not change productive scoring from this leakage audit.",
        ],
        "productive_safety": (
            "No DB writes, migrations, AVM/Radar/frontend changes, scrapers, external geocoding, "
            "backfills or productive scoring changes were made."
        ),
    }


def variant_audits() -> list[VariantLeakageAudit]:
    safe_core = {
        "production_safe": [
            "subject property_type/comuna/surface/program/location/geocode",
            "eligible comparable prices and price_m2",
            "baseline comparable similarity scores",
            "pool and comuna price_m2 references built without subject price_m2 action input",
        ],
        "forbidden_or_leaky": [],
        "diagnostic_only": [
            "actual_clp used after estimate for APE",
            "subject_price_m2_uf used only in diagnostic_flags/report rows",
        ],
    }
    return [
        VariantLeakageAudit(
            name="baseline",
            production_safe=True,
            uses_subject_price=False,
            uses_subject_price_m2=False,
            uses_actual_error_or_ape=False,
            deployable_as_avm_engine=True,
            deployable_only_for_diagnostics=False,
            input_classes=safe_core,
            explanation="Estimate is weighted mean of selected comparable price_m2 using similarity scores; subject price only appears later for APE.",
        ),
        VariantLeakageAudit(
            name="outlier_filter_mild",
            production_safe=True,
            uses_subject_price=False,
            uses_subject_price_m2=False,
            uses_actual_error_or_ape=False,
            deployable_as_avm_engine=True,
            deployable_only_for_diagnostics=False,
            input_classes=safe_core,
            explanation="Uses action_flags built with subject_price_m2_uf=None; filters severe comparable outliers vs comuna/pool references.",
        ),
        VariantLeakageAudit(
            name="outlier_filter_strict",
            production_safe=True,
            uses_subject_price=False,
            uses_subject_price_m2=False,
            uses_actual_error_or_ape=False,
            deployable_as_avm_engine=True,
            deployable_only_for_diagnostics=False,
            input_classes=safe_core,
            explanation="Uses action_flags built without observed subject price; stricter economic flags are based on comparable vs comuna/pool medians.",
        ),
        VariantLeakageAudit(
            name="economic_similarity_bonus",
            production_safe=True,
            uses_subject_price=False,
            uses_subject_price_m2=False,
            uses_actual_error_or_ape=False,
            deployable_as_avm_engine=True,
            deployable_only_for_diagnostics=False,
            input_classes=safe_core,
            explanation="Reranks by comparable price_m2 similarity to pool/comuna reference, not to subject observed price_m2.",
        ),
        VariantLeakageAudit(
            name="surface_rebalanced",
            production_safe=True,
            uses_subject_price=False,
            uses_subject_price_m2=False,
            uses_actual_error_or_ape=False,
            deployable_as_avm_engine=True,
            deployable_only_for_diagnostics=False,
            input_classes=safe_core,
            explanation="Uses subject surface/program/location and comparable economic reference; no APE or subject price in ranking.",
        ),
        VariantLeakageAudit(
            name="robust_estimator",
            production_safe=True,
            uses_subject_price=False,
            uses_subject_price_m2=False,
            uses_actual_error_or_ape=False,
            deployable_as_avm_engine=True,
            deployable_only_for_diagnostics=False,
            input_classes=safe_core,
            explanation="Median, trimmed mean and winsorized mean use only baseline comparable price_m2 values.",
        ),
        VariantLeakageAudit(
            name="robust_weighted_median",
            production_safe=True,
            uses_subject_price=False,
            uses_subject_price_m2=False,
            uses_actual_error_or_ape=False,
            deployable_as_avm_engine=True,
            deployable_only_for_diagnostics=False,
            input_classes=safe_core,
            explanation="Weighted median input is [(comparable price_m2_uf, baseline score)]; actual_clp is consumed only after estimate for APE.",
        ),
        VariantLeakageAudit(
            name="quality_weighted_estimator",
            production_safe=True,
            uses_subject_price=False,
            uses_subject_price_m2=False,
            uses_actual_error_or_ape=False,
            deployable_as_avm_engine=True,
            deployable_only_for_diagnostics=False,
            input_classes=safe_core,
            explanation="Quality penalties come from action_flags without subject price_m2 and from weak comparable location flags.",
        ),
        VariantLeakageAudit(
            name="combined_v2",
            production_safe=True,
            uses_subject_price=False,
            uses_subject_price_m2=False,
            uses_actual_error_or_ape=False,
            deployable_as_avm_engine=True,
            deployable_only_for_diagnostics=False,
            input_classes=safe_core,
            explanation="Combines mild pool/comuna outlier handling, rebalanced safe inputs and microzone_light; no subject observed price.",
        ),
    ]


def data_lineage() -> dict[str, Any]:
    return {
        "safe_estimation_path": [
            "target_listing is converted to Property via listing_as_property; Property does not include price.",
            "candidate pool excludes the target listing via exclude_leakage.",
            "baseline ranking uses filter_candidates and score_and_rank on subject attributes and comparable attributes.",
            "action_flags are built with subject_price_m2_uf=None.",
            "action_flags receive target as Property, so safe_price_m2_uf(target) cannot recover subject price.",
            "variant estimates are produced before APE is calculated.",
        ],
        "diagnostic_path": [
            "subject_ppm2 is computed from target_listing only to populate diagnostic_flags and report rows.",
            "baseline_contamination and top error cases use diagnostic flags after estimates are already built.",
            "actual_clp is passed to evaluate_variant only to compute ape_pct after estimate_clp.",
        ],
        "source_evidence": {
            "action_flags": "flags_for_candidates(... subject_price_m2_uf=None ...)",
            "diagnostic_flags": "flags_for_candidates(... subject_price_m2_uf=subject_ppm2 ...)",
            "robust_weighted_median": "weighted_median([(safe_price_m2_uf(listing, uf_rate), score) for score, listing in selected])",
            "ape_after_estimate": "ape = ape_pct(estimate, actual_clp) if estimate is not None ...",
        },
    }


def diagnostic_only_fields() -> list[str]:
    return [
        "actual_clp",
        "price_uf of the subject",
        "subject_price_m2_uf",
        "baseline_ape_pct",
        "variant_ape_pct",
        "delta_ape_pct",
        "price_m2_too_low_vs_subject",
        "price_m2_too_high_vs_subject",
        "probable_cause derived from baseline_ape",
        "top_baseline_error_cases ordering",
    ]


def source_metric_summary(source: dict[str, Any]) -> dict[str, Any]:
    summary = source.get("summary", {})
    variants = {row["name"]: row for row in source.get("variant_summaries", [])}
    best = summary.get("best_variant")
    return {
        "property_type": summary.get("property_type"),
        "evaluations": summary.get("successful_evaluations"),
        "baseline_mape_pct": summary.get("baseline_mape_pct"),
        "best_variant": best,
        "best_variant_mape_pct": summary.get("best_variant_mape_pct"),
        "best_gain_vs_baseline_pct_points": summary.get("best_gain_vs_baseline_pct_points"),
        "best_improvement_class": summary.get("best_improvement_class"),
        "baseline_p90_pct": variants.get("baseline", {}).get("p90_ape_pct"),
        "best_variant_p90_pct": variants.get(str(best), {}).get("p90_ape_pct"),
        "coverage_pct": variants.get(str(best), {}).get("coverage_pct"),
        "variant_summaries": {
            name: {
                "mape_pct": row.get("mape_pct"),
                "p90_ape_pct": row.get("p90_ape_pct"),
                "coverage_pct": row.get("coverage_pct"),
            }
            for name, row in variants.items()
        },
    }


def best_safe_variant(source: dict[str, Any], deployable: list[VariantLeakageAudit]) -> dict[str, Any]:
    safe_names = {item.name for item in deployable}
    variants = [
        row for row in source.get("variant_summaries", [])
        if row.get("name") in safe_names and row.get("mape_pct") is not None
    ]
    if not variants:
        return {"name": None, "mape_pct": None, "p90_ape_pct": None, "coverage_pct": None}
    best = min(variants, key=lambda row: row["mape_pct"])
    return {
        "name": best.get("name"),
        "mape_pct": best.get("mape_pct"),
        "p90_ape_pct": best.get("p90_ape_pct"),
        "coverage_pct": best.get("coverage_pct"),
    }


def answers(
    source_metrics: dict[str, Any],
    best_safe: dict[str, Any],
    robust: VariantLeakageAudit,
) -> dict[str, Any]:
    return {
        "is_17_791_to_17_1549_valid_for_production": (
            "yes as a shadow benchmark result: robust_weighted_median is production-safe from a leakage perspective. "
            "It still needs temporal/out-of-sample validation before changing production."
        ),
        "can_robust_weighted_median_be_used_in_manual_valuation": (
            "yes from leakage perspective; it uses subject physical/location inputs and comparable prices, not subject observed price."
        ),
        "can_it_be_used_in_listing_or_radar_analysis_without_contamination": (
            "yes if the listing being estimated is excluded from candidate comparables and its own asking price is not used as an input."
        ),
        "production_safe_variants": "all audited CQ v2 estimation variants are production-safe in this implementation.",
        "best_production_safe_variant": best_safe,
        "does_robust_weighted_median_use_leakage": not robust.production_safe,
        "why_robust_weighted_median_is_safe": robust.explanation,
        "rerun_benchmark_without_leakage_needed": False,
        "source_best_variant": {
            "name": source_metrics["best_variant"],
            "mape_pct": source_metrics["best_variant_mape_pct"],
            "gain_pct_points": source_metrics["best_gain_vs_baseline_pct_points"],
            "p90_pct": source_metrics["best_variant_p90_pct"],
            "coverage_pct": source_metrics["coverage_pct"],
        },
    }


def recommendation(best_safe: dict[str, Any]) -> dict[str, Any]:
    return {
        "recommended_path": "keep robust_weighted_median as the leading production-safe shadow candidate",
        "why": (
            f"Best production-safe variant is {best_safe['name']} with MAPE {best_safe['mape_pct']}, "
            f"P90 {best_safe['p90_ape_pct']} and coverage {best_safe['coverage_pct']}%."
        ),
        "next_checks_before_product": [
            "Run a temporal holdout or frozen train/test split.",
            "Verify candidate-pool medians exclude the subject listing in a production implementation.",
            "Keep subject-vs-price_m2 flags diagnostic-only.",
            "Add a service-level guard that manual valuation inputs cannot include observed target asking price.",
        ],
    }


def write_outputs(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / OUTPUT_JSON
    md_path = output_dir / OUTPUT_MD
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: dict[str, Any]) -> str:
    source = report["source_metrics"]
    answers_data = report["answers"]
    lines = [
        "# Comparable Quality v2 Leakage Audit",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Executive Summary",
        "",
        f"- Source report: `{report['summary']['source_report']}`",
        f"- Leakage found in best variant: `{report['summary']['leakage_found_in_best_variant']}`",
        f"- Rerun without leakage required: `{report['summary']['rerun_benchmark_without_leakage_required']}`",
        f"- Best original variant: `{source['best_variant']}` MAPE `{source['best_variant_mape_pct']}`",
        f"- Baseline MAPE: `{source['baseline_mape_pct']}`",
        f"- Gain: `{source['best_gain_vs_baseline_pct_points']}` pts ({source['best_improvement_class']})",
        "",
        "## Data Lineage",
        "",
    ]
    for item in report["data_lineage"]["safe_estimation_path"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Variant Audit", ""])
    lines.append(
        "| Variant | Production Safe | Uses Subject Price | Uses Subject Price/m2 | Uses APE/Error | AVM Deployable | Diagnostic Only |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in report["variant_audits"]:
        lines.append(
            f"| `{row['name']}` | {row['production_safe']} | {row['uses_subject_price']} | "
            f"{row['uses_subject_price_m2']} | {row['uses_actual_error_or_ape']} | "
            f"{row['deployable_as_avm_engine']} | {row['deployable_only_for_diagnostics']} |"
        )
    lines.extend(["", "## Diagnostic-Only Fields", ""])
    for item in report["diagnostic_only_fields"]:
        lines.append(f"- `{item}`")
    lines.extend(["", "## Explicit Answers", ""])
    for key, value in answers_data.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"- Path: `{report['recommendation']['recommended_path']}`",
            f"- Why: {report['recommendation']['why']}",
            "",
            "## What Not To Do Yet",
            "",
        ]
    )
    for item in report["do_not_do_yet"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Productive Safety", "", report["productive_safety"], ""])
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
