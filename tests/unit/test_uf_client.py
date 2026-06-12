from __future__ import annotations

import logging
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest

from core.exceptions import UFServiceError
from core.ports.uf_service import UFRateInfo
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


class TestCacheHit:
    async def test_returns_cached_value_without_http(self) -> None:
        redis = _mock_redis(cached="37500.00")
        http = _mock_httpx(payload={"serie": [{"valor": 99999}]})
        client = _make_client(redis=redis, http=http)

        rate = await client.get_current_rate()

        assert rate == Decimal("37500.00")
        http.get.assert_not_awaited()

    async def test_rate_info_marks_cache_hit(self) -> None:
        redis = _mock_redis(cached="37500.00")
        http = _mock_httpx(payload={"serie": [{"valor": 99999}]})
        client = _make_client(redis=redis, http=http)

        info = await client.get_current_rate_info()

        assert info.rate == Decimal("37500.00")
        assert info.source == "cache"
        assert info.cache_hit is True
        assert info.is_fallback is False

    async def test_handles_bytes_cache_value(self) -> None:
        redis = _mock_redis(cached=b"37500.00")
        client = _make_client(redis=redis)

        rate = await client.get_current_rate()

        assert rate == Decimal("37500.00")

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
        assert Decimal(args[2]) == rate

    async def test_rate_info_marks_remote_source(self) -> None:
        redis = _mock_redis(cached=None)
        http = _mock_httpx(payload={"serie": [{"valor": 37500.5}]})
        client = _make_client(redis=redis, http=http)

        info = await client.get_current_rate_info()

        assert info.rate == Decimal("37500.5")
        assert info.source == "mindicador.cl"
        assert info.cache_hit is False
        assert info.is_fallback is False

    async def test_fetch_logs_real_uf_value(self, caplog: pytest.LogCaptureFixture) -> None:
        redis = _mock_redis(cached=None)
        http = _mock_httpx(payload={"serie": [{"valor": 39000.12}]})
        client = _make_client(redis=redis, http=http)

        with caplog.at_level(logging.INFO, logger="infrastructure.external.uf_client"):
            rate = await client.get_current_rate()

        assert rate == Decimal("39000.12")
        assert "UF obtenida desde mindicador.cl: 39000.12" in caplog.text


class TestNoFallback:
    async def test_http_error_raises_without_fallback(self) -> None:
        http = _mock_httpx(raise_exc=httpx.ConnectError("network down"))
        client = _make_client(http=http)

        with pytest.raises(UFServiceError):
            await client.get_current_rate()

    async def test_rate_info_raises_without_fallback(self) -> None:
        http = _mock_httpx(raise_exc=httpx.ConnectError("network down"))
        client = _make_client(http=http)

        with pytest.raises(UFServiceError):
            await client.get_current_rate_info()

    async def test_http_error_logs_no_fallback_error(self, caplog: pytest.LogCaptureFixture) -> None:
        http = _mock_httpx(raise_exc=httpx.ConnectError("network down"))
        client = _make_client(http=http)

        with caplog.at_level(logging.ERROR, logger="infrastructure.external.uf_client"):
            with pytest.raises(UFServiceError):
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
