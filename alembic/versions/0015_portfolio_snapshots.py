"""add portfolio snapshot skeleton tables

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-19
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_item_valuation_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("watchlist_item_id", sa.Integer(), nullable=True),
        sa.Column("valuation_id", sa.Integer(), nullable=True),
        sa.Column("estimated_value_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("estimated_value_clp", sa.Numeric(18, 2), nullable=True),
        sa.Column("lower_bound_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("upper_bound_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("engine_name", sa.String(length=64), nullable=True),
        sa.Column("engine_version", sa.String(length=64), nullable=True),
        sa.Column("valuation_source", sa.String(length=64), nullable=False),
        sa.Column("valuation_status", sa.String(length=32), nullable=False),
        sa.Column("unavailable_reason", sa.String(length=128), nullable=True),
        sa.Column("published_price_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("published_price_clp", sa.Numeric(18, 2), nullable=True),
        sa.Column("delta_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("delta_pct", sa.Float(), nullable=True),
        sa.Column("delta_status", sa.String(length=32), nullable=False),
        sa.Column("delta_unavailable_reason", sa.String(length=128), nullable=True),
        sa.Column("data_freshness_status", sa.String(length=64), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "estimated_value_uf IS NULL OR estimated_value_uf > 0",
            name="ck_portfolio_item_snapshot_positive_estimated_uf",
        ),
        sa.CheckConstraint(
            "estimated_value_clp IS NULL OR estimated_value_clp > 0",
            name="ck_portfolio_item_snapshot_positive_estimated_clp",
        ),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["watchlist_item_id"], ["saved_listings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_portfolio_item_valuation_snapshots_user_id",
        "portfolio_item_valuation_snapshots",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_portfolio_item_valuation_snapshots_listing_id",
        "portfolio_item_valuation_snapshots",
        ["listing_id"],
        unique=False,
    )
    op.create_index(
        "ix_portfolio_item_valuation_snapshots_watchlist_item_id",
        "portfolio_item_valuation_snapshots",
        ["watchlist_item_id"],
        unique=False,
    )
    op.create_index(
        "ix_portfolio_item_snapshots_user_created",
        "portfolio_item_valuation_snapshots",
        ["user_id", "snapshot_at"],
        unique=False,
    )
    op.create_index(
        "ix_portfolio_item_snapshots_listing_created",
        "portfolio_item_valuation_snapshots",
        ["listing_id", "snapshot_at"],
        unique=False,
    )

    op.create_table(
        "portfolio_aggregate_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("total_estimated_value_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("average_estimated_value_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("total_published_price_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("total_upside_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("average_delta_pct", sa.Float(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("coverage_count", sa.Integer(), nullable=False),
        sa.Column("unavailable_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("item_count >= 0", name="ck_portfolio_aggregate_item_count_non_negative"),
        sa.CheckConstraint("coverage_count >= 0", name="ck_portfolio_aggregate_coverage_count_non_negative"),
        sa.CheckConstraint("unavailable_count >= 0", name="ck_portfolio_aggregate_unavailable_count_non_negative"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_portfolio_aggregate_snapshots_user_id",
        "portfolio_aggregate_snapshots",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_portfolio_aggregate_snapshots_snapshot_date",
        "portfolio_aggregate_snapshots",
        ["snapshot_date"],
        unique=False,
    )
    op.create_index(
        "ix_portfolio_aggregate_user_snapshot_at",
        "portfolio_aggregate_snapshots",
        ["user_id", "snapshot_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_aggregate_user_snapshot_at", table_name="portfolio_aggregate_snapshots")
    op.drop_index("ix_portfolio_aggregate_snapshots_snapshot_date", table_name="portfolio_aggregate_snapshots")
    op.drop_index("ix_portfolio_aggregate_snapshots_user_id", table_name="portfolio_aggregate_snapshots")
    op.drop_table("portfolio_aggregate_snapshots")
    op.drop_index("ix_portfolio_item_snapshots_listing_created", table_name="portfolio_item_valuation_snapshots")
    op.drop_index("ix_portfolio_item_snapshots_user_created", table_name="portfolio_item_valuation_snapshots")
    op.drop_index("ix_portfolio_item_valuation_snapshots_watchlist_item_id", table_name="portfolio_item_valuation_snapshots")
    op.drop_index("ix_portfolio_item_valuation_snapshots_listing_id", table_name="portfolio_item_valuation_snapshots")
    op.drop_index("ix_portfolio_item_valuation_snapshots_user_id", table_name="portfolio_item_valuation_snapshots")
    op.drop_table("portfolio_item_valuation_snapshots")
