from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import UFServiceError
from infrastructure.db.models import (
    ListingORM,
    PortfolioAggregateSnapshotORM,
    PortfolioItemValuationSnapshotORM,
    SavedListingORM,
    UserORM,
)
from services.portfolio_snapshots import PortfolioSnapshotService


class FakeValuationService:
    def __init__(self, *, fail_titles: set[str] | None = None, fail_uf: bool = False) -> None:
        self.fail_titles = fail_titles or set()
        self.fail_uf = fail_uf
        self.calls: list[str] = []

    async def valuate_property(self, data):
        self.calls.append(data.comuna)
        if self.fail_uf:
            raise UFServiceError("UF real no disponible")
        if data.comuna in self.fail_titles:
            raise RuntimeError("controlled failure")
        return SimpleNamespace(
            estimated_price_uf=Decimal("7000"),
            estimated_price_clp=Decimal("280000000"),
            price_range_low_uf=Decimal("6650"),
            price_range_high_uf=Decimal("7350"),
            confidence="medium",
            selected_engine_names=["comparables_legacy"],
            consensus_method="test",
        )


async def test_snapshot_empty_watchlist_creates_empty_aggregate(session: AsyncSession) -> None:
    user = await _seed_user(session, "empty")
    await session.commit()

    result = await PortfolioSnapshotService(session, FakeValuationService()).create_snapshot(
        user_id=user.id,
        dry_run=False,
        limit=10,
    )

    assert result.processed_count == 0
    assert result.valued_count == 0
    assert result.unavailable_count == 0
    aggregate = (
        await session.execute(select(PortfolioAggregateSnapshotORM).where(PortfolioAggregateSnapshotORM.user_id == user.id))
    ).scalar_one()
    assert aggregate.item_count == 0
    assert aggregate.coverage_count == 0


async def test_snapshot_values_item_and_calculates_delta(session: AsyncSession) -> None:
    user, listing = await _seed_watchlist(session, "valuable", price_currency="UF", price_uf=Decimal("6000"))
    await session.commit()

    result = await PortfolioSnapshotService(session, FakeValuationService()).create_snapshot(
        user_id=user.id,
        dry_run=False,
        limit=10,
    )

    assert result.processed_count == 1
    assert result.valued_count == 1
    row = (
        await session.execute(
            select(PortfolioItemValuationSnapshotORM).where(
                PortfolioItemValuationSnapshotORM.listing_id == listing.id
            )
        )
    ).scalar_one()
    assert row.valuation_status == "available"
    assert row.estimated_value_uf == Decimal("7000.00")
    assert row.delta_uf == Decimal("1000.00")
    assert row.delta_status == "available"


async def test_snapshot_marks_item_unavailable_without_input(session: AsyncSession) -> None:
    user, listing = await _seed_watchlist(session, "missing-input", m2=None)
    fake = FakeValuationService()
    await session.commit()

    result = await PortfolioSnapshotService(session, fake).create_snapshot(
        user_id=user.id,
        dry_run=False,
        limit=10,
    )

    assert result.valued_count == 0
    assert result.unavailable_count == 1
    assert result.reasons["needs_valuation_input"] == 1
    assert fake.calls == []
    row = (
        await session.execute(
            select(PortfolioItemValuationSnapshotORM).where(
                PortfolioItemValuationSnapshotORM.listing_id == listing.id
            )
        )
    ).scalar_one()
    assert row.valuation_status == "unavailable"


async def test_snapshot_item_error_does_not_break_whole_run(session: AsyncSession) -> None:
    user = await _seed_user(session, "mixed")
    await _seed_listing_and_save(session, user, "ok", comuna="providencia")
    await _seed_listing_and_save(session, user, "fails", comuna="fail-comuna")
    await session.commit()

    result = await PortfolioSnapshotService(
        session,
        FakeValuationService(fail_titles={"fail-comuna"}),
    ).create_snapshot(user_id=user.id, dry_run=False, limit=10)

    assert result.processed_count == 2
    assert result.valued_count == 1
    assert result.unavailable_count == 1
    assert result.reasons["valuation_failed"] == 1


async def test_snapshot_no_delta_without_canonical_price(session: AsyncSession) -> None:
    user, listing = await _seed_watchlist(session, "clp-price", price_currency="CLP", price_uf=None)
    await session.commit()

    result = await PortfolioSnapshotService(session, FakeValuationService()).create_snapshot(
        user_id=user.id,
        dry_run=False,
        limit=10,
    )

    assert result.items[0].valuation_status == "available"
    assert result.items[0].delta_status == "unavailable"
    assert result.items[0].delta_unavailable_reason == "needs_canonical_price"
    row = (
        await session.execute(
            select(PortfolioItemValuationSnapshotORM).where(
                PortfolioItemValuationSnapshotORM.listing_id == listing.id
            )
        )
    ).scalar_one()
    assert row.delta_uf is None


async def test_snapshot_no_upside_without_avm(session: AsyncSession) -> None:
    user, _listing = await _seed_watchlist(session, "no-avm", m2=None)
    await session.commit()

    await PortfolioSnapshotService(session, FakeValuationService()).create_snapshot(
        user_id=user.id,
        dry_run=False,
        limit=10,
    )

    aggregate = (
        await session.execute(select(PortfolioAggregateSnapshotORM).where(PortfolioAggregateSnapshotORM.user_id == user.id))
    ).scalar_one()
    assert aggregate.coverage_count == 0
    assert aggregate.total_upside_uf is None


async def test_snapshot_records_specific_reason_when_uf_blocks_valuation(session: AsyncSession) -> None:
    user, listing = await _seed_watchlist(session, "uf-blocked", price_currency="UF", price_uf=Decimal("6000"))
    await session.commit()

    result = await PortfolioSnapshotService(session, FakeValuationService(fail_uf=True)).create_snapshot(
        user_id=user.id,
        dry_run=False,
        limit=10,
    )

    assert result.valued_count == 0
    assert result.unavailable_count == 1
    assert result.reasons["needs_uf_rate"] == 1
    row = (
        await session.execute(
            select(PortfolioItemValuationSnapshotORM).where(
                PortfolioItemValuationSnapshotORM.listing_id == listing.id
            )
        )
    ).scalar_one()
    assert row.valuation_status == "unavailable"
    assert row.unavailable_reason == "needs_uf_rate"
    assert row.estimated_value_uf is None


async def test_snapshot_dry_run_does_not_persist(session: AsyncSession) -> None:
    user, _listing = await _seed_watchlist(session, "dry-run", price_currency="UF", price_uf=Decimal("6000"))
    await session.commit()

    result = await PortfolioSnapshotService(session, FakeValuationService()).create_snapshot(
        user_id=user.id,
        dry_run=True,
        limit=10,
    )

    assert result.processed_count == 1
    assert result.valued_count == 1
    assert result.aggregate_snapshot_id is None
    aggregate_count = await session.scalar(
        select(func.count(PortfolioAggregateSnapshotORM.id)).where(PortfolioAggregateSnapshotORM.user_id == user.id)
    )
    assert aggregate_count == 0


async def test_snapshot_min_interval_skips_recent_snapshot(session: AsyncSession) -> None:
    now = datetime(2026, 6, 20, 14, tzinfo=UTC)
    user, _listing = await _seed_watchlist(session, "recent-skip", price_currency="UF", price_uf=Decimal("6000"))
    await _seed_aggregate_snapshot(session, user_id=user.id, snapshot_at=now - timedelta(hours=2))
    await session.commit()

    result = await PortfolioSnapshotService(session, FakeValuationService()).create_snapshot(
        user_id=user.id,
        dry_run=False,
        limit=10,
        min_interval_hours=20,
        now=now,
    )

    assert result.skipped_count == 1
    assert result.skipped_reason == "recent_snapshot"
    assert result.processed_count == 0


async def _seed_user(session: AsyncSession, suffix: str) -> UserORM:
    user = UserORM(
        email=f"portfolio-snapshot-{suffix}@example.com",
        password_hash="hash",
        role="beta_user",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_watchlist(
    session: AsyncSession,
    suffix: str,
    *,
    m2: float | None = 72,
    price_currency: str = "UF",
    price_uf: Decimal | None = Decimal("6000"),
) -> tuple[UserORM, ListingORM]:
    user = await _seed_user(session, suffix)
    listing = await _seed_listing_and_save(
        session,
        user,
        suffix,
        m2=m2,
        price_currency=price_currency,
        price_uf=price_uf,
    )
    return user, listing


async def _seed_listing_and_save(
    session: AsyncSession,
    user: UserORM,
    suffix: str,
    *,
    comuna: str = "providencia",
    m2: float | None = 72,
    price_currency: str = "UF",
    price_uf: Decimal | None = Decimal("6000"),
) -> ListingORM:
    listing = ListingORM(
        source="yapo",
        external_id=f"portfolio-snapshot-{suffix}",
        title=f"Snapshot {suffix}",
        comuna=comuna,
        property_type="apartment",
        m2=m2,
        bedrooms=2,
        bathrooms=2,
        parking=1,
        price_clp=Decimal("240000000"),
        price_uf=price_uf,
        price_currency=price_currency,
        status="active",
        fingerprint=f"portfolio-snapshot-{suffix}-fp",
        scraped_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    session.add(listing)
    await session.flush()
    session.add(
        SavedListingORM(
            user_id=user.id,
            listing_id=listing.id,
            saved_price_clp=listing.price_clp,
            saved_price_uf=listing.price_uf,
            status="active",
        )
    )
    await session.flush()
    return listing


async def _seed_aggregate_snapshot(
    session: AsyncSession,
    *,
    user_id: int,
    snapshot_at: datetime,
) -> None:
    session.add(
        PortfolioAggregateSnapshotORM(
            user_id=user_id,
            snapshot_date=snapshot_at.date(),
            total_estimated_value_uf=Decimal("7000"),
            average_estimated_value_uf=Decimal("7000"),
            total_published_price_uf=Decimal("6000"),
            total_upside_uf=Decimal("1000"),
            average_delta_pct=10.0,
            item_count=1,
            coverage_count=1,
            unavailable_count=0,
            snapshot_at=snapshot_at,
        )
    )
