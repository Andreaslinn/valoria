"""add patrimony strategies

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-20
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "patrimony_strategies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("property_asset_id", sa.Integer(), nullable=False),
        sa.Column("objective", sa.String(length=32), nullable=False),
        sa.Column("horizon", sa.String(length=64), nullable=True),
        sa.Column("target_value_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("urgency", sa.String(length=32), nullable=True),
        sa.Column("risk_profile", sa.String(length=32), nullable=True),
        sa.Column("next_move", sa.Text(), nullable=True),
        sa.Column("desired_property_type", sa.String(length=32), nullable=True),
        sa.Column("desired_communes", sa.JSON(), nullable=False),
        sa.Column("desired_budget_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("target_value_uf IS NULL OR target_value_uf > 0", name="ck_patrimony_strategy_target_value_uf"),
        sa.CheckConstraint("desired_budget_uf IS NULL OR desired_budget_uf > 0", name="ck_patrimony_strategy_budget_uf"),
        sa.ForeignKeyConstraint(["property_asset_id"], ["property_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_patrimony_strategies_property_asset_id", "patrimony_strategies", ["property_asset_id"], unique=False)
    op.create_index("ix_patrimony_strategies_user_id", "patrimony_strategies", ["user_id"], unique=False)
    op.create_index("ix_patrimony_strategies_user_updated", "patrimony_strategies", ["user_id", "updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_patrimony_strategies_user_updated", table_name="patrimony_strategies")
    op.drop_index("ix_patrimony_strategies_user_id", table_name="patrimony_strategies")
    op.drop_index("ix_patrimony_strategies_property_asset_id", table_name="patrimony_strategies")
    op.drop_table("patrimony_strategies")
