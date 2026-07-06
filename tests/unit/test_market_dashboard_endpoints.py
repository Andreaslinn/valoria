from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from api import deps
from api.v1 import market as market_api
from core.entities.user import User


@pytest.mark.asyncio
async def test_market_briefing_returns_honest_coming_soon_contract() -> None:
    async with _client() as client:
        response = await client.get("/api/v1/market/briefing")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "coming_soon"
    assert body["available"] is False
    assert body["valoria_index"]["value"] is None
    assert body["indicators"][0]["value"] is None
    assert body["source"] == "valoria_market_contract_placeholder"


@pytest.mark.asyncio
async def test_microzones_summary_returns_empty_coming_soon_contract() -> None:
    async with _client() as client:
        response = await client.get("/api/v1/market/microzones/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "coming_soon"
    assert body["available"] is False
    assert body["items"] == []
    assert body["source"] == "microzone_contract_placeholder"


@pytest.mark.asyncio
async def test_liquidity_summary_returns_empty_coming_soon_contract() -> None:
    async with _client() as client:
        response = await client.get("/api/v1/market/liquidity/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "coming_soon"
    assert body["available"] is False
    assert body["value"] is None
    assert body["source"] == "liquidity_contract_placeholder"


def _client() -> httpx.AsyncClient:
    app = FastAPI()
    app.dependency_overrides[deps._resolve_current_user] = _authenticated_user
    app.include_router(market_api.router, prefix="/api/v1")
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _authenticated_user() -> User:
    return User(
        id=7,
        email="dashboard-user@example.com",
        password_hash="hash",
        role="beta_user",
        is_active=True,
    )
