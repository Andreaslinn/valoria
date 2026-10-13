"""Add independent append-only ingestion observations; no historical backfill."""

from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "listing_observations",
        sa.Column("observation_id", sa.String(64), primary_key=True),
        # Deliberately no FK: deleting/merging a listing must not delete historical evidence.
        sa.Column("listing_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_kind", sa.String(32), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_listing_observations_publication_time",
        "listing_observations",
        ["source", "external_id", "observed_at"],
    )
    op.create_index(
        "ix_listing_observations_listing_time",
        "listing_observations",
        ["listing_id", "observed_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION reject_listing_observation_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'listing_observations is append-only'; END $$""")
        op.execute("""CREATE TRIGGER listing_observations_immutable BEFORE UPDATE OR DELETE
        ON listing_observations FOR EACH ROW EXECUTE FUNCTION reject_listing_observation_mutation()""")
        op.execute("""CREATE TRIGGER listing_observations_no_truncate BEFORE TRUNCATE
        ON listing_observations FOR EACH STATEMENT EXECUTE FUNCTION reject_listing_observation_mutation()""")
    elif op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER listing_observations_no_{action.lower()} BEFORE {action} ON listing_observations BEGIN SELECT RAISE(ABORT, 'listing_observations is append-only'); END"
            )


def downgrade():
    # Destructive: export history before an explicitly approved downgrade.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER listing_observations_immutable ON listing_observations")
        op.execute("DROP TRIGGER listing_observations_no_truncate ON listing_observations")
        op.execute("DROP FUNCTION reject_listing_observation_mutation()")
    op.drop_index("ix_listing_observations_listing_time", table_name="listing_observations")
    op.drop_index("ix_listing_observations_publication_time", table_name="listing_observations")
    op.drop_table("listing_observations")
