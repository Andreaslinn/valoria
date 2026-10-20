"""Offline confidence gate learned only from 2025H2, never from 2026.

This is a fixed three-way segmentation and a validation lookup, not a change
to SII kNN weights, neighbors, surfaces, dates or predictions.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from statistics import median

PROTOCOL = {
    "version": "sii-confidence-2025h2-v1",
    "validation_start": "2025-07-01",
    "validation_end_exclusive": "2026-01-01",
    "pool_end_exclusive": "2025-07-01",
    "location": "building>=5; else block_including_building>=5; else commune",
    "age_bands": ["0-9", "10-19", "20-39", "40+"],
    "relative_iqr_upper_bounds": [0.10, 0.20, 0.35],
    "relative_iqr": "(P75-P25)/median",
    "minimum_validation_cases_per_cell": 30,
    "maximum_validation_mdape_pct": 10.0,
    "rule": "trust iff successful prediction and fixed cell has n>=30 and 2025H2 MdAPE<=10%; otherwise abstain",
    "selection": "No search over boundaries, no commune-specific rules, no holdout input",
}


def age_band(year: int | None, valuation_date: str) -> str:
    if year is None:
        return "unknown"
    age = date.fromisoformat(valuation_date).year - year
    if age < 0:
        return "unknown"
    return "0-9" if age < 10 else "10-19" if age < 20 else "20-39" if age < 40 else "40+"


def features(target: dict, prediction: dict) -> dict | None:
    if prediction.get("status") != "ok" or prediction.get("value_uf", 0) <= 0:
        return None
    comps = prediction["comparables"]
    same_building = sum(c["building"] == target["building"] for c in comps)
    prefix = f"{target['comuna']}|{target['block']}|"
    same_block = sum(c["building"].startswith(prefix) for c in comps)
    level = "building5" if same_building >= 5 else "block5" if same_block >= 5 else "commune"
    relative_iqr = (prediction["p75_uf"] - prediction["p25_uf"]) / prediction["value_uf"]
    if not math.isfinite(relative_iqr) or relative_iqr < 0:
        return None
    dispersion = (
        "0-10"
        if relative_iqr <= 0.10
        else "10-20"
        if relative_iqr <= 0.20
        else "20-35"
        if relative_iqr <= 0.35
        else "35+"
    )
    age = age_band(target.get("year"), target["date"])
    return {
        "same_building": same_building,
        "same_block": same_block,
        "location": level,
        "age_band": age,
        "relative_iqr": relative_iqr,
        "dispersion_band": dispersion,
        "cell": f"{level}/{age}/{dispersion}",
    }


def fit_rule(validation_records: list[dict]) -> dict:
    groups = defaultdict(list)
    for row in validation_records:
        if not "2025-07-01" <= row["date"] < "2026-01-01":
            raise ValueError("Only 2025H2 may define the confidence rule")
        if row.get("features") and row.get("ape_pct") is not None:
            groups[row["features"]["cell"]].append(row["ape_pct"])
    cells = []
    for key, errors in sorted(groups.items()):
        mdape = median(errors)
        eligible = "/unknown/" not in key and len(errors) >= 30 and mdape <= 10.0
        cells.append({"cell": key, "n": len(errors), "mdape_pct": mdape, "trusted": eligible})
    return {
        "protocol": PROTOCOL,
        "allowed_cells": [r["cell"] for r in cells if r["trusted"]],
        "validation_cells": cells,
    }


def is_trusted(rule: dict, target: dict, prediction: dict) -> bool:
    f = features(target, prediction)
    return bool(f and f["cell"] in rule["allowed_cells"])


def apply_rule(rule: dict, target: dict, prediction: dict) -> dict:
    """Return the unchanged estimate inside the frozen zone; abstain elsewhere."""
    f = features(target, prediction)
    if not f or f["cell"] not in rule["allowed_cells"]:
        return {
            "status": "abstained",
            "reason": prediction.get("reason", "outside_2025H2_validated_zone"),
            "features": f,
        }
    return {
        **prediction,
        "confidence_cell": f["cell"],
        "confidence_rule_version": rule["protocol"]["version"],
    }
