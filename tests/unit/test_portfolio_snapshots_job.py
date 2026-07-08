from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from infrastructure.db.models import (
    ListingORM,
    PortfolioAggregateSnapshotORM,
    SavedListingORM,
    UserORM,
)
from workers.portfolio_snapshots_job import (
    PortfolioSnapshotsJobConfig,
    run_portfolio_snapshots_job,
)


class FakeValuationService:
    def __init__(self, *, failing_comunas: set[str] | None = None) -> None:
        self.failing_comunas = failing_comunas or set()
        self.calls: list[str] = []

    async def valuate_property(self, data):
        self.calls.append(data.comuna)
        if data.comuna in self.failing_comunas:
            raise RuntimeError("controlled user item failure")
        return SimpleNamespace(
            estimated_price_uf=Decimal("7000"),
            estimated_price_clp=Decimal("280000000"),
            price_range_low_uf=Decimal("6600"),
            price_range_high_uf=Decimal("7400"),
            confidence="medium",
            selected_engine_names=["test_engine"],
            consensus_method="test",
        )


async def test_portfolio_snapshots_job_disabled_by_default_does_not_write(engine: AsyncEngine) -> None:
    session_factory = _session_factory(engine)
    async with session_factory() as session:
        await _seed_user_with_watchlist(session, "disabled")
        await session.commit()

    stats = await run_portfolio_snapshots_job(
        PortfolioSnapshotsJobConfig(),
        session_factory=session_factory,
        valuation_service_factory=lambda _session: FakeValuationService(),
    )

    assert stats.users_seen == 0
    assert stats.snapshots_created == 0
    assert await _aggregate_count(session_factory) == 0


async def test_portfolio_snapshots_job_skips_user_without_watchlist(engine: AsyncEngine) -> None:
    session_factory = _session_factory(engine)
    async with session_factory() as session:
        user = await _seed_user(session, "no-watchlist")
        await session.commit()

    stats = await run_portfolio_snapshots_job(
        PortfolioSnapshotsJobConfig(enabled=True, user_id=user.id),
        session_factory=session_factory,
        valuation_service_factory=lambda _session: FakeValuationService(),
    )

    assert stats.users_seen == 1
    assert stats.users_selected == 0
    assert stats.users_skipped_no_watchlist == 1
    assert stats.users_processed == 0


async def test_portfolio_snapshots_job_skips_recent_snapshot(engine: AsyncEngine) -> None:
    session_factory = _session_factory(engine)
    now = datetime(2026, 6, 20, 14, tzinfo=UTC)
    async with session_factory() as session:
        user, _listing = await _seed_user_with_watchlist(session, "recent")
        await _seed_aggregate(session, user_id=user.id, snapshot_at=now - timedelta(hours=2))
        await session.commit()

    stats = await run_portfolio_snapshots_job(
        PortfolioSnapshotsJobConfig(enabled=True, min_interval_hours=20),
        session_factory=session_factory,
        valuation_service_factory=lambda _session: FakeValuationService(),
        now=now,
    )

    assert stats.users_selected == 1
    assert stats.users_skipped_recent_snapshot == 1
    assert stats.users_processed == 0
    assert await _aggregate_count(session_factory) == 1


async def test_portfolio_snapshots_job_processes_watchlist_user(engine: AsyncEngine) -> None:
    session_factory = _session_factory(engine)
    async with session_factory() as session:
        await _seed_user_with_watchlist(session, "process", price_currency="UF", price_uf=Decimal("6000"))
        await session.commit()

    stats = await run_portfolio_snapshots_job(
        PortfolioSnapshotsJobConfig(enabled=True, limit_users=10, limit_items_per_user=20),
        session_factory=session_factory,
        valuation_service_factory=lambda _session: FakeValuationService(),
    )

    assert stats.users_seen == 1
    assert stats.users_processed == 1
    assert stats.items_attempted == 1
    assert stats.items_valued == 1
    assert stats.snapshots_created == 1
    assert await _aggregate_count(session_factory) == 1


async def test_portfolio_snapshots_job_dry_run_does_not_persist(engine: AsyncEngine) -> None:
    session_factory = _session_factory(engine)
    async with session_factory() as session:
        await _seed_user_with_watchlist(session, "dry-run")
        await session.commit()

    stats = await run_portfolio_snapshots_job(
        PortfolioSnapshotsJobConfig(enabled=True, dry_run=True),
        session_factory=session_factory,
        valuation_service_factory=lambda _session: FakeValuationService(),
    )

    assert stats.dry_run is True
    assert stats.users_processed == 1
    assert stats.snapshots_created == 0
    assert await _aggregate_count(session_factory) == 0


async def test_portfolio_snapshots_job_continues_after_user_error(engine: AsyncEngine) -> None:
    session_factory = _session_factory(engine)
    async with session_factory() as session:
        await _seed_user_with_watchlist(session, "fails", comuna="fail-comuna")
        await _seed_user_with_watchlist(session, "ok", comuna="providencia")
        await session.commit()

    stats = await run_portfolio_snapshots_job(
        PortfolioSnapshotsJobConfig(enabled=True, limit_users=10),
        session_factory=session_factory,
        valuation_service_factory=lambda _session: FakeValuationService(failing_comunas={"fail-comuna"}),
    )

    assert stats.users_selected == 2
    assert stats.users_processed == 2
    assert stats.items_valued == 1
    assert stats.items_unavailable == 1
    assert stats.unavailable_reasons_count["valuation_failed"] == 1


async def test_portfolio_snapshots_job_respects_user_and_item_limits(engine: AsyncEngine) -> None:
    session_factory = _session_factory(engine)
    async with session_factory() as session:
        user, _listing = await _seed_user_with_watchlist(session, "limited-a")
        await _seed_listing_and_save(session, user, "limited-a-extra")
        await _seed_user_with_watchlist(session, "limited-b")
        await session.commit()

    stats = await run_portfolio_snapshots_job(
        PortfolioSnapshotsJobConfig(
            enabled=True,
            user_id=user.id,
            limit_users=1,
            limit_items_per_user=1,
        ),
        session_factory=session_factory,
        valuation_service_factory=lambda _session: FakeValuationService(),
    )

    assert stats.users_seen == 1
    assert stats.users_selected == 1
    assert stats.users_processed == 1
    assert stats.items_attempted == 1


def _session_factory(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _aggregate_count(session_factory) -> int:
    async with session_factory() as session:
        return int(await session.scalar(select(func.count(PortfolioAggregateSnapshotORM.id))) or 0)


async def _seed_user(session: AsyncSession, suffix: str) -> UserORM:
    user = UserORM(
        email=f"portfolio-job-{suffix}@example.com",
        password_hash="hash",
        role="beta_user",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_user_with_watchlist(
    session: AsyncSession,
    suffix: str,
    *,
    comuna: str = "providencia",
    price_currency: str = "UF",
    price_uf: Decimal | None = Decimal("6000"),
) -> tuple[UserORM, ListingORM]:
    user = await _seed_user(session, suffix)
    listing = await _seed_listing_and_save(
        session,
        user,
        suffix,
        comuna=comuna,
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
    price_currency: str = "UF",
    price_uf: Decimal | None = Decimal("6000"),
) -> ListingORM:
    listing = ListingORM(
        source="yapo",
        external_id=f"portfolio-job-{suffix}",
        title=f"Portfolio job {suffix}",
        comuna=comuna,
        property_type="apartment",
        m2=72,
        bedrooms=2,
        bathrooms=2,
        parking=1,
        price_clp=Decimal("240000000"),
        price_uf=price_uf,
        price_currency=price_currency,
        status="active",
        fingerprint=f"portfolio-job-{suffix}-fp",
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


async def _seed_aggregate(
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
