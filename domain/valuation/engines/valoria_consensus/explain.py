"""Structured explanations for consensus decisions."""
from __future__ import annotations

from collections.abc import Mapping


def build_explanations(
    *,
    weights: Mapping[str, float],
    weight_reasons: Mapping[str, str],
    excluded: Mapping[str, str],
    agreement_level: str,
) -> list[str]:
    explanations: list[str] = []
    for engine, weight in sorted(weights.items(), key=lambda item: item[1], reverse=True):
        reason = weight_reasons.get(engine, "included")
        explanations.append(f"{engine} weight {weight:.2f}: {reason}")

    for engine, reason in sorted(excluded.items()):
        explanations.append(f"{engine} excluded: {reason}")

    if agreement_level == "strong":
        explanations.append("high convergence among included engines")
    elif agreement_level == "moderate":
        explanations.append("moderate convergence among included engines")
    else:
        explanations.append("weak convergence; consensus confidence reduced")
    return explanations
