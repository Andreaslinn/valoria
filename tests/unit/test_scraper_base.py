"""Tests unitarios de RateLimiter, with_retry y helpers de precio."""
from __future__ import annotations

import asyncio
import time
from decimal import Decimal

import httpx
import pytest

from infrastructure.scrapers.base import (
    RateLimiter,
    parse_price_text,
    parse_spanish_number,
    to_clp,
    with_retry,
)


class TestRateLimiter:
    async def test_first_wait_is_immediate(self):
        rl = RateLimiter(min_interval=0.1)
        start = time.monotonic()
        await rl.wait()
        elapsed = time.monotonic() - start
        assert elapsed < 0.05

    async def test_second_wait_respects_interval(self):
        rl = RateLimiter(min_interval=0.1)
        await rl.wait()
        start = time.monotonic()
        await rl.wait()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.09  # tolerancia por scheduler

    async def test_long_gap_does_not_delay(self):
        """Si ya pasó más del intervalo, el siguiente wait es inmediato."""
        rl = RateLimiter(min_interval=0.05)
        await rl.wait()
        await asyncio.sleep(0.1)
        start = time.monotonic()
        await rl.wait()
        elapsed = time.monotonic() - start
        assert elapsed < 0.02

    def test_rejects_negative_interval(self):
        with pytest.raises(ValueError):
            RateLimiter(min_interval=-1)

    async def test_zero_interval_never_sleeps(self):
        rl = RateLimiter(min_interval=0)
        for _ in range(3):
            start = time.monotonic()
            await rl.wait()
            assert time.monotonic() - start < 0.01


class TestWithRetry:
    async def test_returns_on_first_success(self):
        async def ok():
            return "result"

        sleeps: list[float] = []

        async def fake_sleep(d: float):
            sleeps.append(d)

        result = await with_retry(ok, sleep=fake_sleep)
        assert result == "result"
        assert sleeps == []  # no hubo retry

    async def test_retries_and_succeeds(self):
        attempts = {"count": 0}

        async def flaky():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise httpx.ConnectError("flaky")
            return "ok"

        sleeps: list[float] = []

        async def fake_sleep(d: float):
            sleeps.append(d)

        result = await with_retry(flaky, max_attempts=5, sleep=fake_sleep)
        assert result == "ok"
        assert attempts["count"] == 3
        # Backoff exponencial: 1s, 2s
        assert sleeps == [1.0, 2.0]

    async def test_raises_after_max_attempts(self):
        async def always_fails():
            raise httpx.ConnectError("down")

        async def fake_sleep(d: float):
            pass

        with pytest.raises(httpx.ConnectError):
            await with_retry(always_fails, max_attempts=3, sleep=fake_sleep)

    async def test_non_matching_exception_not_retried(self):
        calls = {"count": 0}

        async def type_error():
            calls["count"] += 1
            raise ValueError("not retriable")

        async def fake_sleep(d: float):
            pass

        with pytest.raises(ValueError):
            await with_retry(
                type_error,
                exceptions=(httpx.HTTPError,),
                sleep=fake_sleep,
            )
        assert calls["count"] == 1  # sin reintentos

    async def test_rejects_zero_max_attempts(self):
        async def noop():
            return None

        with pytest.raises(ValueError):
            await with_retry(noop, max_attempts=0)

    async def test_custom_base_delay(self):
        attempts = {"count": 0}

        async def fails_twice():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise httpx.ConnectError("x")
            return "ok"

        sleeps: list[float] = []

        async def fake_sleep(d: float):
            sleeps.append(d)

        await with_retry(
            fails_twice, max_attempts=5, base_delay=0.5, sleep=fake_sleep
        )
        assert sleeps == [0.5, 1.0]  # 0.5 × 2^0, 0.5 × 2^1


class TestParseSpanishNumber:
    def test_thousands_separator_only(self):
        assert parse_spanish_number("180.000.000") == Decimal(180_000_000)

    def test_no_separators(self):
        assert parse_spanish_number("37000") == Decimal(37000)

    def test_comma_as_decimal(self):
        assert parse_spanish_number("8.200,00") == Decimal("8200.00")
        assert parse_spanish_number("12.400,50") == Decimal("12400.50")

    def test_small_number(self):
        assert parse_spanish_number("12.400") == Decimal(12400)

    def test_empty_returns_none(self):
        assert parse_spanish_number("") is None
        assert parse_spanish_number("   ") is None

    def test_garbage_returns_none(self):
        assert parse_spanish_number("abc") is None


class TestParsePriceText:
    def test_clp_with_dollar(self):
        result = parse_price_text("$260.000.000")
        assert result == ("CLP", Decimal(260_000_000))

    def test_clp_without_dollar(self):
        result = parse_price_text("260.000.000")
        assert result == ("CLP", Decimal(260_000_000))

    def test_uf_concatenated(self):
        result = parse_price_text("UF8.200,00")
        assert result == ("UF", Decimal("8200.00"))

    def test_uf_with_space(self):
        result = parse_price_text("UF 12.400")
        assert result == ("UF", Decimal(12400))

    def test_uf_lowercase(self):
        assert parse_price_text("uf 8.200") == ("UF", Decimal(8200))

    def test_empty_returns_none(self):
        assert parse_price_text("") is None

    def test_garbage_returns_none(self):
        assert parse_price_text("gratis") is None


class TestToClp:
    def test_clp_passthrough(self):
        assert to_clp("CLP", Decimal(180_000_000), uf_to_clp=None) == Decimal(180_000_000)

    def test_uf_with_rate(self):
        assert to_clp("UF", Decimal(8200), uf_to_clp=Decimal(37000)) == Decimal(
            8200 * 37000
        )

    def test_uf_without_rate_returns_none(self):
        assert to_clp("UF", Decimal(8200), uf_to_clp=None) is None
