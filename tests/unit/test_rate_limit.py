from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException

from api.rate_limit import (
    RateLimiter,
    RateLimitRule,
    digest_identifier,
    enforce_rate_limit,
)
from config import get_settings


class FakeRedis:
    def __init__(self) -> None:
        self.now = 0
        self.values: dict[str, int] = {}
        self.expires_at: dict[str, int] = {}
        self.keys_seen: list[str] = []

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[int]:
        key = str(keys_and_args[0])
        window = int(keys_and_args[1])
        self.keys_seen.append(key)
        if key in self.expires_at and self.expires_at[key] <= self.now:
            self.values.pop(key, None)
            self.expires_at.pop(key, None)
        self.values[key] = self.values.get(key, 0) + 1
        if key not in self.expires_at:
            self.expires_at[key] = self.now + window
        return [self.values[key], self.expires_at[key] - self.now]

    def advance(self, seconds: int) -> None:
        self.now += seconds


class BrokenRedis:
    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        raise RuntimeError("redis down with secret-ish detail")


@pytest.mark.asyncio
async def test_allows_within_limit_and_blocks_after_limit_with_retry_after() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(redis=redis, settings=get_settings())
    rule = RateLimitRule("auth:login:ip", max_requests=2, window_seconds=300)

    await enforce_rate_limit(limiter, rule, "ip:203.0.113.1")
    await enforce_rate_limit(limiter, rule, "ip:203.0.113.1")
    with pytest.raises(HTTPException) as exc:
        await enforce_rate_limit(limiter, rule, "ip:203.0.113.1")

    assert exc.value.status_code == 429
    assert exc.value.headers is not None
    assert int(exc.value.headers["Retry-After"]) > 0
    assert exc.value.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_window_expiration_resets_counter() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(redis=redis, settings=get_settings())
    rule = RateLimitRule("reports:generate:user", max_requests=1, window_seconds=10)

    await enforce_rate_limit(limiter, rule, "user-id:1")
    with pytest.raises(HTTPException):
        await enforce_rate_limit(limiter, rule, "user-id:1")

    redis.advance(10)
    await enforce_rate_limit(limiter, rule, "user-id:1")


@pytest.mark.asyncio
async def test_distinct_users_ips_and_endpoints_have_distinct_buckets() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(redis=redis, settings=get_settings())
    rule_a = RateLimitRule("listings:lookup-url:user", max_requests=1, window_seconds=600)
    rule_b = RateLimitRule("listings:analyze-url:user", max_requests=1, window_seconds=600)

    await enforce_rate_limit(limiter, rule_a, "user-id:1")
    await enforce_rate_limit(limiter, rule_a, "user-id:2")
    await enforce_rate_limit(limiter, rule_b, "user-id:1")
    await enforce_rate_limit(limiter, rule_a, "ip:198.51.100.1")
    await enforce_rate_limit(limiter, rule_a, "ip:198.51.100.2")

    assert len(set(redis.keys_seen)) == 5


@pytest.mark.asyncio
async def test_keys_do_not_contain_email_url_jwt_or_password() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(redis=redis, settings=get_settings())
    rule = RateLimitRule("auth:login:account", max_requests=10, window_seconds=3600)
    sensitive = "ip:203.0.113.9:account:person@example.com:https://example.test/a.jwt.value:password123"

    await enforce_rate_limit(limiter, rule, sensitive)

    key = redis.keys_seen[0]
    assert "person@example.com" not in key
    assert "example.test" not in key
    assert "a.jwt.value" not in key
    assert "password123" not in key


def test_digest_identifier_is_stable_and_hmac_sha256() -> None:
    settings = get_settings()

    first = digest_identifier("user-id:1", settings)
    second = digest_identifier("user-id:1", settings)

    assert first == second
    assert len(first) == 64
    assert first != "user-id:1"


@pytest.mark.asyncio
async def test_redis_unavailable_fail_open_logs_sanitized_warning(caplog) -> None:
    settings = get_settings().model_copy(update={"rate_limit_fail_open": True})
    limiter = RateLimiter(redis=BrokenRedis(), settings=settings)
    rule = RateLimitRule("auth:login:ip", max_requests=1, window_seconds=300)

    with caplog.at_level(logging.WARNING):
        await enforce_rate_limit(limiter, rule, "person@example.com:password123")

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "rate_limit_unavailable" in messages
    assert "person@example.com" not in messages
    assert "password123" not in messages


@pytest.mark.asyncio
async def test_redis_unavailable_fail_closed_is_not_500() -> None:
    settings = get_settings().model_copy(update={"rate_limit_fail_open": False})
    limiter = RateLimiter(redis=BrokenRedis(), settings=settings)
    rule = RateLimitRule("auth:login:ip", max_requests=1, window_seconds=300)

    with pytest.raises(HTTPException) as exc:
        await enforce_rate_limit(limiter, rule, "ip:203.0.113.1")

    assert exc.value.status_code == 503
