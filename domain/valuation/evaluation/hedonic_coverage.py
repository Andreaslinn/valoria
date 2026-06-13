"""Read-only hedonic viability diagnostics.

This module estimates data coverage and improvement ceilings for future
hedonic work. It deliberately does not fit or train any model.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from core.entities.listing import Listing
from core.normalization.property_type import normalize_property_type
from domain.geocoding.quality import has_valid_coordinates, normalized_precision_for
from domain.valuation.canonical_price import valuation_price_basis
from domain.valuation.evaluation.dataset import EvaluationCase
from domain.valuation.evaluation.evaluator import EngineEvaluationRow
from domain.valuation.price_surface import microzone_tokens_for
from domain.valuation.product_classification import PRODUCT_UNKNOWN, classify_product


SEGMENTS = ("global", "apartment", "house", "house_with_land", "house_without_land")
REDUCTION_SCENARIOS = {
    "conservative_5pct": 0.05,
    "conservative_10pct": 0.10,
    "base_15pct": 0.15,
    "base_20pct": 0.20,
    "aggressive_25pct": 0.25,
    "aggressive_30pct": 0.30,
}


@dataclass(frozen=True)
class AuditRecord:
    listing: Listing
    benchmark_case_id: str | None
    canonical_price_usable: bool
    canonical_exclusion_reason: str | None
    price_uf_usable: bool
    property_type: str
    comuna: str
    has_built_area: bool
    has_usable_area: bool
    has_land_area: bool
    effective_area_valid: bool
    land_building_ratio_valid: bool
    bedrooms_valid: bool
    bathrooms_valid: bool
    parking_present: bool
    scraped_at_valid: bool
    coordinates_valid: bool
    geocode_precision: str
    useful_geocode: bool
    fine_geo: bool
    microzone_useful: bool
    product_class: str
    product_class_usable: bool
    source: str
    price_clp: Decimal
    price_uf: Decimal | None
    built_area: float | None
    land_area: float | None

    @property
    def segment_keys(self) -> tuple[str, ...]:
        keys = ["global", self.property_type]
        if self.property_type == "house":
            keys.append("house_with_land" if self.has_land_area else "house_without_land")
        return tuple(keys)


def build_audit_records(
    listings: Sequence[Listing],
    cases: Sequence[EvaluationCase],
    *,
    uf_to_clp: Decimal,
) -> list[AuditRecord]:
    case_by_fingerprint = {case.listing.fingerprint: f"case-{idx}" for idx, case in enumerate(cases)}
    records: list[AuditRecord] = []
    for listing in sorted(listings, key=_listing_sort_key):
        basis = valuation_price_basis(listing, uf_to_clp)
        product = classify_product(listing)
        precision = normalized_precision_for(listing)
        microzones = microzone_tokens_for(listing)
        built = _built_area(listing)
        land = listing.land_area_m2 if listing.land_area_m2 and listing.land_area_m2 > 0 else None
        records.append(
            AuditRecord(
                listing=listing,
                benchmark_case_id=case_by_fingerprint.get(listing.fingerprint),
                canonical_price_usable=bool(basis.is_usable_for_valuation and basis.amount_uf is not None),
                canonical_exclusion_reason=basis.exclusion_reason,
                price_uf_usable=bool(listing.price_uf and listing.price_uf > 0),
                property_type=normalize_property_type(listing),
                comuna=str(listing.comuna or "unknown"),
                has_built_area=bool(listing.built_area_m2 and listing.built_area_m2 > 0),
                has_usable_area=bool(listing.usable_area_m2 and listing.usable_area_m2 > 0),
                has_land_area=bool(land),
                effective_area_valid=bool(built and 10 <= built <= 1000),
                land_building_ratio_valid=bool(built and land and 0.25 <= land / built <= 25),
                bedrooms_valid=0 <= int(listing.bedrooms or 0) <= 10,
                bathrooms_valid=0 <= int(listing.bathrooms or 0) <= 10,
                parking_present=listing.parking is not None and int(listing.parking) >= 0,
                scraped_at_valid=isinstance(listing.scraped_at, datetime),
                coordinates_valid=has_valid_coordinates(listing),
                geocode_precision=precision,
                useful_geocode=precision in {"address", "street"} or has_valid_coordinates(listing),
                fine_geo=precision in {"address", "street"} or bool(microzones),
                microzone_useful=bool(microzones),
                product_class=product.product_class,
                product_class_usable=product.product_class != PRODUCT_UNKNOWN,
                source=str(listing.source or "unknown"),
                price_clp=listing.price.clp,
                price_uf=listing.price_uf,
                built_area=built,
                land_area=land,
            )
        )
    return records


def dataset_signature(records: Sequence[AuditRecord]) -> str:
    payload = [
        {
            "fingerprint": record.listing.fingerprint,
            "id": record.listing.id,
            "price_clp": str(record.price_clp),
            "property_type": record.property_type,
            "comuna": record.comuna,
            "benchmark_case_id": record.benchmark_case_id,
        }
        for record in sorted(records, key=lambda item: _listing_sort_key(item.listing))
    ]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def individual_feature_coverage(records: Sequence[AuditRecord]) -> dict[str, Any]:
    features: dict[str, Callable[[AuditRecord], bool]] = {
        "canonical_price_clp": lambda r: r.canonical_price_usable,
        "price_uf_real": lambda r: r.price_uf_usable,
        "property_type": lambda r: r.property_type in {"apartment", "house"},
        "comuna": lambda r: bool(r.comuna and r.comuna != "unknown"),
        "built_area_m2": lambda r: r.has_built_area,
        "usable_area_m2": lambda r: r.has_usable_area,
        "land_area_m2": lambda r: r.has_land_area,
        "effective_area": lambda r: r.effective_area_valid,
        "land_building_ratio": lambda r: r.land_building_ratio_valid,
        "bedrooms": lambda r: r.bedrooms_valid,
        "bathrooms": lambda r: r.bathrooms_valid,
        "parking": lambda r: r.parking_present,
        "scraped_at": lambda r: r.scraped_at_valid,
        "lat_lon": lambda r: r.coordinates_valid,
        "geocode_address": lambda r: r.geocode_precision == "address",
        "geocode_street": lambda r: r.geocode_precision == "street",
        "useful_geocode": lambda r: r.useful_geocode,
        "microzone": lambda r: r.microzone_useful,
        "product_classification": lambda r: r.product_class_usable,
    }
    return {
        segment: {
            name: _coverage_row(_segment(records, segment), predicate)
            for name, predicate in features.items()
        }
        for segment in SEGMENTS
    }


def joint_eligibility(records: Sequence[AuditRecord], cases: Sequence[EvaluationCase]) -> dict[str, Any]:
    case_fingerprints = {case.listing.fingerprint for case in cases}
    specs = {
        "apartment": {
            "H0_min_structural": lambda r: _apt(r) and r.canonical_price_usable and r.comuna and r.effective_area_valid,
            "H1_basic": lambda r: _apt(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid,
            "H2_expanded": lambda r: _apt(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid and r.parking_present and r.scraped_at_valid and r.useful_geocode,
            "H3_fine_geo": lambda r: _apt(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid and r.parking_present and r.scraped_at_valid and r.fine_geo,
        },
        "house": {
            "H0_min_structural": lambda r: _house(r) and r.canonical_price_usable and r.comuna and r.effective_area_valid,
            "H1_basic": lambda r: _house(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid,
            "H2_land": lambda r: _house(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid and r.has_land_area,
            "H3_land_geo": lambda r: _house(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid and r.has_land_area and r.fine_geo,
            "H4_product": lambda r: _house(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid and r.has_land_area and r.fine_geo and r.product_class_usable,
        },
    }
    result: dict[str, Any] = {}
    for property_type, spec_map in specs.items():
        universe = [record for record in records if record.property_type == property_type]
        for spec_name, predicate in spec_map.items():
            eligible = [record for record in universe if predicate(record)]
            benchmark_covered = [
                record for record in eligible if record.listing.fingerprint in case_fingerprints
            ]
            result[f"{property_type}_{spec_name}"] = {
                **_effective_size(eligible, total=len(universe)),
                "benchmark_coverage_count": len(benchmark_covered),
                "benchmark_coverage_pct": _pct(len(benchmark_covered), len(cases)),
                "can_split_train_validation_test": len(eligible) >= 100 and _communes_at_least(eligible, 20) >= 3,
            }
    return result


def residual_error_by_features(
    rows: Sequence[EngineEvaluationRow],
    records: Sequence[AuditRecord],
) -> dict[str, Any]:
    by_fingerprint = {record.listing.fingerprint: record for record in records}
    by_case = {}
    for record in records:
        if record.benchmark_case_id:
            by_case[record.benchmark_case_id] = record
    dimensions: dict[str, Callable[[AuditRecord], str]] = {
        "coordinates": lambda r: "useful" if r.coordinates_valid else "not_useful",
        "microzone": lambda r: "useful" if r.microzone_useful else "missing",
        "land_area": lambda r: "present" if r.has_land_area else "missing",
        "bed_bath": lambda r: "complete" if r.bedrooms_valid and r.bathrooms_valid else "incomplete",
        "product_class": lambda r: "available" if r.product_class_usable else "unknown",
        "density": lambda r: "dense_comuna" if r.comuna in _dense_communes(records) else "sparse_comuna",
        "property_type": lambda r: r.property_type,
    }
    result: dict[str, Any] = {}
    for engine in sorted({row.engine_name for row in rows}):
        engine_rows = [row for row in rows if row.engine_name == engine]
        result[engine] = {}
        for dim_name, dim_fn in dimensions.items():
            groups: dict[str, list[EngineEvaluationRow]] = defaultdict(list)
            for row in engine_rows:
                record = by_case.get(row.case_id)
                if record is not None:
                    groups[dim_fn(record)].append(row)
            result[engine][dim_name] = {name: _error_summary(group) for name, group in sorted(groups.items())}
    return result


def improvement_scenarios(
    rows: Sequence[EngineEvaluationRow],
    records: Sequence[AuditRecord],
    eligibility: dict[str, Any],
) -> dict[str, Any]:
    by_case = {record.benchmark_case_id: record for record in records if record.benchmark_case_id}
    spec_predicates = _scenario_predicates()
    result: dict[str, Any] = {}
    for engine in sorted({row.engine_name for row in rows}):
        engine_rows = [
            row for row in rows
            if row.engine_name == engine and row.absolute_percentage_error is not None
        ]
        current = _error_summary(engine_rows)
        result[engine] = {"current": current, "specs": {}}
        for spec_name, predicate in spec_predicates.items():
            eligible_rows = [
                row for row in engine_rows
                if (record := by_case.get(row.case_id)) is not None and predicate(record)
            ]
            non_eligible_rows = [row for row in engine_rows if row not in eligible_rows]
            mape_eligible = _mean([row.absolute_percentage_error for row in eligible_rows])
            mape_non = _mean([row.absolute_percentage_error for row in non_eligible_rows])
            share = len(eligible_rows) / len(engine_rows) if engine_rows else 0.0
            scenarios: dict[str, Any] = {}
            for scenario_name, reduction in REDUCTION_SCENARIOS.items():
                new_mape = _weighted_mape(share, mape_eligible, reduction, mape_non)
                scenarios[scenario_name] = {
                    "estimated_mape_pct": round(new_mape, 2) if new_mape is not None else None,
                    "improvement_pp": round((current["mape_pct"] or 0) - new_mape, 2) if new_mape is not None else None,
                }
            upper = _weighted_mape(share, mape_eligible, 1.0, mape_non)
            result[engine]["specs"][spec_name] = {
                "eligible_cases": len(eligible_rows),
                "eligible_share_pct": round(share * 100, 2),
                "mape_eligible_pct": round(mape_eligible, 2) if mape_eligible is not None else None,
                "mape_non_eligible_pct": round(mape_non, 2) if mape_non is not None else None,
                "scenarios": scenarios,
                "upper_bound_unrealistic": {
                    "estimated_mape_pct": round(upper, 2) if upper is not None else None,
                    "improvement_pp": round((current["mape_pct"] or 0) - upper, 2) if upper is not None else None,
                },
            }
    return result


def target_quality(records: Sequence[AuditRecord]) -> dict[str, Any]:
    canonical = [record for record in records if record.canonical_price_usable]
    return {
        "canonical_usable": _coverage_row(records, lambda r: r.canonical_price_usable),
        "canonical_exclusion_reasons": dict(Counter(record.canonical_exclusion_reason or "usable" for record in records)),
        "price_clp_distribution": _distribution([float(record.price_clp) for record in canonical]),
        "price_uf_distribution": _distribution([float(record.price_uf) for record in canonical if record.price_uf]),
        "log_price_clp_distribution": _distribution([math.log(float(record.price_clp)) for record in canonical if record.price_clp > 0]),
        "source_counts": dict(Counter(record.source for record in records)),
        "product_class_counts": dict(Counter(record.product_class for record in records)),
        "geocode_precision_counts": dict(Counter(record.geocode_precision for record in records)),
    }


def candidate_specs(eligibility: dict[str, Any], scenarios: dict[str, Any]) -> list[dict[str, Any]]:
    canonical_outliers = scenarios.get("comparables_canonical_outliers", {}).get("specs", {})
    apt_gain = _base20_gain(canonical_outliers.get("apartment_H1_basic", {}))
    house_gain = _base20_gain(canonical_outliers.get("house_H1_basic", {}))
    geo_gain = _base20_gain(canonical_outliers.get("house_H3_land_geo", {}))
    return [
        {
            "name": "apartment_minimal",
            "formula": "log(price) ~ log(area) + bedrooms + bathrooms + parking + comuna + time_effect",
            "eligibility_level": "apartment_H1_basic",
            "coverage": eligibility.get("apartment_H1_basic", {}),
            "incremental_reference": canonical_outliers.get("apartment_H1_basic", {}),
            "decision": "limited_pilot" if apt_gain >= 0.75 else "defer",
            "risk": "No training yet; validate against canonical_plus_outliers and keep geography optional.",
        },
        {
            "name": "house_minimal_with_missing_land_indicator",
            "formula": "log(price) ~ log(built_area) + land_area_missing + log(land_area when present) + bedrooms + bathrooms + comuna + time_effect",
            "eligibility_level": "house_H1_basic",
            "coverage": eligibility.get("house_H1_basic", {}),
            "incremental_reference": canonical_outliers.get("house_H1_basic", {}),
            "decision": "limited_pilot" if house_gain >= 0.75 else "defer",
            "risk": "Land is too sparse for a strict land model; use missing indicator only in a future pilot.",
        },
        {
            "name": "geographic_variant",
            "formula": "minimal model + microzone or reliable coordinates",
            "eligibility_level": "house_H3_land_geo",
            "coverage": eligibility.get("house_H3_land_geo", {}),
            "incremental_reference": canonical_outliers.get("house_H3_land_geo", {}),
            "decision": "limited_pilot" if geo_gain >= 0.75 else "defer",
            "risk": "Fine geography coverage is the limiting factor.",
        },
    ]


def write_outputs(
    *,
    output_dir: Path,
    report: dict[str, Any],
    feature_rows: list[dict[str, Any]],
    segment_rows: list[dict[str, Any]],
    scenario_rows: list[dict[str, Any]],
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "phase2_hedonic_coverage_latest.json"
    md_path = output_dir / "phase2_hedonic_coverage_latest.md"
    feature_csv = output_dir / "phase2_feature_coverage.csv"
    segment_csv = output_dir / "phase2_segment_coverage.csv"
    scenario_csv = output_dir / "phase2_improvement_scenarios.csv"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    _write_csv(feature_csv, feature_rows)
    _write_csv(segment_csv, segment_rows)
    _write_csv(scenario_csv, scenario_rows)
    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "feature_csv": str(feature_csv),
        "segment_csv": str(segment_csv),
        "scenario_csv": str(scenario_csv),
    }


def markdown_report(report: dict[str, Any]) -> str:
    decision = report["decision"]
    lines = [
        "# Phase 2 Hedonic Viability Audit",
        "",
        f"Dataset signature: `{report['preflight']['dataset_signature']}`",
        f"Recommendation apartments: `{decision['apartments']}`",
        f"Recommendation houses: `{decision['houses']}`",
        f"Recommendation geography: `{decision['geographic']}`",
        f"Recommendation land: `{decision['land']}`",
        "",
        "## Universe",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key, value in report["universe"].items():
        if not isinstance(value, dict | list):
            lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Feature Coverage", ""])
    for segment in ("apartment", "house"):
        lines.extend([f"### {segment}", "", "| Feature | Valid % | Valid | Total |", "| --- | ---: | ---: | ---: |"])
        for feature, row in report["feature_coverage"][segment].items():
            lines.append(f"| `{feature}` | {row['valid_pct']} | {row['valid_count']} | {row['total']} |")
        lines.append("")
    lines.extend(["## Joint Eligibility", "", "| Spec | Eligible | Coverage | Communes | Can split |", "| --- | ---: | ---: | ---: | --- |"])
    for spec, row in report["joint_eligibility"].items():
        lines.append(f"| `{spec}` | {row['observations']} | {row['coverage_pct']} | {row['communes_covered']} | {row['can_split_train_validation_test']} |")
    lines.extend(["", "## Improvement Ceiling", ""])
    for engine, payload in report["improvement_scenarios"].items():
        lines.append(f"### {engine}")
        lines.append("")
        lines.append("| Spec | Eligible % | Current/elegible MAPE | Base 20 pp gain | Unrealistic upper gain |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        current = payload.get("current", {})
        for spec, spec_payload in payload.get("specs", {}).items():
            base20 = spec_payload["scenarios"]["base_20pct"]["improvement_pp"]
            upper = spec_payload["upper_bound_unrealistic"]["improvement_pp"]
            lines.append(
                f"| `{spec}` | {spec_payload['eligible_share_pct']} | "
                f"{current.get('mape_pct')} / {spec_payload['mape_eligible_pct']} | {base20} | {upper} |"
            )
        lines.append("")
    lines.extend(["## Roadmap", "", "| Item | Current | Target | Priority |", "| --- | ---: | ---: | --- |"])
    for item in report["roadmap"]:
        lines.append(f"| {item['item']} | {item['current_pct']} | {item['target_pct']} | {item['priority']} |")
    return "\n".join(lines)


def feature_rows(feature_coverage: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"segment": segment, "feature": feature, **row}
        for segment, features in feature_coverage.items()
        for feature, row in features.items()
    ]


def segment_rows(joint: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"spec": spec, **row} for spec, row in joint.items()]


def scenario_rows(scenarios: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for engine, payload in scenarios.items():
        for spec, spec_payload in payload.get("specs", {}).items():
            for scenario, values in spec_payload["scenarios"].items():
                rows.append({"engine": engine, "spec": spec, "scenario": scenario, **values})
            rows.append({"engine": engine, "spec": spec, "scenario": "upper_bound_unrealistic", **spec_payload["upper_bound_unrealistic"]})
    return rows


def _coverage_row(records: Sequence[AuditRecord], predicate: Callable[[AuditRecord], bool]) -> dict[str, Any]:
    total = len(records)
    valid = sum(1 for record in records if predicate(record))
    present = valid
    return {
        "total": total,
        "present_count": present,
        "present_pct": _pct(present, total),
        "valid_count": valid,
        "valid_pct": _pct(valid, total),
        "invalid_count": total - valid,
    }


def _effective_size(records: Sequence[AuditRecord], *, total: int) -> dict[str, Any]:
    counts = Counter(record.comuna for record in records)
    values = sorted(counts.values())
    return {
        "observations": len(records),
        "coverage_pct": _pct(len(records), total),
        "communes_covered": len(counts),
        "median_observations_per_comuna": _percentile(values, 50),
        "p10_observations_per_comuna": _percentile(values, 10),
        "p25_observations_per_comuna": _percentile(values, 25),
        "p75_observations_per_comuna": _percentile(values, 75),
        "p90_observations_per_comuna": _percentile(values, 90),
        "communes_lt_10": sum(1 for value in values if value < 10),
        "communes_lt_20": sum(1 for value in values if value < 20),
        "communes_ge_30": sum(1 for value in values if value >= 30),
        "communes_ge_50": sum(1 for value in values if value >= 50),
    }


def _error_summary(rows: Sequence[EngineEvaluationRow]) -> dict[str, Any]:
    successful = [row for row in rows if row.absolute_percentage_error is not None]
    apes = [row.absolute_percentage_error for row in successful if row.absolute_percentage_error is not None]
    signed = [row.signed_percentage_error for row in successful if row.signed_percentage_error is not None]
    return {
        "total_cases": len(rows),
        "successful": len(successful),
        "coverage_pct": _pct(len(successful), len(rows)),
        "mape_pct": round(_mean(apes), 2) if apes else None,
        "median_ape_pct": round(float(median(apes)), 2) if apes else None,
        "p90_ape_pct": _percentile(apes, 90),
        "bias_pct": round(_mean(signed), 2) if signed else None,
        "error_gt_50_pct": _pct(sum(1 for value in apes if value > 50), len(apes)),
        "error_gt_100_pct": _pct(sum(1 for value in apes if value > 100), len(apes)),
    }


def _scenario_predicates() -> dict[str, Callable[[AuditRecord], bool]]:
    return {
        "apartment_H0_min_structural": lambda r: _apt(r) and _common_h0(r),
        "apartment_H1_basic": lambda r: _apt(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid,
        "apartment_H2_expanded": lambda r: _apt(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid and r.parking_present and r.scraped_at_valid and r.useful_geocode,
        "apartment_H3_fine_geo": lambda r: _apt(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid and r.parking_present and r.scraped_at_valid and r.fine_geo,
        "house_H0_min_structural": lambda r: _house(r) and _common_h0(r),
        "house_H1_basic": lambda r: _house(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid,
        "house_H2_land": lambda r: _house(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid and r.has_land_area,
        "house_H3_land_geo": lambda r: _house(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid and r.has_land_area and r.fine_geo,
        "house_H4_product": lambda r: _house(r) and _common_h0(r) and r.bedrooms_valid and r.bathrooms_valid and r.has_land_area and r.fine_geo and r.product_class_usable,
    }


def _common_h0(record: AuditRecord) -> bool:
    return record.canonical_price_usable and bool(record.comuna) and record.effective_area_valid and record.property_type in {"apartment", "house"}


def _apt(record: AuditRecord) -> bool:
    return record.property_type == "apartment"


def _house(record: AuditRecord) -> bool:
    return record.property_type == "house"


def _segment(records: Sequence[AuditRecord], segment: str) -> list[AuditRecord]:
    if segment == "global":
        return list(records)
    if segment == "house_with_land":
        return [record for record in records if record.property_type == "house" and record.has_land_area]
    if segment == "house_without_land":
        return [record for record in records if record.property_type == "house" and not record.has_land_area]
    return [record for record in records if record.property_type == segment]


def _dense_communes(records: Sequence[AuditRecord], threshold: int = 50) -> set[str]:
    counts = Counter(record.comuna for record in records)
    return {comuna for comuna, count in counts.items() if count >= threshold}


def _communes_at_least(records: Sequence[AuditRecord], threshold: int) -> int:
    counts = Counter(record.comuna for record in records)
    return sum(1 for value in counts.values() if value >= threshold)


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    clean = sorted(value for value in values if value is not None and math.isfinite(float(value)))
    return {
        "count": len(clean),
        "min": round(clean[0], 4) if clean else None,
        "p10": _percentile(clean, 10),
        "p25": _percentile(clean, 25),
        "p50": _percentile(clean, 50),
        "p75": _percentile(clean, 75),
        "p90": _percentile(clean, 90),
        "max": round(clean[-1], 4) if clean else None,
    }


def _weighted_mape(
    share_eligible: float,
    mape_eligible: float | None,
    reduction: float,
    mape_non_eligible: float | None,
) -> float | None:
    if mape_eligible is None and mape_non_eligible is None:
        return None
    eligible_component = share_eligible * (mape_eligible or 0.0) * (1 - reduction)
    non_component = (1 - share_eligible) * (mape_non_eligible or 0.0)
    return eligible_component + non_component


def _base20_gain(spec_payload: dict[str, Any]) -> float:
    value = (
        spec_payload.get("scenarios", {})
        .get("base_20pct", {})
        .get("improvement_pp")
    )
    return float(value or 0.0)


def _built_area(listing: Listing) -> float | None:
    value = listing.built_area_m2 or listing.usable_area_m2 or listing.m2
    return float(value) if value and value > 0 else None


def _listing_sort_key(listing: Listing) -> tuple[str, str, str, str]:
    return (
        str(listing.id if listing.id is not None else ""),
        str(listing.source or ""),
        str(listing.external_id or ""),
        str(listing.fingerprint or ""),
    )


def _pct(value: int | float, total: int | float) -> float:
    return round(float(value) / float(total) * 100, 2) if total else 0.0


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _percentile(values: Sequence[float | int], pct: int) -> float | None:
    clean = sorted(float(value) for value in values)
    if not clean:
        return None
    if len(clean) == 1:
        return round(clean[0], 2)
    rank = (len(clean) - 1) * pct / 100
    lower = int(rank)
    upper = min(lower + 1, len(clean) - 1)
    weight = rank - lower
    return round(clean[lower] * (1 - weight) + clean[upper] * weight, 2)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
