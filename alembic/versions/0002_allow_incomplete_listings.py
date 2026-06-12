"""allow incomplete listings

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_listings_positive_m2", "listings", type_="check")
    op.alter_column("listings", "m2", existing_type=sa.Float(), nullable=True)
    op.create_check_constraint(
        "ck_listings_positive_m2",
        "listings",
        "m2 IS NULL OR m2 > 0",
    )


def downgrade() -> None:
    op.execute("UPDATE listings SET m2 = 1 WHERE m2 IS NULL")
    op.drop_constraint("ck_listings_positive_m2", "listings", type_="check")
    op.alter_column("listings", "m2", existing_type=sa.Float(), nullable=False)
    op.create_check_constraint("ck_listings_positive_m2", "listings", "m2 > 0")
