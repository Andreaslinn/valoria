from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from core.value_objects.location import Coordinates
from infrastructure.external.nominatim_client import (
    NominatimClient,
    build_nominatim_query,
    geocoding_cache_key,
)
from scripts.geocode_listings import (
    build_geocoding_query,
    extract_geocoding_hint,
    select_location_text,
    should_skip_comuna,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.setex_calls: list[tuple[str, int, str]] = []

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.setex_calls.append((key, ttl, value))


@pytest.mark.asyncio
async def test_successful_response_returns_coordinates() -> None:
    redis = FakeRedis()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["countrycodes"] == "cl"
        assert request.headers["User-Agent"] == "AVM-v2-geocoder/0.1 (contact: dev-local)"
        assert request.headers["Accept-Language"] == "es-CL,es;q=0.9,en;q=0.5"
        return httpx.Response(200, json=[{"lat": "-33.4569", "lon": "-70.6483"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = _client(http, redis)
        coords = await client.geocode("Av Providencia 123", "Providencia")

    assert coords == Coordinates(lat=-33.4569, lon=-70.6483)
    assert client.external_requests == 1


@pytest.mark.asyncio
async def test_empty_response_returns_none() -> None:
    redis = FakeRedis()

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[]))) as http:
        client = _client(http, redis)
        coords = await client.geocode("Sin numero", "Providencia")

    assert coords is None


@pytest.mark.asyncio
async def test_http_error_returns_none() -> None:
    redis = FakeRedis()

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as http:
        client = _client(http, redis)
        coords = await client.geocode("Av Providencia 123", "Providencia")

    assert coords is None
    assert redis.setex_calls == []


@pytest.mark.asyncio
async def test_invalid_lat_lon_returns_none() -> None:
    redis = FakeRedis()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[{"lat": "x", "lon": "-70"}]))
    ) as http:
        client = _client(http, redis)
        coords = await client.geocode("Av Providencia 123", "Providencia")

    assert coords is None


@pytest.mark.asyncio
async def test_cache_hit_avoids_http_call() -> None:
    redis = FakeRedis()
    key = geocoding_cache_key("Av Providencia 123", "Providencia")
    redis.values[key] = json.dumps({"status": "hit", "lat": -33.4, "lon": -70.6})

    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[{"lat": "-33.4569", "lon": "-70.6483"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = _client(http, redis)
        coords = await client.geocode("Av Providencia 123", "Providencia")

    assert coords == Coordinates(lat=-33.4, lon=-70.6)
    assert calls == 0
    assert client.cache_hits == 1


@pytest.mark.asyncio
async def test_cache_set_after_successful_call() -> None:
    redis = FakeRedis()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[{"lat": "-33.4", "lon": "-70.6"}]))
    ) as http:
        client = _client(http, redis)
        await client.geocode("Av Providencia 123", "Providencia")

    assert redis.setex_calls
    _, ttl, raw = redis.setex_calls[0]
    assert ttl == 2_592_000
    payload = json.loads(raw)
    assert payload["status"] == "hit"
    assert payload["lat"] == -33.4
    assert payload["lon"] == -70.6
    assert payload["provider"] == "nominatim"


def test_query_building_dedupes_chile_and_comuna() -> None:
    assert build_nominatim_query("Av Providencia 123, Providencia, Chile", "Providencia") == (
        "Av Providencia 123, Providencia, Chile"
    )


def test_cache_key_normalization_is_deterministic() -> None:
    assert geocoding_cache_key("  Avenida Nunoa 123 ", "Nunoa") == geocoding_cache_key(
        "avenida nunoa 123",
        "nunoa",
    )


def test_address_metadata_wins() -> None:
    listing = SimpleNamespace(
        title="Depto luminoso",
        comuna="Nunoa",
        raw_metadata={"address_label": "Av Grecia 100"},
    )
    # The shared hint extractor expands avenue abbreviations before geocoding.
    assert build_geocoding_query(listing) == ("Avenida Grecia 100, Nunoa, Chile", "street_address")


def test_address_fallback_selection() -> None:
    assert (
        select_location_text(
            title="Depto luminoso",
            comuna="Nunoa",
            raw_metadata={"address_label": "Av Grecia 100"},
        )
        == ("Avenida Grecia 100", "street_address")
    )
    assert select_location_text(title="Depto luminoso", comuna="Nunoa", raw_metadata={}) == (None, "unknown")


def test_location_text_is_preferred_before_title() -> None:
    assert (
        select_location_text(
            title="Depto luminoso",
            comuna="Providencia",
            raw_metadata={"location_text": "Metro Pedro de Valdivia"},
        )
        == ("Metro Pedro de Valdivia", "landmark_or_sector")
    )


def test_calle_and_av_are_extracted_from_title() -> None:
    calle_listing = SimpleNamespace(
        title="DPTO N 407, 1D+1B, CALLE PORTUGAL, METRO IRARRAZA",
        comuna="Santiago",
        raw_metadata={},
    )
    av_listing = SimpleNamespace(
        title="EN VENTA 1D+1B AMPLIO DPTO. AV. PORTUGAL 451",
        comuna="Santiago",
        raw_metadata={},
    )

    assert build_geocoding_query(calle_listing) == ("CALLE PORTUGAL, Santiago, Chile", "street_name")
    assert build_geocoding_query(av_listing) == ("AV. PORTUGAL 451, Santiago, Chile", "street_address")


def test_street_address_precision_from_known_street_snippet() -> None:
    listing = SimpleNamespace(
        title="LORD COCHRANE 635 EN VENTA 1DORMITORIO+1BANO+ESTAC",
        comuna="Santiago",
        raw_metadata={},
    )
    assert build_geocoding_query(listing) == ("LORD COCHRANE 635, Santiago, Chile", "street_address")


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("DPTO N 407, 1D+1B, CALLE PORTUGAL, METRO IRARRAZA", ("CALLE PORTUGAL", "street_name")),
        ("EN VENTA 1D+1B AMPLIO DPTO. AV PORTUGAL / SANTA ISABEL", ("AV PORTUGAL y Santa Isabel", "street_name")),
        ("Portugal con Santa Isabel excelente conectividad", ("Portugal y Santa Isabel", "street_name")),
        ("Departamento Antonio Varas comuna Providencia", ("Antonio Varas", "street_name")),
        ("Fray Camilo Henriquez cercano a todo", ("Fray Camilo Henriquez", "street_name")),
        ("DPTO CALLE BLEST GANA METRO", ("CALLE BLEST GANA", "street_name")),
        ("a pasos de Metro Irarrazaval", ("Metro Irarrazaval", "landmark_or_sector")),
        ("cerca de Metro Cal y Canto", ("Metro Cal y Canto", "landmark_or_sector")),
        ("sector Metro Pedro de Valdivia", ("Metro Pedro de Valdivia", "landmark_or_sector")),
        ("Departamento en Morande", ("Morande", "street_name")),
        ("Departamento en San Diego", ("San Diego", "street_name")),
    ],
)
def test_extracts_new_geocoding_hints(title: str, expected: tuple[str, str]) -> None:
    assert extract_geocoding_hint(title, "", "Santiago") == expected


def test_department_in_comuna_does_not_become_street_hint() -> None:
    assert extract_geocoding_hint("Departamento en Nunoa", "", "Nunoa") == (None, "unknown")


def test_extracts_hint_from_description() -> None:
    assert extract_geocoding_hint(
        "Departamento remodelado",
        "Ubicado en Av Portugal / Santa Isabel, cercano a servicios",
        "Santiago",
    ) == ("Av Portugal y Santa Isabel", "street_name")


def test_noisy_title_falls_back_to_comuna() -> None:
    listing = SimpleNamespace(
        title="Se Vende Dpto. Townhouse +un Estacionamiento+bodega 7807 Uf",
        comuna="san_miguel",
        raw_metadata={},
    )
    assert build_geocoding_query(listing) == ("San Miguel, Santiago, Chile", "comuna_centroid")


def test_missing_comuna_returns_none() -> None:
    listing = SimpleNamespace(title="Calle Portugal 451", comuna=None, raw_metadata={})
    assert build_geocoding_query(listing) == (None, "unknown")


def test_unknown_comuna_is_skipped() -> None:
    assert should_skip_comuna(None)
    assert should_skip_comuna("Desconocida")
    assert not should_skip_comuna("Providencia")


def _client(http: httpx.AsyncClient, redis: Any) -> NominatimClient:
    return NominatimClient(
        api_url="https://nominatim.openstreetmap.org/search",
        http_client=http,
        redis=redis,
        user_agent="AVM-v2-geocoder/0.1 (contact: dev-local)",
    )
