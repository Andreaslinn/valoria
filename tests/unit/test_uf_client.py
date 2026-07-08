from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.exceptions import UFServiceError
from core.ports.uf_service import UFRateInfo
from infrastructure.db.models import UFRateORM
from infrastructure.external.uf_client import UF_CACHE_KEY, UFClient
from services.uf_rate import require_real_uf_rate, validate_real_uf_rate


def _mock_redis(*, cached: str | bytes | None = None) -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=cached)
    redis.setex = AsyncMock(return_value=True)
    return redis


def _mock_httpx(*, payload: dict | None = None, raise_exc: Exception | None = None) -> AsyncMock:
    client = AsyncMock()
    if raise_exc is not None:
        client.get = AsyncMock(side_effect=raise_exc)
    else:
        response = AsyncMock()
        response.raise_for_status = lambda: None
        response.json = lambda: payload
        client.get = AsyncMock(return_value=response)
    return client


def _make_client(redis=None, http=None, api_url="https://mindicador.cl/api/uf") -> UFClient:
    return UFClient(
        api_url=api_url,
        http_client=http or _mock_httpx(payload={"serie": [{"valor": 37453.21}]}),
        redis=redis or _mock_redis(),
    )


def _cache_payload(
    value: str = "37500.00",
    *,
    fetched_at: datetime | None = None,
    rate_date: str | None = None,
) -> str:
    return json.dumps(
        {
            "value": value,
            "source": "mindicador.cl",
            "rate_date": rate_date or datetime.now(UTC).date().isoformat(),
            "fetched_at": (fetched_at or datetime.now(UTC)).isoformat(),
        }
    )


class TestCacheHit:
    async def test_returns_cached_value_without_http(self) -> None:
        redis = _mock_redis(cached=_cache_payload("37500.00"))
        http = _mock_httpx(payload={"serie": [{"valor": 99999}]})
        client = _make_client(redis=redis, http=http)

        rate = await client.get_current_rate()

        assert rate == Decimal("37500.00")
        http.get.assert_not_awaited()

    async def test_rate_info_marks_cache_hit(self) -> None:
        redis = _mock_redis(cached=_cache_payload("37500.00"))
        http = _mock_httpx(payload={"serie": [{"valor": 99999}]})
        client = _make_client(redis=redis, http=http)

        info = await client.get_current_rate_info()

        assert info.rate == Decimal("37500.00")
        assert info.source == "mindicador.cl"
        assert info.cache_hit is True
        assert info.is_fallback is False
        assert info.rate_date is not None
        assert info.fetched_at is not None
        assert info.is_stale is False

    async def test_handles_bytes_cache_value(self) -> None:
        redis = _mock_redis(cached=_cache_payload("37500.00").encode("utf-8"))
        client = _make_client(redis=redis)

        rate = await client.get_current_rate()

        assert rate == Decimal("37500.00")

    async def test_legacy_scalar_cache_is_stale_and_refetched(self) -> None:
        redis = _mock_redis(cached="37500.00")
        http = _mock_httpx(payload={"serie": [{"valor": 41931.34, "fecha": "2026-06-19T04:00:00.000Z"}]})
        client = _make_client(redis=redis, http=http)

        info = await client.get_current_rate_info()

        assert info.rate == Decimal("41931.34")
        assert info.source == "mindicador.cl"
        assert info.cache_hit is False
        http.get.assert_awaited_once()

    async def test_stale_json_cache_is_refetched(self) -> None:
        old = datetime.now(UTC) - timedelta(days=3)
        redis = _mock_redis(cached=_cache_payload("37500.00", fetched_at=old))
        http = _mock_httpx(payload={"serie": [{"valor": 41931.34, "fecha": "2026-06-19T04:00:00.000Z"}]})
        client = _make_client(redis=redis, http=http)

        info = await client.get_current_rate_info()

        assert info.rate == Decimal("41931.34")
        assert info.cache_hit is False
        http.get.assert_awaited_once()

    async def test_corrupt_cache_triggers_refetch(self) -> None:
        redis = _mock_redis(cached="not-a-number")
        http = _mock_httpx(payload={"serie": [{"valor": 37450}]})
        client = _make_client(redis=redis, http=http)

        rate = await client.get_current_rate()

        assert rate == Decimal("37450")
        http.get.assert_awaited_once()


class TestCacheMiss:
    async def test_fetches_from_api_and_caches(self) -> None:
        redis = _mock_redis(cached=None)
        http = _mock_httpx(payload={"serie": [{"valor": 37500.5}]})
        client = _make_client(redis=redis, http=http)

        rate = await client.get_current_rate()

        assert rate == Decimal("37500.5")
        http.get.assert_awaited_once()
        redis.setex.assert_awaited_once()
        args, _ = redis.setex.call_args
        assert args[0] == UF_CACHE_KEY
        payload = json.loads(args[2])
        assert Decimal(payload["value"]) == rate
        assert payload["fetched_at"]

    async def test_rate_info_marks_remote_source(self) -> None:
        redis = _mock_redis(cached=None)
        http = _mock_httpx(payload={"serie": [{"valor": 37500.5}]})
        client = _make_client(redis=redis, http=http)

        info = await client.get_current_rate_info()

        assert info.rate == Decimal("37500.5")
        assert info.source == "mindicador.cl"
        assert info.cache_hit is False
        assert info.is_fallback is False
        assert info.fetched_at is not None

    async def test_fetch_logs_real_uf_value(self, caplog: pytest.LogCaptureFixture) -> None:
        redis = _mock_redis(cached=None)
        http = _mock_httpx(payload={"serie": [{"valor": 39000.12}]})
        client = _make_client(redis=redis, http=http)

        with caplog.at_level(logging.INFO, logger="infrastructure.external.uf_client"):
            rate = await client.get_current_rate()

        assert rate == Decimal("39000.12")
        assert "UF obtenida desde mindicador.cl: 39000.12" in caplog.text


class TestDailySnapshotDB:
    async def test_uses_today_snapshot_from_db(self, engine: AsyncEngine) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            session.add(
                UFRateORM(
                    date=datetime.now(UTC).date(),
                    value_clp=Decimal("41931.34"),
                    source="db-test",
                    fetched_at=datetime.now(UTC),
                )
            )
            await session.commit()
        redis = _mock_redis(cached=None)
        http = _mock_httpx(payload={"serie": [{"valor": 99999}]})
        client = UFClient(
            api_url="https://mindicador.cl/api/uf",
            http_client=http,
            redis=redis,
            session_factory=factory,
        )

        info = await client.get_current_rate_info()

        assert info.rate == Decimal("41931.34")
        assert info.rate_date == datetime.now(UTC).date()
        assert info.source == "db-test"
        http.get.assert_not_awaited()
        redis.setex.assert_awaited_once()

    async def test_api_success_persists_daily_snapshot(self, engine: AsyncEngine) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        redis = _mock_redis(cached=None)
        http = _mock_httpx(payload={"serie": [{"valor": 41931.34, "fecha": "2026-06-19T04:00:00Z"}]})
        client = UFClient(
            api_url="https://mindicador.cl/api/uf",
            http_client=http,
            redis=redis,
            session_factory=factory,
        )

        info = await client.ensure_daily_snapshot(target_date=datetime(2026, 6, 19, tzinfo=UTC).date())

        async with factory() as session:
            rows = (await session.scalars(select(UFRateORM))).all()
        assert info.rate == Decimal("41931.34")
        assert len(rows) == 1
        assert rows[0].date.isoformat() == "2026-06-19"
        assert rows[0].value_clp == Decimal("41931.34")

    async def test_old_redis_but_today_db_uses_db_and_refreshes_redis(self, engine: AsyncEngine) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            session.add(
                UFRateORM(
                    date=datetime.now(UTC).date(),
                    value_clp=Decimal("41931.34"),
                    source="db-test",
                    fetched_at=datetime.now(UTC),
                )
            )
            await session.commit()
        redis = _mock_redis(cached="40787.7")
        http = _mock_httpx(payload={"serie": [{"valor": 99999}]})
        client = UFClient(
            api_url="https://mindicador.cl/api/uf",
            http_client=http,
            redis=redis,
            session_factory=factory,
        )

        info = await client.get_current_rate_info()

        assert info.rate == Decimal("41931.34")
        assert info.source == "db-test"
        http.get.assert_not_awaited()
        redis.setex.assert_awaited_once()

    async def test_scheduler_existing_snapshot_does_not_fetch(self, engine: AsyncEngine) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        today = datetime.now(UTC).date()
        async with factory() as session:
            session.add(
                UFRateORM(
                    date=today,
                    value_clp=Decimal("41931.34"),
                    source="db-test",
                    fetched_at=datetime.now(UTC),
                )
            )
            await session.commit()
        redis = _mock_redis(cached=None)
        http = _mock_httpx(payload={"serie": [{"valor": 99999}]})
        client = UFClient(
            api_url="https://mindicador.cl/api/uf",
            http_client=http,
            redis=redis,
            session_factory=factory,
        )

        info = await client.ensure_daily_snapshot(target_date=today)

        assert info.rate == Decimal("41931.34")
        http.get.assert_not_awaited()

    async def test_http_failure_uses_recent_latest_db_snapshot(self, engine: AsyncEngine) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        yesterday = (datetime.now(UTC) - timedelta(hours=12)).date()
        async with factory() as session:
            session.add(
                UFRateORM(
                    date=yesterday,
                    value_clp=Decimal("41931.34"),
                    source="db-test",
                    fetched_at=datetime.now(UTC) - timedelta(hours=12),
                )
            )
            await session.commit()
        redis = _mock_redis(cached=None)
        http = _mock_httpx(raise_exc=httpx.ConnectError("network down"))
        client = UFClient(
            api_url="https://mindicador.cl/api/uf",
            http_client=http,
            redis=redis,
            session_factory=factory,
            max_staleness_days=1,
        )

        info = await require_real_uf_rate(client)

        assert info.rate == Decimal("41931.34")
        assert info.source == "db-test:latest_db_snapshot_within_max_staleness"
        assert info.is_stale is False
        assert info.is_fallback is False

    async def test_http_failure_rejects_old_latest_db_snapshot(self, engine: AsyncEngine) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        old = datetime.now(UTC) - timedelta(days=5)
        async with factory() as session:
            session.add(
                UFRateORM(
                    date=old.date(),
                    value_clp=Decimal("41931.34"),
                    source="db-test",
                    fetched_at=old,
                )
            )
            await session.commit()
        http = _mock_httpx(raise_exc=httpx.ConnectError("network down"))
        client = UFClient(
            api_url="https://mindicador.cl/api/uf",
            http_client=http,
            redis=_mock_redis(cached=None),
            session_factory=factory,
            max_staleness_days=1,
        )

        with pytest.raises(UFServiceError):
            await require_real_uf_rate(client)

    async def test_recent_latest_db_snapshot_with_legacy_artifact_rate_is_rejected(self, engine: AsyncEngine) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            session.add(
                UFRateORM(
                    date=(datetime.now(UTC) - timedelta(hours=2)).date(),
                    value_clp=Decimal("37000.00"),
                    source="db-test",
                    fetched_at=datetime.now(UTC) - timedelta(hours=2),
                )
            )
            await session.commit()
        client = UFClient(
            api_url="https://mindicador.cl/api/uf",
            http_client=_mock_httpx(raise_exc=httpx.ConnectError("network down")),
            redis=_mock_redis(cached=None),
            session_factory=factory,
            max_staleness_days=1,
        )

        with pytest.raises(UFServiceError, match="37000"):
            await require_real_uf_rate(client)


class TestNoFallback:
    async def test_http_error_raises_without_fallback(self) -> None:
        http = _mock_httpx(raise_exc=httpx.ConnectError("network down"))
        client = _make_client(http=http)

        with pytest.raises(UFServiceError):
            await client.get_current_rate()

    async def test_http_error_can_return_stale_info_when_policy_allows(self) -> None:
        old = datetime.now(UTC) - timedelta(days=3)
        redis = _mock_redis(cached=_cache_payload("40787.7", fetched_at=old))
        http = _mock_httpx(raise_exc=httpx.ConnectError("network down"))
        client = UFClient(
            api_url="https://mindicador.cl/api/uf",
            http_client=http,
            redis=redis,
            allow_stale_on_failure=True,
        )

        info = await client.get_current_rate_info()

        assert info.rate == Decimal("40787.7")
        assert info.cache_hit is True
        assert info.is_stale is True
        assert info.stale_reason == "cache_fetched_at_exceeds_max_staleness"

    async def test_require_real_uf_rate_rejects_stale_info_even_if_returned_by_client(self) -> None:
        old = datetime.now(UTC) - timedelta(days=3)
        redis = _mock_redis(cached=_cache_payload("40787.7", fetched_at=old))
        http = _mock_httpx(raise_exc=httpx.ConnectError("network down"))
        client = UFClient(
            api_url="https://mindicador.cl/api/uf",
            http_client=http,
            redis=redis,
            allow_stale_on_failure=True,
        )

        with pytest.raises(UFServiceError, match="stale"):
            await require_real_uf_rate(client)

    async def test_rate_info_raises_without_fallback(self) -> None:
        http = _mock_httpx(raise_exc=httpx.ConnectError("network down"))
        client = _make_client(http=http)

        with pytest.raises(UFServiceError):
            await client.get_current_rate_info()

    async def test_http_error_logs_no_fallback_error(self, caplog: pytest.LogCaptureFixture) -> None:
        http = _mock_httpx(raise_exc=httpx.ConnectError("network down"))
        client = _make_client(http=http)

        with (
            caplog.at_level(logging.ERROR, logger="infrastructure.external.uf_client"),
            pytest.raises(UFServiceError),
        ):
            await client.get_current_rate()

        assert "no fallback rate will be used" in caplog.text

    async def test_http_status_error_raises(self) -> None:
        response = AsyncMock()

        def _raise() -> None:
            raise httpx.HTTPStatusError("500", request=None, response=None)

        response.raise_for_status = _raise
        response.json = lambda: {}
        http = AsyncMock()
        http.get = AsyncMock(return_value=response)
        client = _make_client(http=http)

        with pytest.raises(UFServiceError):
            await client.get_current_rate()

    async def test_malformed_payload_raises(self) -> None:
        http = _mock_httpx(payload={"unexpected": "shape"})
        client = _make_client(http=http)

        with pytest.raises(UFServiceError):
            await client.get_current_rate()

    async def test_empty_serie_raises(self) -> None:
        http = _mock_httpx(payload={"serie": []})
        client = _make_client(http=http)

        with pytest.raises(UFServiceError):
            await client.get_current_rate()

    async def test_non_positive_remote_value_raises(self) -> None:
        http = _mock_httpx(payload={"serie": [{"valor": 0}]})
        client = _make_client(http=http)

        with pytest.raises(UFServiceError):
            await client.get_current_rate()

    async def test_failed_rate_is_not_cached(self) -> None:
        redis = _mock_redis(cached=None)
        http = _mock_httpx(raise_exc=httpx.ConnectError("down"))
        client = _make_client(redis=redis, http=http)

        with pytest.raises(UFServiceError):
            await client.get_current_rate()
        redis.setex.assert_not_awaited()

    async def test_require_real_uf_rate_rejects_legacy_artifact_rate(self) -> None:
        http = _mock_httpx(payload={"serie": [{"valor": 37000}]})
        client = _make_client(http=http)

        with pytest.raises(UFServiceError, match="37000"):
            await require_real_uf_rate(client)

    def test_validate_real_uf_rate_rejects_fallback_marked_info(self) -> None:
        with pytest.raises(UFServiceError):
            validate_real_uf_rate(UFRateInfo(rate=Decimal("39000"), source="fallback", is_fallback=True))


class TestResilience:
    async def test_redis_get_error_falls_through_to_http(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=Exception("redis down"))
        redis.setex = AsyncMock(return_value=True)
        http = _mock_httpx(payload={"serie": [{"valor": 39000}]})
        client = _make_client(redis=redis, http=http)

        rate = await client.get_current_rate()

        assert rate == Decimal("39000")

    async def test_redis_setex_error_does_not_break(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock(side_effect=Exception("redis full"))
        http = _mock_httpx(payload={"serie": [{"valor": 39000}]})
        client = _make_client(redis=redis, http=http)

        rate = await client.get_current_rate()

        assert rate == Decimal("39000")
