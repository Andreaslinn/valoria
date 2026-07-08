from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.db.models import (
    AlertORM,
    ListingORM,
    PortfolioAggregateSnapshotORM,
    PortfolioItemValuationSnapshotORM,
    SavedListingORM,
    UserORM,
)
from services.portfolio import PortfolioService


async def test_portfolio_summary_counts_real_watchlist_and_alerts(session: AsyncSession) -> None:
    user, listing = await _seed_user_listing_and_watchlist(session, property_type="apartment")
    session.add(AlertORM(listing_id=listing.id, alert_type="price_drop", payload={}, is_read=False))
    session.add(AlertORM(listing_id=listing.id, alert_type="price_drop", payload={}, is_read=True))
    await session.commit()

    summary = await PortfolioService(session).build_summary(user_id=user.id)

    assert summary.tracked_properties == 1
    assert summary.unread_alert_count == 1
    assert len(summary.items) == 1
    assert summary.items[0].title == "Depto portfolio"
    assert summary.items[0].property_type == "apartment"
    assert summary.items[0].published_price_clp == Decimal("150000000.00")


async def test_portfolio_service_does_not_return_fake_avm_delta_trend_or_upside(
    session: AsyncSession,
) -> None:
    user, _listing = await _seed_user_listing_and_watchlist(session)
    await session.commit()

    summary = await PortfolioService(session).build_summary(user_id=user.id)
    item = summary.items[0]

    assert item.avm.available is False
    assert item.avm.estimated_value_uf is None
    assert item.avm.reason == "needs_portfolio_avm_snapshot"
    assert item.delta.available is False
    assert item.delta.delta_uf is None
    assert item.delta.delta_pct is None
    assert item.delta.reason == "needs_current_valuation"
    assert item.trend.available is False
    assert item.trend.points == ()
    assert item.trend.reason == "needs_repeated_avm_snapshots"
    assert summary.upside.available is False
    assert summary.upside.total_upside_uf is None
    assert summary.upside.reason == "needs_portfolio_avm_snapshot"


async def test_portfolio_service_does_not_invent_future_collections(session: AsyncSession) -> None:
    user, _listing = await _seed_user_listing_and_watchlist(session)
    await session.commit()

    summary = await PortfolioService(session).build_summary(user_id=user.id)

    assert summary.compared.available is True
    assert summary.compared.compared_listing_ids == ()
    assert summary.compared.reason is None
    assert summary.favorites.available is False
    assert summary.favorites.favorite_listing_ids == ()
    assert summary.favorites.reason == "needs_favorites_model"
    assert summary.recommendations.available is False
    assert summary.recommendations.recommendations == ()
    assert summary.recommendations.reason == "portfolio_recommendation_engine_not_implemented"


async def test_portfolio_service_payload_is_serializable(session: AsyncSession) -> None:
    user, _listing = await _seed_user_listing_and_watchlist(session)
    await session.commit()

    payload = (await PortfolioService(session).build_summary(user_id=user.id)).to_payload()

    assert payload["tracked_properties"] == 1
    assert payload["items"][0]["avm"]["estimated_value_uf"] is None
    assert payload["items"][0]["delta"]["delta_pct"] is None
    assert payload["history"]["reason"] == "needs_repeated_avm_snapshots"


async def test_portfolio_summary_uses_latest_snapshot_when_available(session: AsyncSession) -> None:
    user, listing = await _seed_user_listing_and_watchlist(session, price_currency="UF", price_uf=Decimal("6000"))
    await _seed_item_snapshot(session, user_id=user.id, listing_id=listing.id, estimated=Decimal("7000"))
    await _seed_aggregate_snapshot(session, user_id=user.id, average=Decimal("7000"), total_upside=Decimal("1000"))
    await session.commit()

    summary = await PortfolioService(session).build_summary(user_id=user.id)
    item = summary.items[0]

    assert item.avm.available is True
    assert item.avm.estimated_value_uf == Decimal("7000.00")
    assert item.delta.available is True
    assert item.delta.delta_uf == Decimal("1000.00")
    assert summary.upside.available is True
    assert summary.upside.total_upside_uf == Decimal("1000.00")


async def test_portfolio_trend_needs_history_with_one_snapshot(session: AsyncSession) -> None:
    user, listing = await _seed_user_listing_and_watchlist(session, price_currency="UF", price_uf=Decimal("6000"))
    await _seed_item_snapshot(session, user_id=user.id, listing_id=listing.id, estimated=Decimal("7000"))
    await _seed_aggregate_snapshot(session, user_id=user.id, average=Decimal("7000"), total_upside=Decimal("1000"))
    await session.commit()

    summary = await PortfolioService(session).build_summary(user_id=user.id)

    assert summary.average_avm_variation.available is False
    assert summary.average_avm_variation.reason == "needs_repeated_avm_snapshots"
    assert summary.history.available is False
    assert summary.items[0].trend.available is False


async def test_portfolio_trend_available_with_sufficient_history(session: AsyncSession) -> None:
    user, listing = await _seed_user_listing_and_watchlist(session, price_currency="UF", price_uf=Decimal("6000"))
    old = datetime(2026, 6, 1, tzinfo=UTC)
    new = datetime(2026, 6, 19, tzinfo=UTC)
    await _seed_item_snapshot(session, user_id=user.id, listing_id=listing.id, estimated=Decimal("6500"), snapshot_at=old)
    await _seed_item_snapshot(session, user_id=user.id, listing_id=listing.id, estimated=Decimal("7000"), snapshot_at=new)
    await _seed_aggregate_snapshot(session, user_id=user.id, average=Decimal("6500"), snapshot_at=old)
    await _seed_aggregate_snapshot(session, user_id=user.id, average=Decimal("7000"), total_upside=Decimal("1000"), snapshot_at=new)
    await session.commit()

    summary = await PortfolioService(session).build_summary(user_id=user.id)

    assert summary.average_avm_variation.available is True
    assert summary.average_avm_variation.variation_pct is not None
    assert summary.history.available is True
    assert len(summary.history.points) == 2
    assert summary.items[0].trend.available is True
    assert summary.items[0].trend.points == (Decimal("6500.00"), Decimal("7000.00"))


async def _seed_user_listing_and_watchlist(
    session: AsyncSession,
    *,
    property_type: str = "house",
    price_currency: str = "CLP",
    price_uf: Decimal | None = None,
) -> tuple[UserORM, ListingORM]:
    user = UserORM(
        email=f"portfolio-{property_type}@example.com",
        password_hash="hash",
        role="beta_user",
        is_active=True,
    )
    listing = ListingORM(
        source="yapo",
        external_id=f"portfolio-{property_type}",
        title="Depto portfolio",
        comuna="nunoa",
        property_type=property_type,
        m2=72,
        bedrooms=2,
        bathrooms=2,
        parking=1,
        price_clp=Decimal("150000000"),
        price_uf=price_uf,
        price_currency=price_currency,
        status="active",
        fingerprint=f"portfolio-{property_type}-fp",
        scraped_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    session.add_all([user, listing])
    await session.flush()
    session.add(
        SavedListingORM(
            user_id=user.id,
            listing_id=listing.id,
            saved_price_clp=listing.price_clp,
            status="active",
        )
    )
    await session.flush()
    return user, listing


async def _seed_item_snapshot(
    session: AsyncSession,
    *,
    user_id: int,
    listing_id: int,
    estimated: Decimal,
    snapshot_at: datetime | None = None,
) -> None:
    snapshot_at = snapshot_at or datetime.now(UTC)
    session.add(
        PortfolioItemValuationSnapshotORM(
            user_id=user_id,
            listing_id=listing_id,
            watchlist_item_id=None,
            valuation_id=None,
            estimated_value_uf=estimated,
            estimated_value_clp=estimated * Decimal("40000"),
            lower_bound_uf=estimated - Decimal("300"),
            upper_bound_uf=estimated + Decimal("300"),
            confidence="medium",
            engine_name="test",
            engine_version="test",
            valuation_source="test",
            valuation_status="available",
            unavailable_reason=None,
            published_price_uf=Decimal("6000"),
            published_price_clp=Decimal("240000000"),
            delta_uf=estimated - Decimal("6000"),
            delta_pct=float(((estimated - Decimal("6000")) / Decimal("6000")) * Decimal("100")),
            delta_status="available",
            delta_unavailable_reason=None,
            data_freshness_status="manual_snapshot",
            snapshot_at=snapshot_at,
        )
    )


async def _seed_aggregate_snapshot(
    session: AsyncSession,
    *,
    user_id: int,
    average: Decimal,
    total_upside: Decimal | None = None,
    snapshot_at: datetime | None = None,
) -> None:
    snapshot_at = snapshot_at or datetime.now(UTC)
    session.add(
        PortfolioAggregateSnapshotORM(
            user_id=user_id,
            snapshot_date=snapshot_at.date(),
            total_estimated_value_uf=average,
            average_estimated_value_uf=average,
            total_published_price_uf=Decimal("6000"),
            total_upside_uf=total_upside,
            average_delta_pct=10.0 if total_upside is not None else None,
            item_count=1,
            coverage_count=1,
            unavailable_count=0,
            snapshot_at=snapshot_at,
        )
    )
