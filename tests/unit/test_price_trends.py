from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.db.models import ListingORM, PriceHistoryORM
from services.price_trends import PriceTrendService


@pytest.mark.asyncio
async def test_price_trend_available_with_sufficient_price_history(session: AsyncSession) -> None:
    listing_ids = [
        await _listing(session, fingerprint=f"available-{index}", m2=50, price_uf=Decimal("5000"))
        for index in range(3)
    ]
    for month, base in enumerate([80, 82, 84, 86, 88, 90], start=1):
        for offset, listing_id in enumerate(listing_ids):
            session.add(
                _history(
                    listing_id=listing_id,
                    month=month,
                    price_uf=Decimal(str((base + offset) * 50)),
                )
            )
    await session.commit()

    trend = await PriceTrendService(session).price_m2_trend(
        comuna="providencia",
        property_type="apartment",
        period_months=12,
    )

    assert trend.status == "available"
    assert trend.source == "price_history"
    assert len(trend.points) == 6
    assert trend.points[0].median_price_m2_uf == 81.0
    assert trend.points[-1].median_price_m2_uf == 91.0
    assert trend.latest_value == 91.0
    assert trend.previous_value == 89.0
    assert trend.change_pct == 2.25
    assert trend.direction == "up"
    assert trend.coverage_count == 18


@pytest.mark.asyncio
async def test_price_trend_partial_with_limited_monthly_coverage(session: AsyncSession) -> None:
    listing_id = await _listing(session, fingerprint="partial", m2=50, price_uf=Decimal("5000"))
    for month, price_m2 in [(1, 80), (3, 82), (6, 81)]:
        session.add(_history(listing_id=listing_id, month=month, price_uf=Decimal(str(price_m2 * 50))))
    await session.commit()

    trend = await PriceTrendService(session).price_m2_trend(
        comuna="providencia",
        property_type="apartment",
        period_months=12,
    )

    assert trend.status == "partial"
    assert [point.month for point in trend.points] == ["2026-01", "2026-03", "2026-06"]
    assert "insufficient_sample_count" in trend.reasons
    assert "low_monthly_sample_count" in trend.warnings


@pytest.mark.asyncio
async def test_price_trend_not_available_without_enough_data(session: AsyncSession) -> None:
    listing_id = await _listing(session, fingerprint="not-available", m2=50, price_uf=Decimal("5000"))
    session.add(_history(listing_id=listing_id, month=1, price_uf=Decimal("4000")))
    await session.commit()

    trend = await PriceTrendService(session).price_m2_trend(
        comuna="providencia",
        property_type="apartment",
        period_months=12,
    )

    assert trend.status == "not_available"
    assert trend.points == ()
    assert "insufficient_monthly_points" in trend.reasons


@pytest.mark.asyncio
async def test_price_trend_excludes_artifacts_missing_uf_and_missing_surface(session: AsyncSession) -> None:
    artifact_id = await _listing(session, fingerprint="artifact", m2=50, price_uf=Decimal("5000"))
    missing_surface_id = await _listing(session, fingerprint="missing-surface", m2=None, price_uf=Decimal("5000"))
    missing_uf_id = await _listing(session, fingerprint="missing-uf", m2=50, price_uf=None)
    session.add(_history(listing_id=artifact_id, month=1, price_uf=Decimal("4000"), is_artifact=True))
    session.add(_history(listing_id=missing_surface_id, month=2, price_uf=Decimal("4000")))
    session.add(_history(listing_id=missing_uf_id, month=3, price_uf=None))
    await session.commit()

    trend = await PriceTrendService(session).price_m2_trend(
        comuna="providencia",
        property_type="apartment",
        period_months=12,
    )

    assert trend.status == "not_available"
    assert trend.coverage_count == 0
    assert "missing_canonical_price" in trend.reasons
    assert "missing_surface" in trend.reasons


@pytest.mark.asyncio
async def test_price_trend_falls_back_to_observed_listings_when_history_is_insufficient(
    session: AsyncSession,
) -> None:
    for month, price_m2 in [(1, 80), (3, 82), (6, 84)]:
        await _listing(
            session,
            fingerprint=f"fallback-{month}",
            m2=50,
            price_uf=Decimal(str(price_m2 * 50)),
            last_seen_at=datetime(2026, month, 15, tzinfo=UTC),
        )
    await session.commit()

    trend = await PriceTrendService(session).price_m2_trend(
        comuna="providencia",
        property_type="apartment",
        period_months=12,
    )

    assert trend.status == "partial"
    assert trend.source == "listing_observed"
    assert "insufficient_price_history" in trend.reasons
    assert "source_listing_observed" in trend.warnings


async def _listing(
    session: AsyncSession,
    *,
    fingerprint: str,
    m2: float | None,
    price_uf: Decimal | None,
    last_seen_at: datetime | None = None,
) -> int:
    observed = last_seen_at or datetime(2026, 6, 15, tzinfo=UTC)
    listing = ListingORM(
        source="test",
        external_id=fingerprint,
        title=f"Listing {fingerprint}",
        comuna="providencia",
        property_type="apartment",
        m2=m2,
        built_area_m2=None,
        usable_area_m2=None,
        bedrooms=2,
        bathrooms=2,
        parking=1,
        price_clp=Decimal("200000000"),
        price_uf=price_uf,
        price_uf_source="scraped" if price_uf is not None else None,
        price_currency="UF" if price_uf is not None else None,
        status="active",
        fingerprint=fingerprint,
        raw_metadata={},
        scraped_at=observed,
        last_seen_at=observed,
    )
    session.add(listing)
    await session.flush()
    return int(listing.id)


def _history(
    *,
    listing_id: int,
    month: int,
    price_uf: Decimal | None,
    is_artifact: bool = False,
) -> PriceHistoryORM:
    return PriceHistoryORM(
        listing_id=listing_id,
        price_clp=Decimal("200000000"),
        price_uf=price_uf,
        price_clp_snapshot=Decimal("200000000"),
        price_currency="UF" if price_uf is not None else None,
        change_basis="uf" if price_uf is not None else None,
        is_artifact=is_artifact,
        artifact_reason="test_artifact" if is_artifact else None,
        observed_at=datetime(2026, month, 15, tzinfo=UTC),
    )
