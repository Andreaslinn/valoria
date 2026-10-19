"""Read-only local SII export, pinned to the address index's exact source IDs.

Adds facts omitted from the original address index without rewriting that index,
the closing pool or any model. The resulting SQLite file is private/local only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from scripts.validate_sii_closing import connect
from services.sii.settings import value

FACTS_SCHEMA = """CREATE TABLE facts(
 rol TEXT NOT NULL, source_id INTEGER NOT NULL, land_area_m2 REAL,
 source_period TEXT, PRIMARY KEY(rol,source_id));"""


def export(index_path: Path, output: Path, url: str):
    if output.exists():
        raise ValueError("Use a new output file; never overwrite an existing facts snapshot")
    with sqlite3.connect(index_path.resolve().as_uri() + "?mode=ro", uri=True) as index:
        source_ids = [r[0] for r in index.execute("SELECT DISTINCT source FROM role")]
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with connect(url) as source, sqlite3.connect(output) as target:
        source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        source.execute("SET LOCAL statement_timeout='120s'")
        assert (
            source.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"] == "on"
        )
        target.executescript(FACTS_SCHEMA)
        with source.cursor(name="address_facts_export") as cursor:
            cursor.execute(
                """SELECT p.rol,p.source_file_id,p.m2_terreno::float8 AS land_area_m2,s.semestre
              FROM sii.predio p JOIN sii.source_file s ON s.id=p.source_file_id
              WHERE p.source_file_id=ANY(%s) AND p.tipo='casa' AND p.m2_terreno>0""",
                (source_ids,),
            )
            while batch := cursor.fetchmany(10000):
                target.executemany(
                    "INSERT INTO facts VALUES (?,?,?,?)",
                    [
                        (r["rol"], r["source_file_id"], r["land_area_m2"], r["semestre"])
                        for r in batch
                    ],
                )
                count += len(batch)
        target.commit()
        source.rollback()
    return {
        "rows": count,
        "source_count": len(source_ids),
        "source_read_only": True,
        "individual_records_published": False,
    }


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = export(args.index, args.output, value("SII_DATABASE_URL"))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
