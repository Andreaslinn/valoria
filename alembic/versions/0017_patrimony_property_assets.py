"""add patrimony property assets

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-16
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "property_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("comuna", sa.String(length=64), nullable=False),
        sa.Column("property_type", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("m2", sa.Float(), nullable=False),
        sa.Column("built_area_m2", sa.Float(), nullable=True),
        sa.Column("land_area_m2", sa.Float(), nullable=True),
        sa.Column("usable_area_m2", sa.Float(), nullable=True),
        sa.Column("bedrooms", sa.Integer(), nullable=True),
        sa.Column("bathrooms", sa.Integer(), nullable=True),
        sa.Column("parking", sa.Integer(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("characteristics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("m2 > 0", name="ck_property_assets_positive_m2"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_property_assets_comuna", "property_assets", ["comuna"], unique=False)
    op.create_index("ix_property_assets_user_id", "property_assets", ["user_id"], unique=False)
    op.create_index("ix_property_assets_user_updated", "property_assets", ["user_id", "updated_at"], unique=False)

    op.create_table(
        "property_valuation_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("estimated_value_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("estimated_value_clp", sa.Numeric(18, 2), nullable=True),
        sa.Column("lower_bound_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("upper_bound_uf", sa.Numeric(18, 2), nullable=True),
        sa.Column("lower_bound_clp", sa.Numeric(18, 2), nullable=True),
        sa.Column("upper_bound_clp", sa.Numeric(18, 2), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("engine_name", sa.String(length=64), nullable=True),
        sa.Column("engine_version", sa.String(length=64), nullable=True),
        sa.Column("engine_payload", sa.JSON(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "estimated_value_uf IS NULL OR estimated_value_uf > 0",
            name="ck_property_valuation_snapshots_positive_estimated_uf",
        ),
        sa.CheckConstraint(
            "estimated_value_clp IS NULL OR estimated_value_clp > 0",
            name="ck_property_valuation_snapshots_positive_estimated_clp",
        ),
        sa.ForeignKeyConstraint(["property_id"], ["property_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_property_valuation_snapshots_property_id",
        "property_valuation_snapshots",
        ["property_id"],
        unique=False,
    )
    op.create_index(
        "ix_property_valuation_snapshots_property_snapshot",
        "property_valuation_snapshots",
        ["property_id", "snapshot_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_property_valuation_snapshots_property_snapshot", table_name="property_valuation_snapshots")
    op.drop_index("ix_property_valuation_snapshots_property_id", table_name="property_valuation_snapshots")
    op.drop_table("property_valuation_snapshots")
    op.drop_index("ix_property_assets_user_updated", table_name="property_assets")
    op.drop_index("ix_property_assets_user_id", table_name="property_assets")
    op.drop_index("ix_property_assets_comuna", table_name="property_assets")
    op.drop_table("property_assets")
