"""add listing price provenance fields

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-05
"""
# ruff: noqa: I001
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("listings") as batch_op:
        batch_op.add_column(sa.Column("price_uf", sa.Numeric(18, 2), nullable=True))
        batch_op.add_column(sa.Column("price_currency", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("price_uf_confidence", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("price_uf_source", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("price_recovery_method", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("listings") as batch_op:
        batch_op.drop_column("price_recovery_method")
        batch_op.drop_column("price_uf_source")
        batch_op.drop_column("price_uf_confidence")
        batch_op.drop_column("price_currency")
        batch_op.drop_column("price_uf")
