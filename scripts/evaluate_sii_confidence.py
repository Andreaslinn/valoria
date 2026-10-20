"""Two explicit offline stages: fit 2025H2, then frozen-rule evaluation 2026.

Row-level inputs/outputs must remain local. No database access, application
settings, production execution, GitHub uploads or changes to the SII estimator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from services.sii.closing_confidence import (
    PROTOCOL,
    age_band,
    apply_rule,
    features,
    fit_rule,
    is_trusted,
)
from services.sii.closing_knn import ClosingKNN
from services.sii.parsing import COMUNAS, EXPECTED_MEDIANS


def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest(path: Path):
    """Ignore Git's Windows CRLF conversion while freezing identical source."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def save(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf8")


def metrics(records):
    errors = [r["ape_pct"] for r in records if r.get("ape_pct") is not None]
    return {
        "n": len(records),
        "predicted": len(errors),
        "mdape_pct": float(np.median(errors)) if errors else None,
        "p95_ape_pct": float(np.percentile(errors, 95)) if errors else None,
    }


def predictions(pool, targets):
    excluded = {r["rol"] for r in targets}
    model = ClosingKNN(pool, excluded_roles=excluded)
    rows = []
    for target in targets:
        pred = model.estimate(target)
        if pred["status"] == "ok":
            assert all(
                c["rol"] not in excluded and c["fecha"] < target["date"]
                for c in pred["comparables"]
            )
        ape = abs(pred["value_uf"] / target["uf"] - 1) * 100 if pred["status"] == "ok" else None
        rows.append(
            {
                "raw_id": target["raw_id"],
                "rol": target["rol"],
                "comuna": target["comuna"],
                "kind": target["kind"],
                "date": target["date"],
                "year": target["year"],
                "area": target["area"],
                "actual_uf": target["uf"],
                "age_band": age_band(target["year"], target["date"]),
                "ape_pct": ape,
                "features": features(target, pred),
                "prediction": pred,
            }
        )
    return rows


def segment_report(rows):
    groups = defaultdict(list)
    for row in rows:
        if row["features"]:
            groups[row["features"]["cell"]].append(row)
    return [{"cell": key, **metrics(group)} for key, group in sorted(groups.items())]


def fit(args):
    rows = json.loads(args.input.read_text(encoding="utf8"))
    if any(r["date"] >= "2026-01-01" for r in rows):
        raise ValueError("Training input must not contain any 2026 rows")
    protocol = args.output / "protocol.json"
    if protocol.exists():
        raise ValueError("Use a new fit directory; protocol must precede validation measurement")
    save(
        protocol,
        {
            "protocol": PROTOCOL,
            "registered_at_utc": datetime.now(UTC).isoformat(),
            "input_sha256": digest(args.input),
            "knn_sha256": source_digest(Path(__file__).parents[1] / "services/sii/closing_knn.py"),
        },
    )
    targets = [r for r in rows if "2025-07-01" <= r["date"] < "2026-01-01"]
    pool = [r for r in rows if r["date"] < "2025-07-01"]
    values = predictions(pool, targets)
    rule = fit_rule(values)
    rule.update(
        frozen_at_utc=datetime.now(UTC).isoformat(),
        input_sha256=digest(args.input),
        protocol_sha256=digest(protocol),
        knn_sha256=source_digest(Path(__file__).parents[1] / "services/sii/closing_knn.py"),
    )
    save(args.output / "frozen-rule.json", rule)
    save(args.output / "validation-records-local.json", values)
    allowed = set(rule["allowed_cells"])
    by_commune = []
    for code in sorted(EXPECTED_MEDIANS):
        cases = [r for r in values if r["comuna"] == code]
        trusted = [r for r in cases if r["features"] and r["features"]["cell"] in allowed]
        by_commune.append(
            {
                "comuna": code,
                "name": COMUNAS[code],
                "total": len(cases),
                "trusted": metrics(trusted),
                "all": metrics(cases),
                "coverage_pct": 100 * len(trusted) / len(cases) if cases else 0,
            }
        )
    summary = {
        "stage": "2025H2",
        "total": len(values),
        "pool_before_role_exclusion": len(pool),
        "segments": segment_report(values),
        "by_commune": by_commune,
        "rule_sha256": digest(args.output / "frozen-rule.json"),
        "rule": rule,
    }
    save(args.output / "validation-summary.json", summary)
    print(
        json.dumps(
            {
                "stage": "rule_frozen",
                "validation_n": len(values),
                "allowed_cells": rule["allowed_cells"],
                "rule_sha256": summary["rule_sha256"],
            }
        ),
        flush=True,
    )


def evaluate(args):
    rule_hash = digest(args.rule)
    rule = json.loads(args.rule.read_text(encoding="utf8"))
    if rule["knn_sha256"] != source_digest(Path(__file__).parents[1] / "services/sii/closing_knn.py"):
        raise ValueError("SII kNN changed after rule freeze")
    rows = json.loads(args.input.read_text(encoding="utf8"))
    pool = [r for r in rows if r["date"] < "2026-01-01"]
    targets = [r for r in rows if "2026-01-01" <= r["date"] < "2027-01-01"]
    values = predictions(pool, targets)
    target_by_id = {r["raw_id"]: r for r in targets}
    by_commune = []
    for row in values:
        row["trusted"] = is_trusted(rule, target_by_id[row["raw_id"]], row["prediction"])
        row["gated_prediction"] = apply_rule(rule, target_by_id[row["raw_id"]], row["prediction"])
    for code in sorted(EXPECTED_MEDIANS):
        cases = [r for r in values if r["comuna"] == code]
        trusted = [r for r in cases if r["trusted"]]
        m = metrics(trusted)
        coverage = 100 * len(trusted) / len(cases) if cases else 0
        by_commune.append(
            {
                "comuna": code,
                "name": COMUNAS[code],
                "total": len(cases),
                "trusted": m,
                "all": metrics(cases),
                "coverage_pct": coverage,
                "passes_mdape_and_coverage": bool(
                    m["mdape_pct"] is not None and m["mdape_pct"] <= 10 and coverage >= 50
                ),
            }
        )
    assert rule_hash == digest(args.rule), "Frozen rule changed during holdout evaluation"
    save(args.output / "holdout-records-local.json", values)
    summary = {
        "stage": "2026",
        "rule_sha256": rule_hash,
        "input_sha256": digest(args.input),
        "segments": segment_report(values),
        "by_commune": by_commune,
        "communes_passing": sum(r["passes_mdape_and_coverage"] for r in by_commune),
    }
    save(args.output / "holdout-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("stage", choices=["fit", "evaluate"])
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--rule", type=Path)
    args = p.parse_args()
    if args.stage == "fit":
        fit(args)
    elif args.rule is None:
        p.error("evaluate requires --rule")
    else:
        evaluate(args)


if __name__ == "__main__":
    main()
