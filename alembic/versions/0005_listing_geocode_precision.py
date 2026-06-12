"""add listing geocode precision

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-11

Diagnostic:
    SELECT geocode_precision, COUNT(*)
    FROM listings
    GROUP BY geocode_precision;
"""
# ruff: noqa: I001
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("geocode_precision", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("listings", "geocode_precision")
