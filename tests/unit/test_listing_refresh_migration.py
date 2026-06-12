from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_migration_adds_refresh_fields(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    migration = _load_migration()

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE listings (
                    id INTEGER PRIMARY KEY
                )
                """
            )
        )

        context = MigrationContext.configure(conn)
        monkeypatch.setattr(migration, "op", Operations(context))

        migration.upgrade()

        columns = {column["name"] for column in inspect(conn).get_columns("listings")}
        assert "last_refresh_attempted_at" in columns
        assert "last_refresh_status" in columns


def _load_migration():
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0010_listing_refresh_fields.py"
    spec = importlib.util.spec_from_file_location("migration_0010_listing_refresh_fields", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
