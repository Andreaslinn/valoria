from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_migration_copies_scraped_at_to_last_seen_at(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    scraped_at = "2026-05-01 12:00:00+00:00"
    migration = _load_migration()

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE listings (
                    id INTEGER PRIMARY KEY,
                    scraped_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text("INSERT INTO listings (id, scraped_at) VALUES (1, :scraped_at)"),
            {"scraped_at": scraped_at},
        )

        context = MigrationContext.configure(conn)
        monkeypatch.setattr(migration, "op", Operations(context))

        migration.upgrade()

        row = conn.execute(
            text("SELECT scraped_at, last_seen_at FROM listings WHERE id = 1")
        ).mappings().one()
        assert row["last_seen_at"] == row["scraped_at"]
        assert row["last_seen_at"] == scraped_at


def _load_migration():
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0009_listing_last_seen_at.py"
    spec = importlib.util.spec_from_file_location("migration_0009_listing_last_seen_at", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
