"""add patrimony alerts

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-21
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "patrimony_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("property_asset_id", sa.Integer(), nullable=True),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("territorial_development_id", sa.Integer(), nullable=True),
        sa.Column("alert_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "alert_type IN ("
            "'valuation_refresh_due',"
            "'property_value_changed',"
            "'target_value_reached',"
            "'market_recommendation_changed',"
            "'market_became_seller_favorable',"
            "'territorial_development_updated',"
            "'strategy_review_due'"
            ")",
            name="ck_patrimony_alerts_type",
        ),
        sa.ForeignKeyConstraint(["property_asset_id"], ["property_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["strategy_id"], ["patrimony_strategies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["territorial_development_id"], ["territorial_developments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_patrimony_alerts_user_dedupe"),
    )
    op.create_index("ix_patrimony_alerts_property_asset_id", "patrimony_alerts", ["property_asset_id"], unique=False)
    op.create_index("ix_patrimony_alerts_strategy_id", "patrimony_alerts", ["strategy_id"], unique=False)
    op.create_index(
        "ix_patrimony_alerts_territorial_development_id",
        "patrimony_alerts",
        ["territorial_development_id"],
        unique=False,
    )
    op.create_index("ix_patrimony_alerts_user_id", "patrimony_alerts", ["user_id"], unique=False)
    op.create_index(
        "ix_patrimony_alerts_user_unread",
        "patrimony_alerts",
        ["user_id", "read_at", "dismissed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_patrimony_alerts_user_unread", table_name="patrimony_alerts")
    op.drop_index("ix_patrimony_alerts_user_id", table_name="patrimony_alerts")
    op.drop_index("ix_patrimony_alerts_territorial_development_id", table_name="patrimony_alerts")
    op.drop_index("ix_patrimony_alerts_strategy_id", table_name="patrimony_alerts")
    op.drop_index("ix_patrimony_alerts_property_asset_id", table_name="patrimony_alerts")
    op.drop_table("patrimony_alerts")
