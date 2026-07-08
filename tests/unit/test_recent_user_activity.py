from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.db.models import UsageLogORM
from services.recent_user_activity import RecentUserActivityService


@pytest.mark.asyncio
async def test_recent_user_activity_empty_when_no_events(session: AsyncSession) -> None:
    activity = await RecentUserActivityService(session).get_recent_activity(user_id=7)

    assert activity.status == "empty"
    assert activity.events_count == 0
    assert activity.events == []
    assert "no_tasar_user_activity_events" in activity.reasons


@pytest.mark.asyncio
async def test_recent_user_activity_returns_only_current_user_events(session: AsyncSession) -> None:
    now = datetime(2026, 6, 25, 10, 30, tzinfo=UTC)
    session.add_all(
        [
            _usage_log(7, "valuation_completed", now, comuna="providencia", estimated_value_uf=6294),
            _usage_log(8, "valuation_completed", now + timedelta(minutes=1), comuna="las_condes"),
        ]
    )
    await session.commit()

    activity = await RecentUserActivityService(session).get_recent_activity(user_id=7)

    assert activity.status == "partial"
    assert activity.events_count == 1
    assert activity.events[0].title == "Tasaste una propiedad"
    assert activity.events[0].description == "Providencia · UF 6.294"


@pytest.mark.asyncio
async def test_recent_user_activity_orders_desc_and_limits(session: AsyncSession) -> None:
    base = datetime(2026, 6, 25, 10, 0, tzinfo=UTC)
    session.add_all(
        [
            _usage_log(7, "valuation_completed", base, comuna="nunoa"),
            _usage_log(7, "property_analysis_completed", base + timedelta(minutes=2), comuna="las_condes"),
            _usage_log(7, "valuation_completed", base + timedelta(minutes=1), comuna="providencia"),
        ]
    )
    await session.commit()

    activity = await RecentUserActivityService(session).get_recent_activity(user_id=7, limit=2)

    assert [event.comuna for event in activity.events] == ["las_condes", "providencia"]
    assert [event.event_type for event in activity.events] == [
        "url_analysis_created",
        "valuation_created",
    ]


@pytest.mark.asyncio
async def test_recent_user_activity_maps_valuation_with_price(session: AsyncSession) -> None:
    session.add(
        _usage_log(
            7,
            "valuation_completed",
            datetime(2026, 6, 25, 10, 0, tzinfo=UTC),
            comuna="providencia",
            property_type="apartment",
            estimated_value_uf=6294,
            precio_publicado_uf=6000,
        )
    )
    await session.commit()

    event = (await RecentUserActivityService(session).get_recent_activity(user_id=7)).events[0]

    assert event.event_type == "valuation_with_price"
    assert event.title == "Tasaste con precio publicado"
    assert event.description == "Departamento en Providencia · UF 6.294"


@pytest.mark.asyncio
async def test_recent_user_activity_does_not_duplicate_on_repeated_reads(session: AsyncSession) -> None:
    session.add(_usage_log(7, "valuation_completed", datetime(2026, 6, 25, 10, 0, tzinfo=UTC)))
    await session.commit()
    service = RecentUserActivityService(session)

    first = await service.get_recent_activity(user_id=7)
    second = await service.get_recent_activity(user_id=7)

    assert [event.id for event in first.events] == [event.id for event in second.events]


def _usage_log(
    user_id: int,
    event_type: str,
    created_at: datetime,
    **metadata,
) -> UsageLogORM:
    return UsageLogORM(
        user_id=user_id,
        event_type=event_type,
        payload={"feature": "tasar_playground", "metadata": metadata},
        created_at=created_at,
    )
