from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.db.models import AlertORM, ListingORM
from infrastructure.db.repositories import SqlAlchemyAlertRepository

NOW = datetime.now(UTC)


@pytest.mark.asyncio
async def test_create_alert_persists_json_safe_payload(session: AsyncSession) -> None:
    listing = await _save_listing(session, "repo-create")
    repo = SqlAlchemyAlertRepository(session)

    alert = await repo.create_alert(
        listing_id=listing.id,
        alert_type="price_drop",
        payload={"amount": Decimal("123.00"), "detected_at": NOW},
    )
    await session.commit()

    assert alert.id is not None
    assert alert.payload["amount"] == 123
    assert alert.payload["detected_at"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_get_unread_alerts_returns_newest_first_and_excludes_read(session: AsyncSession) -> None:
    listing = await _save_listing(session, "repo-unread")
    old = AlertORM(listing_id=listing.id, alert_type="price_drop", payload={}, created_at=NOW - timedelta(hours=2))
    new = AlertORM(listing_id=listing.id, alert_type="price_drop", payload={}, created_at=NOW)
    read = AlertORM(listing_id=listing.id, alert_type="price_drop", payload={}, is_read=True, created_at=NOW + timedelta(hours=1))
    session.add_all([old, new, read])
    await session.commit()

    alerts = await SqlAlchemyAlertRepository(session).get_unread_alerts(limit=10)

    assert [alert.id for alert in alerts] == [new.id, old.id]


@pytest.mark.asyncio
async def test_alert_exists_recently_blocks_recent_but_not_old_alert(session: AsyncSession) -> None:
    listing = await _save_listing(session, "repo-recent")
    recent = AlertORM(
        listing_id=listing.id,
        alert_type="price_drop",
        payload={},
        created_at=NOW - timedelta(hours=2),
    )
    old_listing = await _save_listing(session, "repo-old")
    old = AlertORM(
        listing_id=old_listing.id,
        alert_type="price_drop",
        payload={},
        created_at=NOW - timedelta(days=2),
    )
    session.add_all([recent, old])
    await session.commit()
    repo = SqlAlchemyAlertRepository(session)

    assert await repo.alert_exists_recently(listing_id=listing.id, alert_type="price_drop", since=NOW - timedelta(hours=24))
    assert not await repo.alert_exists_recently(listing_id=old_listing.id, alert_type="price_drop", since=NOW - timedelta(hours=24))


async def _save_listing(session: AsyncSession, fingerprint: str) -> ListingORM:
    listing = ListingORM(
        source="yapo",
        external_id=fingerprint,
        title=f"Listing {fingerprint}",
        comuna="nunoa",
        m2=70.0,
        bedrooms=2,
        bathrooms=2,
        parking=1,
        price_clp=Decimal("100000000"),
        status="active",
        fingerprint=fingerprint,
        scraped_at=NOW,
        last_seen_at=NOW,
        raw_metadata={},
    )
    session.add(listing)
    await session.flush()
    return listing
