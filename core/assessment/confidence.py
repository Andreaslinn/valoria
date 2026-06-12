"""Canonical AVM confidence contract.

``confidence_score`` is the final model confidence in [0, 1] after valuation
reliability guardrails have been applied. ``confidence_label`` is the stable
presentation bucket derived from that score.

Confidence is not comparable-set quality: comparable quality describes the
health of the evidence used by the valuation. Confidence is the model's final
numeric confidence after reliability penalties.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from core.assessment.contracts import ConfidencePayload
from core.value_objects.score import Score


class ConfidenceLabel:
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT_DATA = "insufficient_data"
    UNKNOWN = "unknown"


CONFIDENCE_LABELS = frozenset(
    {
        ConfidenceLabel.HIGH,
        ConfidenceLabel.MEDIUM,
        ConfidenceLabel.LOW,
        ConfidenceLabel.INSUFFICIENT_DATA,
        ConfidenceLabel.UNKNOWN,
    }
)


@dataclass(frozen=True)
class ConfidenceContract:
    confidence_score: float | None
    confidence_label: str
    confidence_reasons: tuple[str, ...] = ()
    confidence_risk_flags: tuple[str, ...] = ()

    @property
    def legacy_confidence(self) -> str:
        return self.confidence_label

    def to_payload(self) -> ConfidencePayload:
        return {
            "confidence": self.legacy_confidence,
            "confidence_score": self.confidence_score,
            "confidence_label": self.confidence_label,
            "confidence_reasons": list(self.confidence_reasons),
            "confidence_risk_flags": list(self.confidence_risk_flags),
        }


def confidence_label_for_score(value: float | int | Score | None) -> str:
    score = confidence_score_value(value)
    if score is None:
        return ConfidenceLabel.INSUFFICIENT_DATA
    if score >= 0.75:
        return ConfidenceLabel.HIGH
    if score >= 0.5:
        return ConfidenceLabel.MEDIUM
    return ConfidenceLabel.LOW


def confidence_score_value(value: float | int | Score | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Score):
        return round(value.value, 4)
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return None


def normalize_confidence_label(value: Any) -> str:
    if value is None or value == "":
        return ConfidenceLabel.UNKNOWN
    if isinstance(value, int | float) and not isinstance(value, bool):
        return confidence_label_for_score(value)
    text = str(value).strip().lower()
    if text in CONFIDENCE_LABELS:
        return text
    return ConfidenceLabel.UNKNOWN


def build_confidence_contract(
    *,
    score: float | int | Score | None,
    base_score: float | int | Score | None = None,
    reliability_warnings: Iterable[str] = (),
) -> ConfidenceContract:
    confidence_score = confidence_score_value(score)
    confidence_label = confidence_label_for_score(score)
    risk_flags = _dedupe(reliability_warnings)
    reasons: list[str] = []
    base = confidence_score_value(base_score)
    if confidence_score is None:
        reasons.append("insufficient_data")
    elif base is not None and confidence_score < base:
        reasons.append("reliability_penalty_applied")
    reasons.extend(f"reliability:{flag}" for flag in risk_flags)
    return ConfidenceContract(
        confidence_score=confidence_score,
        confidence_label=confidence_label,
        confidence_reasons=tuple(_dedupe(reasons)),
        confidence_risk_flags=tuple(risk_flags),
    )


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
