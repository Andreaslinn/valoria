from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from domain.valuation.engines.contracts import EngineContext, EngineRequest, EngineResult, EngineStatus
from domain.valuation.engines.registry import EngineRegistry
from domain.valuation.evaluation.dataset import build_evaluation_cases, infer_uf_rate
from domain.valuation.evaluation.evaluator import evaluate_engines
from domain.valuation.evaluation.metrics import summarize_results
from domain.valuation.evaluation.reports import write_evaluation_reports
from tests.unit.factories import make_listing


class StaticEngine:
    name = "static"
    version = "v1"

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        return EngineResult(
            engine_name=self.name,
            engine_version=self.version,
            status=EngineStatus.OK,
            estimated_price_clp=100_000_000,
            confidence=0.8,
            comparables_used=len(context.candidates),
        )


def test_dataset_excludes_target_and_duplicates() -> None:
    target = make_listing(fingerprint="same", price_clp=100_000_000, price_uf=Decimal("2500"))
    duplicate = make_listing(fingerprint="same", price_clp=100_000_000, price_uf=Decimal("2500"))
    candidate = make_listing(fingerprint="other", price_clp=110_000_000, price_uf=Decimal("2750"))

    cases = build_evaluation_cases([target, duplicate, candidate], seed=1)

    assert cases
    first = next(case for case in cases if case.listing.fingerprint == "same")
    assert [listing.fingerprint for listing in first.candidates] == ["other"]


def test_infer_uf_rate_uses_local_canonical_prices() -> None:
    listings = [
        make_listing(fingerprint="a", price_clp=100_000_000, price_uf=Decimal("2500")),
        make_listing(fingerprint="b", price_clp=120_000_000, price_uf=Decimal("3000")),
    ]

    assert infer_uf_rate(listings) == Decimal("40000")


def test_evaluator_metrics_and_reports() -> None:
    listings = [
        make_listing(fingerprint=f"row-{idx}", price_clp=100_000_000, price_uf=Decimal("2500"))
        for idx in range(6)
    ]
    cases = build_evaluation_cases(listings, limit=2, seed=1)
    registry = EngineRegistry()
    registry.register(StaticEngine())

    rows = evaluate_engines(cases=cases, registry=registry, engine_names=["static"], uf_to_clp=Decimal("40000"))
    summary = summarize_results(rows)
    output_dir = Path(".tmp") / "phase0b_test_framework"
    paths = write_evaluation_reports(
        output_dir=output_dir,
        rows=rows,
        summary=summary,
        metadata={"engines": ["static"], "git_commit": "test", "git_status": "clean"},
    )

    assert summary["global"]["total_cases"] == 2
    assert summary["global"]["coverage_pct"] == 100.0
    assert summary["global"]["mape_pct"] == 0.0
    assert json.loads((output_dir / "valuation_engine_benchmark.json").read_text(encoding="utf-8"))
    assert paths["markdown"].endswith(".md")
