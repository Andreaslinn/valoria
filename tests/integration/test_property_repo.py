"""Tests de integración para SqlAlchemyPropertyRepository."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.entities.listing import Property
from core.exceptions import PropertyNotFoundError
from core.value_objects.location import Coordinates
from infrastructure.db.repositories import SqlAlchemyPropertyRepository


def _make_property(
    *,
    comuna: str = "nunoa",
    m2: float = 75.0,
    bedrooms: int = 3,
    bathrooms: int = 2,
    parking: int = 1,
    with_coords: bool = True,
) -> Property:
    return Property(
        id=None,
        comuna=comuna,
        m2=m2,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        parking=parking,
        coordinates=Coordinates(-33.4569, -70.5969) if with_coords else None,
    )


class TestSave:
    async def test_inserts_new_property(self, session: AsyncSession):
        repo = SqlAlchemyPropertyRepository(session)
        saved = await repo.save(_make_property())
        await session.commit()

        assert saved.id is not None
        assert saved.comuna == "nunoa"
        assert saved.m2 == 75.0

    async def test_updates_existing_property(self, session: AsyncSession):
        repo = SqlAlchemyPropertyRepository(session)
        first = await repo.save(_make_property(m2=75.0))
        await session.commit()

        first.m2 = 77.5
        first.parking = 2
        updated = await repo.save(first)
        await session.commit()

        assert updated.id == first.id
        assert updated.m2 == 77.5
        assert updated.parking == 2

    async def test_update_unknown_id_raises(self, session: AsyncSession):
        repo = SqlAlchemyPropertyRepository(session)
        ghost = _make_property()
        ghost.id = 99999

        with pytest.raises(PropertyNotFoundError):
            await repo.save(ghost)


class TestFindMatching:
    async def test_exact_match(self, session: AsyncSession):
        repo = SqlAlchemyPropertyRepository(session)
        await repo.save(_make_property(m2=75.0, bedrooms=3, bathrooms=2, parking=1))
        await session.commit()

        match = await repo.find_matching(
            comuna_slug="nunoa", m2=75.0, bedrooms=3, bathrooms=2, parking=1
        )
        assert match is not None
        assert match.m2 == 75.0

    async def test_match_within_m2_tolerance(self, session: AsyncSession):
        """±1 m² de tolerancia: 75.0 debe matchear con 75.8 ingresado."""
        repo = SqlAlchemyPropertyRepository(session)
        await repo.save(_make_property(m2=75.8))
        await session.commit()

        match = await repo.find_matching(
            comuna_slug="nunoa", m2=75.0, bedrooms=3, bathrooms=2, parking=1
        )
        assert match is not None

    async def test_no_match_beyond_tolerance(self, session: AsyncSession):
        repo = SqlAlchemyPropertyRepository(session)
        await repo.save(_make_property(m2=75.0))
        await session.commit()

        # 80 m² está más allá de ±1 m²
        match = await repo.find_matching(
            comuna_slug="nunoa", m2=80.0, bedrooms=3, bathrooms=2, parking=1
        )
        assert match is None

    async def test_different_comuna_does_not_match(self, session: AsyncSession):
        repo = SqlAlchemyPropertyRepository(session)
        await repo.save(_make_property(comuna="nunoa"))
        await session.commit()

        match = await repo.find_matching(
            comuna_slug="providencia", m2=75.0, bedrooms=3, bathrooms=2, parking=1
        )
        assert match is None

    async def test_different_bedrooms_does_not_match(self, session: AsyncSession):
        repo = SqlAlchemyPropertyRepository(session)
        await repo.save(_make_property(bedrooms=3))
        await session.commit()

        match = await repo.find_matching(
            comuna_slug="nunoa", m2=75.0, bedrooms=2, bathrooms=2, parking=1
        )
        assert match is None


class TestMapperRoundtrip:
    async def test_property_without_coordinates(self, session: AsyncSession):
        repo = SqlAlchemyPropertyRepository(session)
        saved = await repo.save(_make_property(with_coords=False))
        await session.commit()

        retrieved = await repo.find_by_id(saved.id)
        assert retrieved is not None
        assert retrieved.coordinates is None

    async def test_property_with_coordinates(self, session: AsyncSession):
        repo = SqlAlchemyPropertyRepository(session)
        saved = await repo.save(_make_property(with_coords=True))
        await session.commit()

        retrieved = await repo.find_by_id(saved.id)
        assert retrieved is not None
        assert retrieved.coordinates == Coordinates(-33.4569, -70.5969)
