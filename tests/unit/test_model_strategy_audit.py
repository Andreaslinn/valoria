from __future__ import annotations

import json
import subprocess
from decimal import Decimal
from pathlib import Path

from domain.valuation.evaluation.dataset import build_evaluation_cases
from domain.valuation.evaluation.evaluator import EngineEvaluationRow
from domain.valuation.evaluation.hedonic_coverage import build_audit_records
from domain.valuation.evaluation.model_strategy_audit import (
    build_report,
    consensus_audit,
    evidence_summary,
    house_land_building_coverage,
    house_land_predicates,
    improvement_scenarios,
    load_json_report,
    markdown_report,
    ml_eligibility,
    report_dataset_hash,
    strategic_decisions,
    write_outputs,
)
from tests.unit.factories import make_listing


UF = Decimal("40000")


def _listing(idx: int, *, property_type: str, land: float | None = None, comuna: str = "nunoa"):
    price = 120_000_000 + idx * 1_000_000
    return make_listing(
        fingerprint=f"{property_type}-{idx}",
        property_type=property_type,
        title="Casa familiar" if property_type == "house" else "Departamento familiar",
        comuna=comuna,
        m2=100 if property_type == "house" else 60,
        built_area_m2=100 if property_type == "house" else 60,
        usable_area_m2=60 if property_type == "apartment" else None,
        land_area_m2=land,
        price_clp=price,
        price_currency="CLP",
        price_uf=Decimal(str(price / 40000)),
        raw_metadata={"nearby_metro": "Irarrazaval", "nearby_avenue": "Grecia"},
    )


def _records_cases_rows():
    listings = [
        *[_listing(idx, property_type="apartment", comuna="nunoa") for idx in range(8)],
        *[_listing(idx, property_type="house", land=250, comuna="la florida") for idx in range(8)],
        *[_listing(idx + 20, property_type="house", land=None, comuna="maipu") for idx in range(4)],
    ]
    cases = build_evaluation_cases(listings, seed=7)
    records = build_audit_records(listings, cases, uf_to_clp=UF)
    rows = []
    for idx, case in enumerate(cases):
        for engine in ("comparables_legacy", "comparables_canonical_outliers"):
            ape = 20.0 if engine == "comparables_legacy" else 15.0
            estimate = case.actual_price_clp * (Decimal("1") + Decimal(str(ape)) / Decimal("100"))
            rows.append(
                EngineEvaluationRow(
                    case_id=f"case-{idx}",
                    target_id=case.target_id,
                    engine_name=engine,
                    engine_version="test",
                    status="ok",
                    actual_price_clp=case.actual_price_clp,
                    estimated_price_clp=estimate,
                    absolute_percentage_error=ape,
                    signed_percentage_error=ape,
                    elapsed_ms=1.0,
                    property_type=case.target.property_type,
                    comuna=case.target.comuna,
                    geocode_precision=case.target.geocode_precision,
                    has_land_area=bool(case.target.land_area_m2),
                    comparables_used=5,
                )
            )
    return records, cases, rows


def test_load_json_report_and_evidence_summary() -> None:
    output_dir = Path(".tmp") / "phase3_model_strategy_tests"
    output_dir.mkdir(parents=True, exist_ok=True)
    phase1 = output_dir / "phase1.json"
    phase1.write_text(
        json.dumps({
            "benchmark": {"dataset_signature": "sig1", "segments": {"house": {"legacy": {"mape_pct": 33}}}},
            "ablation": {"variants_house": {"canonical_plus_outliers": {"mape_pct": 31}}},
        }),
        encoding="utf-8",
    )

    loaded, payload = load_json_report(phase1)
    evidence = evidence_summary(phase0b={}, phase1=payload, phase2={}, registry_engines=["comparables_legacy"])

    assert loaded.parse_ok is True
    assert evidence["main_practical_challenger"] == "comparables_canonical_outliers"
    assert "hedonic" in evidence["future_engines_not_registered"]


def test_ml_eligibility_levels_and_improvement_scenarios() -> None:
    records, cases, rows = _records_cases_rows()
    eligibility = ml_eligibility(records, cases)
    predicates = {
        "ML0_basic": lambda r: r.canonical_price_usable and r.effective_area_valid,
        "ML1_physical": lambda r: r.canonical_price_usable and r.effective_area_valid and r.bedrooms_valid and r.bathrooms_valid,
    }

    scenarios = improvement_scenarios(
        rows,
        records,
        eligibility,
        predicates,
        reference_engines=["comparables_canonical_outliers"],
    )

    assert eligibility["ML0_basic"]["global"]["observations"] == len(records)
    assert eligibility["ML3_house_enriched"]["apartment"]["observations"] == 0
    base20 = scenarios["comparables_canonical_outliers"]["levels"]["ML1_physical"]["scenarios"]["base_20pct"]
    assert base20["improvement_pp"] == 3.0


def test_house_land_building_coverage_and_scenarios() -> None:
    records, cases, rows = _records_cases_rows()
    coverage = house_land_building_coverage(records, cases)
    scenarios = improvement_scenarios(
        rows,
        records,
        {},
        house_land_predicates(),
        reference_engines=["comparables_legacy"],
    )

    assert coverage["houses_with_land"]["valid_count"] == 8
    assert coverage["communes_ge_5"] == 1
    assert coverage["component_viability"]["land_value"]["viable"] is False
    assert scenarios["comparables_legacy"]["levels"]["HLB0_land_price_area"]["eligible_cases"] == 8


def test_consensus_audit_detects_contract_connected_but_unregistered() -> None:
    audit = consensus_audit(Path("."), ["comparables_legacy", "comparables_canonical"])

    assert audit["imports_real_engine_result"] is True
    assert audit["imports_real_engine_context"] is True
    assert audit["registered"] is False
    assert audit["status"] == "contract_connected_but_not_operationally_ready"
    assert "ml" in audit["missing_expected_engines"]


def test_report_json_markdown_csv_and_determinism() -> None:
    records, cases, rows = _records_cases_rows()
    consensus = consensus_audit(Path("."), ["comparables_legacy", "comparables_canonical"])
    evidence = {
        "real_engines": ["comparables_legacy", "comparables_canonical"],
        "future_engines_not_registered": ["hedonic", "ml", "house_land_building", "valoria_consensus"],
        "main_practical_challenger": "comparables_canonical_outliers",
    }
    report = build_report(
        preflight={"branch": "test", "head": "abc", "git_status": "clean"},
        loaded_reports=[],
        evidence=evidence,
        records=records,
        cases=cases,
        rows=rows,
        consensus=consensus,
        canonical_reference="comparables_canonical_outliers",
    )
    output_dir = Path(".tmp") / "phase3_model_strategy_tests"
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = write_outputs(output_dir, report)

    assert json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    assert "Phase 3 Model Strategy Audit" in markdown_report(report)
    assert Path(paths["ml_csv"]).read_text(encoding="utf-8-sig").startswith("level")
    assert report_dataset_hash(report) == report_dataset_hash(report)
    decisions = strategic_decisions(
        ml_scenarios=report["ml"]["improvement_scenarios"],
        hlb_coverage=report["house_land_building"]["coverage"],
        consensus=report["valoria_consensus"],
        canonical_reference="comparables_canonical_outliers",
    )
    assert set(decisions.values()) <= {"go", "limited_pilot", "defer", "no_go"}


def test_no_training_or_db_write_tokens_and_cli_help() -> None:
    sources = [
        Path("domain/valuation/evaluation/model_strategy_audit.py").read_text(encoding="utf-8"),
        Path("scripts/audit_model_strategy.py").read_text(encoding="utf-8"),
    ]
    forbidden = ["sklearn", "catboost", "lightgbm", "xgboost", ".fit(", "joblib", "pickle", "session.add", ".commit("]

    assert not any(token in source for source in sources for token in forbidden)
    result = subprocess.run(
        ["python", "scripts/audit_model_strategy.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
