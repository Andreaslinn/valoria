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

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
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


class UFRateORM(Base):
    __tablename__ = "uf_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    value_clp: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("value_clp > 0", name="positive_uf_value_clp"),
    )


class PortfolioItemValuationSnapshotORM(Base):
    __tablename__ = "portfolio_item_valuation_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), nullable=False, index=True)
    watchlist_item_id: Mapped[int | None] = mapped_column(ForeignKey("saved_listings.id", ondelete="SET NULL"), index=True)
    valuation_id: Mapped[int | None] = mapped_column(Integer)
    estimated_value_uf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    estimated_value_clp: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    lower_bound_uf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    upper_bound_uf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    confidence: Mapped[str | None] = mapped_column(String(32))
    engine_name: Mapped[str | None] = mapped_column(String(64))
    engine_version: Mapped[str | None] = mapped_column(String(64))
    valuation_source: Mapped[str] = mapped_column(String(64), nullable=False)
    valuation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    unavailable_reason: Mapped[str | None] = mapped_column(String(128))
    published_price_uf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    published_price_clp: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    delta_uf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    delta_pct: Mapped[float | None] = mapped_column(Float)
    delta_status: Mapped[str] = mapped_column(String(32), nullable=False)
    delta_unavailable_reason: Mapped[str | None] = mapped_column(String(128))
    data_freshness_status: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_portfolio_item_snapshots_user_created", "user_id", "snapshot_at"),
        Index("ix_portfolio_item_snapshots_listing_created", "listing_id", "snapshot_at"),
        CheckConstraint(
            "estimated_value_uf IS NULL OR estimated_value_uf > 0",
            name="ck_portfolio_item_snapshot_positive_estimated_uf",
        ),
        CheckConstraint(
            "estimated_value_clp IS NULL OR estimated_value_clp > 0",
            name="ck_portfolio_item_snapshot_positive_estimated_clp",
        ),
    )


class PortfolioAggregateSnapshotORM(Base):
    __tablename__ = "portfolio_aggregate_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_estimated_value_uf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    average_estimated_value_uf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total_published_price_uf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total_upside_uf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    average_delta_pct: Mapped[float | None] = mapped_column(Float)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unavailable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_portfolio_aggregate_user_snapshot_at", "user_id", "snapshot_at"),
        CheckConstraint("item_count >= 0", name="ck_portfolio_aggregate_item_count_non_negative"),
        CheckConstraint("coverage_count >= 0", name="ck_portfolio_aggregate_coverage_count_non_negative"),
        CheckConstraint("unavailable_count >= 0", name="ck_portfolio_aggregate_unavailable_count_non_negative"),
    )


class PortfolioComparisonORM(Base):
    __tablename__ = "portfolio_comparisons"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="Comparacion de Portafolio")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", server_default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[UserORM] = relationship(back_populates="portfolio_comparisons")
    items: Mapped[list[PortfolioComparisonItemORM]] = relationship(
        back_populates="comparison",
        cascade="all, delete-orphan",
        order_by="PortfolioComparisonItemORM.position",
    )

    __table_args__ = (
        Index("ix_portfolio_comparisons_user_updated", "user_id", "updated_at"),
    )


class PortfolioComparisonItemORM(Base):
    __tablename__ = "portfolio_comparison_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_comparisons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), nullable=False, index=True)
    watchlist_item_id: Mapped[int | None] = mapped_column(ForeignKey("saved_listings.id", ondelete="SET NULL"), index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    comparison: Mapped[PortfolioComparisonORM] = relationship(back_populates="items")
    listing: Mapped[ListingORM] = relationship()
    watchlist_item: Mapped[SavedListingORM | None] = relationship()

    __table_args__ = (
        UniqueConstraint("comparison_id", "listing_id", name="uq_portfolio_comparison_listing"),
        UniqueConstraint("comparison_id", "position", name="uq_portfolio_comparison_position"),
        CheckConstraint("position >= 1 AND position <= 4", name="ck_portfolio_comparison_position_range"),
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
    portfolio_comparisons: Mapped[list[PortfolioComparisonORM]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


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
