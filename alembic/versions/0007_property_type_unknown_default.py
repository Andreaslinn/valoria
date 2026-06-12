"""make property_type structural with unknown default

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-12
"""
# ruff: noqa: I001
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE listings SET property_type = 'unknown' WHERE property_type IS NULL")
    op.execute("UPDATE properties SET property_type = 'unknown' WHERE property_type IS NULL")
    op.alter_column(
        "listings",
        "property_type",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default="unknown",
    )
    op.alter_column(
        "properties",
        "property_type",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default="unknown",
    )


def downgrade() -> None:
    op.alter_column(
        "properties",
        "property_type",
        existing_type=sa.String(length=32),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "listings",
        "property_type",
        existing_type=sa.String(length=32),
        nullable=True,
        server_default=None,
    )
