"""Redis-backed rate limiting helpers for public beta endpoints."""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from config.settings import Settings
from core.entities.user import User

_log = logging.getLogger(__name__)

RATE_LIMIT_DETAIL = "Demasiadas solicitudes. Intenta nuevamente mas tarde."
_KEY_PREFIX = "valoria:ratelimit"
_SCRIPT = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[1])
end
local ttl = redis.call("TTL", KEYS[1])
if ttl < 0 then
  redis.call("EXPIRE", KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {current, ttl}
"""


class RedisLike(Protocol):
    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


@dataclass(frozen=True)
class RateLimitRule:
    namespace: str
    max_requests: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int


class RateLimiter:
    def __init__(self, *, redis: RedisLike | None, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    async def check(self, rule: RateLimitRule, identifier: str) -> RateLimitResult:
        if not self._settings.rate_limit_enabled:
            return RateLimitResult(allowed=True, retry_after_seconds=0)
        if self._redis is None:
            return self._handle_unavailable("redis_not_configured")

        key = self._key(rule, identifier)
        try:
            raw = await self._redis.eval(_SCRIPT, 1, key, int(rule.window_seconds))
        except Exception:
            return self._handle_unavailable("redis_error")

        count, ttl = _parse_eval_result(raw, fallback_ttl=rule.window_seconds)
        if count > rule.max_requests:
            return RateLimitResult(allowed=False, retry_after_seconds=max(1, ttl))
        return RateLimitResult(allowed=True, retry_after_seconds=max(0, ttl))

    def _handle_unavailable(self, reason: str) -> RateLimitResult:
        _log.warning("rate_limit_unavailable reason=%s fail_open=%s", reason, self._settings.rate_limit_fail_open)
        if self._settings.rate_limit_fail_open:
            return RateLimitResult(allowed=True, retry_after_seconds=0)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio temporalmente no disponible",
        )

    def _key(self, rule: RateLimitRule, identifier: str) -> str:
        digest = digest_identifier(identifier, self._settings)
        return ":".join(
            [
                _KEY_PREFIX,
                self._settings.environment,
                rule.namespace,
                str(rule.window_seconds),
                digest,
            ]
        )


def digest_identifier(value: str, settings: Settings) -> str:
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def client_ip_identifier(request: Request) -> str:
    # Caddy is the only public entrypoint and API port 8000 is not published.
    # Uvicorn is configured with proxy headers, so request.client.host is the
    # trusted client address after proxy processing.
    if request.client is None or not request.client.host:
        return "ip:unknown"
    return f"ip:{request.client.host}"


def normalized_account_identifier(username: str) -> str:
    return f"account:{username.strip().lower()}"


def user_identifier(user: User) -> str:
    if user.id is not None:
        return f"user-id:{user.id}"
    return f"user-email:{user.email.strip().lower()}"


async def enforce_rate_limit(limiter: RateLimiter, rule: RateLimitRule, identifier: str) -> None:
    result = await limiter.check(rule, identifier)
    if result.allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=RATE_LIMIT_DETAIL,
        headers={
            "Retry-After": str(max(1, int(result.retry_after_seconds))),
            "Cache-Control": "no-store",
        },
    )


def _parse_eval_result(raw: object, *, fallback_ttl: int) -> tuple[int, int]:
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return int(raw[0]), int(raw[1])
    return int(raw), fallback_ttl
