"""Local matched-case baseline against the unchanged productive canonical engine.

The candidate snapshot is current active asking-price stock, not historical
stock as of each 2026 sale. This is an operational retrospective comparison,
not a time-correct historical backtest of the canonical listing model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from core.entities.listing import Listing, Property
from core.value_objects.location import Coordinates
from core.value_objects.price import Price
from domain.valuation.engines.canonical_comparables import ComparablesCanonicalEngine
from domain.valuation.engines.contracts import EngineContext, EngineRequest
from scripts.evaluate_sii_confidence import digest, metrics, save
from services.sii.closing_confidence import age_band
from services.sii.parsing import COMUNAS, EXPECTED_MEDIANS

SLUG = {
    13101: "santiago",
    14157: "estacion_central",
    15103: "providencia",
    15105: "nunoa",
    15108: "las_condes",
    15128: "la_florida",
    15160: "vitacura",
    16106: "san_miguel",
}
SEED = 20261019


def stratified_sample(rows, maximum=150):
    """Proportional largest-remainder allocation with at least one per age band."""
    by_age = defaultdict(list)
    for row in sorted(rows, key=lambda r: r["raw_id"]):
        by_age[age_band(row["year"], row["date"])].append(row)
    n = min(maximum, len(rows))
    if not n:
        return [], {}
    quotas = {
        band: min(len(group), max(1, int(n * len(group) / len(rows))))
        for band, group in by_age.items()
    }
    while sum(quotas.values()) < n:
        band = max(
            (b for b in by_age if quotas[b] < len(by_age[b])),
            key=lambda b: (n * len(by_age[b]) / len(rows) - quotas[b], b),
        )
        quotas[band] += 1
    while sum(quotas.values()) > n:
        band = max(
            (b for b in by_age if quotas[b] > 1),
            key=lambda b: (quotas[b] - n * len(by_age[b]) / len(rows), b),
        )
        quotas[band] -= 1
    rng = random.Random(SEED)
    selected = []
    for band in sorted(by_age):
        selected.extend(rng.sample(by_age[band], quotas[band]))
    return sorted(selected, key=lambda r: r["raw_id"]), quotas


def listing_from_snapshot(row):
    values = dict(row)
    values["price"] = Price(clp=Decimal(str(values["price"]["clp"])))
    if values.get("price_uf") is not None:
        values["price_uf"] = Decimal(str(values["price_uf"]))
    values["coordinates"] = (
        Coordinates(**values["coordinates"]) if values.get("coordinates") else None
    )
    for key in ("scraped_at", "last_seen_at", "last_refresh_attempted_at"):
        if values.get(key):
            values[key] = datetime.fromisoformat(values[key].replace("Z", "+00:00"))
    return Listing(**values)


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("--closings", type=Path, required=True)
    p.add_argument("--knn-holdout", type=Path, required=True)
    p.add_argument("--canonical-pool", type=Path, required=True)
    p.add_argument("--uf-snapshot", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    pool = json.loads(args.canonical_pool.read_text(encoding="utf-8-sig"))
    for path, expected in pool["code_sha256"].items():
        actual = hashlib.sha256(
            (Path(__file__).parents[1] / path).read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
        if actual != expected:
            raise ValueError(
                f"Current productive source differs from local canonical source: {path}"
            )
    uf_snapshot = json.loads(args.uf_snapshot.read_text(encoding="utf-8-sig"))
    rate = next(
        r
        for r in uf_snapshot["calendar_today"]
        if r["date"] == "2026-10-19" and r["source"] == "sii.cl"
    )
    uf = Decimal(rate["value"])
    if uf <= 0 or uf == Decimal("37000"):
        raise ValueError("Invalid UF snapshot")
    candidates = defaultdict(list)
    for row in pool["rows"]:
        item = listing_from_snapshot(row)
        candidates[(item.comuna, item.property_type)].append(item)
    closings = json.loads(args.closings.read_text(encoding="utf8"))
    knn = {r["raw_id"]: r for r in json.loads(args.knn_holdout.read_text(encoding="utf8"))}
    engine = ComparablesCanonicalEngine(name="comparables_canonical_outliers", variant="outliers")
    shadow_checks = []
    for check in pool.get("full_input_shadow_checks", []):
        area, kind = check["area"], check["kind"]
        target = Property(
            id=None,
            comuna=check["comuna"],
            m2=area,
            bedrooms=0,
            bathrooms=0,
            parking=0,
            property_type=kind,
            built_area_m2=area,
            usable_area_m2=area if kind == "apartment" else None,
        )
        result = engine.valuate(
            EngineRequest(published_price_provided=False),
            EngineContext(
                target=target, candidates=candidates[(check["comuna"], kind)], uf_to_clp=uf
            ),
        )
        if result.status != check["status"] or result.estimated_price_uf != (
            Decimal(check["value_uf"]) if check["value_uf"] is not None else None
        ):
            raise ValueError("Projected local inputs do not reproduce full productive inputs")
        shadow_checks.append(True)
    results, summaries = [], []
    allocation = {}
    for code in sorted(EXPECTED_MEDIANS):
        targets = [
            r for r in closings if r["comuna"] == code and "2026-01-01" <= r["date"] < "2027-01-01"
        ]
        sample, quotas = stratified_sample(targets)
        allocation[str(code)] = quotas
        cases = []
        for target in sample:
            kind = "apartment" if target["kind"] == "depto" else "house"
            property_ = Property(
                id=None,
                comuna=SLUG[code],
                m2=target["area"],
                bedrooms=0,
                bathrooms=0,
                parking=0,
                property_type=kind,
                built_area_m2=target["area"],
                usable_area_m2=target["area"] if kind == "apartment" else None,
                raw_metadata={"construction_year": target["year"]},
            )
            result = engine.valuate(
                EngineRequest(published_price_provided=False),
                EngineContext(
                    target=property_,
                    candidates=candidates[(SLUG[code], kind)],
                    uf_to_clp=uf,
                    valuation_date=datetime.fromisoformat(target["date"]),
                ),
            )
            value = float(result.estimated_price_uf) if result.is_successful else None
            sii = knn[target["raw_id"]]
            cases.append(
                {
                    "raw_id": target["raw_id"],
                    "rol": target["rol"],
                    "comuna": code,
                    "date": target["date"],
                    "year": target["year"],
                    "kind": target["kind"],
                    "age_band": age_band(target["year"], target["date"]),
                    "area": target["area"],
                    "actual_uf": target["uf"],
                    "canonical_value_uf": value,
                    "canonical_ape_pct": abs(value / target["uf"] - 1) * 100
                    if value is not None
                    else None,
                    "canonical_status": result.status,
                    "canonical_reason": result.error_message,
                    "canonical_comparable_count": result.comparables_used,
                    "canonical_comparable_ids": [r.listing_id for r in result.selected_comparables],
                    "sii_value_uf": sii["prediction"].get("value_uf"),
                    "sii_ape_pct": sii["ape_pct"],
                    "sii_trusted": sii["trusted"],
                }
            )
        paired = [
            r for r in cases if r["canonical_ape_pct"] is not None and r["sii_ape_pct"] is not None
        ]
        c_errors = [{"ape_pct": r["canonical_ape_pct"]} for r in paired]
        s_errors = [{"ape_pct": r["sii_ape_pct"]} for r in paired]
        summary = {
            "comuna": code,
            "name": COMUNAS[code],
            "sample_n": len(cases),
            "canonical_predicted": sum(r["canonical_value_uf"] is not None for r in cases),
            "sii_predicted": sum(r["sii_value_uf"] is not None for r in cases),
            "paired_n": len(paired),
            "canonical_paired": metrics(c_errors),
            "sii_paired": metrics(s_errors),
            "age_allocation": quotas,
            "canonical_status_counts": dict(Counter(r["canonical_status"] for r in cases)),
        }
        summaries.append(summary)
        results.extend(cases)
        print(json.dumps({"stage": "baseline_commune", **summary}, ensure_ascii=False), flush=True)
    save(args.output / "comparison-records-local.json", results)
    save(
        args.output / "comparison-summary.json",
        {
            "by_commune": summaries,
            "sampling_seed": SEED,
            "age_allocation": allocation,
            "canonical_stock_as_of": pool["as_of_utc"],
            "canonical_stock_count": len(pool["rows"]),
            "canonical_pool_sha256": digest(args.canonical_pool),
            "code_sha256": pool["code_sha256"],
            "uf": rate,
            "engine_version": engine.version,
            "full_input_synthetic_shadow_checks_passed": len(shadow_checks),
            "paired_error": "Identical cases where both models return an estimate; all abstentions reported separately",
            "age_note": "Same construction year retained in target metadata; unchanged canonical engine ignores year",
            "temporal_limitation": "Current asking-price stock snapshot, not historical stock at each transaction date",
            "target_missing_attributes": "SII provides no bedroom/bathroom/parking: 0 matches absent values in current Tasar; no inferred values",
            "row_level_records": "Local only; never publish comparison-records-local.json or source snapshots",
        },
    )


if __name__ == "__main__":
    main()
