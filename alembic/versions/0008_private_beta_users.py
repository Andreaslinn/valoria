"""private beta users by email

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-14
"""
# ruff: noqa: I001
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "username", new_column_name="email", existing_type=sa.String(64))
    op.alter_column("users", "email", existing_type=sa.String(64), type_=sa.String(255))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET role = 'beta_user' WHERE role IN ('viewer', 'analyst')")
    op.drop_constraint("uq_users_username", "users", type_="unique")
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.create_index("ix_users_email", "users", ["email"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.create_unique_constraint("uq_users_username", "users", ["email"])
    op.drop_column("users", "last_login_at")
    op.alter_column("users", "email", existing_type=sa.String(255), type_=sa.String(64))
    op.alter_column("users", "email", new_column_name="username", existing_type=sa.String(64))
