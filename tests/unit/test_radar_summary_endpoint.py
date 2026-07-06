from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from api import deps
from api.v1 import radar as radar_api
from core.entities.user import User


@pytest.mark.asyncio
async def test_radar_summary_is_manual_and_does_not_return_fake_counts() -> None:
    async with _client() as client:
        response = await client.get("/api/v1/radar/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["mode"] == "manual"
    assert body["auto_run"] is False
    assert body["requires_manual_run"] is True
    assert body["opportunities_count"] is None
    assert body["fresh_candidates_count"] is None
    assert body["allowed_property_types"] == ["apartment"]


@pytest.mark.asyncio
async def test_radar_summary_does_not_require_radar_service_dependency() -> None:
    app = FastAPI()
    app.dependency_overrides[deps._resolve_current_user] = _authenticated_user

    def fail_radar_service():
        raise AssertionError("RadarService should not be resolved by /radar/summary")

    app.dependency_overrides[deps.get_radar_service] = fail_radar_service
    app.include_router(radar_api.router, prefix="/api/v1")

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/radar/summary")

    assert response.status_code == 200


def _client() -> httpx.AsyncClient:
    app = FastAPI()
    app.dependency_overrides[deps._resolve_current_user] = _authenticated_user
    app.include_router(radar_api.router, prefix="/api/v1")
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _authenticated_user() -> User:
    return User(
        id=7,
        email="dashboard-user@example.com",
        password_hash="hash",
        role="beta_user",
        is_active=True,
    )
