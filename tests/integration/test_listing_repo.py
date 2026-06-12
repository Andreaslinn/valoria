"""Tests de integración para SqlAlchemyListingRepository."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.entities.listing import Listing
from core.exceptions import ListingNotFoundError
from core.value_objects.location import Coordinates
from core.value_objects.price import Price
from infrastructure.db.models import ListingORM
from infrastructure.db.repositories import SqlAlchemyListingRepository


def _make_listing(
    *,
    fingerprint: str = "fp-1",
    comuna: str = "nunoa",
    status: str = "active",
    price_clp: Decimal = Decimal("180000000"),
    with_coords: bool = True,
    property_type: str = "apartment",
) -> Listing:
    return Listing(
        id=None,
        source="yapo",
        external_id=f"ext-{fingerprint}",
        title=f"Depto en {comuna}",
        comuna=comuna,
        m2=75.0,
        bedrooms=3,
        bathrooms=2,
        parking=1,
        price=Price(clp=price_clp),
        status=status,
        fingerprint=fingerprint,
        scraped_at=datetime.now(UTC),
        url=f"https://yapo.cl/{fingerprint}",
        property_type=property_type,
        coordinates=Coordinates(-33.4569, -70.5969) if with_coords else None,
        raw_metadata={"source_hint": "test"},
    )


class TestSave:
    async def test_inserts_new_listing(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        saved = await repo.save(_make_listing())
        await session.commit()

        assert saved.id is not None
        assert saved.fingerprint == "fp-1"
        assert saved.price.clp == Decimal("180000000")
        assert saved.property_type == "apartment"
        assert saved.coordinates == Coordinates(-33.4569, -70.5969)
        assert saved.raw_metadata["source_hint"] == "test"

    async def test_persists_property_type(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        saved = await repo.save(_make_listing(fingerprint="house", property_type="house"))
        await session.commit()

        orm = await session.get(ListingORM, saved.id)
        retrieved = await repo.find_by_id(saved.id)

        assert orm is not None
        assert orm.property_type == "house"
        assert retrieved is not None
        assert retrieved.property_type == "house"

    async def test_updates_existing_listing(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        first = await repo.save(_make_listing())
        await session.commit()

        first.status = "sold"
        first.price = Price(clp=Decimal("200000000"))
        updated = await repo.save(first)
        await session.commit()

        assert updated.id == first.id
        assert updated.status == "sold"
        assert updated.price.clp == Decimal("200000000")

    async def test_update_unknown_id_raises(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        ghost = _make_listing()
        ghost.id = 99999

        with pytest.raises(ListingNotFoundError):
            await repo.save(ghost)

    async def test_duplicate_fingerprint_rejected(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        await repo.save(_make_listing(fingerprint="dup"))
        await session.commit()

        with pytest.raises(IntegrityError):
            await repo.save(_make_listing(fingerprint="dup"))
            await session.commit()


class TestFindByFingerprint:
    async def test_returns_listing_if_exists(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        await repo.save(_make_listing(fingerprint="unique-abc"))
        await session.commit()

        found = await repo.find_by_fingerprint("unique-abc")
        assert found is not None
        assert found.fingerprint == "unique-abc"

    async def test_returns_none_when_missing(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        assert await repo.find_by_fingerprint("does-not-exist") is None


class TestFindBySourceExternalId:
    async def test_returns_listing_if_source_external_id_exists(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        await repo.save(_make_listing(fingerprint="source-ext", status="active"))
        await session.commit()

        found = await repo.find_by_source_external_id("yapo", "ext-source-ext")
        assert found is not None
        assert found.fingerprint == "source-ext"

    async def test_returns_none_when_source_external_id_missing(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        await repo.save(_make_listing(fingerprint="source-ext", status="active"))
        await session.commit()

        assert await repo.find_by_source_external_id("yapo", "missing") is None


class TestFindActiveInComuna:
    async def test_filters_by_comuna_and_status(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        await repo.save(_make_listing(fingerprint="a1", comuna="nunoa", status="active"))
        await repo.save(_make_listing(fingerprint="a2", comuna="nunoa", status="active"))
        await repo.save(_make_listing(fingerprint="s1", comuna="nunoa", status="sold"))
        await repo.save(_make_listing(fingerprint="o1", comuna="providencia", status="active"))
        await session.commit()

        results = await repo.find_active_in_comuna("nunoa")
        fingerprints = {listing.fingerprint for listing in results}
        assert fingerprints == {"a1", "a2"}

    async def test_returns_empty_for_unknown_comuna(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        await repo.save(_make_listing())
        await session.commit()

        assert list(await repo.find_active_in_comuna("no-existe")) == []

    async def test_can_filter_active_comuna_by_property_type(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        await repo.save(_make_listing(fingerprint="apt", comuna="nunoa", status="active", property_type="apartment"))
        await repo.save(_make_listing(fingerprint="house", comuna="nunoa", status="active", property_type="house"))
        await repo.save(_make_listing(fingerprint="house-other", comuna="providencia", status="active", property_type="house"))
        await session.commit()

        results = await repo.find_active_in_comuna("nunoa", property_type="house")

        assert [listing.fingerprint for listing in results] == ["house"]


class TestCountActive:
    async def test_counts_only_active_listings(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        await repo.save(_make_listing(fingerprint="a1", status="active"))
        await repo.save(_make_listing(fingerprint="a2", status="active"))
        await repo.save(_make_listing(fingerprint="s1", status="sold"))
        await repo.save(_make_listing(fingerprint="r1", status="removed"))
        await session.commit()

        assert await repo.count_active() == 2

    async def test_zero_when_empty(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        assert await repo.count_active() == 0


class TestMarkStaleListings:
    async def test_marks_only_old_active_listings_as_removed(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        old_1 = await repo.save(_make_listing(fingerprint="old-1", status="active"))
        old_2 = await repo.save(_make_listing(fingerprint="old-2", status="active"))
        recent = await repo.save(_make_listing(fingerprint="recent", status="active"))
        await session.commit()

        now = datetime.now(UTC)
        await _set_updated_at(session, old_1.id, now - timedelta(days=50))
        await _set_updated_at(session, old_2.id, now - timedelta(days=50))
        await _set_updated_at(session, recent.id, now - timedelta(days=5))
        await session.commit()

        count = await repo.mark_stale_listings(stale_days=45)
        await session.commit()

        assert count == 2
        statuses = await _statuses_by_fingerprint(session)
        assert statuses["old-1"] == "removed"
        assert statuses["old-2"] == "removed"
        assert statuses["recent"] == "active"

    async def test_already_removed_old_listing_is_not_counted_again(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        active_old = await repo.save(_make_listing(fingerprint="active-old", status="active"))
        removed_old = await repo.save(_make_listing(fingerprint="removed-old", status="removed"))
        await session.commit()

        old = datetime.now(UTC) - timedelta(days=50)
        await _set_updated_at(session, active_old.id, old)
        await _set_updated_at(session, removed_old.id, old)
        await session.commit()

        count = await repo.mark_stale_listings(stale_days=45)
        await session.commit()

        assert count == 1
        statuses = await _statuses_by_fingerprint(session)
        assert statuses["active-old"] == "removed"
        assert statuses["removed-old"] == "removed"


class TestMapperRoundtrip:
    async def test_listing_without_coordinates(self, session: AsyncSession):
        repo = SqlAlchemyListingRepository(session)
        original = _make_listing(fingerprint="nocoords", with_coords=False)
        saved = await repo.save(original)
        await session.commit()

        retrieved = await repo.find_by_id(saved.id)
        assert retrieved is not None
        assert retrieved.coordinates is None
        assert retrieved.m2 == original.m2
        assert retrieved.bedrooms == original.bedrooms
        assert retrieved.property_type == original.property_type

    async def test_price_precision_preserved(self, session: AsyncSession):
        """Numeric(18,2) no debe perder precisión en montos grandes."""
        repo = SqlAlchemyListingRepository(session)
        precise = Decimal("999999999.99")
        saved = await repo.save(_make_listing(fingerprint="precise", price_clp=precise))
        await session.commit()

        retrieved = await repo.find_by_id(saved.id)
        assert retrieved is not None
        assert retrieved.price.clp == precise


async def _set_updated_at(session: AsyncSession, listing_id: int | None, value: datetime) -> None:
    assert listing_id is not None
    orm = await session.get(ListingORM, listing_id)
    assert orm is not None
    orm.updated_at = value
    await session.flush()


async def _statuses_by_fingerprint(session: AsyncSession) -> dict[str, str]:
    rows = await session.execute(select(ListingORM.fingerprint, ListingORM.status))
    return dict(rows.all())
