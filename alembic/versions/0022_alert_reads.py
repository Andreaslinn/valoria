"""Add per-user alert acknowledgements without rewriting shared alert history."""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("alert_reads",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("alert_id", sa.Integer(), sa.ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade():
    # Automatic rollback must not destroy acknowledgement history.
    raise RuntimeError("Preserve alert_reads during application rollback; removal requires an explicit data-retention decision")
