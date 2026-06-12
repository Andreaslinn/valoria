"""add area fields and property type

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-11
"""
# ruff: noqa: I001
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("property_type", sa.String(length=32), nullable=True))
    op.add_column("listings", sa.Column("built_area_m2", sa.Float(), nullable=True))
    op.add_column("listings", sa.Column("land_area_m2", sa.Float(), nullable=True))
    op.add_column("listings", sa.Column("usable_area_m2", sa.Float(), nullable=True))
    op.create_index("ix_listings_property_type", "listings", ["property_type"])
    op.execute(
        """
        UPDATE listings
        SET property_type = COALESCE(
                property_type,
                CASE WHEN lower(title) LIKE '%casa%' THEN 'house' ELSE 'apartment' END
            ),
            built_area_m2 = COALESCE(built_area_m2, m2),
            usable_area_m2 = COALESCE(usable_area_m2, m2)
        """
    )

    op.add_column("properties", sa.Column("property_type", sa.String(length=32), nullable=True))
    op.add_column("properties", sa.Column("built_area_m2", sa.Float(), nullable=True))
    op.add_column("properties", sa.Column("land_area_m2", sa.Float(), nullable=True))
    op.add_column("properties", sa.Column("usable_area_m2", sa.Float(), nullable=True))
    op.execute(
        """
        UPDATE properties
        SET property_type = COALESCE(property_type, 'apartment'),
            built_area_m2 = COALESCE(built_area_m2, m2),
            usable_area_m2 = COALESCE(usable_area_m2, m2)
        """
    )


def downgrade() -> None:
    op.drop_column("properties", "usable_area_m2")
    op.drop_column("properties", "land_area_m2")
    op.drop_column("properties", "built_area_m2")
    op.drop_column("properties", "property_type")
    op.drop_index("ix_listings_property_type", table_name="listings")
    op.drop_column("listings", "usable_area_m2")
    op.drop_column("listings", "land_area_m2")
    op.drop_column("listings", "built_area_m2")
    op.drop_column("listings", "property_type")
