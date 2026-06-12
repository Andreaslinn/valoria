"""Validation-only calibration helpers for consensus weights."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SegmentWeights:
    segment: str
    n_validation: int
    weights: dict[str, float]
    strategy: str


def inverse_error_weights(
    validation_rows: Iterable[Mapping[str, Any]],
    *,
    segment_key: str = "segment",
    engine_key: str = "engine_name",
    error_key: str = "absolute_percentage_error",
    min_validation_n: int = 30,
) -> dict[str, SegmentWeights]:
    """Build simple validation weights from inverse mean APE.

    This helper must be fed validation rows only. It deliberately does not know
    about test rows.
    """
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in validation_rows:
        segment = str(row.get(segment_key) or "global")
        engine = str(row.get(engine_key) or "")
        error = row.get(error_key)
        if not engine or error is None:
            continue
        grouped[segment][engine].append(float(error))

    result: dict[str, SegmentWeights] = {}
    for segment, by_engine in grouped.items():
        total_n = sum(len(values) for values in by_engine.values())
        if total_n < min_validation_n:
            continue
        raw: dict[str, float] = {}
        for engine, values in by_engine.items():
            if not values:
                continue
            mean_error = sum(values) / len(values)
            raw[engine] = 1.0 / max(mean_error, 0.001)
        total = sum(raw.values())
        if total <= 0:
            continue
        result[segment] = SegmentWeights(
            segment=segment,
            n_validation=total_n,
            weights={engine: value / total for engine, value in raw.items()},
            strategy="inverse_validation_error",
        )
    return result
