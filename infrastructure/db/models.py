"""Modelos SQLAlchemy ORM.

Convenciones:
    · Schema completo aquí (incluyendo saved_listings y usage_logs que antes
      se creaban con SQL imperativo desde app.py).
    · price_clp usa Numeric(18,2) — evita errores de float en montos.
    · raw_metadata/payload usan JSON genérico (compatible SQLite/Postgres).
    · Todos los timestamps son timezone-aware.
    · Mapeo typed con Mapped[] + mapped_column() (SQLAlchemy 2.0).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from infrastructure.db.base import Base, TimestampMixin


# ─────────────────────────────────────────────────────────
#  Property — inmueble físico único
# ─────────────────────────────────────────────────────────
class PropertyORM(Base, TimestampMixin):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    comuna: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    property_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", server_default="unknown")
    m2: Mapped[float] = mapped_column(Float, nullable=False)
    built_area_m2: Mapped[float | None] = mapped_column(Float)
    land_area_m2: Mapped[float | None] = mapped_column(Float)
    usable_area_m2: Mapped[float | None] = mapped_column(Float)
    bedrooms: Mapped[int] = mapped_column(Integer, nullable=False)
    bathrooms: Mapped[int] = mapped_column(Integer, nullable=False)
    parking: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)

    listings: Mapped[list[ListingORM]] = relationship(back_populates="property")

    __table_args__ = (
        Index(
            "ix_properties_match",
            "comuna", "m2", "bedrooms", "bathrooms", "parking",
        ),
        CheckConstraint("m2 > 0", name="positive_m2"),
        CheckConstraint("bedrooms >= 0", name="non_negative_bedrooms"),
    )


# ─────────────────────────────────────────────────────────
#  Listing — publicación de venta
# ─────────────────────────────────────────────────────────
class ListingORM(Base, TimestampMixin):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int | None] = mapped_column(
        ForeignKey("properties.id", ondelete="SET NULL"),
        index=True,
    )

    # Origen
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128))

    # Datos de la publicación
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1024))

    # Atributos físicos (denormalizados para queries rápidas del radar)
    comuna: Mapped[str] = mapped_column(String(64), nullable=False)
    property_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", server_default="unknown", index=True)
    m2: Mapped[float | None] = mapped_column(Float)
    built_area_m2: Mapped[float | None] = mapped_column(Float)
    land_area_m2: Mapped[float | None] = mapped_column(Float)
    usable_area_m2: Mapped[float | None] = mapped_column(Float)
    bedrooms: Mapped[int] = mapped_column(Integer, nullable=False)
    bathrooms: Mapped[int] = mapped_column(Integer, nullable=False)
    parking: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    geocode_precision: Mapped[str | None] = mapped_column(String(32))

    # Precio + estado
    price_clp: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    price_uf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    price_currency: Mapped[str | None] = mapped_column(String(16))
    price_uf_confidence: Mapped[str | None] = mapped_column(String(32))
    price_uf_source: Mapped[str | None] = mapped_column(String(64))
    price_recovery_method: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    # Deduplicación
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    # Payload crudo del scraper (para auditoría / debugging)
    raw_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_refresh_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refresh_status: Mapped[str | None] = mapped_column(String(64))

    property: Mapped[PropertyORM | None] = relationship(back_populates="listings")
    price_history: Mapped[list[PriceHistoryORM]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )
    alerts: Mapped[list[AlertORM]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )
    saved_by: Mapped[list[SavedListingORM]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Hot path del radar: activos por comuna ordenados por precio
        Index("ix_listings_comuna_status", "comuna", "status"),
        Index("ix_listings_status_scraped_at", "status", "scraped_at"),
        # Upsert desde scrapers por (source, external_id)
        UniqueConstraint("source", "external_id", name="uq_listings_source_external"),
        Index("ix_listings_scraped_at", "scraped_at"),
        CheckConstraint("price_clp > 0", name="positive_price"),
        CheckConstraint("m2 IS NULL OR m2 > 0", name="ck_listings_positive_m2"),
    )


# ─────────────────────────────────────────────────────────
#  PriceHistory — historial de precios por listing
# ─────────────────────────────────────────────────────────
class PriceHistoryORM(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"),
        nullable=False,
    )
    price_clp: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    price_uf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    price_clp_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    price_currency: Mapped[str | None] = mapped_column(String(16))
    uf_rate_used: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    change_basis: Mapped[str | None] = mapped_column(String(32))
    is_artifact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    artifact_reason: Mapped[str | None] = mapped_column(String(128))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    listing: Mapped[ListingORM] = relationship(back_populates="price_history")

    __table_args__ = (
        Index("ix_price_history_listing_observed", "listing_id", "observed_at"),
    )


class AlertORM(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    listing: Mapped[ListingORM] = relationship(back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_listing_type_created", "listing_id", "alert_type", "created_at"),
    )


# ─────────────────────────────────────────────────────────
#  User — autenticación + roles
# ─────────────────────────────────────────────────────────
class UserORM(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'admin' | 'beta_user'
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="beta_user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    saved_listings: Mapped[list[SavedListingORM]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    usage_logs: Mapped[list[UsageLogORM]] = relationship(back_populates="user")


# ─────────────────────────────────────────────────────────
#  SavedListing — favoritos del usuario
# ─────────────────────────────────────────────────────────
class SavedListingORM(Base):
    __tablename__ = "saved_listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)
    saved_price_clp: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    saved_price_uf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[UserORM] = relationship(back_populates="saved_listings")
    listing: Mapped[ListingORM] = relationship(back_populates="saved_by")

    __table_args__ = (
        UniqueConstraint("user_id", "listing_id", name="uq_saved_listings_user_listing"),
    )


# ─────────────────────────────────────────────────────────
#  UsageLog — tracking de eventos (reemplaza usage_log.json)
# ─────────────────────────────────────────────────────────
class UsageLogORM(Base):
    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[UserORM | None] = relationship(back_populates="usage_logs")

    __table_args__ = (
        Index("ix_usage_logs_type_created", "event_type", "created_at"),
    )
