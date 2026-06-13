from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from domain.valuation.evaluation.dataset import build_evaluation_cases
from domain.valuation.evaluation.evaluator import EngineEvaluationRow
from domain.valuation.evaluation.hedonic_coverage import (
    build_audit_records,
    dataset_signature,
    feature_rows,
    improvement_scenarios,
    individual_feature_coverage,
    joint_eligibility,
    markdown_report,
    residual_error_by_features,
    scenario_rows,
    segment_rows,
    target_quality,
    write_outputs,
)
from tests.unit.factories import make_listing


UF = Decimal("40000")


def _listing(idx: int, *, property_type: str, land: float | None = None, price: int = 100_000_000):
    return make_listing(
        fingerprint=f"{property_type}-{idx}",
        property_type=property_type,
        title="Casa familiar" if property_type == "house" else "Departamento familiar",
        m2=100 if property_type == "house" else 60,
        built_area_m2=100 if property_type == "house" else 60,
        land_area_m2=land,
        price_clp=price,
        price_currency="CLP",
        price_uf=Decimal(str(price / 40000)),
    )


def _records_and_cases():
    listings = [
        *[_listing(idx, property_type="apartment", price=120_000_000 + idx) for idx in range(6)],
        *[_listing(idx, property_type="house", land=250, price=220_000_000 + idx) for idx in range(6)],
    ]
    cases = build_evaluation_cases(listings, seed=3)
    records = build_audit_records(listings, cases, uf_to_clp=UF)
    return records, cases


def _rows(cases, engine_name: str = "comparables_canonical_outliers"):
    rows = []
    for idx, case in enumerate(cases):
        estimate = case.actual_price_clp * Decimal("1.10")
        rows.append(
            EngineEvaluationRow(
                case_id=f"case-{idx}",
                target_id=case.target_id,
                engine_name=engine_name,
                engine_version="test",
                status="ok",
                actual_price_clp=case.actual_price_clp,
                estimated_price_clp=estimate,
                absolute_percentage_error=10.0,
                signed_percentage_error=10.0,
                elapsed_ms=1.0,
                property_type=case.target.property_type,
                comuna=case.target.comuna,
                geocode_precision=case.target.geocode_precision,
                has_land_area=bool(case.target.land_area_m2),
                comparables_used=5,
            )
        )
    return rows


def test_individual_feature_coverage_distinguishes_segments() -> None:
    records, cases = _records_and_cases()

    coverage = individual_feature_coverage(records)

    assert coverage["global"]["canonical_price_clp"]["valid_count"] == len(records)
    assert coverage["apartment"]["land_area_m2"]["valid_pct"] == 0.0
    assert coverage["house"]["land_area_m2"]["valid_pct"] == 100.0
    assert dataset_signature(records) == dataset_signature(list(reversed(records)))


def test_joint_eligibility_cascades_h0_to_h4() -> None:
    records, cases = _records_and_cases()

    joint = joint_eligibility(records, cases)

    assert joint["apartment_H0_min_structural"]["observations"] == 6
    assert joint["apartment_H1_basic"]["observations"] == 6
    assert joint["house_H2_land"]["observations"] == 6
    assert joint["house_H4_product"]["observations"] == 6


def test_residual_error_and_improvement_scenarios() -> None:
    records, cases = _records_and_cases()
    rows = _rows(cases)
    joint = joint_eligibility(records, cases)

    residual = residual_error_by_features(rows, records)
    scenarios = improvement_scenarios(rows, records, joint)

    assert residual["comparables_canonical_outliers"]["property_type"]["apartment"]["mape_pct"] == 10.0
    spec = scenarios["comparables_canonical_outliers"]["specs"]["house_H1_basic"]
    assert spec["scenarios"]["base_20pct"]["estimated_mape_pct"] <= 10.0
    assert spec["upper_bound_unrealistic"]["estimated_mape_pct"] == 5.0


def test_target_quality_and_reports_are_serializable() -> None:
    records, cases = _records_and_cases()
    rows = _rows(cases)
    joint = joint_eligibility(records, cases)
    features = individual_feature_coverage(records)
    scenarios = improvement_scenarios(rows, records, joint)
    report = {
        "preflight": {"dataset_signature": dataset_signature(records)},
        "universe": {"active_listings": len(records)},
        "target_quality": target_quality(records),
        "feature_coverage": features,
        "joint_eligibility": joint,
        "improvement_scenarios": scenarios,
        "decision": {
            "apartments": "limited_pilot",
            "houses": "limited_pilot",
            "geographic": "defer",
            "land": "limited_pilot",
        },
        "roadmap": [
            {"item": "microzone", "current_pct": 0.0, "target_pct": 50.0, "priority": "high"}
        ],
    }
    output_dir = Path(".tmp") / "phase2_hedonic_coverage"

    paths = write_outputs(
        output_dir=output_dir,
        report=report,
        feature_rows=feature_rows(features),
        segment_rows=segment_rows(joint),
        scenario_rows=scenario_rows(scenarios),
    )

    assert json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    assert "Phase 2 Hedonic Viability Audit" in markdown_report(report)
    assert Path(paths["feature_csv"]).read_text(encoding="utf-8-sig").startswith("feature")


def test_audit_module_does_not_import_training_libraries() -> None:
    source = Path("domain/valuation/evaluation/hedonic_coverage.py").read_text(encoding="utf-8")

    forbidden = ["sklearn", "statsmodels", "fit(", "Ridge", "ElasticNet", "LinearRegression"]
    assert not any(token in source for token in forbidden)
