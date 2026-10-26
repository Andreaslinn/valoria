"""Tests del parser de yapo contra fixture HTML real."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from config.constants import YAPO_HOUSE_SEARCH_BASE_URL, YAPO_TARGETS
from infrastructure.scrapers.base import RateLimiter
from infrastructure.scrapers.yapo import (
    YapoScraper,
    build_page_url,
    build_target_url,
    parse_listing_detail,
)

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "yapo_list.html"
_UF = Decimal("37000")


class _FakeUFService:
    async def get_current_rate(self) -> Decimal:
        return _UF


def _load() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def _page_html(page: int) -> str:
    html = _load()
    replacements = {
        "31672033": f"316720{page:02d}",
        "32321098": f"323210{page:02d}",
        "99000001": f"990000{page:02d}",
    }
    for old, new in replacements.items():
        html = html.replace(old, new)
    return html


class TestYapoParser:
    def test_parses_valid_cards_only(self):
        """3 válidas + 1 malformada (sin precio) → 3 resultados."""
        results = YapoScraper.parse_listings(_load(), uf_to_clp=_UF)
        assert len(results) == 3

    def test_clp_card_fields(self):
        """Card Arica — precio en CLP."""
        results = YapoScraper.parse_listings(_load(), uf_to_clp=_UF)
        arica = next(r for r in results if r["comuna"] == "Arica")
        assert arica["source"] == "yapo"
        assert arica["property_type"] == "apartment"
        assert arica["external_id"] == "31672033"
        assert arica["title"] == "City Center Departamento VENTA - NOVACION"
        assert arica["price_clp"] == 260_000_000
        assert arica["m2"] == 115
        assert arica["bedrooms"] == 3
        assert arica["bathrooms"] == 1
        assert arica["parking"] == 3
        assert arica["url"].startswith("https://www.yapo.cl")
        assert arica["raw_metadata"]["currency_original"] == "CLP"
        assert arica["raw_metadata"]["category"] == "departamentos"
        assert arica["raw_metadata"]["location_text"] == "Arica"
        assert arica["raw_metadata"]["geocode_precision"] == "comuna"
        assert arica["raw_metadata"]["seller"] == "CKPropiedades m.r."
        assert arica["raw_metadata"]["price_reduction"] == "-10%"
        assert arica["raw_metadata"]["hallmark"] == "Exclusivo"

    def test_uf_card_converts_to_clp(self):
        """Card Viña — UF 8.200,00 x 37.000 = 303.400.000 CLP."""
        results = YapoScraper.parse_listings(_load(), uf_to_clp=_UF)
        vina = next(r for r in results if r["comuna"] == "Viña del Mar")
        assert vina["price_clp"] == 8200 * 37000
        assert vina["raw_metadata"]["currency_original"] == "UF"

    def test_card_without_parking_defaults_zero(self):
        """Card Viña tiene solo 3 items (sin parking)."""
        results = YapoScraper.parse_listings(_load(), uf_to_clp=_UF)
        vina = next(r for r in results if r["comuna"] == "Viña del Mar")
        assert vina["parking"] == 0

    def test_santiago_card_all_fields(self):
        results = YapoScraper.parse_listings(_load(), uf_to_clp=_UF)
        stgo = next(r for r in results if r["comuna"] == "Ñuñoa")
        assert stgo["m2"] == 75
        assert stgo["bedrooms"] == 3
        assert stgo["bathrooms"] == 2
        assert stgo["parking"] == 1
        assert stgo["price_clp"] == 180_000_000
        assert stgo["raw_metadata"]["address_label"] == "Metro Irarrázaval"
        assert stgo["raw_metadata"]["geocode_precision"] == "address"

    def test_extracts_street_hint_from_title_or_url(self):
        results = YapoScraper.parse_listings(_load(), uf_to_clp=_UF)
        vina = next(r for r in results if r["comuna"].startswith("Vi"))
        assert vina["raw_metadata"]["address_label"] == "San Martín"
        assert vina["raw_metadata"]["geocode_precision"] == "address"

    def test_card_body_intersection_noise_is_not_address(self):
        html = """
        <div class="d3-ad-tile">
          <a class="d3-ad-tile__description" href="/bienes-raices-venta-de-propiedades-apartamentos/departamento-amplio/12345">
            <div class="d3-ad-tile__location"><span>Ñuñoa</span></div>
            <h2 class="d3-ad-tile__title">Departamento amplio en venta</h2>
            <span class="d3-ad-tile__price">$180.000.000</span>
            <p>Cuenta y orientación poniente</p>
            <ul><li class="d3-ad-tile__details-item">75 m²</li></ul>
          </a>
        </div>
        """
        result = YapoScraper.parse_listings(html, uf_to_clp=_UF)[0]
        assert "address_label" not in result["raw_metadata"]
        assert result["raw_metadata"]["geocode_precision"] == "comuna"

    def test_uf_without_rate_drops_uf_cards(self):
        """Sin UFService, las cards en UF se descartan — mejor que inventar."""
        results = YapoScraper.parse_listings(_load(), uf_to_clp=None)
        currencies = {r["raw_metadata"]["currency_original"] for r in results}
        assert currencies == {"CLP"}  # solo las CLP sobreviven
        assert len(results) == 2

    def test_scraped_at_is_timestamp(self):
        results = YapoScraper.parse_listings(_load(), uf_to_clp=_UF)
        assert all(isinstance(r["scraped_at"], datetime) for r in results)

    def test_absolute_url_from_relative_href(self):
        results = YapoScraper.parse_listings(_load(), uf_to_clp=_UF)
        assert all(r["url"].startswith("https://www.yapo.cl") for r in results)

    def test_empty_html_returns_empty(self):
        assert YapoScraper.parse_listings("<html></html>", uf_to_clp=_UF) == []

    def test_corrupt_html_does_not_raise(self):
        YapoScraper.parse_listings("<<not html>>", uf_to_clp=_UF)

    def test_detail_url_prioritizes_known_comuna_from_url(self):
        html = """
        <html>
          <head><meta property="og:title" content="Depto 1D en Macul a pasos de metro"></head>
          <body>
            <h1>Depto 1D en Macul a pasos de metro</h1>
            <div class="listing-location">Ubicacion estrategica</div>
            <div class="price">$120.000.000</div>
            <p>45 m2, 1 dormitorio, 1 bano</p>
          </body>
        </html>
        """
        result = parse_listing_detail(
            html,
            url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/depto-1d-en-macul-a-pasos-de-metro/123",
        )

        assert result is not None
        assert result["comuna"] == "macul"
        assert result["price_clp"] == 120_000_000

    def test_detail_generic_location_is_not_used_as_comuna(self):
        html = """
        <html>
          <head><meta property="og:title" content="Depto remodelado"></head>
          <body>
            <h1>Depto remodelado</h1>
            <div class="listing-location">Ubicacion estrategica</div>
            <div class="price">$120.000.000</div>
            <p>45 m2, 1 dormitorio, 1 bano</p>
          </body>
        </html>
        """
        result = parse_listing_detail(
            html,
            url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/depto-remodelado/123",
        )

        assert result is not None
        assert result["comuna"] == ""

    def test_detail_uf_price_without_rate_does_not_convert_with_fallback(self):
        html = """
        <html>
          <head><meta property="og:title" content="Depto 1D en Macul"></head>
          <body>
            <h1>Depto 1D en Macul</h1>
            <div class="price">UF 3.200</div>
            <p>45 m2, 1 dormitorio, 1 bano</p>
          </body>
        </html>
        """
        result = parse_listing_detail(
            html,
            url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/depto-1d-en-macul/123",
        )

        assert result is not None
        assert result["price_clp"] == 0
        assert result["price_uf"] == 3200.0

    def test_detail_uf_price_converts_to_clp_with_explicit_rate(self):
        html = """
        <html>
          <head><meta property="og:title" content="Depto 1D en Macul"></head>
          <body>
            <h1>Depto 1D en Macul</h1>
            <div class="price">UF 3.200</div>
            <p>45 m2, 1 dormitorio, 1 bano</p>
          </body>
        </html>
        """
        result = parse_listing_detail(
            html,
            url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/depto-1d-en-macul/123",
            uf_to_clp=_UF,
        )

        assert result is not None
        assert result["price_clp"] == 3200 * 37000
        assert result["price_uf"] == 3200.0

    def test_detail_uf_price_per_m2_is_not_used_as_total_price(self):
        html = """
        <html>
          <head><meta property="og:title" content="Depto 1D en Macul"></head>
          <body>
            <h1>Depto 1D en Macul</h1>
            <p>Precio/M2 UF 3,15</p>
            <p>45 m2, 1 dormitorio, 1 bano</p>
          </body>
        </html>
        """
        result = parse_listing_detail(
            html,
            url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/depto-1d-en-macul/123",
            uf_to_clp=_UF,
        )

        assert result is not None
        assert result["price_clp"] == 0
        assert result["price_uf"] is None

    def test_detail_skips_uf_price_per_m2_and_uses_total_uf_price(self):
        html = """
        <html>
          <head><meta property="og:title" content="Depto 1D en Macul"></head>
          <body>
            <h1>Depto 1D en Macul</h1>
            <p>Precio/M2 UF 3,15</p>
            <div class="d3-property-info__price">UF 3.200</div>
            <p>45 m2, 1 dormitorio, 1 bano</p>
          </body>
        </html>
        """
        result = parse_listing_detail(
            html,
            url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/depto-1d-en-macul/123",
            uf_to_clp=_UF,
        )

        assert result is not None
        assert result["price_clp"] == 3200 * 37000
        assert result["price_uf"] == 3200.0

    def test_detail_structured_built_area_ignores_price_per_m2(self):
        html = """
        <html>
          <head><meta property="og:title" content="Casa remodelada en Estacion Central"></head>
          <body>
            <h1>Casa remodelada en Estacion Central</h1>
            <div class="d3-property-info__price">$140.000.000</div>
            <div class="d3-property-insight__attribute">
              <dt class="d3-property-insight__attribute-title">Precio</dt>
              <dd class="d3-property-insight__attribute-value">$140.000.000</dd>
            </div>
            <div class="d3-property-insight__attribute">
              <dt class="d3-property-insight__attribute-title">Dormitorios</dt>
              <dd class="d3-property-insight__attribute-value">3</dd>
            </div>
            <div class="d3-property-insight__attribute">
              <dt class="d3-property-insight__attribute-title">Baños</dt>
              <dd class="d3-property-insight__attribute-value">2</dd>
            </div>
            <div class="d3-property-insight__attribute">
              <dt class="d3-property-insight__attribute-title">Estacionamientos</dt>
              <dd class="d3-property-insight__attribute-value">4</dd>
            </div>
            <div class="d3-property-insight__attribute">
              <dt class="d3-property-insight__attribute-title">Área construida (m²)</dt>
              <dd class="d3-property-insight__attribute-value">150</dd>
            </div>
            <p>Precio/M² de construcción $933.333 M² totales ¡Pregunta al anunciante!</p>
          </body>
        </html>
        """
        result = parse_listing_detail(
            html,
            url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-casas/casa-remodelada-estacion-central/26139896",
        )

        assert result is not None
        assert result["m2"] == 150
        assert result["built_area_m2"] == 150
        assert result["bedrooms"] == 3
        assert result["bathrooms"] == 2
        assert result["parking"] == 4

    def test_detail_total_area_ignores_price_per_m2(self):
        html = """
        <html>
          <head><meta property="og:title" content="Casa familiar en Estacion Central"></head>
          <body>
            <h1>Casa familiar en Estacion Central</h1>
            <div class="d3-property-info__price">$150.000.000</div>
            <div class="d3-property-insight__attribute">
              <dt class="d3-property-insight__attribute-title">M² totales</dt>
              <dd class="d3-property-insight__attribute-value">190</dd>
            </div>
            <div class="d3-property-insight__attribute">
              <dt class="d3-property-insight__attribute-title">Precio/M² de terreno</dt>
              <dd class="d3-property-insight__attribute-value">$789.473</dd>
            </div>
          </body>
        </html>
        """
        result = parse_listing_detail(
            html,
            url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-casas/casa-familiar-en-estacion-central/28703730",
        )

        assert result is not None
        assert result["m2"] == 0
        assert result["built_area_m2"] is None
        assert result["land_area_m2"] == 190

    def test_detail_house_total_area_does_not_feed_built_area(self):
        html = """
        <html>
          <head><meta property="og:title" content="Casa con terreno en La Florida"></head>
          <body>
            <h1>Casa con terreno en La Florida</h1>
            <div class="d3-property-info__price">$150.000.000</div>
            <div class="d3-property-insight__attribute">
              <dt class="d3-property-insight__attribute-title">M2 totales</dt>
              <dd class="d3-property-insight__attribute-value">1.000</dd>
            </div>
          </body>
        </html>
        """
        result = parse_listing_detail(
            html,
            url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-casas/casa-con-terreno-la-florida/28703731",
        )

        assert result is not None
        assert result["m2"] == 0
        assert result["built_area_m2"] is None
        assert result["land_area_m2"] == 1000

    def test_detail_house_land_area_parses_thousands_separator(self):
        html = """
        <html>
          <head><meta property="og:title" content="Casa en Lo Curro Vitacura"></head>
          <body>
            <h1>Casa en Lo Curro Vitacura</h1>
            <div class="d3-property-info__price">$1.200.000.000</div>
            <div class="d3-property-insight__attribute">
              <dt class="d3-property-insight__attribute-title">Ãrea construida (mÂ²)</dt>
              <dd class="d3-property-insight__attribute-value">590</dd>
            </div>
            <p>Terreno de 5.432 m2 con gran parque.</p>
          </body>
        </html>
        """
        result = parse_listing_detail(
            html,
            url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-casas/casa-lo-curro-vitacura/32209325",
        )

        assert result is not None
        assert result["m2"] == 590
        assert result["built_area_m2"] == 590
        assert result["land_area_m2"] == 5432

    def test_detail_apartment_url_wins_over_generic_page_text(self):
        html = """
        <html>
          <head><meta property="og:title" content="Departamento en San Diego"></head>
          <body>
            <h1>Departamento en San Diego</h1>
            <div class="d3-property-info__price">UF973,00</div>
            <div class="d3-property-insight__attribute">
              <dt class="d3-property-insight__attribute-title">Área construida (m²)</dt>
              <dd class="d3-property-insight__attribute-value">21</dd>
            </div>
            <p>Textos genericos del portal mencionan casa y casas relacionadas.</p>
          </body>
        </html>
        """
        result = parse_listing_detail(
            html,
            url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-san-diego/29273175",
            uf_to_clp=_UF,
        )

        assert result is not None
        assert result["property_type"] == "apartment"
        assert result["price_uf"] == 973.0
        assert result["price_clp"] == 973 * 37000
        assert result["m2"] == 21

    def test_detail_casa_url_maps_to_house(self):
        html = """
        <html>
          <head><meta property="og:title" content="Casa familiar en Vitacura"></head>
          <body>
            <h1>Casa familiar en Vitacura</h1>
            <div class="price">$450.000.000</div>
            <p>180 m2, 4 dormitorios, 3 banos</p>
          </body>
        </html>
        """
        result = parse_listing_detail(
            html,
            url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-casas/casa-familiar-en-vitacura/123",
        )

        assert result is not None
        assert result["property_type"] == "house"
        assert result["raw_metadata"]["category"] == "casas"


class TestYapoPagination:
    def test_yapo_targets_config_is_valid(self):
        labels = [str(target["label"]) for target in YAPO_TARGETS]
        apartment_targets = [target for target in YAPO_TARGETS if target.get("property_type") == "apartment"]
        house_targets = [target for target in YAPO_TARGETS if target.get("property_type") == "house"]

        assert labels[0] == "general"
        assert len(labels) == len(set(labels))
        assert any(target["scope"] == "rm" for target in YAPO_TARGETS)
        assert apartment_targets
        assert house_targets
        for label in {
            "providencia",
            "nunoa",
            "las_condes",
            "santiago",
            "vitacura",
            "la_florida",
            "san_miguel",
            "maipu",
            "macul",
            "recoleta",
            "independencia",
            "estacion_central",
        }:
            assert label in labels
            assert f"{label}_house" in labels
        for target in YAPO_TARGETS:
            assert target["label"]
            assert target["scope"] in {"general", "rm"}
            assert 1 <= int(target["max_pages"]) <= 10
        for target in apartment_targets:
            assert str(target["query"]).startswith("keyword.departamentos venta")
        for target in house_targets:
            assert str(target["query"]).startswith("keyword.casa venta")
            assert target["scope"] == "rm"
            assert target["search_base_url"] == YAPO_HOUSE_SEARCH_BASE_URL

    def test_build_target_url_uses_validated_query_pattern(self):
        url = build_target_url({
            "label": "las_condes",
            "query": "keyword.departamentos venta Las Condes",
            "scope": "rm",
            "max_pages": 3,
        })
        assert url == (
            "https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-apartamentos"
            "?q=keyword.departamentos+venta+Las+Condes"
        )

    def test_build_target_url_supports_house_base_url(self):
        url = build_target_url({
            "label": "las_condes_house",
            "query": "keyword.casa venta Las Condes",
            "scope": "rm",
            "max_pages": 3,
            "property_type": "house",
            "search_base_url": YAPO_HOUSE_SEARCH_BASE_URL,
        })
        assert url == (
            "https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-casas"
            "?q=keyword.casa+venta+Las+Condes"
        )

    def test_build_page_url_uses_yapo_path_suffix(self):
        url = "https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-apartamentos?q=keyword.departamentos%20venta"
        assert build_page_url(url, 1) == url
        assert build_page_url(url, 2) == (
            "https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-apartamentos.2?q=keyword.departamentos%20venta"
        )
        assert build_page_url(build_page_url(url, 2), 3) == (
            "https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-apartamentos.3?q=keyword.departamentos%20venta"
        )

    def test_legacy_start_url_with_plus_query_is_not_double_encoded(self):
        requests: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(str(request.url))
            return httpx.Response(200, text="<html></html>")

        async def run() -> None:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                scraper = YapoScraper(
                    http_client=client,
                    rate_limiter=RateLimiter(0),
                    start_urls=[
                        "https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-apartamentos"
                        "?q=keyword.departamentos+venta+nunoa"
                    ],
                    uf_service=_FakeUFService(),
                    max_pages=1,
                )
                await scraper.scrape()

        import asyncio

        asyncio.run(run())

        assert requests == [
            "https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-apartamentos"
            "?q=keyword.departamentos+venta+nunoa"
        ]

    @pytest.mark.asyncio
    async def test_max_pages_respected(self):
        requests: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(str(request.url))
            return httpx.Response(200, text=_page_html(len(requests)))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = YapoScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                start_urls=["https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-apartamentos?q=x"],
                uf_service=_FakeUFService(),
                max_pages=2,
            )
            results = await scraper.scrape()

        assert len(requests) == 2
        assert scraper.last_raw_count == 6
        assert len(results) == 6

    @pytest.mark.asyncio
    async def test_hard_page_limit_is_enforced(self):
        requests = 0

        async def handler(_: httpx.Request) -> httpx.Response:
            nonlocal requests
            requests += 1
            return httpx.Response(200, text=_page_html(requests))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = YapoScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                start_urls=["https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-apartamentos?q=x"],
                uf_service=_FakeUFService(),
                max_pages=99,
            )
            await scraper.scrape()

        assert requests == 10

    @pytest.mark.asyncio
    async def test_stops_on_empty_page(self):
        requests = 0

        async def handler(_: httpx.Request) -> httpx.Response:
            nonlocal requests
            requests += 1
            return httpx.Response(200, text=_page_html(1) if requests == 1 else "<html></html>")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = YapoScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                start_urls=["https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-apartamentos?q=x"],
                uf_service=_FakeUFService(),
                max_pages=3,
            )
            results = await scraper.scrape()

        assert requests == 2
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_stops_discovery_on_429_without_retrying(self):
        requests = 0

        async def handler(_: httpx.Request) -> httpx.Response:
            nonlocal requests
            requests += 1
            return httpx.Response(429, text="rate limited")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = YapoScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                targets=[
                    {
                        "label": "nunoa",
                        "query": "keyword.departamentos venta nunoa",
                        "scope": "rm",
                        "max_pages": 2,
                    }
                ],
                uf_service=_FakeUFService(),
            )
            results = await scraper.scrape()

        assert requests == 1
        assert results == []
        assert scraper.last_rate_limited_count == 1
        assert scraper.last_blocked_or_captcha_count == 1

    @pytest.mark.asyncio
    async def test_stops_discovery_on_captcha_html(self):
        requests = 0

        async def handler(_: httpx.Request) -> httpx.Response:
            nonlocal requests
            requests += 1
            return httpx.Response(200, text="<html><title>captcha</title></html>")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = YapoScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                targets=[
                    {
                        "label": "nunoa",
                        "query": "keyword.departamentos venta nunoa",
                        "scope": "rm",
                        "max_pages": 2,
                    }
                ],
                uf_service=_FakeUFService(),
            )
            results = await scraper.scrape()

        assert requests == 1
        assert results == []
        assert scraper.last_blocked_or_captcha_count == 1

    @pytest.mark.asyncio
    async def test_stops_when_page_repeats_previous_listings(self):
        requests = 0

        async def handler(_: httpx.Request) -> httpx.Response:
            nonlocal requests
            requests += 1
            return httpx.Response(200, text=_page_html(1))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = YapoScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                start_urls=["https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-apartamentos?q=x"],
                uf_service=_FakeUFService(),
                max_pages=3,
            )
            results = await scraper.scrape()

        assert requests == 2
        assert scraper.last_raw_count == 6
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_deduplicates_within_run(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            page = 2 if ".2" in request.url.path else 1
            html = _page_html(1) if page == 1 else _page_html(2).replace("31672002", "31672001")
            return httpx.Response(200, text=html)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = YapoScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                start_urls=["https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-apartamentos?q=x"],
                uf_service=_FakeUFService(),
                max_pages=2,
            )
            results = await scraper.scrape()

        assert scraper.last_raw_count == 6
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_multi_target_pagination_respects_target_max_pages(self):
        requests: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            requests.append(url)
            page = 2 if ".2" in request.url.path else 1
            html = _page_html(page)
            if "Macul" in url:
                html = html.replace("316720", "416720").replace("323210", "423210").replace("990000", "490000")
            return httpx.Response(200, text=html)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = YapoScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                targets=[
                    {
                        "label": "santiago",
                        "query": "keyword.departamentos venta Santiago",
                        "scope": "rm",
                        "max_pages": 2,
                    },
                    {
                        "label": "macul",
                        "query": "keyword.departamentos venta Macul",
                        "scope": "rm",
                        "max_pages": 1,
                    },
                ],
                uf_service=_FakeUFService(),
            )
            results = await scraper.scrape()

        assert len(requests) == 3
        assert len(results) == 9
        assert scraper.last_raw_count == 9
        assert [(s.label, s.raw_count, s.unique_count) for s in scraper.last_target_stats] == [
            ("santiago", 6, 6),
            ("macul", 3, 3),
        ]

    @pytest.mark.asyncio
    async def test_deduplicates_across_targets_by_source_external_id(self):
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_page_html(1))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = YapoScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                targets=[
                    {
                        "label": "general",
                        "query": "keyword.departamentos venta",
                        "scope": "general",
                        "max_pages": 1,
                    },
                    {
                        "label": "nunoa",
                        "query": "keyword.departamentos venta nunoa",
                        "scope": "rm",
                        "max_pages": 1,
                    },
                ],
                uf_service=_FakeUFService(),
            )
            results = await scraper.scrape()

        assert scraper.last_raw_count == 6
        assert len(results) == 3
        assert [(s.label, s.raw_count, s.unique_count) for s in scraper.last_target_stats] == [
            ("general", 3, 3),
            ("nunoa", 3, 0),
        ]

    @pytest.mark.asyncio
    async def test_target_metadata_is_propagated(self):
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_page_html(1))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = YapoScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                targets=[
                    {
                        "label": "nunoa",
                        "query": "keyword.departamentos venta nunoa",
                        "scope": "rm",
                        "max_pages": 1,
                    }
                ],
                uf_service=_FakeUFService(),
            )
            results = await scraper.scrape()

        assert results
        metadata = results[0]["raw_metadata"]
        assert metadata["target_label"] == "nunoa"
        assert metadata["target_scope"] == "rm"
        assert metadata["target_query"] == "keyword.departamentos venta nunoa"
        assert metadata["target_property_type"] == "apartment"
        assert metadata["category"] == "departamentos"
        assert results[0]["property_type"] == "apartment"

    @pytest.mark.asyncio
    async def test_legacy_target_without_property_type_defaults_to_apartment(self):
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_page_html(1))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = YapoScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                targets=[
                    {
                        "label": "legacy_no_type",
                        "query": "keyword.departamentos venta nunoa",
                        "scope": "rm",
                        "max_pages": 1,
                    }
                ],
                uf_service=_FakeUFService(),
            )
            results = await scraper.scrape()

        assert results
        assert {result["property_type"] for result in results} == {"apartment"}
        assert {result["raw_metadata"]["target_property_type"] for result in results} == {"apartment"}

    @pytest.mark.asyncio
    async def test_house_target_metadata_is_propagated(self):
        requests: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(str(request.url))
            return httpx.Response(200, text=_page_html(1))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = YapoScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                targets=[
                    {
                        "label": "nunoa_house",
                        "query": "keyword.casa venta nunoa",
                        "scope": "rm",
                        "max_pages": 1,
                        "property_type": "house",
                        "search_base_url": YAPO_HOUSE_SEARCH_BASE_URL,
                    }
                ],
                uf_service=_FakeUFService(),
            )
            results = await scraper.scrape()

        assert requests
        assert "/bienes-raices-venta-de-propiedades-casas" in requests[0]
        assert results
        assert {result["property_type"] for result in results} == {"house"}
        assert {result["raw_metadata"]["target_property_type"] for result in results} == {"house"}
        assert {result["raw_metadata"]["category"] for result in results} == {"casas"}


class TestYapoPipelineCompat:
    """El output del parser debe ser consumible por clean_listing."""

    def test_santiago_card_flows_through_pipeline(self):
        from domain.ingestion.data_cleaning import clean_listing

        results = YapoScraper.parse_listings(_load(), uf_to_clp=_UF)
        stgo = next(r for r in results if r["comuna"] == "Ñuñoa")
        cleaned = clean_listing(dict(stgo))
        assert cleaned.price.clp == 180_000_000
        assert cleaned.comuna == "nunoa"
        assert cleaned.m2 == 75
