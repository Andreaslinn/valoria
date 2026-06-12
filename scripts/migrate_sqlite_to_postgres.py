"""Migrate useful legacy SQLite data into the current PostgreSQL schema.

This script reads SQLite directly. It does not import the old AVM application.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_settings  # noqa: E402
from config.constants import LEGACY_UF_ARTIFACT_RATE  # noqa: E402

BATCH_SIZE = 500


@dataclass
class TableStats:
    read: int = 0
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass
class MigrationSummary:
    tables: dict[str, TableStats] = field(default_factory=dict)

    def table(self, name: str) -> TableStats:
        return self.tables.setdefault(name, TableStats())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy SQLite data to PostgreSQL.")
    parser.add_argument("--sqlite-path", required=True, help="Path to legacy SQLite DB.")
    parser.add_argument("--dry-run", action="store_true", help="Read and validate without writing.")
    parser.add_argument("--limit", type=int, default=None, help="Max rows per table.")
    parser.add_argument("--truncate-target", action="store_true", help="Delete target table rows first.")
    args = parser.parse_args(argv)

    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.is_file():
        print(f"SQLite file not found: {sqlite_path}", file=sys.stderr)
        return 1

    summary = MigrationSummary()
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    if args.dry_run:
        pg_conn = None
    else:
        engine = create_engine(get_settings().sync_database_url)
        pg_conn = engine.connect()

    try:
        if pg_conn is not None:
            with pg_conn.begin():
                if args.truncate_target:
                    _truncate(pg_conn)
                id_map = migrate_listings(sqlite_conn, pg_conn, summary, args.limit, args.dry_run)
                migrate_price_history(sqlite_conn, pg_conn, summary, args.limit, args.dry_run, id_map)
                migrate_users(sqlite_conn, pg_conn, summary, args.limit, args.dry_run)
        else:
            id_map = migrate_listings(sqlite_conn, None, summary, args.limit, True)
            migrate_price_history(sqlite_conn, None, summary, args.limit, True, id_map)
            migrate_users(sqlite_conn, None, summary, args.limit, True)
    finally:
        sqlite_conn.close()
        if pg_conn is not None:
            pg_conn.close()

    _print_summary(summary, dry_run=args.dry_run)
    return 0 if not any(stats.errors for stats in summary.tables.values()) else 1


def migrate_listings(
    sqlite_conn: sqlite3.Connection,
    pg_conn: Connection | None,
    summary: MigrationSummary,
    limit: int | None,
    dry_run: bool,
) -> dict[Any, int]:
    stats = summary.table("listings")
    if not _table_exists(sqlite_conn, "listings"):
        print("WARNING: SQLite table listings does not exist; skipping.")
        return {}

    id_map: dict[Any, int] = {}
    columns = _columns(sqlite_conn, "listings")
    for row in _iter_rows(sqlite_conn, "listings", limit):
        stats.read += 1
        try:
            data = _listing_payload(row, columns)
            old_id = _first(row, columns, ["id", "listing_id"])
            if data is None:
                stats.skipped += 1
                continue
            if dry_run:
                stats.inserted += 1
                continue
            assert pg_conn is not None
            existing_id = _find_existing_listing(pg_conn, data)
            if existing_id is not None:
                stats.skipped += 1
                if old_id is not None:
                    id_map[old_id] = existing_id
                continue
            new_id = _insert_listing(pg_conn, data)
            if old_id is not None:
                id_map[old_id] = new_id
            stats.inserted += 1
        except Exception as e:
            stats.errors += 1
            print(f"ERROR listings row={stats.read}: {e}", file=sys.stderr)
    return id_map


def migrate_price_history(
    sqlite_conn: sqlite3.Connection,
    pg_conn: Connection | None,
    summary: MigrationSummary,
    limit: int | None,
    dry_run: bool,
    listing_id_map: dict[Any, int],
) -> None:
    stats = summary.table("price_history")
    if not _table_exists(sqlite_conn, "price_history"):
        print("WARNING: SQLite table price_history does not exist; skipping.")
        return

    columns = _columns(sqlite_conn, "price_history")
    for row in _iter_rows(sqlite_conn, "price_history", limit):
        stats.read += 1
        try:
            old_listing_id = _first(row, columns, ["listing_id", "property_id"])
            target_listing_id = listing_id_map.get(old_listing_id)
            price_clp = _price_clp(row, columns)
            if target_listing_id is None or price_clp is None:
                stats.skipped += 1
                continue
            if dry_run:
                stats.inserted += 1
                continue
            assert pg_conn is not None
            pg_conn.execute(
                text(
                    """
                    INSERT INTO price_history (listing_id, price_clp, observed_at)
                    VALUES (:listing_id, :price_clp, :observed_at)
                    """
                ),
                {
                    "listing_id": target_listing_id,
                    "price_clp": price_clp,
                    "observed_at": _datetime_value(_first(row, columns, ["observed_at", "created_at", "date"])),
                },
            )
            stats.inserted += 1
        except Exception as e:
            stats.errors += 1
            print(f"ERROR price_history row={stats.read}: {e}", file=sys.stderr)


def migrate_users(
    sqlite_conn: sqlite3.Connection,
    pg_conn: Connection | None,
    summary: MigrationSummary,
    limit: int | None,
    dry_run: bool,
) -> None:
    stats = summary.table("users")
    if not _table_exists(sqlite_conn, "users"):
        print("WARNING: SQLite table users does not exist; skipping.")
        return

    columns = _columns(sqlite_conn, "users")
    for row in _iter_rows(sqlite_conn, "users", limit):
        stats.read += 1
        try:
            username = _first(row, columns, ["username", "email", "user"])
            password_hash = _first(row, columns, ["password_hash", "hashed_password"])
            if not username or not password_hash:
                stats.skipped += 1
                continue
            if dry_run:
                stats.inserted += 1
                continue
            assert pg_conn is not None
            exists = pg_conn.execute(
                text("SELECT id FROM users WHERE username = :username"),
                {"username": username},
            ).scalar_one_or_none()
            if exists is not None:
                stats.skipped += 1
                continue
            pg_conn.execute(
                text(
                    """
                    INSERT INTO users (username, password_hash, role, is_active)
                    VALUES (:username, :password_hash, :role, :is_active)
                    """
                ),
                {
                    "username": username,
                    "password_hash": password_hash,
                    "role": _role(_first(row, columns, ["role"])),
                    "is_active": bool(_first(row, columns, ["is_active", "active"]) if "is_active" in columns or "active" in columns else True),
                },
            )
            stats.inserted += 1
        except Exception as e:
            stats.errors += 1
            print(f"ERROR users row={stats.read}: {e}", file=sys.stderr)


def _listing_payload(row: sqlite3.Row, columns: set[str]) -> dict[str, Any] | None:
    source = str(_first(row, columns, ["source", "fuente", "portal"]) or "legacy")
    url = _first(row, columns, ["url", "link", "permalink"])
    external_id = _first(row, columns, ["external_id", "source_listing_id", "listing_external_id"])
    title = _first(row, columns, ["title", "titulo", "name"]) or "Listing legado"
    comuna = _first(row, columns, ["comuna", "commune", "municipality"])
    m2 = _float(_first(row, columns, ["m2", "surface", "metros", "mts"]))
    price_clp = _price_clp(row, columns)
    if not comuna or not m2 or not price_clp:
        return None
    raw = dict(row)
    fingerprint = _first(row, columns, ["fingerprint"]) or _fingerprint(source, external_id, url, raw)
    data = {
        "source": source[:32],
        "external_id": str(external_id)[:128] if external_id is not None else None,
        "title": str(title)[:512],
        "url": str(url)[:1024] if url else None,
        "comuna": str(comuna)[:64],
        "m2": m2,
        "bedrooms": _int(_first(row, columns, ["bedrooms", "dormitorios", "habitaciones"]), 0),
        "bathrooms": _int(_first(row, columns, ["bathrooms", "banos", "baños"]), 0),
        "parking": _int(_first(row, columns, ["parking", "estacionamientos"]), 0),
        "lat": _float(_first(row, columns, ["lat", "latitude"])),
        "lon": _float(_first(row, columns, ["lon", "lng", "longitude"])),
        "price_clp": price_clp,
        "status": str(_first(row, columns, ["status", "estado"]) or "active")[:32],
        "fingerprint": str(fingerprint)[:128],
        "raw_metadata": json.dumps(raw, default=str),
        "scraped_at": _datetime_value(_first(row, columns, ["scraped_at", "captured_at", "created_at", "date"])),
    }
    data["last_seen_at"] = _datetime_value(_first(row, columns, ["last_seen_at"])) or data["scraped_at"]
    data["last_refresh_attempted_at"] = _datetime_value(
        _first(row, columns, ["last_refresh_attempted_at"])
    )
    last_refresh_status = _first(row, columns, ["last_refresh_status"])
    data["last_refresh_status"] = str(last_refresh_status)[:64] if last_refresh_status else None
    return data


def _insert_listing(conn: Connection, data: dict[str, Any]) -> int:
    return conn.execute(
        text(
            """
            INSERT INTO listings (
                source, external_id, title, url, comuna, m2, bedrooms, bathrooms,
                parking, lat, lon, price_clp, status, fingerprint, raw_metadata, scraped_at, last_seen_at,
                last_refresh_attempted_at, last_refresh_status
            )
            VALUES (
                :source, :external_id, :title, :url, :comuna, :m2, :bedrooms, :bathrooms,
                :parking, :lat, :lon, :price_clp, :status, :fingerprint,
                CAST(:raw_metadata AS JSON), :scraped_at, :last_seen_at,
                :last_refresh_attempted_at, :last_refresh_status
            )
            RETURNING id
            """
        ),
        data,
    ).scalar_one()


def _find_existing_listing(conn: Connection, data: dict[str, Any]) -> int | None:
    found = conn.execute(
        text("SELECT id FROM listings WHERE fingerprint = :fingerprint"),
        {"fingerprint": data["fingerprint"]},
    ).scalar_one_or_none()
    if found is not None:
        return found
    if data.get("external_id"):
        found = conn.execute(
            text("SELECT id FROM listings WHERE source = :source AND external_id = :external_id"),
            {"source": data["source"], "external_id": data["external_id"]},
        ).scalar_one_or_none()
        if found is not None:
            return found
    if data.get("url"):
        return conn.execute(
            text("SELECT id FROM listings WHERE source = :source AND url = :url"),
            {"source": data["source"], "url": data["url"]},
        ).scalar_one_or_none()
    return None


def _truncate(conn: Connection) -> None:
    conn.execute(text("TRUNCATE usage_logs, saved_listings, price_history, listings, properties, users RESTART IDENTITY CASCADE"))


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _iter_rows(conn: sqlite3.Connection, table: str, limit: int | None) -> Iterable[sqlite3.Row]:
    query = f"SELECT * FROM {table}"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    return conn.execute(query)


def _first(row: sqlite3.Row, columns: set[str], names: list[str]) -> Any:
    for name in names:
        if name in columns:
            return row[name]
    return None


def _price_clp(row: sqlite3.Row, columns: set[str]) -> Decimal | None:
    raw = _first(row, columns, ["price_clp", "precio_clp", "price", "precio"])
    value = _decimal(raw)
    if value is not None:
        return value
    uf = _decimal(_first(row, columns, ["price_uf", "precio_uf", "uf"]))
    return uf * LEGACY_UF_ARTIFACT_RATE if uf is not None else None


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(value: Any, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _datetime_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)


def _role(value: Any) -> str:
    return str(value) if value in {"admin", "analyst", "viewer"} else "viewer"


def _fingerprint(source: str, external_id: Any, url: Any, raw: dict[str, Any]) -> str:
    base = json.dumps({"source": source, "external_id": external_id, "url": url, "raw": raw}, sort_keys=True, default=str)
    return sha256(base.encode("utf-8")).hexdigest()


def _print_summary(summary: MigrationSummary, *, dry_run: bool) -> None:
    print(f"SQLite migration summary ({'dry-run' if dry_run else 'write'})")
    print("=" * 72)
    for name, stats in summary.tables.items():
        print(
            f"{name}: read={stats.read} inserted={stats.inserted} "
            f"skipped={stats.skipped} errors={stats.errors}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
