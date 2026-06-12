"""Repositorio SQLAlchemy para Properties (inmuebles físicos).

Implementa core.ports.property_repo.PropertyRepository.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.entities.listing import Property
from core.exceptions import PropertyNotFoundError
from core.ports.property_repo import PropertyRepository
from infrastructure.db.mappers import (
    property_from_orm,
    property_to_orm,
    update_property_orm,
)
from infrastructure.db.models import PropertyORM

# Tolerancia en m² para considerar que dos listings apuntan al mismo inmueble.
# El scraping tiene variaciones menores (redondeos, errores de tipeo).
_M2_TOLERANCE = 1.0


class SqlAlchemyPropertyRepository(PropertyRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, prop: Property) -> Property:
        if prop.id is None:
            orm = property_to_orm(prop)
            self._session.add(orm)
            await self._session.flush()
            await self._session.refresh(orm)
            return property_from_orm(orm)

        orm = await self._session.get(PropertyORM, prop.id)
        if orm is None:
            raise PropertyNotFoundError(f"Property id={prop.id} no existe")
        update_property_orm(orm, prop)
        await self._session.flush()
        return property_from_orm(orm)

    async def find_by_id(self, property_id: int) -> Property | None:
        orm = await self._session.get(PropertyORM, property_id)
        return property_from_orm(orm) if orm else None

    async def find_matching(
        self,
        comuna_slug: str,
        m2: float,
        bedrooms: int,
        bathrooms: int,
        parking: int,
        property_type: str | None = None,
        built_area_m2: float | None = None,
        land_area_m2: float | None = None,
    ) -> Property | None:
        area = built_area_m2 or m2
        stmt = (
            select(PropertyORM)
            .where(PropertyORM.comuna == comuna_slug)
            .where(PropertyORM.bedrooms == bedrooms)
            .where(PropertyORM.bathrooms == bathrooms)
            .where(PropertyORM.parking == parking)
            .where(PropertyORM.m2.between(m2 - _M2_TOLERANCE, m2 + _M2_TOLERANCE))
            .where(func.coalesce(PropertyORM.built_area_m2, PropertyORM.m2).between(area - _M2_TOLERANCE, area + _M2_TOLERANCE))
            .limit(1)
        )
        if property_type is not None:
            stmt = stmt.where(PropertyORM.property_type == property_type)
        if property_type == "house" and land_area_m2 is not None:
            stmt = stmt.where(PropertyORM.land_area_m2.between(land_area_m2 - _M2_TOLERANCE, land_area_m2 + _M2_TOLERANCE))
        orm = (await self._session.execute(stmt)).scalar_one_or_none()
        return property_from_orm(orm) if orm else None
