"""add territorial developments

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-21
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "territorial_developments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("development_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("affected_communes", sa.JSON(), nullable=False),
        sa.Column("affected_microzones", sa.JSON(), nullable=False),
        sa.Column("expected_start_date", sa.Date(), nullable=True),
        sa.Column("expected_completion_date", sa.Date(), nullable=True),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=False),
        sa.Column("conservative_min_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("conservative_max_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("central_min_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("central_max_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("favorable_max_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("methodology_note", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('announced', 'planned', 'confirmed', 'under_construction', 'completed', 'cancelled')",
            name="ck_territorial_developments_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_territorial_developments_active_status",
        "territorial_developments",
        ["is_active", "status"],
        unique=False,
    )
    op.create_index("ix_territorial_developments_status", "territorial_developments", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_territorial_developments_status", table_name="territorial_developments")
    op.drop_index("ix_territorial_developments_active_status", table_name="territorial_developments")
    op.drop_table("territorial_developments")
