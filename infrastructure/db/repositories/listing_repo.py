"""Repositorio SQLAlchemy para Listings.

Implementa core.ports.listing_repo.ListingRepository.

Diseño:
    · Recibe una AsyncSession inyectada (no la crea).
    · NO hace commit — eso es responsabilidad del caller (unit of work).
    · Usa flush() para obtener IDs generados por la DB antes de retornar.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config.constants import LISTING_STALE_DAYS
from core.entities.listing import Listing
from core.exceptions import ListingNotFoundError
from core.ports.listing_repo import ListingRepository
from domain.geocoding.quality import apply_geocoding_guardrails
from infrastructure.db.mappers import (
    listing_from_orm,
    listing_to_orm,
    update_listing_orm,
)
from infrastructure.db.models import ListingORM


class SqlAlchemyListingRepository(ListingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_observation(self, raw, cleaned, saved) -> None:
        from domain.ingestion.observations import build_observation
        from infrastructure.db.observation_history import append_observation
        from config import get_settings
        if get_settings().ingestion_observation_history_enabled and cleaned.source in {"yapo", "portalinmobiliario"}:
            await append_observation(self._session, build_observation(raw, cleaned, saved), enabled=True)

    async def save(self, listing: Listing) -> Listing:
        if listing.id is None:
            orm = listing_to_orm(listing)
            self._session.add(orm)
            await self._session.flush()
            await self._session.refresh(orm)
            return listing_from_orm(orm)

        orm = await self._session.get(ListingORM, listing.id)
        if orm is None:
            raise ListingNotFoundError(f"Listing id={listing.id} no existe")
        update_listing_orm(orm, listing)
        await self._session.flush()
        return listing_from_orm(orm)

    async def find_by_id(self, listing_id: int) -> Listing | None:
        orm = await self._session.get(ListingORM, listing_id)
        return listing_from_orm(orm) if orm else None

    async def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        comuna: str | None = None,
        status: str | None = None,
    ) -> Sequence[Listing]:
        stmt = select(ListingORM).order_by(ListingORM.scraped_at.desc())
        if comuna is not None:
            stmt = stmt.where(ListingORM.comuna == comuna)
        if status is not None:
            stmt = stmt.where(ListingORM.status == status)
        stmt = stmt.offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return [listing_from_orm(orm) for orm in result.scalars().all()]

    async def list_active(self, *, limit: int | None = None) -> Sequence[Listing]:
        stmt = (
            select(ListingORM)
            .where(ListingORM.status == "active")
            .order_by(ListingORM.scraped_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return apply_geocoding_guardrails([listing_from_orm(orm) for orm in result.scalars().all()])

    async def find_by_fingerprint(self, fingerprint: str) -> Listing | None:
        stmt = select(ListingORM).where(ListingORM.fingerprint == fingerprint)
        orm = (await self._session.execute(stmt)).scalar_one_or_none()
        return listing_from_orm(orm) if orm else None

    async def find_by_source_external_id(self, source: str, external_id: str) -> Listing | None:
        stmt = (
            select(ListingORM)
            .where(ListingORM.source == source)
            .where(ListingORM.external_id == external_id)
        )
        orm = (await self._session.execute(stmt)).scalar_one_or_none()
        return listing_from_orm(orm) if orm else None

    async def find_active_in_comuna(
        self,
        comuna_slug: str,
        *,
        property_type: str | None = None,
    ) -> Sequence[Listing]:
        stmt = (
            select(ListingORM)
            .where(ListingORM.comuna == comuna_slug)
            .where(ListingORM.status == "active")
        )
        if property_type is not None:
            stmt = stmt.where(ListingORM.property_type == property_type)
        result = await self._session.execute(stmt)
        return apply_geocoding_guardrails([listing_from_orm(orm) for orm in result.scalars().all()])

    async def count_active(self) -> int:
        stmt = (
            select(func.count())
            .select_from(ListingORM)
            .where(ListingORM.status == "active")
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def mark_stale_listings(self, stale_days: int = LISTING_STALE_DAYS) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=stale_days)
        stmt = (
            update(ListingORM)
            .where(ListingORM.status == "active")
            .where(ListingORM.updated_at < cutoff)
            .values(status="removed")
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)
