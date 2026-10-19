"""Specified SII kNN, closed H surface, weighted empirical quantiles.

No learned coefficients, price trimming or calibration against the holdout.
Temporal and role leakage guards are part of the estimator, not only the audit.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np

K = 10
WEIGHTS = {"area": 0.30, "location": 0.30, "age": 0.30, "date": 0.10}


def weighted_quantile(values, weights, q):
    pairs = sorted(zip(values, weights, strict=True))
    total = sum(w for _, w in pairs)
    if not pairs or total <= 0 or not 0 <= q <= 1:
        raise ValueError("invalid_weighted_quantile")
    if any(w < 0 or not math.isfinite(v) or not math.isfinite(w) for v, w in pairs):
        raise ValueError("invalid_weighted_quantile")
    cumulative = 0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= total * q:
            return float(value)
    return float(pairs[-1][0])


class ClosingKNN:
    def __init__(self, rows: list[dict], excluded_roles=frozenset()):
        self.rows = [
            r
            for r in rows
            if r["rol"] not in excluded_roles
            and r.get("area") is not None
            and math.isfinite(r["area"])
            and r["area"] > 0
            and r.get("uf") is not None
            and math.isfinite(r["uf"])
            and r["uf"] > 0
            and r.get("year")
            and r.get("building")
            and r["date"] >= "2024-01-01"
        ]
        self.groups = {}
        for r in self.rows:
            self.groups.setdefault((r["comuna"], r["kind"]), []).append(r)
        self.arrays = {}
        for key, group in self.groups.items():
            self.arrays[key] = (
                np.array([r["area"] for r in group]),
                np.array([r["year"] for r in group]),
                np.array([date.fromisoformat(r["date"]).toordinal() for r in group]),
                np.array([r["block"] for r in group]),
                np.array([r["building"] for r in group]),
                np.array([r["rol"] for r in group]),
                np.array([r["raw_id"] for r in group]),
            )

    def estimate(self, target: dict) -> dict:
        key = (target["comuna"], target["kind"])
        if (
            key not in self.groups
            or target.get("area") is None
            or not math.isfinite(target["area"])
            or target["area"] <= 0
            or not target.get("year")
            or not target.get("building")
        ):
            return {"status": "unavailable", "reason": "missing_target_or_pool_fields"}
        area, year, days, block, building, roles, raw_ids = self.arrays[key]
        target_day = date.fromisoformat(target["date"]).toordinal()
        ratio = area / target["area"]
        valid = (ratio >= 0.5) & (ratio <= 1.5) & (days < target_day) & (roles != target["rol"])
        # Logarithmic area similarity; +/-50% is an explicit eligibility bound.
        area_similarity = np.maximum(0.0, 1.0 - np.abs(np.log(ratio)) / math.log(1.5))
        location = np.where(
            building == target["building"], 1.0, np.where(block == target["block"], 0.7, 0.2)
        )
        age_similarity = np.maximum(0.0, 1.0 - np.abs(year - target["year"]) / 20.0)
        recency = np.maximum(0.0, 1.0 - (target_day - days) / (365.25 * 2))
        similarity = 0.3 * area_similarity + 0.3 * location + 0.3 * age_similarity + 0.1 * recency
        indices = np.flatnonzero(valid)
        # Stable raw-ID ordering breaks ties reproducibly, independently of UF/m2.
        indices = indices[np.lexsort((raw_ids[indices], -similarity[indices]))[:K]]
        if len(indices) < K:
            return {
                "status": "unavailable",
                "reason": "fewer_than_10_comparables",
                "count": len(indices),
            }
        comps = []
        for i in indices:
            r = self.groups[key][i]
            comps.append(
                {
                    "rol": r["rol"],
                    "raw_id": r["raw_id"],
                    "fecha": r["date"],
                    "m2": r["area"],
                    "uf_m2": r["uf"] / r["area"],
                    "similarity": float(similarity[i]),
                    "building": r["building"],
                }
            )
        values, weights = [r["uf_m2"] for r in comps], [r["similarity"] for r in comps]
        low, median, high = [weighted_quantile(values, weights, q) for q in (0.25, 0.5, 0.75)]
        return {
            "status": "ok",
            "value_uf": median * target["area"],
            "p25_uf": low * target["area"],
            "p75_uf": high * target["area"],
            "uf_m2": median,
            "comparables": comps,
        }
