"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-23
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─── properties ────────────────────────────────────────
    op.create_table(
        "properties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("comuna", sa.String(64), nullable=False),
        sa.Column("m2", sa.Float(), nullable=False),
        sa.Column("bedrooms", sa.Integer(), nullable=False),
        sa.Column("bathrooms", sa.Integer(), nullable=False),
        sa.Column("parking", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("m2 > 0", name="ck_properties_positive_m2"),
        sa.CheckConstraint("bedrooms >= 0", name="ck_properties_non_negative_bedrooms"),
    )
    op.create_index("ix_properties_comuna", "properties", ["comuna"])
    op.create_index(
        "ix_properties_match",
        "properties",
        ["comuna", "m2", "bedrooms", "bathrooms", "parking"],
    )

    # ─── listings ──────────────────────────────────────────
    op.create_table(
        "listings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("properties.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("url", sa.String(1024), nullable=True),
        sa.Column("comuna", sa.String(64), nullable=False),
        sa.Column("m2", sa.Float(), nullable=False),
        sa.Column("bedrooms", sa.Integer(), nullable=False),
        sa.Column("bathrooms", sa.Integer(), nullable=False),
        sa.Column("parking", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("price_clp", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column(
            "raw_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("price_clp > 0", name="ck_listings_positive_price"),
        sa.CheckConstraint("m2 > 0", name="ck_listings_positive_m2"),
        sa.UniqueConstraint("fingerprint", name="uq_listings_fingerprint"),
        sa.UniqueConstraint("source", "external_id", name="uq_listings_source_external"),
    )
    op.create_index("ix_listings_property_id", "listings", ["property_id"])
    op.create_index("ix_listings_comuna_status", "listings", ["comuna", "status"])
    op.create_index("ix_listings_scraped_at", "listings", ["scraped_at"])

    # ─── price_history ─────────────────────────────────────
    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "listing_id",
            sa.Integer(),
            sa.ForeignKey("listings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("price_clp", sa.Numeric(18, 2), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_price_history_listing_observed",
        "price_history",
        ["listing_id", "observed_at"],
    )

    # ─── users ─────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )

    # ─── saved_listings ────────────────────────────────────
    op.create_table(
        "saved_listings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "listing_id",
            sa.Integer(),
            sa.ForeignKey("listings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "listing_id", name="uq_saved_listings_user_listing"
        ),
    )

    # ─── usage_logs ────────────────────────────────────────
    op.create_table(
        "usage_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_usage_logs_type_created",
        "usage_logs",
        ["event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_logs_type_created", table_name="usage_logs")
    op.drop_table("usage_logs")

    op.drop_table("saved_listings")
    op.drop_table("users")

    op.drop_index("ix_price_history_listing_observed", table_name="price_history")
    op.drop_table("price_history")

    op.drop_index("ix_listings_scraped_at", table_name="listings")
    op.drop_index("ix_listings_comuna_status", table_name="listings")
    op.drop_index("ix_listings_property_id", table_name="listings")
    op.drop_table("listings")

    op.drop_index("ix_properties_match", table_name="properties")
    op.drop_index("ix_properties_comuna", table_name="properties")
    op.drop_table("properties")
