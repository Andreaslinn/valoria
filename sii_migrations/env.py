"""SII uses an independent, guarded local connection, never config.settings."""

from sqlalchemy import create_engine, pool

from alembic import context
from services.sii.settings import Settings

settings = Settings.load()
engine = create_engine(settings.url, poolclass=pool.NullPool)
with engine.begin() as connection:
    connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS sii")
    context.configure(
        connection=connection, version_table="alembic_version", version_table_schema="sii"
    )
    with context.begin_transaction():
        context.run_migrations()
    # Alembic first removes its final version row; only then can its own schema go.
    if (
        connection.exec_driver_sql("SELECT to_regclass('sii.alembic_version')").scalar()
        and not connection.exec_driver_sql("SELECT 1 FROM sii.alembic_version LIMIT 1").scalar()
    ):
        connection.exec_driver_sql("DROP SCHEMA sii CASCADE")
