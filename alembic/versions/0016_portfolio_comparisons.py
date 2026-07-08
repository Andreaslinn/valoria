"""add portfolio comparisons

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-20
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_comparisons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portfolio_comparisons_user_id", "portfolio_comparisons", ["user_id"], unique=False)
    op.create_index("ix_portfolio_comparisons_status", "portfolio_comparisons", ["status"], unique=False)
    op.create_index(
        "ix_portfolio_comparisons_user_updated",
        "portfolio_comparisons",
        ["user_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "portfolio_comparison_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comparison_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("watchlist_item_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("position >= 1 AND position <= 4", name="ck_portfolio_comparison_position_range"),
        sa.ForeignKeyConstraint(["comparison_id"], ["portfolio_comparisons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["watchlist_item_id"], ["saved_listings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comparison_id", "listing_id", name="uq_portfolio_comparison_listing"),
        sa.UniqueConstraint("comparison_id", "position", name="uq_portfolio_comparison_position"),
    )
    op.create_index("ix_portfolio_comparison_items_comparison_id", "portfolio_comparison_items", ["comparison_id"], unique=False)
    op.create_index("ix_portfolio_comparison_items_listing_id", "portfolio_comparison_items", ["listing_id"], unique=False)
    op.create_index(
        "ix_portfolio_comparison_items_watchlist_item_id",
        "portfolio_comparison_items",
        ["watchlist_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_comparison_items_watchlist_item_id", table_name="portfolio_comparison_items")
    op.drop_index("ix_portfolio_comparison_items_listing_id", table_name="portfolio_comparison_items")
    op.drop_index("ix_portfolio_comparison_items_comparison_id", table_name="portfolio_comparison_items")
    op.drop_table("portfolio_comparison_items")
    op.drop_index("ix_portfolio_comparisons_user_updated", table_name="portfolio_comparisons")
    op.drop_index("ix_portfolio_comparisons_status", table_name="portfolio_comparisons")
    op.drop_index("ix_portfolio_comparisons_user_id", table_name="portfolio_comparisons")
    op.drop_table("portfolio_comparisons")
