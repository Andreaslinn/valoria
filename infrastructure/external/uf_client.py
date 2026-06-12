"""Cliente para mindicador.cl/api/uf con caché Redis.

Implementa core.ports.uf_service.UFService.

Flujo:
    1. Buscar en Redis bajo la clave UF_CACHE_KEY.
    2. Si hit → devolver.
    3. Si miss → GET al API, parsear `serie[0].valor`, cachear TTL=12h.
    4. Si falla la red o el parsing, fallar explicitamente. Nunca retornar
       una tasa hardcodeada.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

import httpx
from redis.asyncio import Redis

from config.constants import UF_CACHE_TTL
from core.exceptions import UFServiceError
from core.ports.uf_service import UFRateInfo, UFService

_log = logging.getLogger(__name__)

UF_CACHE_KEY = "uf:current"
_HTTP_TIMEOUT_SECONDS = 10.0


class UFClient(UFService):
    def __init__(
        self,
        *,
        api_url: str,
        http_client: httpx.AsyncClient,
        redis: Redis,
        cache_ttl: int = UF_CACHE_TTL,
    ) -> None:
        self._api_url = api_url
        self._http = http_client
        self._redis = redis
        self._cache_ttl = cache_ttl

    async def get_current_rate(self) -> Decimal:
        return (await self.get_current_rate_info()).rate

    async def get_current_rate_info(self) -> UFRateInfo:
        cached = await self._from_cache()
        if cached is not None:
            return UFRateInfo(rate=cached, source="cache", is_fallback=False, cache_hit=True)

        fresh = await self._fetch_remote()
        if fresh is None:
            _log.error("UF fetch failed; no fallback rate will be used")
            raise UFServiceError("UF real no disponible")

        await self._store_in_cache(fresh)
        return UFRateInfo(rate=fresh, source="mindicador.cl", is_fallback=False, cache_hit=False)

    # ── Cache ──────────────────────────────────────────────
    async def _from_cache(self) -> Decimal | None:
        try:
            raw = await self._redis.get(UF_CACHE_KEY)
        except Exception as e:
            _log.warning("Redis GET failed: %s", e)
            return None
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            value = Decimal(raw)
        except InvalidOperation:
            _log.warning("Valor corrupto en caché UF: %r", raw)
            return None
        if value <= 0:
            _log.warning("Valor UF inválido en caché: %s", value)
            return None
        return value

    async def _store_in_cache(self, value: Decimal) -> None:
        try:
            await self._redis.setex(UF_CACHE_KEY, self._cache_ttl, str(value))
        except Exception as e:
            _log.warning("Redis SETEX failed: %s", e)

    # ── HTTP ───────────────────────────────────────────────
    async def _fetch_remote(self) -> Decimal | None:
        try:
            resp = await self._http.get(self._api_url, timeout=_HTTP_TIMEOUT_SECONDS)
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            _log.warning("UF API request failed: %s", e)
            return None

        try:
            valor = payload["serie"][0]["valor"]
            value = Decimal(str(valor))
        except (KeyError, IndexError, TypeError, InvalidOperation) as e:
            _log.warning("UF API payload inesperado: %s (%s)", payload, e)
            return None
        if value <= 0:
            _log.warning("UF API devolvió valor inválido: %s", value)
            return None
        _log.info("UF obtenida desde mindicador.cl: %s", value)
        return value
