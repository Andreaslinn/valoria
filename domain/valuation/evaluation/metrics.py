"""Evaluation metrics for valuation engine runs."""
from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any

from domain.valuation.evaluation.evaluator import EngineEvaluationRow


def summarize_results(rows: list[EngineEvaluationRow]) -> dict[str, Any]:
    return {
        "global": _summary(rows),
        "by_engine": _group_summary(rows, lambda row: row.engine_name),
        "by_property_type": _group_summary(rows, lambda row: row.property_type),
        "by_geocode_precision": _group_summary(rows, lambda row: row.geocode_precision or "unknown"),
        "by_house_land": _group_summary(
            [row for row in rows if row.property_type == "house"],
            lambda row: "house_with_land" if row.has_land_area else "house_without_land",
        ),
        "by_comuna": _group_summary(rows, lambda row: row.comuna, min_count=5),
    }


def _group_summary(
    rows: list[EngineEvaluationRow],
    key_fn,
    *,
    min_count: int = 1,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[EngineEvaluationRow]] = defaultdict(list)
    for row in rows:
        grouped[str(key_fn(row))].append(row)
    return {
        key: _summary(group_rows)
        for key, group_rows in sorted(grouped.items())
        if len(group_rows) >= min_count
    }


def _summary(rows: list[EngineEvaluationRow]) -> dict[str, Any]:
    total = len(rows)
    successful = [row for row in rows if row.estimated_price_clp is not None and row.absolute_percentage_error is not None]
    apes = [row.absolute_percentage_error for row in successful if row.absolute_percentage_error is not None]
    signed = [row.signed_percentage_error for row in successful if row.signed_percentage_error is not None]
    abs_clp = [
        abs(float(row.estimated_price_clp - row.actual_price_clp))
        for row in successful
        if row.estimated_price_clp is not None
    ]
    return {
        "total_cases": total,
        "successful": len(successful),
        "failed": total - len(successful),
        "coverage_pct": round(len(successful) / total * 100, 2) if total else 0.0,
        "mape_pct": _mean(apes),
        "median_ape_pct": _median(apes),
        "p90_ape_pct": _percentile(apes, 90),
        "mae_clp": round(_mean_raw(abs_clp), 2) if abs_clp else None,
        "signed_bias_pct": _mean(signed),
        "overvaluation_rate_pct": _rate([value for value in signed if value > 0], signed),
        "undervaluation_rate_pct": _rate([value for value in signed if value < 0], signed),
        "error_gt_50_pct": _rate([value for value in apes if value > 50], apes),
        "error_gt_100_pct": _rate([value for value in apes if value > 100], apes),
    }


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _mean_raw(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: list[float]) -> float | None:
    return round(float(median(values)), 2) if values else None


def _percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = (len(ordered) - 1) * pct / 100
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def _rate(selected: list[float], population: list[float]) -> float | None:
    if not population:
        return None
    return round(len(selected) / len(population) * 100, 2)
