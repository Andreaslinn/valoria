"""Combination strategies for consensus estimates."""
from __future__ import annotations

from decimal import Decimal


def simple_average(estimates: dict[str, Decimal]) -> Decimal:
    if not estimates:
        raise ValueError("estimates cannot be empty")
    return sum(estimates.values()) / Decimal(str(len(estimates)))


def weighted_average(estimates: dict[str, Decimal], weights: dict[str, float]) -> Decimal:
    normalized = normalize_weights({name: weights.get(name, 0.0) for name in estimates})
    if not normalized:
        return simple_average(estimates)
    total = Decimal("0")
    for name, estimate in estimates.items():
        total += estimate * Decimal(str(normalized.get(name, 0.0)))
    return total


def confidence_weights(confidences: dict[str, float | None]) -> dict[str, float]:
    raw = {name: max(0.0, float(value or 0.0)) for name, value in confidences.items()}
    return normalize_weights(raw)


def weighted_median(estimates: dict[str, Decimal], weights: dict[str, float]) -> Decimal:
    if not estimates:
        raise ValueError("estimates cannot be empty")
    normalized = normalize_weights({name: weights.get(name, 0.0) for name in estimates})
    if not normalized:
        return Decimal(str(sorted(float(value) for value in estimates.values())[len(estimates) // 2]))

    cumulative = 0.0
    ordered = sorted(estimates.items(), key=lambda item: item[1])
    for name, value in ordered:
        cumulative += normalized.get(name, 0.0)
        if cumulative >= 0.5:
            return value
    return ordered[-1][1]


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    clean = {name: max(0.0, float(weight)) for name, weight in weights.items() if weight > 0}
    total = sum(clean.values())
    if total <= 0:
        return {}
    return {name: weight / total for name, weight in clean.items()}
