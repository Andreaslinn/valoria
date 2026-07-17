"""Tests del parser de portalinmobiliario contra fixture HTML real."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from infrastructure.scrapers.base import RateLimiter
from infrastructure.scrapers.portalinmobiliario import (
    PortalInmobiliarioScraper,
    apply_portal_uf_conversion,
    build_portal_page_url,
    classify_portal_detail_page_state,
    parse_listing_detail_portal,
    portal_dedupe_key,
    validate_portal_rm_location,
)

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "portal_list.html"
_REAL_FIXTURE = Path(__file__).parent.parent / "fixtures" / "portal_results_real_sanitized.html"
_DETAIL_FIXTURE_1 = Path(__file__).parent.parent / "fixtures" / "portal_detail_real_1_sanitized.html"
_DETAIL_FIXTURE_2 = Path(__file__).parent.parent / "fixtures" / "portal_detail_real_2_sanitized.html"
_UF = Decimal("37000")


def _load() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


class TestPortalParser:
    def test_parses_valid_items_only(self):
        """2 válidas + 1 sin precio → 2 resultados."""
        results = PortalInmobiliarioScraper.parse_listings(_load(), uf_to_clp=_UF)
        assert len(results) == 2

    def test_uf_without_rate_keeps_items_with_zero_clp(self):
        """Sin tasa UF conservamos la publicacion y dejamos trazabilidad en metadata."""
        results = PortalInmobiliarioScraper.parse_listings(_load(), uf_to_clp=None)
        assert len(results) == 2
        assert results[0]["price_clp"] == 0
        assert results[0]["raw_metadata"]["price_uf"] == 12400.0
        assert results[0]["raw_metadata"]["price_clp_missing_reason"] == "missing_uf_rate"


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


class TestCurrentResultsLayout:
    def test_real_sanitized_fixture_parses_items(self):
        html = _REAL_FIXTURE.read_text(encoding="utf-8")
        results = PortalInmobiliarioScraper.parse_listings(html, uf_to_clp=None)
        assert len(results) > 0
        assert all(result["title"] for result in results)
        assert all(result["url"] for result in results)

    def test_ignores_empty_image_link_before_title(self):
        html = """
        <li class="ui-search-layout__item"><div class="poly-card">
          <a class="poly-component__badge poly-component__badge--image poly-component__link"
             href="/MLC-1949798443-empty-image"></a>
          <a class="poly-component__title" href="/MLC-1949798443-eco-espana-fundamenta-_JM">
            Eco España - Fundamenta
          </a>
          <div class="poly-component__price">DesdeUF3.139</div>
          <span class="poly-component__location">Domeyko 2477, Barrio República, Santiago</span>
          <ul class="poly-attributes_list">
            <li class="poly-attributes_list__item poly-attributes_list__separator">Estudio a 2 dormitorios</li>
            <li class="poly-attributes_list__item poly-attributes_list__separator">1 a 2 baños</li>
            <li class="poly-attributes_list__item poly-attributes_list__separator">27 - 58 m² útiles</li>
          </ul>
        </div></li>
        """

        results = PortalInmobiliarioScraper.parse_listings(html, uf_to_clp=None)

        assert len(results) == 1
        assert results[0]["external_id"] == "MLC-1949798443"
        assert results[0]["title"] == "Eco España - Fundamenta"
        assert results[0]["url"] == "/MLC-1949798443-eco-espana-fundamenta-_JM"
        assert results[0]["price_clp"] == 0
        assert results[0]["raw_metadata"]["price_uf"] == 3139.0
        assert results[0]["m2"] == 27
        assert results[0]["bedrooms"] == 2
        assert results[0]["bathrooms"] == 1

    def test_desde_uf_with_space_and_clp_prices_parse(self):
        html = """
        <ol>
          <li class="ui-search-layout__item"><div class="poly-card">
            <a class="poly-component__title" href="/MLC-1">UF con desde</a>
            <div class="poly-component__price">Desde UF 2.551</div>
            <span class="poly-component__location">Santiago, Región Metropolitana</span>
          </div></li>
          <li class="ui-search-layout__item"><div class="poly-card">
            <a class="poly-component__title" href="/MLC-2">CLP</a>
            <div class="poly-component__price">$128.211.801</div>
            <span class="poly-component__location">Santiago, Región Metropolitana</span>
          </div></li>
        </ol>
        """

        results = PortalInmobiliarioScraper.parse_listings(html, uf_to_clp=_UF)

        assert [r["price_clp"] for r in results] == [2551 * 37000, 128_211_801]

    def test_detailed_report_counts_discards(self):
        report = PortalInmobiliarioScraper.parse_listings_detailed(_load(), uf_to_clp=_UF)
        assert report["cards_detected"] == 3
        assert len(report["items"]) == 2
        assert [discard["reason"] for discard in report["discarded"]] == ["missing_price"]


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
    """Scripts pasivos de challenge no deben clasificarse como CAPTCHA visible."""

    def test_recaptcha_script_without_visible_challenge_returns_empty_without_warning(self, caplog):
        import logging

        shell = (
            '<!DOCTYPE html><html><head><title> </title></head><body>'
            '<script>document.cookie=`_bmc=...`;'
            'function verifyChallenge(){}</script>'
            '</body></html>'
        )
        with caplog.at_level(logging.WARNING):
            results = PortalInmobiliarioScraper.parse_listings(shell, uf_to_clp=_UF)
        assert results == []
        assert not any("CAPTCHA/BLOCK DETECTADO" in rec.message for rec in caplog.records)

    def test_large_html_not_flagged_as_challenge(self):
        """HTML grande con contenido real no debe marcarse como shell."""
        content = _load()  # fixture de ~2kb... pero tiene poly-card, pasa
        # Construir algo grande sin marcadores
        big = "<html><body>" + ("<div>content</div>" * 5000) + "</body></html>"
        # No debería disparar la detección por tamaño
        results = PortalInmobiliarioScraper.parse_listings(big, uf_to_clp=_UF)
        assert results == []  # sin items, pero sin warning

    def test_login_link_does_not_block_real_results(self):
        html = """
        <html><body>
          <a href="/login">Iniciar sesión</a>
          <li class="ui-search-layout__item"><div class="poly-card">
            <a class="poly-component__title" href="/MLC-1">Depto</a>
            <div class="poly-component__price">UF 3.139</div>
            <span class="poly-component__location">Santiago, Región Metropolitana</span>
          </div></li>
        </body></html>
        """

        results = PortalInmobiliarioScraper.parse_listings(html, uf_to_clp=None)

        assert len(results) == 1


class TestPipelineCompat:
    def test_las_condes_flows_through_clean_listing(self):
        from domain.ingestion.data_cleaning import clean_listing

        results = PortalInmobiliarioScraper.parse_listings(_load(), uf_to_clp=_UF)
        raw = dict(results[0])
        cleaned = clean_listing(raw)
        assert cleaned.comuna == "las_condes"
        assert cleaned.price.clp == 12_400 * 37_000
        assert cleaned.m2 == 160


class TestPortalDetailParser:
    @pytest.mark.parametrize("external_id", ["MLC-3225344318", "MLC-3252270364"])
    def test_parking_note_with_publication_id_is_not_parsed_as_parking(self, external_id):
        html = f"""
        <html><head><link rel="canonical" href="https://www.portalinmobiliario.com/venta/departamento/santiago-metropolitana/{external_id}-x"/></head>
        <body><h1>Departamento de prueba</h1><div class="price">UF 3.000</div>
        <p>Nota: estacionamientos y bodegas, revisar condiciones. Publicación #{external_id.split('-')[1]}</p></body></html>
        """

        detail = parse_listing_detail_portal(html, f"https://www.portalinmobiliario.com/{external_id}-x")

        assert detail["state"] == "detail"
        assert detail["parking"] is None
        assert detail["raw_metadata"]["parking_rejection_reason"] == "out_of_range"

    def test_real_detail_fixture_1_parses_refresh_fields(self):
        html = _DETAIL_FIXTURE_1.read_text(encoding="utf-8")
        detail = parse_listing_detail_portal(html, "https://www.portalinmobiliario.com/MLC-1949798443-x")

        assert detail["state"] == "detail"
        assert detail["external_id"] == "MLC-1949798443"
        assert detail["canonical_url"].startswith("https://www.portalinmobiliario.com/venta/")
        assert detail["title"] == "Eco España - Fundamenta"
        assert detail["price_uf"] == 3139.0
        assert detail["price_clp"] == 128_211_801
        assert detail["usable_area_m2"] == 27.9
        assert detail["total_area_m2"] == 30.9
        assert detail["bedrooms"] == 2
        assert detail["bathrooms"] == 2
        assert detail["comuna"] == "Santiago"
        assert detail["seller"] == "Fundamenta"
        assert detail["description"]

    def test_real_detail_fixture_2_parses_refresh_fields(self):
        html = _DETAIL_FIXTURE_2.read_text(encoding="utf-8")
        detail = parse_listing_detail_portal(html, "https://www.portalinmobiliario.com/MLC-3621878454-x")

        assert detail["state"] == "detail"
        assert detail["external_id"] == "MLC-3621878454"
        assert detail["title"] == "Edificio Centenario - Ingevec"
        assert detail["price_uf"] == 3040.0
        assert detail["price_clp"] == 124_168_167
        assert detail["usable_area_m2"] == 27.03
        assert detail["total_area_m2"] == 50.74
        assert detail["bedrooms"] == 2
        assert detail["bathrooms"] == 2
        assert detail["comuna"] == "Santiago"
        assert detail["seller"] == "Inmobiliaria Ingevec"

    def test_json_ld_product_is_positive_detail_evidence_before_passive_login(self):
        html = """
        <html><body>
          <script>const passive = "login captcha recaptcha";</script>
          <script type="application/ld+json">
            {"@context":"https://schema.org","@type":"Product","name":"Depto",
             "productID":"MLC123","offers":{"price":3139,"priceCurrency":"CLF"}}
          </script>
        </body></html>
        """

        assert classify_portal_detail_page_state(html) == "detail"
        detail = parse_listing_detail_portal(html, "https://www.portalinmobiliario.com/MLC-123-x")
        assert detail["external_id"] == "MLC-123"
        assert detail["title"] == "Depto"
        assert detail["price_uf"] == 3139.0

    def test_uf_price_provenance_keeps_displayed_clp_separate_from_runner_conversion(self):
        html = _DETAIL_FIXTURE_1.read_text(encoding="utf-8")
        detail = parse_listing_detail_portal(html, "https://www.portalinmobiliario.com/MLC-1949798443-x")

        assert detail["currency_original"] == "UF"
        assert detail["price_clp_displayed"] == 128_211_801
        assert detail["price_clp_published"] is None
        apply_portal_uf_conversion(detail, uf_to_clp=Decimal("40845"))
        assert detail["price_clp_derived"] == 128_212_455
        assert detail["uf_rate_used"] == 40845.0


class TestPortalDiscoveryHelpers:
    def test_build_page_url_preserves_scope_and_uses_portal_offset(self):
        base = "https://www.portalinmobiliario.com/venta/departamento/santiago-metropolitana"

        assert build_portal_page_url(base, 1) == base
        assert build_portal_page_url(base, 2) == base + "_Desde_49"
        assert build_portal_page_url(base + "_Desde_49", 2) == base + "_Desde_49"

    def test_dedupe_prefers_source_and_external_id_then_canonical_url(self):
        assert portal_dedupe_key(source="portalinmobiliario", external_id="MLC-5", url="https://x/a") == (
            "source_external:portalinmobiliario|MLC-5"
        )
        assert portal_dedupe_key(source="portalinmobiliario", external_id=None, url="https://x/a?track=1#top") == "url:https://x/a"

    def test_rm_validation_rejects_unknown_or_explicitly_non_metropolitan_location(self):
        assert validate_portal_rm_location({"comuna": "Ñuñoa"}) == "accepted_rm"
        assert validate_portal_rm_location({"comuna": None, "location": "Viña del Mar, Región de Valparaíso"}) == "outside_rm"
        assert validate_portal_rm_location({"comuna": None, "location": "Barrio sin comuna"}) == "unknown_comuna"


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
