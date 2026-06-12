from __future__ import annotations

from core.assessment.confidence import (
    ConfidenceLabel,
    build_confidence_contract,
    confidence_label_for_score,
    normalize_confidence_label,
)
from core.value_objects.score import Score


def test_confidence_label_thresholds_are_shared_contract() -> None:
    assert confidence_label_for_score(0.75) == ConfidenceLabel.HIGH
    assert confidence_label_for_score(0.5) == ConfidenceLabel.MEDIUM
    assert confidence_label_for_score(0.49) == ConfidenceLabel.LOW
    assert confidence_label_for_score(None) == ConfidenceLabel.INSUFFICIENT_DATA


def test_build_confidence_contract_keeps_score_label_and_reliability_reasons() -> None:
    contract = build_confidence_contract(
        score=Score.clamped(0.62),
        base_score=Score.clamped(0.8),
        reliability_warnings=["low_comparable_count", "low_comparable_count"],
    )

    assert contract.confidence_score == 0.62
    assert contract.confidence_label == "medium"
    assert contract.legacy_confidence == "medium"
    assert contract.confidence_risk_flags == ("low_comparable_count",)
    assert contract.confidence_reasons == (
        "reliability_penalty_applied",
        "reliability:low_comparable_count",
    )


def test_normalize_confidence_label_accepts_numeric_and_legacy_label_values() -> None:
    assert normalize_confidence_label(0.8) == "high"
    assert normalize_confidence_label("medium") == "medium"
    assert normalize_confidence_label("unexpected") == "unknown"

