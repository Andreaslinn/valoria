"""Cliente Nominatim best-effort con caché Redis."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import httpx
from redis.asyncio import Redis

from config.constants import GEOCODING_CACHE_TTL
from core.ports.geocoding_service import GeocodingService
from core.value_objects.location import Coordinates

_log = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 10.0
_NEGATIVE_CACHE_TTL = 86_400
_COUNTRY_CODE = "cl"


@dataclass(frozen=True)
class GeocodingResult:
    coordinates: Coordinates
    query: str
    provider: str
    raw_class: str | None = None
    raw_type: str | None = None
    raw_addresstype: str | None = None
    display_name: str | None = None
    address: dict[str, Any] | None = None
    importance: float | None = None
    from_cache: bool = False


class NominatimClient(GeocodingService):
    def __init__(
        self,
        *,
        api_url: str,
        http_client: httpx.AsyncClient,
        redis: Redis,
        user_agent: str,
        cache_ttl: int = GEOCODING_CACHE_TTL,
        negative_cache_ttl: int = _NEGATIVE_CACHE_TTL,
    ) -> None:
        self._api_url = api_url
        self._http = http_client
        self._redis = redis
        self._user_agent = user_agent
        self._cache_ttl = cache_ttl
        self._negative_cache_ttl = negative_cache_ttl
        self.cache_hits = 0
        self.cache_misses = 0
        self.external_requests = 0
        self.last_cache_hit = False

    async def geocode(self, address: str, comuna: str) -> Coordinates | None:
        result = await self.geocode_with_metadata(address, comuna)
        return result.coordinates if result is not None else None

    async def geocode_with_metadata(self, address: str, comuna: str) -> GeocodingResult | None:
        query = build_nominatim_query(address, comuna)
        if not query:
            return None

        cache_key = geocoding_cache_key(address, comuna)
        cached = await self._from_cache(cache_key)
        if cached is not _CACHE_MISS:
            self.last_cache_hit = True
            self.cache_hits += 1
            if cached is None:
                return None
            if isinstance(cached, GeocodingResult):
                return cached
            return GeocodingResult(coordinates=cached, query=query, provider="nominatim", from_cache=True)

        self.last_cache_hit = False
        self.cache_misses += 1
        result = await self._fetch_remote(query)
        if result is _REMOTE_ERROR:
            return None
        await self._store_in_cache(cache_key, result)
        return result

    async def _from_cache(self, cache_key: str) -> GeocodingResult | Coordinates | None | object:
        try:
            raw = await self._redis.get(cache_key)
        except Exception as e:
            _log.warning("Redis GET geocoding failed: %s", e)
            return _CACHE_MISS
        if raw is None:
            return _CACHE_MISS
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as e:
            _log.warning("Valor corrupto en caché geocoding: %r (%s)", raw, e)
            return _CACHE_MISS
        if payload.get("status") == "miss":
            return None
        try:
            coords = Coordinates(lat=float(payload["lat"]), lon=float(payload["lon"]))
            if "query" not in payload:
                return coords
            return GeocodingResult(
                coordinates=coords,
                query=str(payload.get("query") or ""),
                provider=str(payload.get("provider") or "nominatim"),
                raw_class=_optional_payload_str(payload.get("raw_class")),
                raw_type=_optional_payload_str(payload.get("raw_type")),
                raw_addresstype=_optional_payload_str(payload.get("raw_addresstype")),
                display_name=_optional_payload_str(payload.get("display_name")),
                address=payload.get("address") if isinstance(payload.get("address"), dict) else None,
                importance=_optional_payload_float(payload.get("importance")),
                from_cache=True,
            )
        except (KeyError, TypeError, ValueError) as e:
            _log.warning("Coordenadas corruptas en caché geocoding: %r (%s)", payload, e)
            return _CACHE_MISS

    async def _store_in_cache(self, cache_key: str, result: GeocodingResult | None) -> None:
        if result is None:
            payload = {"status": "miss"}
            ttl = self._negative_cache_ttl
        else:
            payload = {
                "status": "hit",
                "lat": result.coordinates.lat,
                "lon": result.coordinates.lon,
                "query": result.query,
                "provider": result.provider,
                "raw_class": result.raw_class,
                "raw_type": result.raw_type,
                "raw_addresstype": result.raw_addresstype,
                "display_name": result.display_name,
                "address": result.address or {},
                "importance": result.importance,
            }
            ttl = self._cache_ttl
        try:
            await self._redis.setex(cache_key, ttl, json.dumps(payload))
        except Exception as e:
            _log.warning("Redis SETEX geocoding failed: %s", e)

    async def _fetch_remote(self, query: str) -> GeocodingResult | None | object:
        self.external_requests += 1
        try:
            resp = await self._http.get(
                self._api_url,
                params={
                    "q": query,
                    "format": "json",
                    "limit": 1,
                    "countrycodes": _COUNTRY_CODE,
                    "addressdetails": 1,
                },
                headers={
                    "User-Agent": self._user_agent,
                    "Accept-Language": "es-CL,es;q=0.9,en;q=0.5",
                },
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            _log.warning("Nominatim request failed: %s", e)
            return _REMOTE_ERROR

        if not isinstance(payload, list) or not payload:
            return None
        first = payload[0]
        if not isinstance(first, dict):
            return None
        try:
            coords = Coordinates(lat=float(first["lat"]), lon=float(first["lon"]))
        except (KeyError, TypeError, ValueError) as e:
            _log.warning("Nominatim payload inesperado: %s (%s)", first, e)
            return None
        return GeocodingResult(
            coordinates=coords,
            query=query,
            provider="nominatim",
            raw_class=_optional_payload_str(first.get("class")),
            raw_type=_optional_payload_str(first.get("type")),
            raw_addresstype=_optional_payload_str(first.get("addresstype")),
            display_name=_optional_payload_str(first.get("display_name")),
            address=first.get("address") if isinstance(first.get("address"), dict) else None,
            importance=_optional_payload_float(first.get("importance")),
        )


_CACHE_MISS = object()
_REMOTE_ERROR = object()


def build_nominatim_query(address: str, comuna: str) -> str:
    address_part = _clean_part(address)
    address_key = normalize_geocoding_text(address_part)
    parts = [address_part]
    for part in (_clean_part(comuna), "Chile"):
        part_key = normalize_geocoding_text(part)
        if part_key and part_key not in address_key:
            parts.append(part)
    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        key = normalize_geocoding_text(part)
        if key and key not in seen:
            seen.add(key)
            deduped.append(part)
    return ", ".join(deduped)


def geocoding_cache_key(address: str, comuna: str) -> str:
    normalized = f"{normalize_geocoding_text(address)}|{normalize_geocoding_text(comuna)}"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"geocoding:nominatim:{digest}"


def normalize_geocoding_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text).strip().lower()


def _clean_part(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip(" ,")


def _optional_payload_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_payload_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
