"""add watchlist price snapshots

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-07
"""
# ruff: noqa: I001
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("saved_listings") as batch_op:
        batch_op.add_column(sa.Column("saved_price_clp", sa.Numeric(18, 2), nullable=True))
        batch_op.add_column(sa.Column("saved_price_uf", sa.Numeric(18, 2), nullable=True))
        batch_op.add_column(
            sa.Column("status", sa.String(32), nullable=False, server_default="active")
        )
    op.execute(
        """
        UPDATE saved_listings
        SET saved_price_clp = (
            SELECT listings.price_clp
            FROM listings
            WHERE listings.id = saved_listings.listing_id
        )
        WHERE saved_price_clp IS NULL
        """
    )
    with op.batch_alter_table("saved_listings") as batch_op:
        batch_op.alter_column("saved_price_clp", nullable=False)
        batch_op.alter_column("status", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("saved_listings") as batch_op:
        batch_op.drop_column("status")
        batch_op.drop_column("saved_price_uf")
        batch_op.drop_column("saved_price_clp")
