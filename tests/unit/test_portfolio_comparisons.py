from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.db.models import (
    AlertORM,
    ListingORM,
    PortfolioItemValuationSnapshotORM,
    SavedListingORM,
    UserORM,
)
from services.portfolio_comparisons import PortfolioComparisonError, PortfolioComparisonService


async def test_portfolio_comparison_create_add_detail_and_report(session: AsyncSession) -> None:
    user = await _seed_user(session, "cmp@example.com")
    listing_a = await _seed_listing(session, suffix="a", price_currency="UF", price_uf=Decimal("6400"))
    listing_b = await _seed_listing(session, suffix="b")
    saved_a = await _save_listing(session, user_id=user.id, listing=listing_a)
    await _save_listing(session, user_id=user.id, listing=listing_b)
    await _seed_snapshot(session, user_id=user.id, listing_id=listing_a.id)
    session.add(AlertORM(listing_id=listing_a.id, alert_type="price_drop", payload={}, is_read=False))
    await session.commit()

    service = PortfolioComparisonService(session)
    comparison = await service.create_comparison(user_id=user.id, title="Mi comparacion")
    comparison_id = comparison["comparison"]["id"]
    await service.add_item(user_id=user.id, comparison_id=comparison_id, watchlist_item_id=saved_a.id)
    detail = await service.add_item(user_id=user.id, comparison_id=comparison_id, listing_id=listing_b.id)

    assert detail["comparison"]["is_ready"] is True
    assert len(detail["items"]) == 2
    first = detail["items"][0]
    assert first["avm"]["available"] is True
    assert first["avm"]["estimated_value_uf"] == 7200.0
    assert first["delta"]["available"] is True
    assert first["alerts_count"] == 1
    second = detail["items"][1]
    assert second["avm"]["reason"] == "needs_portfolio_avm_snapshot"
    assert second["delta"]["reason"] == "needs_current_valuation"

    html = await service.build_report_html(user_id=user.id, comparison_id=comparison_id)
    assert "Mi comparacion" in html
    assert "UF 7.200" in html
    assert "No disponible" in html
    assert "Score" not in html


async def test_portfolio_comparison_rejects_duplicates_and_more_than_four(session: AsyncSession) -> None:
    user = await _seed_user(session, "cmp-max@example.com")
    listings = [await _seed_listing(session, suffix=str(index), price_currency="UF", price_uf=Decimal("6000")) for index in range(5)]
    for listing in listings:
        await _save_listing(session, user_id=user.id, listing=listing)
    await session.commit()
    service = PortfolioComparisonService(session)
    comparison_id = (await service.create_comparison(user_id=user.id))["comparison"]["id"]

    await service.add_item(user_id=user.id, comparison_id=comparison_id, listing_id=listings[0].id)
    with pytest.raises(PortfolioComparisonError, match="ya esta"):
        await service.add_item(user_id=user.id, comparison_id=comparison_id, listing_id=listings[0].id)

    for listing in listings[1:4]:
        await service.add_item(user_id=user.id, comparison_id=comparison_id, listing_id=listing.id)
    with pytest.raises(PortfolioComparisonError, match="maximo 4"):
        await service.add_item(user_id=user.id, comparison_id=comparison_id, listing_id=listings[4].id)


async def test_portfolio_comparison_blocks_cross_user_access(session: AsyncSession) -> None:
    owner = await _seed_user(session, "owner@example.com")
    other = await _seed_user(session, "other@example.com")
    listing = await _seed_listing(session, suffix="cross")
    await _save_listing(session, user_id=owner.id, listing=listing)
    await session.commit()
    service = PortfolioComparisonService(session)
    comparison_id = (await service.create_comparison(user_id=owner.id))["comparison"]["id"]

    with pytest.raises(PortfolioComparisonError) as exc:
        await service.get_comparison(user_id=other.id, comparison_id=comparison_id)

    assert exc.value.status_code == 404
    with pytest.raises(PortfolioComparisonError) as add_exc:
        await service.add_item(user_id=other.id, comparison_id=comparison_id, listing_id=listing.id)
    assert add_exc.value.status_code == 404


async def _seed_user(session: AsyncSession, email: str) -> UserORM:
    user = UserORM(email=email, password_hash="hash", role="beta_user", is_active=True)
    session.add(user)
    await session.flush()
    return user


async def _seed_listing(
    session: AsyncSession,
    *,
    suffix: str,
    price_currency: str = "CLP",
    price_uf: Decimal | None = None,
) -> ListingORM:
    listing = ListingORM(
        source="yapo",
        external_id=f"cmp-{suffix}",
        title=f"Propiedad comparada {suffix}",
        comuna="nunoa",
        property_type="apartment",
        m2=80,
        bedrooms=2,
        bathrooms=2,
        parking=1,
        price_clp=Decimal("250000000"),
        price_uf=price_uf,
        price_currency=price_currency,
        price_uf_source="scraped" if price_uf else None,
        status="active",
        fingerprint=f"cmp-{suffix}-fp",
        scraped_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        url=f"https://example.test/{suffix}",
    )
    session.add(listing)
    await session.flush()
    return listing


async def _save_listing(session: AsyncSession, *, user_id: int, listing: ListingORM) -> SavedListingORM:
    saved = SavedListingORM(
        user_id=user_id,
        listing_id=listing.id,
        saved_price_clp=listing.price_clp,
        status="active",
    )
    session.add(saved)
    await session.flush()
    return saved


async def _seed_snapshot(session: AsyncSession, *, user_id: int, listing_id: int) -> None:
    session.add(
        PortfolioItemValuationSnapshotORM(
            user_id=user_id,
            listing_id=listing_id,
            watchlist_item_id=None,
            valuation_id=None,
            estimated_value_uf=Decimal("7200"),
            estimated_value_clp=Decimal("288000000"),
            lower_bound_uf=Decimal("6900"),
            upper_bound_uf=Decimal("7500"),
            confidence="medium",
            engine_name="test",
            engine_version="test",
            valuation_source="test",
            valuation_status="available",
            unavailable_reason=None,
            published_price_uf=Decimal("6400"),
            published_price_clp=Decimal("250000000"),
            delta_uf=Decimal("800"),
            delta_pct=12.5,
            delta_status="available",
            delta_unavailable_reason=None,
            data_freshness_status="manual_snapshot",
            snapshot_at=datetime.now(UTC),
        )
    )
