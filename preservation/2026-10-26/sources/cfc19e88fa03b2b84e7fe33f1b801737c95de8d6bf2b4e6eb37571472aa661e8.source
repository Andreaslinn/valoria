from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api import deps
from api.v1 import tasar as tasar_api
from api.v1 import valuations as valuations_api
from core.entities.user import User
from infrastructure.db.database import get_db
from infrastructure.db.models import UsageLogORM


@pytest.mark.asyncio
async def test_valuation_endpoint_records_one_recent_activity_event(engine: AsyncEngine) -> None:
    client, session_factory = _client(engine, user_id=7)

    async with client:
        valuation_response = await client.post(
            "/api/v1/valuations",
            json={
                "comuna": "providencia",
                "property_type": "apartment",
                "m2": 72,
                "built_area_m2": 68,
                "precio_publicado_uf": 6900,
            },
        )
        activity_response = await client.get("/api/v1/tasar/activity/recent")

    assert valuation_response.status_code == 200
    assert activity_response.status_code == 200

    async with session_factory() as session:
        logs = (await session.execute(select(UsageLogORM))).scalars().all()

    assert len(logs) == 1
    log = logs[0]
    assert log.user_id == 7
    assert log.event_type == "valuation_completed"
    assert log.payload["feature"] == "tasar_playground"
    assert log.payload["metadata"] == {
        "comuna": "providencia",
        "property_type": "apartment",
        "m2": 72,
        "built_area_m2": 68,
        "precio_publicado_uf": 6900,
        "estimated_value_uf": 7220.36,
        "range_low_uf": 5391.97,
        "range_high_uf": 9048.75,
        "comparable_count": 12,
        "comparables_used": 12,
        "confidence": "medium",
        "confidence_score": 0.6695,
        "status": "ok",
    }

    activity = activity_response.json()
    event = activity["events"][0]
    assert activity["events_count"] == 1
    assert event["event_type"] == "valuation_with_price"
    assert event["estimated_value_uf"] == 7220.36
    assert event["range_low_uf"] == 5391.97
    assert event["range_high_uf"] == 9048.75
    assert event["confidence"] == "medium"


@pytest.mark.asyncio
async def test_recent_activity_does_not_expose_valuation_to_other_user(engine: AsyncEngine) -> None:
    owner_client, _session_factory = _client(engine, user_id=7)
    other_client, _ = _client(engine, user_id=8)

    async with owner_client:
        response = await owner_client.post(
            "/api/v1/valuations",
            json={"comuna": "providencia", "property_type": "apartment", "m2": 72},
        )
    assert response.status_code == 200

    async with other_client:
        activity_response = await other_client.get("/api/v1/tasar/activity/recent")

    assert activity_response.status_code == 200
    assert activity_response.json()["events"] == []


@pytest.mark.asyncio
async def test_valuation_endpoint_succeeds_when_usage_event_recording_fails(
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _raise_recording_error(**_kwargs: Any) -> None:
        raise RuntimeError("usage log unavailable")

    monkeypatch.setattr(valuations_api, "_record_valuation_completed_event", _raise_recording_error)
    caplog.set_level(logging.ERROR, logger="api.v1.valuations")
    client, session_factory = _client(engine, user_id=7)

    async with client:
        response = await client.post(
            "/api/v1/valuations",
            json={"comuna": "providencia", "property_type": "apartment", "m2": 72},
        )

    assert response.status_code == 200
    assert "Failed to record valuation_completed usage event" in caplog.text
    async with session_factory() as session:
        logs = (await session.execute(select(UsageLogORM))).scalars().all()
    assert logs == []


def _client(
    engine: AsyncEngine,
    *,
    user_id: int,
) -> tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def _authenticated_user() -> User:
        return User(
            id=user_id,
            email=f"user-{user_id}@example.com",
            password_hash="hash",
            role="beta_user",
            is_active=True,
        )

    app = FastAPI()
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[deps._resolve_current_user] = _authenticated_user
    app.dependency_overrides[deps.get_valuation_service] = lambda: _FakeValuationService()
    app.include_router(valuations_api.router, prefix="/api/v1")
    app.include_router(tasar_api.router, prefix="/api/v1")

    return (
        httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test"),
        session_factory,
    )


class _FakeValuationService:
    async def valuate_property(self, _payload: Any, *, valuation_strategy: str) -> dict[str, Any]:
        assert valuation_strategy == "consensus_v1"
        return {
            "estimated_price_uf": 7220.36,
            "estimated_price_clp": 271000000,
            "price_range_low_uf": 5391.97,
            "price_range_high_uf": 9048.75,
            "price_range_low_clp": 202000000,
            "price_range_high_clp": 339000000,
            "confidence": "medium",
            "confidence_score": 0.6695,
            "confidence_label": "medium",
            "comparable_count": 12,
            "price_m2_uf": 100.28,
            "status": "ok",
            "warnings": [],
            "comparables": [],
        }