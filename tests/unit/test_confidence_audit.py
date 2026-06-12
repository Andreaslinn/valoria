from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from scripts.confidence_audit import (
    ConfidenceAuditRow,
    _confidence_bucket,
    _pearson,
    evaluate_confidence_holdout,
    summarize_confidence_rows,
)
from tests.unit.factories import make_listing

UF = Decimal("37000")


def _listing(index: int, **kwargs):
    listing = make_listing(fingerprint=f"fp-{index}", **kwargs)
    listing.id = index
    return listing


def _row(*, confidence: float, ape: float, quality: str = "acceptable") -> ConfidenceAuditRow:
    return ConfidenceAuditRow(
        listing_id=1,
        fingerprint="fp",
        comuna="nunoa",
        property_type="apartment",
        m2_bucket="60-79",
        actual_clp=100_000_000,
        estimated_clp=100_000_000 * (1 + ape / 100),
        confidence=confidence,
        confidence_bucket=_confidence_bucket(confidence),
        absolute_error_clp=100_000_000 * ape / 100,
        ape_pct=ape,
        comparable_quality_level=quality,
        coverage_metrics={
            "address_level_geo_ratio": 1.0,
            "same_microzone_ratio": 1.0,
            "m2_bucket_coverage": 1.0,
            "property_type_consistency": 1.0,
            "price_per_m2_dispersion": 10.0,
        },
        status="ok",
        reason=None,
        detail=None,
    )


def test_confidence_bucket_edges() -> None:
    assert _confidence_bucket(0.0) == "0.0-0.2"
    assert _confidence_bucket(0.2) == "0.2-0.4"
    assert _confidence_bucket(0.8) == "0.8-1.0"
    assert _confidence_bucket(1.0) == "0.8-1.0"


def test_pearson_detects_inverse_confidence_error_signal() -> None:
    value = _pearson([0.1, 0.5, 0.9], [50.0, 20.0, 5.0])

    assert value is not None
    assert value < -0.9


def test_summarize_confidence_rows_groups_by_bucket_and_concludes_partial_signal() -> None:
    rows = [
        _row(confidence=0.1, ape=50),
        _row(confidence=0.3, ape=35),
        _row(confidence=0.5, ape=25),
        _row(confidence=0.7, ape=18),
        _row(confidence=0.9, ape=10),
    ]

    report = summarize_confidence_rows(
        rows,
        holdout={"listing_ids": [1, 2, 3, 4, 5], "strata": []},
        total_active=20,
        training_count=15,
        holdout_count=5,
        stale_holdout_ids=0,
        holdout_path=Path("holdout.json"),
        min_samples=5,
    )

    assert report["summary"]["status"] == "ok"
    assert report["summary"]["conclusion"] in {"serves", "serves_partially"}
    assert report["by_confidence_bucket"]["0.0-0.2"]["n"] == 1
    assert report["by_confidence_bucket"]["0.8-1.0"]["mape_pct"] == 10.0


def test_evaluate_confidence_holdout_rejects_training_leakage() -> None:
    holdout = [_listing(1)]
    training = [_listing(i) for i in range(1, 8)]

    with pytest.raises(ValueError, match="holdout leakage"):
        evaluate_confidence_holdout(holdout, training, uf_to_clp=UF)


def test_evaluate_confidence_holdout_records_quality_metrics() -> None:
    holdout = [_listing(100, price_clp=180_000_000)]
    training = [_listing(i, price_clp=180_000_000) for i in range(1, 8)]

    rows = evaluate_confidence_holdout(holdout, training, uf_to_clp=UF)

    assert rows[0].status == "ok"
    assert rows[0].confidence is not None
    assert rows[0].ape_pct == 0.0
    assert rows[0].comparable_quality_level in {"poor", "weak", "acceptable", "strong"}
    assert rows[0].coverage_metrics["comparables_used"] == 7
    assert "property_type_consistency" in rows[0].coverage_metrics
