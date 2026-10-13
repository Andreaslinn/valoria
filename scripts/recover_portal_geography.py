"""Offline-only Portal recovery. SQLite copies, dry-run by default; no HTTP."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from domain.geocoding.source_quality import mlc, validate_context
from infrastructure.db.models import ListingORM
from infrastructure.db.portal_geography import archived_evidence, apply_geography, eligible
from infrastructure.scrapers.portalinmobiliario import parse_listing_detail_portal


async def recover_copy(database: Path, *, apply=False, archive=None):
    """Resume by canonical state; no checkpoint may bypass eligibility recheck."""
    database = database.resolve(strict=True)
    if database.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        raise ValueError("An explicit existing SQLite copy is required")
    engine = create_async_engine("sqlite+aiosqlite:///" + database.as_posix())
    if not apply:

        @event.listens_for(engine.sync_engine, "connect")
        def read_only(connection, _):
            connection.execute("PRAGMA query_only=ON")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    archive = archive or {}
    audit = []
    try:
        async with factory() as session:
            rows = (
                await session.scalars(
                    select(ListingORM)
                    .where(ListingORM.source == "portalinmobiliario")
                    .order_by(ListingORM.id)
                )
            ).all()
            for row in rows:
                entry = {
                    "listing_id": row.id,
                    "external_id": row.external_id,
                    "at": datetime.now(UTC).isoformat(),
                    "mode": "apply" if apply else "dry_run",
                }
                if not eligible(row):
                    entry["result"] = "preserved_or_inactive"
                else:
                    ev = await archived_evidence(session, row)
                    entry["origin"] = "stored_evidence"
                    record = archive.get(mlc(row.external_id))
                    if not ev and record:
                        html = Path(record["path"]).read_text(encoding="utf-8")
                        detail = parse_listing_detail_portal(html, row.url or "")
                        ev = (detail.get("raw_metadata") or {}).get("coordinates_evidence")
                        if ev:
                            # Parser execution time is not historical acquisition time.
                            ev["observed_at"] = record.get("observed_at")
                        entry["origin"] = "archived_detail"
                    ev = validate_context(ev, row.comuna) if ev else None
                    usable = bool(
                        ev
                        and ev.get("normalized")
                        and ev["quality"].get("local_eligible")
                        and ev["quality"]["status"] != "INVALID"
                        and mlc(ev.get("source_listing_id")) == mlc(row.external_id)
                    )
                    entry["result"] = "recoverable" if usable else "requires_detail_or_review"
                    if usable and apply:
                        entry["result"] = await apply_geography(session, row, ev, origin="archive")
                        await session.commit()
                audit.append(entry)
    finally:
        await engine.dispose()
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-copy", type=Path, required=True)
    parser.add_argument("--archive-manifest", type=Path)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    archive = (
        json.loads(args.archive_manifest.read_text(encoding="utf-8"))
        if args.archive_manifest
        else None
    )
    rows = asyncio.run(recover_copy(args.sqlite_copy, apply=args.apply, archive=archive))
    # Append audit; never overwrite the record of prior attempts. No raw payload/secrets.
    with args.audit.open("a", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "rows": len(rows),
                "recovered": sum(x["result"] == "recovered" for x in rows),
                "recoverable": sum(x["result"] == "recoverable" for x in rows),
                "mode": "apply" if args.apply else "dry_run",
            }
        )
    )


if __name__ == "__main__":
    main()
