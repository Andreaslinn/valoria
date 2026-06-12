"""add canonical price provenance to price history

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-05
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("price_history") as batch_op:
        batch_op.add_column(sa.Column("price_uf", sa.Numeric(18, 2), nullable=True))
        batch_op.add_column(sa.Column("price_clp_snapshot", sa.Numeric(18, 2), nullable=True))
        batch_op.add_column(sa.Column("price_currency", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("uf_rate_used", sa.Numeric(18, 2), nullable=True))
        batch_op.add_column(sa.Column("change_basis", sa.String(32), nullable=True))
        batch_op.add_column(
            sa.Column(
                "is_artifact",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("artifact_reason", sa.String(128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("price_history") as batch_op:
        batch_op.drop_column("artifact_reason")
        batch_op.drop_column("is_artifact")
        batch_op.drop_column("change_basis")
        batch_op.drop_column("uf_rate_used")
        batch_op.drop_column("price_currency")
        batch_op.drop_column("price_clp_snapshot")
        batch_op.drop_column("price_uf")
