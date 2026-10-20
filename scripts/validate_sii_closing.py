"""Offline pre-product exit gates for the SII closing layer.

Reads only the existing, explicitly local SII database. Produces a disposable
address index and complete reproducible evidence. Never accesses app settings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import psycopg
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from services.sii.closing_address import SCHEMA, AddressIndex, parse_address
from services.sii.closing_knn import ClosingKNN
from services.sii.parsing import COMUNAS, EXPECTED_MEDIANS, normalize
from services.sii.settings import local_url

COMMUNES = sorted(EXPECTED_MEDIANS)
SEED = 20261019
ACTIVE = """WITH active AS (
 SELECT DISTINCT ON(s.comuna) s.id,s.comuna FROM sii.source_file s
 WHERE s.tipo='N' AND EXISTS (SELECT 1 FROM sii.source_file l
 WHERE l.tipo='NL' AND l.comuna=s.comuna AND l.semestre=s.semestre)
 ORDER BY s.comuna,s.semestre DESC,s.cargado_en DESC,s.id DESC)
"""


def connect(url):
    u = make_url(local_url(url))
    return psycopg.connect(
        host=u.host,
        port=u.port,
        dbname=u.database,
        user=u.username,
        password=u.password,
        connect_timeout=5,
        row_factory=dict_row,
    )


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf8")


def export_snapshot(url, output):
    path = output / "address-index.sqlite"
    if path.exists():
        raise ValueError("Use a new output directory; never overwrite an existing snapshot")
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    metadata = {}
    with connect(url) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        c.execute("SET LOCAL statement_timeout='120s'")
        assert c.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"] == "on"
        metadata["sources"] = c.execute(
            "SELECT id,tipo,nombre,semestre,comuna,hash,fecha FROM sii.source_file ORDER BY id"
        ).fetchall()
        metadata["as_of_utc"] = datetime.now(UTC).isoformat()
        metadata["transaction_read_only"] = True
        count = 0
        with c.cursor(name="closing_address_export") as cur:
            cur.execute(
                ACTIVE
                + """SELECT p.rol,p.comuna,p.manzana,p.direccion_raw,
             p.tipo,p.anio_min,p.m2_cerrado,p.source_file_id FROM sii.predio p
             JOIN active a ON p.source_file_id=a.id WHERE p.comuna=ANY(%s)
             ORDER BY p.comuna,p.manzana,p.predio""",
                (COMMUNES,),
            )
            while batch := cur.fetchmany(10000):
                records = []
                for r in batch:
                    a = parse_address(r["direccion_raw"])
                    records.append(
                        (
                            r["rol"],
                            r["comuna"],
                            r["manzana"],
                            a.street,
                            a.number,
                            a.unit,
                            a.tower,
                            r["direccion_raw"],
                            r["tipo"],
                            r["anio_min"],
                            float(r["m2_cerrado"] or 0),
                            r["source_file_id"],
                        )
                    )
                db.executemany("INSERT INTO role VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", records)
                count += len(records)
        db.commit()
        print(json.dumps({"stage": "index_built", "roles": count}), flush=True)
        closings = c.execute(
            """SELECT t.raw_id,t.rol,t.comuna,t.manzana AS block,t.tipo AS kind,
          t.fecha::text AS date,t.fi::text AS fi,t.monto_uf::float8 AS uf,
          t.m2_cerrado::float8 AS area,p.anio_min AS year,p.direccion_raw
          FROM sii.transferencia t JOIN sii.predio p ON
          (t.predio_source_file_id,t.comuna,t.manzana,t.predio)=
          (p.source_file_id,p.comuna,p.manzana,p.predio)
          WHERE t.cierre_comparable AND t.tipo IN ('depto','casa') AND t.comuna=ANY(%s)
          AND t.fecha>=DATE '2024-01-01' ORDER BY t.raw_id""",
            (COMMUNES,),
        ).fetchall()
        c.rollback()
    for r in closings:
        a = parse_address(r.pop("direccion_raw"))
        r["building"] = f"{r['comuna']}|{r['block']}|{a.street}|{a.number}" if a.number else None
    db.close()
    metadata["roles_indexed"] = count
    metadata["closing_count"] = len(closings)
    save(output / "snapshot.json", metadata)
    save(output / "closings.json", closings)
    return path, closings, metadata


def human_variant(raw, variant):
    # Rewrites original source text, independently of the production parser.
    text = normalize(raw)
    text = re.sub(r"\b(?:DEPARTAMENTO|DEPTO|DPTO|DP|DEP)\b\s+", "depto ", text)
    if variant % 2 == 0:
        text = re.split(r"\b(?:depto|PISO|ESTAC|EST|BOD|BD|BOX|OF|LOCAL|CASA)\b", text)[0]
    aliases = {
        "AVENIDA": "Av.",
        "AVDA": "av",
        "PASAJE": "Pje.",
        "PRESIDENTE": "Pdte.",
        "GENERAL": "Gral.",
        "DOCTOR": "Dr.",
        "SANTA": "Sta.",
        "FRANCISCO": "Fco.",
    }
    for full, short in aliases.items():
        text = re.sub(r"\b" + full + r"\b", short, text)
    if variant % 3 == 0:
        text = re.sub(r"\bdepto\b", "dpto.", text)
    if variant % 3 == 1:
        text = re.sub(r"\bdepto\b", "departamento", text)
    return text.lower().strip()


def address_gate(index):
    rng = random.Random(SEED)
    all_cases = []
    for j, code in enumerate(COMMUNES):
        # Stratified sample of 300 random roles, no pre-filter on address quality,
        # type, civic number or availability of units.
        population = index.db.execute(
            "SELECT rol FROM role WHERE comuna=? ORDER BY rol", (code,)
        ).fetchall()
        ids = rng.sample([r["rol"] for r in population], 38 if j < 4 else 37)
        for i, rol in enumerate(ids):
            r = dict(index.db.execute("SELECT * FROM role WHERE rol=?", (rol,)).fetchone())
            query = human_variant(r["raw"], i)
            result = index.resolve(code, query)
            building = result.get("building")
            # Building-only correctness is independent of whether a unit is unique.
            correct = bool(
                building
                and building[:2] == [code, r["block"]]
                and building[2:] == [r["street"], r["number"]]
            )
            all_cases.append(
                {
                    "rol": rol,
                    "comuna": code,
                    "raw": r["raw"],
                    "query": query,
                    "expected_building": [code, r["block"], r["street"], r["number"]],
                    "building_correct": correct,
                    "status": result["status"],
                    "reason": result.get("reason"),
                    "unit_correct": result.get("role", {}).get("rol") == rol,
                    "candidate_count": len(result["candidates"]),
                }
            )
    rows = []
    for code in COMMUNES:
        cases = [r for r in all_cases if r["comuna"] == code]
        failed = [r for r in cases if not r["building_correct"]]
        rate = sum(r["building_correct"] for r in cases) / len(cases) * 100
        rows.append(
            {
                "comuna": code,
                "name": COMUNAS[code],
                "n": len(cases),
                "resolution_pct": rate,
                "passed": rate >= 90,
                "failed_examples": failed[:5],
                "failure_count": len(failed),
            }
        )
    return {
        "seed": SEED,
        "n": len(all_cases),
        "cases": all_cases,
        "by_commune": rows,
        "passed": sum(r["building_correct"] for r in all_cases) / len(all_cases) >= 0.90,
        "resolution_pct": sum(r["building_correct"] for r in all_cases) / len(all_cases) * 100,
        "limitation": "Automated natural-language rewrites of random source roles, not independent human annotation. Ground truth uses source block and parsed source street/number.",
    }


def age_band(year):
    age = 2026 - year if year else None
    if age is None:
        return "unknown"
    return "0-9" if age < 10 else "10-19" if age < 20 else "20-39" if age < 40 else "40+"


def metrics(rows):
    errors = [r["ape_pct"] for r in rows if r.get("ape_pct") is not None]
    return {
        "n": len(rows),
        "predicted": len(errors),
        "coverage_pct": 100 * len(errors) / len(rows) if rows else 0,
        "mdape_pct": float(np.median(errors)) if errors else None,
        "p95_ape_pct": float(np.percentile(errors, 95)) if errors else None,
    }


def holdout_gate(closings):
    targets = [r for r in closings if "2026-01-01" <= r["date"] < "2027-01-01"]
    excluded = {r["rol"] for r in targets}
    pool = [r for r in closings if r["date"] < "2026-01-01" and r["rol"] not in excluded]
    model = ClosingKNN(pool, excluded_roles=excluded)
    predictions = []
    for target in targets:
        result = model.estimate(target)
        error = (
            abs(result["value_uf"] / target["uf"] - 1) * 100 if result["status"] == "ok" else None
        )
        predictions.append(
            {
                "rol": target["rol"],
                "comuna": target["comuna"],
                "raw_id": target["raw_id"],
                "date": target["date"],
                "year": target["year"],
                "age_band": age_band(target["year"]),
                "area": target["area"],
                "actual_uf": target["uf"],
                "ape_pct": error,
                **result,
            }
        )
    rows = []
    for code in COMMUNES:
        cases = [r for r in predictions if r["comuna"] == code]
        m = metrics(cases)
        m.update(comuna=code, name=COMUNAS[code])
        m["passed"] = bool(
            m["mdape_pct"] is not None and m["mdape_pct"] <= 10
        )
        failures = [r for r in cases if r.get("ape_pct") is None or r["ape_pct"] > 10]
        failures.sort(
            key=lambda r: r.get("ape_pct") if r.get("ape_pct") is not None else float("inf"),
            reverse=True,
        )
        m["failed_examples"] = failures[:5]
        m["by_age"] = {
            band: metrics([r for r in cases if r["age_band"] == band])
            for band in ("0-9", "10-19", "20-39", "40+", "unknown")
        }
        rows.append(m)
        print(
            json.dumps(
                {
                    "stage": "holdout_commune",
                    **{k: v for k, v in m.items() if k not in ("failed_examples", "by_age")},
                }
            ),
            flush=True,
        )
    return {
        "holdout": "fecha (FE else FI) in calendar 2026; FI is also retained",
        "pool": "2024-2025, excluding EVERY role present in holdout; strictly before target",
        "holdout_roles": len(excluded),
        "pool_rows": len(pool),
        "by_commune": rows,
        "passed": all(r["passed"] for r in rows),
        "predictions": predictions,
    }


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("--local-url", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--reuse-snapshot", action="store_true")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.reuse_snapshot:
        path = args.output / "address-index.sqlite"
        closings = json.loads((args.output / "closings.json").read_text(encoding="utf8"))
        metadata = json.loads((args.output / "snapshot.json").read_text(encoding="utf8"))
    else:
        path, closings, metadata = export_snapshot(args.local_url, args.output)
    index = AddressIndex(path)
    addresses = address_gate(index)
    index.close()
    save(args.output / "address-validation.json", addresses)
    print(
        json.dumps(
            {
                "stage": "address_gate",
                "passed": addresses["passed"],
                "resolution_pct": addresses["resolution_pct"],
            }
        ),
        flush=True,
    )
    # Both offline gates are evaluated for the requested per-commune report.
    # Their failure stops product integration, never retunes these frozen rules.
    holdout = holdout_gate(closings)
    save(args.output / "holdout-validation.json", holdout)
    summary = {
        "metadata": metadata,
        "address": {k: v for k, v in addresses.items() if k != "cases"},
        "holdout": {k: v for k, v in holdout.items() if k != "predictions"},
        "passed": addresses["passed"] and holdout["passed"],
    }
    summary["snapshot_sha256"] = hashlib.sha256(
        (args.output / "closings.json").read_bytes()
    ).hexdigest()
    save(args.output / "summary.json", summary)
    print(json.dumps({"stage": "complete", "passed": summary["passed"]}), flush=True)


if __name__ == "__main__":
    main()
