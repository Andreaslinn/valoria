"""Read-only production coverage and candidate-building census for Codex 2a."""
from __future__ import annotations

import asyncio
from collections import defaultdict
import json

from sqlalchemy import select, text

from domain.geocoding.source_quality import assess, mlc
from domain.ingestion.location_evidence import candidate_building_key
from infrastructure.db.database import get_session_factory
from infrastructure.db.models import ListingORM

COMMUNES = ("providencia", "vitacura", "la_florida", "estacion_central", "san_miguel", "santiago")
SOURCES = ("portalinmobiliario", "yapo")


def summarize(rows):
    cells = {(c, s): dict(comuna=c, source=s, active=0, with_coordinates=0,
                         usable=0, with_candidate_key=0) for c in COMMUNES for s in SOURCES}
    buildings = defaultdict(set)
    for row in rows:
        cell = cells[(row["comuna"], row["source"])]
        cell["active"] += 1
        precision = row["geocode_precision"]
        quality = assess(row["lat"], row["lon"], precision=precision,
                         source=row["source"], identity_match=True,
                         declared_precision=precision in {"address", "street"})
        cell["with_coordinates"] += quality["status"] not in {"INVALID", "MISSING"}
        cell["usable"] += quality["status"] == "USABLE"
        address = row.get("address_evidence") or {}
        original = address.get("original") if isinstance(address, dict) else None
        if row["source"] == "portalinmobiliario":
            if mlc(address.get("source_listing_id")) != mlc(row["external_id"]):
                original = None
        else:
            original = original or row.get("address_label")
        key = candidate_building_key(original, row["comuna"])
        if key:
            cell["with_candidate_key"] += 1
            buildings[(row["comuna"], key["key"])].add((row["source"], row["external_id"]))
    for (c, s), cell in cells.items():
        cell["usable_pct"] = round(100 * cell["usable"] / cell["active"], 2) if cell["active"] else None
        cell["candidate_buildings_two_plus"] = sum(
            co == c and sum(source == s for source, _ in ids) >= 2
            for (co, _), ids in buildings.items())
    combined = []
    for c in COMMUNES:
        total = sum(cells[(c, s)]["active"] for s in SOURCES)
        usable = sum(cells[(c, s)]["usable"] for s in SOURCES)
        combined.append(dict(comuna=c, active=total, usable=usable,
            usable_pct=round(100 * usable / total, 2) if total else None,
            exit_passed=total > 0 and usable / total > .4,
            candidate_buildings_two_plus=sum(co == c and len(ids) >= 2 for (co, _), ids in buildings.items())))
    return {"read_only": True,
        "metric": "valid coordinate pair and stored address/street precision; unknown and centroids excluded",
        "building_method": "candidate source street+number+commune, not certified identity",
        "by_source": list(cells.values()), "combined": combined,
        "exit_passed": all(row["exit_passed"] for row in combined)}


async def main():
    async with get_session_factory()() as session:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        rows = (await session.execute(select(
            ListingORM.comuna, ListingORM.source, ListingORM.external_id,
            ListingORM.lat, ListingORM.lon, ListingORM.geocode_precision,
            ListingORM.raw_metadata["address_evidence"].label("address_evidence"),
            ListingORM.raw_metadata["address_label"].label("address_label"),
        ).where(ListingORM.status == "active", ListingORM.property_type == "apartment",
                ListingORM.comuna.in_(COMMUNES), ListingORM.source.in_(SOURCES)))).mappings().all()
        print(json.dumps(summarize(rows), ensure_ascii=True))
        await session.rollback()


if __name__ == "__main__":
    asyncio.run(main())
