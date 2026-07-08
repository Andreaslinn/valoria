"""add daily uf rates table

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-19
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "uf_rates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value_clp", sa.Numeric(18, 2), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("value_clp > 0", name="positive_uf_value_clp"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", name="uq_uf_rates_date"),
    )
    op.create_index("ix_uf_rates_date", "uf_rates", ["date"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_uf_rates_date", table_name="uf_rates")
    op.drop_table("uf_rates")
