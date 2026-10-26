from __future__ import annotations

import httpx
import pytest

from services.listing_url_lookup import (
    detect_source,
    lookup_listing_url,
    validate_public_listing_url,
)
from tests.unit.factories import make_listing


def test_yapo_url_is_recognized() -> None:
    assert detect_source("https://www.yapo.cl/bienes-raices/test/123") == "yapo"


def test_unsupported_source() -> None:
    assert detect_source("https://portalinmobiliario.com/MLC-1") is None


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "file:///tmp/secret",
        "http://localhost:8501",
        "http://127.0.0.1:8000",
        "http://10.0.0.5/listing",
        "http://172.16.0.1/listing",
        "http://192.168.1.10/listing",
        "http://0.0.0.0/listing",
    ],
)
def test_invalid_or_private_urls_are_blocked(url: str) -> None:
    assert validate_public_listing_url(url) == "invalid_url"


@pytest.mark.asyncio
async def test_lookup_returns_unsupported_source() -> None:
    result = await lookup_listing_url("https://example.com/listing/1")

    assert result.status == "unsupported_source"
    assert result.source is None


@pytest.mark.asyncio
async def test_existing_listing_found_by_link() -> None:
    listing = make_listing(fingerprint="url-found")
    listing.id = 123
    listing.url = "https://www.yapo.cl/bienes-raices/test/123"

    async def fake_lookup(url: str):
        assert url == listing.url
        return listing

    result = await lookup_listing_url(listing.url, listing_lookup=fake_lookup)

    assert result.status == "found_existing"
    assert result.listing_data["comuna"] == "nunoa"
    assert result.listing_data["listing_id"] == 123
    assert result.listing_data["property_type"] == "apartment"
    assert result.listing_data["precio_publicado_clp"] == 180_000_000
    assert result.listing_data["precio_publicado_uf"] is None


@pytest.mark.asyncio
async def test_existing_listing_lookup_exposes_canonical_price_uf() -> None:
    listing = make_listing(
        fingerprint="san-diego",
        title="Departamento en San Diego | 1 Dormitorios por 973.00 en Santiago",
        comuna="santiago",
        m2=21,
        bedrooms=1,
        bathrooms=1,
        parking=0,
        price_clp=39_678_502,
        price_uf=973,
        price_currency="UF",
        price_uf_source="scraped",
        price_uf_confidence="high",
        price_recovery_method="raw.price_uf",
    )
    listing.id = 1217
    listing.url = "https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-san-diego/29273175"

    result = await lookup_listing_url(listing.url, listing_lookup=lambda _: _listing(listing))

    assert result.status == "found_existing"
    assert result.listing_data["listing_id"] == 1217
    assert result.listing_data["precio_publicado_uf"] == 973.0
    assert result.listing_data["precio_publicado_clp"] == 39_678_502
    assert result.listing_data["price_clp_snapshot"] == 39_678_502
    assert result.listing_data["price_currency"] == "UF"
    assert result.listing_data["price_uf_source"] == "scraped"
    assert result.listing_data["price_uf_confidence"] == "high"


@pytest.mark.asyncio
async def test_existing_listing_lookup_does_not_derive_uf_from_clp() -> None:
    listing = make_listing(
        fingerprint="clp-only",
        price_clp=120_000_000,
        price_uf=None,
        price_currency="CLP",
    )
    listing.url = "https://www.yapo.cl/bienes-raices/test/clp-only"

    result = await lookup_listing_url(listing.url, listing_lookup=lambda _: _listing(listing))

    assert result.status == "found_existing"
    assert result.listing_data["precio_publicado_uf"] is None
    assert result.listing_data["precio_publicado_clp"] == 120_000_000


@pytest.mark.asyncio
async def test_existing_listing_lookup_hides_legacy_unrecoverable_price_uf() -> None:
    listing = make_listing(
        fingerprint="legacy-unrecoverable",
        price_clp=156_000_000,
        price_uf=4000,
        price_currency="UF",
        price_uf_source="legacy_unrecoverable",
        price_uf_confidence="unknown",
        price_recovery_method="legacy_unrecoverable",
    )
    listing.url = "https://www.yapo.cl/bienes-raices/test/legacy-unrecoverable"

    result = await lookup_listing_url(listing.url, listing_lookup=lambda _: _listing(listing))

    assert result.status == "found_existing"
    assert result.listing_data["precio_publicado_uf"] is None
    assert result.listing_data["precio_publicado_clp"] == 156_000_000


@pytest.mark.asyncio
async def test_existing_listing_lookup_hides_low_confidence_price_uf() -> None:
    listing = make_listing(
        fingerprint="low-confidence",
        price_clp=156_000_000,
        price_uf=4000,
        price_currency="UF",
        price_uf_source="estimated",
        price_uf_confidence="low",
    )
    listing.url = "https://www.yapo.cl/bienes-raices/test/low-confidence"

    result = await lookup_listing_url(listing.url, listing_lookup=lambda _: _listing(listing))

    assert result.status == "found_existing"
    assert result.listing_data["precio_publicado_uf"] is None


@pytest.mark.asyncio
async def test_partial_when_critical_fields_are_missing() -> None:
    html = """
    <html>
      <head><meta property="og:title" content="Departamento amplio en Nunoa"></head>
      <body>
        <h1>Departamento amplio en Nunoa</h1>
        <div class="d3-ad-tile__location"><span>Nunoa</span></div>
        <p>75 m2, 2 dormitorios, 1 bano</p>
      </body>
    </html>
    """

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await lookup_listing_url(
            "https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/test/123",
            listing_lookup=lambda _: _none(),
            http_client=client,
        )

    assert result.status == "partial"
    assert result.listing_data["m2"] == 75
    assert "missing_price" in result.warnings


@pytest.mark.asyncio
async def test_lookup_continues_when_existing_listing_lookup_fails() -> None:
    html = """
    <html>
      <head><meta property="og:title" content="Depto 1D en Macul a pasos de metro"></head>
      <body>
        <h1>Depto 1D en Macul a pasos de metro</h1>
        <div class="listing-location">Ubicacion estrategica</div>
        <strong>$120.000.000</strong>
        <p>45 m2, 1 dormitorio, 1 bano</p>
      </body>
    </html>
    """

    async def failing_lookup(_: str):
        raise AttributeError("'NoneType' object has no attribute 'send'")

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await lookup_listing_url(
            "https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/depto-1d-en-macul-a-pasos-de-metro/123",
            listing_lookup=failing_lookup,
            http_client=client,
        )

    assert result.status == "parsed_new"
    assert result.listing_data["comuna"] == "macul"
    assert result.listing_data["precio_publicado_clp"] == 120_000_000


@pytest.mark.asyncio
async def test_yapo_url_with_uf_price_does_not_emit_missing_price() -> None:
    html = """
    <html>
      <head><meta property="og:title" content="Depto 1D en Macul a pasos de metro"></head>
      <body>
        <h1>Depto 1D en Macul a pasos de metro</h1>
        <div class="listing-location">Ubicacion estrategica</div>
        <strong>UF 3.200</strong>
        <p>45 m2, 1 dormitorio, 1 bano</p>
      </body>
    </html>
    """

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await lookup_listing_url(
            "https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/depto-1d-en-macul-a-pasos-de-metro/123",
            listing_lookup=lambda _: _none(),
            http_client=client,
        )

    assert result.status == "partial"
    assert result.listing_data["comuna"] == "macul"
    assert result.listing_data["precio_publicado_uf"] == 3200.0
    assert "missing_price" not in result.warnings


async def _none():
    return None


async def _listing(listing):
    return listing
