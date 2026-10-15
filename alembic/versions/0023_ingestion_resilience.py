"""Isolated UF calendar, durable pending prices and source execution health."""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = depends_on = None


def upgrade():
    op.create_table("ingestion_uf_calendar", sa.Column("date", sa.Date(), primary_key=True),
                    sa.Column("value", sa.Numeric(18, 2), nullable=False),
                    sa.Column("source", sa.String(64), nullable=False),
                    sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("ingestion_pending_prices", sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("source", sa.String(32), nullable=False),
                    sa.Column("external_id", sa.String(128), nullable=False),
                    sa.Column("payload", sa.JSON(), nullable=False),
                    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("source", "external_id", name="uq_ingestion_pending_identity"))
    op.create_table("ingestion_runs", sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("source", sa.String(32), nullable=False),
                    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("finished_at", sa.DateTime(timezone=True)),
                    sa.Column("successful", sa.Boolean()),
                    sa.Column("counters", sa.JSON(), nullable=False),
                    sa.Column("errors", sa.JSON(), nullable=False))
    op.create_index("ix_ingestion_runs_source_finished", "ingestion_runs", ["source", "finished_at"])


def downgrade():
    # Operational rollback retains original prices/calendar; do not silently lose pending ads.
    raise RuntimeError("Rollback application image; retain ingestion tables until pending prices are reconciled and archived")
