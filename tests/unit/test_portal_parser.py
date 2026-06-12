"""Tests del parser de portalinmobiliario contra fixture HTML real."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx

from infrastructure.scrapers.base import RateLimiter
from infrastructure.scrapers.portalinmobiliario import PortalInmobiliarioScraper

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "portal_list.html"
_UF = Decimal("37000")


def _load() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


class TestPortalParser:
    def test_parses_valid_items_only(self):
        """2 válidas + 1 sin precio → 2 resultados."""
        results = PortalInmobiliarioScraper.parse_listings(_load(), uf_to_clp=_UF)
        assert len(results) == 2

    def test_uf_without_rate_returns_empty(self):
        """Sin tasa UF, todas las cards del portal se descartan (todas en UF)."""
        assert PortalInmobiliarioScraper.parse_listings(_load(), uf_to_clp=None) == []


class TestSsrLayout:
    """Card 1: layout SSR confirmado — a.poly-component__title + .poly-component__location."""

    def test_fields_extracted(self):
        results = PortalInmobiliarioScraper.parse_listings(_load(), uf_to_clp=_UF)
        first = results[0]
        assert first["source"] == "portalinmobiliario"
        assert first["external_id"] == "MLC-3892121810"
        assert first["title"] == "Departamento En Venta De 3 Dorm. En Las Condes"
        assert first["price_clp"] == 12_400 * 37_000
        assert first["m2"] == 160
        assert first["bedrooms"] == 3
        assert first["bathrooms"] == 3
        assert first["raw_metadata"]["seller"] == "Ascui Propiedades"
        assert first["raw_metadata"]["currency_original"] == "UF"

    def test_comuna_extracted_from_last_segment_of_location(self):
        """Location = 'Calle / Del Inca, Metro Escuela Militar, Las Condes'
        → comuna es el tercer segmento."""
        results = PortalInmobiliarioScraper.parse_listings(_load(), uf_to_clp=_UF)
        assert results[0]["comuna"] == "Las Condes"


class TestHydratedSpaLayout:
    """Card 2: layout hidratado SPA — nested andes-money-amount + comuna en attrs."""

    def test_nested_price_parses(self):
        """El texto 'UF' + '12.500' en spans separados debe concatenarse
        y parsearse correctamente."""
        results = PortalInmobiliarioScraper.parse_listings(_load(), uf_to_clp=_UF)
        second = results[1]
        assert second["price_clp"] == 12_500 * 37_000
        assert second["m2"] == 166

    def test_comuna_extracted_from_attributes_list(self):
        """Cuando no hay .poly-component__location, buscamos en la lista
        de atributos con el mismo heurístico."""
        results = PortalInmobiliarioScraper.parse_listings(_load(), uf_to_clp=_UF)
        assert results[1]["comuna"] == "Las Condes"


class TestComunaHeuristic:
    """El extractor de comuna tolera orden y segmentos extra."""

    def test_comuna_at_end(self):
        html = """
        <li class="ui-search-layout__item"><div class="poly-card">
          <a class="poly-component__title" href="/MLC-1">T</a>
          <div class="poly-component__price">UF 10.000</div>
          <span class="poly-component__location">Av. X, Metro Y, Ñuñoa</span>
        </div></li>
        """
        results = PortalInmobiliarioScraper.parse_listings(html, uf_to_clp=_UF)
        assert results[0]["comuna"] == "Ñuñoa"

    def test_comuna_at_start(self):
        html = """
        <li class="ui-search-layout__item"><div class="poly-card">
          <a class="poly-component__title" href="/MLC-2">T</a>
          <div class="poly-component__price">UF 10.000</div>
          <span class="poly-component__location">Providencia, Región Metropolitana</span>
        </div></li>
        """
        results = PortalInmobiliarioScraper.parse_listings(html, uf_to_clp=_UF)
        assert results[0]["comuna"] == "Providencia"

    def test_unknown_comuna_card_discarded(self):
        html = """
        <li class="ui-search-layout__item"><div class="poly-card">
          <a class="poly-component__title" href="/MLC-3">T</a>
          <div class="poly-component__price">UF 10.000</div>
          <span class="poly-component__location">Calle X, Marte</span>
        </div></li>
        """
        assert PortalInmobiliarioScraper.parse_listings(html, uf_to_clp=_UF) == []


class TestEdgeCases:
    def test_malformed_item_without_price_discarded(self):
        results = PortalInmobiliarioScraper.parse_listings(_load(), uf_to_clp=_UF)
        ids = {r["external_id"] for r in results}
        assert "MLC-bad" not in ids

    def test_empty_html_returns_empty(self):
        assert PortalInmobiliarioScraper.parse_listings("<html></html>", uf_to_clp=_UF) == []

    def test_clp_price_works_too(self):
        """Aunque el sitio suele dar UF, aceptamos CLP si aparece."""
        html = """
        <li class="ui-search-layout__item"><div class="poly-card">
          <a class="poly-component__title" href="/MLC-clp">T</a>
          <div class="poly-component__price">$180.000.000</div>
          <span class="poly-component__location">Ñuñoa, Región Metropolitana</span>
        </div></li>
        """
        results = PortalInmobiliarioScraper.parse_listings(html, uf_to_clp=None)
        assert results[0]["price_clp"] == 180_000_000


class TestBotChallengeDetection:
    """Portal devuelve una shell ~5kb con _bmc + verifyChallenge cuando nos detecta
    como bot. Debemos detectarla y loguear en vez de procesar silenciosamente."""

    def test_detects_akamai_shell_and_returns_empty(self, caplog):
        import logging

        shell = (
            '<!DOCTYPE html><html><head><title> </title></head><body>'
            '<script>document.cookie=`_bmc=...`;'
            'function verifyChallenge(){}</script>'
            '<button id="continue-button">Continuar</button></body></html>'
        )
        with caplog.at_level(logging.WARNING):
            results = PortalInmobiliarioScraper.parse_listings(shell, uf_to_clp=_UF)
        assert results == []
        assert any("CAPTCHA/BLOCK DETECTADO" in rec.message for rec in caplog.records)

    def test_large_html_not_flagged_as_challenge(self):
        """HTML grande con contenido real no debe marcarse como shell."""
        content = _load()  # fixture de ~2kb... pero tiene poly-card, pasa
        # Construir algo grande sin marcadores
        big = "<html><body>" + ("<div>content</div>" * 5000) + "</body></html>"
        # No debería disparar la detección por tamaño
        results = PortalInmobiliarioScraper.parse_listings(big, uf_to_clp=_UF)
        assert results == []  # sin items, pero sin warning


class TestPipelineCompat:
    def test_las_condes_flows_through_clean_listing(self):
        from domain.ingestion.data_cleaning import clean_listing

        results = PortalInmobiliarioScraper.parse_listings(_load(), uf_to_clp=_UF)
        raw = dict(results[0])
        cleaned = clean_listing(raw)
        assert cleaned.comuna == "las_condes"
        assert cleaned.price.clp == 12_400 * 37_000
        assert cleaned.m2 == 160


class StaticUFService:
    async def get_current_rate(self) -> Decimal:
        return _UF


class TestPortalScrapeStatus:
    async def test_scrape_detailed_normal_html_is_experimental_with_items(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_load())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = PortalInmobiliarioScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                start_urls=["https://portal.test/list"],
                uf_service=StaticUFService(),
            )
            report = await scraper.scrape_detailed()

        assert report["source"] == "portalinmobiliario"
        assert report["status"] == "experimental"
        assert report["reason"] is None
        assert len(report["items"]) == 2

    async def test_scrape_detailed_login_html_is_blocked(self, caplog):
        import logging

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html><a href='/login'>Iniciar sesión</a></html>")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = PortalInmobiliarioScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                start_urls=["https://portal.test/list"],
                uf_service=StaticUFService(),
            )
            with caplog.at_level(logging.WARNING):
                report = await scraper.scrape_detailed()

        assert report == {
            "source": "portalinmobiliario",
            "status": "blocked",
            "reason": "login_detected",
            "items": [],
        }
        assert any("LOGIN DETECTADO" in rec.message for rec in caplog.records)

    async def test_scrape_detailed_account_verification_html_is_blocked(self, caplog):
        import logging

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>account-verification</html>")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = PortalInmobiliarioScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                start_urls=["https://portal.test/list"],
                uf_service=StaticUFService(),
            )
            with caplog.at_level(logging.WARNING):
                report = await scraper.scrape_detailed()

        assert report["status"] == "blocked"
        assert report["reason"] == "account_verification"
        assert report["items"] == []
        assert any("ACCOUNT VERIFICATION DETECTADO" in rec.message for rec in caplog.records)

    async def test_scrape_detailed_empty_html_is_experimental_without_items(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html></html>")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = PortalInmobiliarioScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                start_urls=["https://portal.test/list"],
                uf_service=StaticUFService(),
            )
            report = await scraper.scrape_detailed()

        assert report["status"] == "experimental"
        assert report["reason"] == "no_items_parsed"
        assert report["items"] == []

    async def test_scrape_detailed_403_is_blocked(self, caplog):
        import logging

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="Forbidden")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = PortalInmobiliarioScraper(
                http_client=client,
                rate_limiter=RateLimiter(0),
                start_urls=["https://portal.test/list"],
                uf_service=StaticUFService(),
            )
            with caplog.at_level(logging.WARNING):
                report = await scraper.scrape_detailed()

        assert report["status"] == "blocked"
        assert report["reason"] == "403_forbidden"
        assert report["items"] == []
        assert any("403 FORBIDDEN" in rec.message for rec in caplog.records)
