from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.v1.portfolio import PortfolioSnapshotRunIn, create_portfolio_snapshot
from api.v1.valuations import ValuationFeedbackRequest, submit_feedback
from config.settings import Settings
from infrastructure.external.uf_client import UFClient
from services.listing_freshness import ensure_listing_fresh
from workers import scheduler as scheduler_module


def _settings(**overrides) -> Settings:
    values = {
        "database_url": "postgresql+asyncpg://user:pass@example.test:5432/avm_cloud_beta?ssl=require",
        "sync_database_url": "postgresql+psycopg://user:pass@example.test:5432/avm_cloud_beta?sslmode=require",
        "jwt_secret_key": "x" * 32,
    }
    values.update(overrides)
    return Settings(**values)


def test_cloud_beta_settings_disable_heavy_runtime_flags() -> None:
    settings = _settings(
        valoria_runtime_profile="cloud_beta",
        redis_enabled=False,
        redis_url="",
        scheduler_enabled=False,
        workers_enabled=False,
        listing_on_demand_refresh_enabled=False,
        portfolio_snapshot_write_enabled=False,
        valuation_feedback_enabled=False,
        database_pool_size=2,
        database_max_overflow=3,
    )

    assert settings.is_cloud_beta is True
    assert settings.redis_enabled is False
    assert settings.redis_url == ""
    assert settings.scheduler_enabled is False
    assert settings.workers_enabled is False
    assert settings.listing_on_demand_refresh_enabled is False
    assert settings.portfolio_snapshot_write_enabled is False
    assert settings.valuation_feedback_enabled is False
    assert settings.database_pool_size == 2
    assert settings.database_max_overflow == 3


def test_local_settings_preserve_defaults() -> None:
    settings = _settings()

    assert settings.is_cloud_beta is False
    assert settings.redis_enabled is True
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.scheduler_enabled is True
    assert settings.workers_enabled is True
    assert settings.listing_on_demand_refresh_enabled is True
    assert settings.portfolio_snapshot_write_enabled is True
    assert settings.valuation_feedback_enabled is True
    assert settings.database_pool_size == 10
    assert settings.database_max_overflow == 20


@pytest.mark.asyncio
async def test_uf_client_without_redis_skips_cache() -> None:
    client = UFClient(api_url="https://example.test/uf", http_client=AsyncMock(), redis=None)

    assert await client._from_cache() is None
    await client._store_in_cache(  # should be a no-op, not an AttributeError
        SimpleNamespace(
            rate="40000",
            source="test",
            rate_date=None,
            fetched_at=None,
        )
    )


@pytest.mark.asyncio
async def test_cloud_beta_scheduler_main_returns_without_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(valoria_runtime_profile="cloud_beta", scheduler_enabled=False)
    monkeypatch.setattr(scheduler_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        scheduler_module,
        "run_startup_catchup",
        AsyncMock(side_effect=AssertionError("startup catchup must not run")),
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_scheduler",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("scheduler must not build")),
    )

    await scheduler_module.main()


@pytest.mark.asyncio
async def test_cloud_beta_listing_freshness_does_not_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = SimpleNamespace(
        id=123,
        last_seen_at=datetime(2026, 7, 8, tzinfo=UTC),
        last_refresh_attempted_at=None,
        last_refresh_status=None,
        status="active",
    )
    monkeypatch.setattr("services.listing_freshness._load_listing", AsyncMock(return_value=listing))
    monkeypatch.setattr(
        "services.listing_freshness.refresh_listing_once",
        AsyncMock(side_effect=AssertionError("refresh must not run")),
    )

    result = await ensure_listing_fresh(
        123,
        reason="test",
        session_factory=object(),
        settings=_settings(valoria_runtime_profile="cloud_beta"),
    )

    assert result.status == "unknown"
    assert result.refresh_attempted is False
    assert result.freshness_note == "on_demand_refresh_disabled"


@pytest.mark.asyncio
async def test_cloud_beta_blocks_portfolio_snapshot() -> None:
    with pytest.raises(HTTPException) as exc:
        await create_portfolio_snapshot(
            PortfolioSnapshotRunIn(dry_run=False, limit=1),
            current_user=SimpleNamespace(id=1),
            service=object(),
            settings=_settings(valoria_runtime_profile="cloud_beta"),
        )

    assert exc.value.status_code == 403
    assert "disabled" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_cloud_beta_blocks_valuation_feedback() -> None:
    with pytest.raises(HTTPException) as exc:
        await submit_feedback(
            ValuationFeedbackRequest(
                valuation_result={},
                valuation_payload={},
                feedback="reasonable",
            ),
            settings=_settings(valoria_runtime_profile="cloud_beta"),
        )

    assert exc.value.status_code == 403
    assert "disabled" in str(exc.value.detail)
