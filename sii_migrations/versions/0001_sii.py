"""SII schema only. Independent version table, no changes to public tables."""

from pathlib import Path

from alembic import op

revision = "sii_0001"
down_revision = None
branch_labels = depends_on = None


def upgrade():
    op.execute((Path(__file__).parents[1] / "schema.sql").read_text(encoding="utf-8"))


def downgrade():
    # Explicit destructive rollback; source files on disk remain available for replay.
    for table in (
        "geo_predio",
        "transferencia",
        "transferencia_raw",
        "linea_construccion",
        "predio",
        "job_run",
        "source_file",
    ):
        op.execute(f"DROP TABLE sii.{table}")
    op.execute("DROP FUNCTION sii.raw_append_only()")
