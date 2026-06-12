"""add listing last seen timestamp

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-31
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("listings") as batch_op:
        batch_op.add_column(sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        UPDATE listings
        SET last_seen_at = scraped_at
        WHERE last_seen_at IS NULL
          AND scraped_at IS NOT NULL
        """
    )

    with op.batch_alter_table("listings") as batch_op:
        batch_op.alter_column(
            "last_seen_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("listings") as batch_op:
        batch_op.drop_column("last_seen_at")
