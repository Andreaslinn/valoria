"""Aggregate-only signed bias diagnostic on the already matched holdout cases.

The ratio is a proxy: median(canonical asking-stock valuation / closing value).
It is NOT a directly linked listing/sale ratio, a causal algorithm comparison,
or a production calibration. No rule fitting or model changes occur here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def summarize(rows):
    paired = [r for r in rows if r.get("canonical_value_uf") and r.get("sii_value_uf")]
    output = []
    for comuna in sorted({r["comuna"] for r in paired}):
        selected = [r for r in paired if r["comuna"] == comuna]
        actual = np.array([r["actual_uf"] for r in selected], dtype=float)
        canonical = np.array([r["canonical_value_uf"] for r in selected], dtype=float)
        knn = np.array([r["sii_value_uf"] for r in selected], dtype=float)
        if not all(np.all(np.isfinite(v) & (v > 0)) for v in (actual, canonical, knn)):
            raise ValueError("All matched values must be finite and positive")
        ratio = float(np.median(canonical / actual))
        adjusted = np.abs(canonical / ratio / actual - 1) * 100
        output.append(
            {
                "comuna": comuna,
                "n": len(selected),
                "canonical_signed_median_pct": float(np.median(canonical / actual - 1) * 100),
                "knn_signed_median_pct": float(np.median(knn / actual - 1) * 100),
                "offer_close_ratio_proxy": ratio,
                "canonical_mdape_pct": float(np.median(np.abs(canonical / actual - 1) * 100)),
                "canonical_adjusted_mdape_pct": float(np.median(adjusted)),
                "canonical_adjusted_p95_pct": float(np.quantile(adjusted, 0.95)),
            }
        )
    return {
        "paired_n": len(paired),
        "by_commune": output,
        "signed_error": "100*(prediction/actual-1); positive means overvaluation",
        "ratio_definition": "median(canonical_value_uf/actual_uf), within commune, same paired holdout",
        "adjusted_value": "canonical_value_uf/offer_close_ratio_proxy",
        "limitation": "Ex-post descriptive proxy, not linked asking/closing prices; current asking stock vs earlier closings. Cannot causally isolate algorithm effects. Never used in serving or frozen confidence rule.",
    }


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.records.read_bytes()
    rows = json.loads(raw.decode("utf-8-sig"))
    result = summarize(rows)
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(f"Aggregate-only summary: {result['paired_n']} paired cases")


if __name__ == "__main__":
    main()
