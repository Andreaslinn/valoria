"""add listings status scraped_at index

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-01
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_listings_status_scraped_at",
        "listings",
        ["status", "scraped_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_listings_status_scraped_at", table_name="listings")
