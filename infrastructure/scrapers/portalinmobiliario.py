"""Scraper para portalinmobiliario.com.

Selectores confirmados contra HTML SSR real (abril 2026):
    Contenedor:   li.ui-search-layout__item > div.poly-card
    Título+link:  a.poly-component__title  (o a.poly-component__link)
    Precio:       .poly-component__price   (texto: "UF 12.400" o nested spans
                                             con andes-money-amount__currency-symbol
                                             + andes-money-amount__fraction)
    Ubicación:    .poly-component__location  (multi-segmento: "Calle, Metro, Comuna")
                  O último ítem de poly-attributes-list  ("Comuna, Región")
    Seller:       span.poly-component__seller
    Atributos:    li.poly-attributes-list__item  (con labels explícitos)

Nota sobre User-Agent: el sitio sirve SPA shell vacía a UAs no-browser.
Para obtener el HTML SSR completo, el scheduler debe usar un UA realista
tipo Chrome/Firefox (ver workers/scheduler.py).

Si la tasa UF no está disponible, las cards en UF se descartan (nunca
inventamos precios).
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, TypedDict

import httpx
from bs4 import BeautifulSoup, Tag

from config.comunas import is_known_comuna
from core.ports.uf_service import UFService
from infrastructure.scrapers.base import (
    RateLimiter,
    ScraperBase,
    ScraperResult,
    parse_price_text,
    to_clp,
    with_retry,
)

_log = logging.getLogger(__name__)

_NUMBER_RE = re.compile(r"[\d.,]+")
_MLC_ID_RE = re.compile(r"/(MLC-?\d+)")

# Marcadores del bot-challenge de Akamai. Cuando el servidor sospecha que
# somos bot, devuelve una shell ~5kb con este script en vez del HTML real.
_BOT_CHALLENGE_MARKERS = ("_bmc", "verifyChallenge", "continue-button")
_BOT_CHALLENGE_MAX_SIZE = 50_000
_LOGIN_MARKERS = ("login", "iniciar sesion", "iniciar sesión", "mercadolibre.com/jms")
_ACCOUNT_VERIFICATION_MARKERS = ("account-verification", "account verification", "verifica tu cuenta")
_CAPTCHA_MARKERS = ("captcha", "recaptcha", "hcaptcha", "verifyChallenge", "_bmc", "continue-button")

ScraperRunStatus = Literal["experimental", "blocked"]


class PortalScrapeReport(TypedDict):
    source: str
    status: ScraperRunStatus
    reason: str | None
    items: list[ScraperResult]


class PortalInmobiliarioScraper(ScraperBase):
    source_name = "portalinmobiliario"

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        rate_limiter: RateLimiter,
        start_urls: Iterable[str],
        uf_service: UFService | None = None,
    ) -> None:
        self._http = http_client
        self._rate = rate_limiter
        self._start_urls = tuple(start_urls)
        self._uf_service = uf_service

    async def scrape(self) -> list[ScraperResult]:
        report = await self.scrape_detailed()
        return report["items"]

    async def scrape_detailed(self) -> PortalScrapeReport:
        uf_rate = await self._resolve_uf_rate()

        results: list[ScraperResult] = []
        for url in self._start_urls:
            try:
                response = await self._fetch(url)
            except httpx.HTTPError as e:
                _log.warning("No se pudo descargar %s: %s", url, e)
                continue

            block_reason = detect_block_reason(
                response.text,
                status_code=response.status_code,
            )
            if block_reason is not None:
                _log_portal_block(block_reason, url)
                return {
                    "source": self.source_name,
                    "status": "blocked",
                    "reason": block_reason,
                    "items": [],
                }

            results.extend(self.parse_listings(response.text, uf_to_clp=uf_rate))

        _log.info("PortalInmobiliarioScraper: %d listings recolectados", len(results))
        return {
            "source": self.source_name,
            "status": "experimental",
            "reason": None if results else "no_items_parsed",
            "items": results,
        }

    async def _resolve_uf_rate(self) -> Decimal | None:
        if self._uf_service is None:
            return None
        try:
            return await self._uf_service.get_current_rate()
        except Exception as e:  # noqa: BLE001
            _log.warning("No se pudo resolver UF: %s. Cards en UF se descartarán.", e)
            return None

    async def _fetch(self, url: str) -> httpx.Response:
        await self._rate.wait()

        async def _do() -> httpx.Response:
            resp = await self._http.get(url)
            if resp.status_code == 403:
                return resp
            resp.raise_for_status()
            return resp

        return await with_retry(_do)

    @staticmethod
    def parse_listings(
        html: str,
        *,
        uf_to_clp: Decimal | None = None,
    ) -> list[ScraperResult]:
        block_reason = detect_block_reason(html)
        if block_reason is not None:
            _log_portal_block(block_reason, "<parser>")
            return []

        soup = BeautifulSoup(html, "lxml")
        items = soup.select("li.ui-search-layout__item")
        scraped_at = datetime.now(timezone.utc)
        results: list[ScraperResult] = []

        for item in items:
            try:
                parsed = _parse_item(item, scraped_at=scraped_at, uf_to_clp=uf_to_clp)
            except Exception as e:  # noqa: BLE001
                _log.debug("Item portal descartado por parsing error: %s", e)
                continue
            if parsed is not None:
                results.append(parsed)

        return results


# ─────────────────────────────────────────────────────────
#  Helpers de parsing
# ─────────────────────────────────────────────────────────
def _parse_item(
    item: Tag, *, scraped_at: datetime, uf_to_clp: Decimal | None
) -> ScraperResult | None:
    # Título + link — el <a> puede tener clase `poly-component__title` o
    # `poly-component__link` según el layout (SSR vs hidratado SPA).
    link = item.select_one("a.poly-component__title, a.poly-component__link")
    if link is None:
        return None
    href = link.get("href")
    title = link.get_text(strip=True)
    if not title:
        return None

    # Precio: get_text sobre el contenedor aplana tanto el layout simple
    # ("UF 12.400") como el nested (andes-money-amount__currency-symbol
    # + andes-money-amount__fraction → "UF 12.400" concatenado).
    price_el = item.select_one(".poly-component__price")
    if price_el is None:
        return None
    price_text = price_el.get_text(" ", strip=True)
    parsed_price = parse_price_text(price_text)
    if parsed_price is None:
        return None
    currency, amount = parsed_price
    price_clp = to_clp(currency, amount, uf_to_clp=uf_to_clp)
    if price_clp is None:
        return None  # UF sin tasa disponible

    # Atributos: m², bedrooms, bathrooms, parking. El último ítem puede
    # contener la comuna (layout hidratado).
    attrs = _parse_attributes(item)

    # Comuna: preferimos .poly-component__location (layout SSR), con fallback
    # al último ítem de la lista de atributos.
    comuna = _comuna_from_location(item) or attrs.get("comuna")
    if not comuna:
        return None

    seller = _text(item.select_one("span.poly-component__seller"))
    highlight = _text(item.select_one("span.poly-component__float-highlight"))
    external_id = _extract_mlc_id(href)

    raw_metadata: dict = {"currency_original": currency}
    if seller:
        raw_metadata["seller"] = seller
    if highlight:
        raw_metadata["highlight"] = highlight

    return {
        "source": "portalinmobiliario",
        "external_id": external_id,
        "title": title,
        "comuna": comuna,
        "m2": attrs.get("m2", 0),
        "bedrooms": int(attrs.get("bedrooms", 0)),
        "bathrooms": int(attrs.get("bathrooms", 0)),
        "parking": int(attrs.get("parking", 0)),
        "price_clp": int(price_clp),
        "url": href,
        "lat": None,
        "lon": None,
        "scraped_at": scraped_at,
        "raw_metadata": raw_metadata,
    }


def _comuna_from_location(item: Tag) -> str | None:
    """Extrae la comuna desde el elemento .poly-component__location.

    El texto viene multi-segmento: 'Calle / Landmark, Metro X, Las Condes'.
    Estrategia: buscar la primera comuna conocida entre los segmentos,
    lo cual es robusto a:
        · orden (comuna al principio o al final)
        · presencia de metro / calle / landmarks opcionales
    """
    loc_el = item.select_one(".poly-component__location")
    if loc_el is None:
        return None
    return _find_known_comuna(loc_el.get_text(" ", strip=True))


def _find_known_comuna(text: str) -> str | None:
    """Busca la primera comuna conocida en un string separado por comas."""
    for segment in text.split(","):
        candidate = segment.strip()
        if is_known_comuna(candidate):
            return candidate
    return None


def _parse_attributes(item: Tag) -> dict[str, float | str]:
    """Extrae m², dormitorios, baños, parking y comuna de la lista de atributos.

    Entries posibles:
        · "3 dormitorios" / "3 dorm."
        · "3 baños"
        · "160 m² útiles" / "100 m² totales"
        · "1 estacionamiento" / "2 cocheras"
        · "Las Condes, Región Metropolitana"  ← ubicación (layout hidratado)
    """
    out: dict[str, float | str] = {}
    for li in item.select("li.poly-attributes-list__item"):
        text = li.get_text(" ", strip=True)
        text_lower = text.lower()
        number = _first_number(text)

        if "m²" in text or "m2" in text_lower or "metros" in text_lower:
            if number is not None:
                out["m2"] = number
        elif "dorm" in text_lower or "hab" in text_lower:
            if number is not None:
                out["bedrooms"] = number
        elif "bañ" in text_lower:
            if number is not None:
                out["bathrooms"] = number
        elif "estac" in text_lower or "cocher" in text_lower:
            if number is not None:
                out["parking"] = number
        elif "," in text:
            # String de ubicación. Usamos el mismo heurístico que en location.
            comuna = _find_known_comuna(text)
            if comuna:
                out["comuna"] = comuna
    return out


def _first_number(text: str) -> float | None:
    m = _NUMBER_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(0).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _text(tag: Tag | None) -> str:
    return tag.get_text(strip=True) if tag else ""


def _extract_mlc_id(url: str | None) -> str | None:
    if not url:
        return None
    m = _MLC_ID_RE.search(url)
    return m.group(1) if m else None


def _looks_like_bot_challenge(html: str) -> bool:
    """Detecta la shell de Akamai que devuelve portalinmobiliario ante UAs
    sospechosos. Se identifica por tamaño (<50 kb) + marcadores característicos."""
    if len(html) > _BOT_CHALLENGE_MAX_SIZE:
        return False
    return any(marker in html for marker in _BOT_CHALLENGE_MARKERS)


def detect_block_reason(html: str, *, status_code: int | None = None) -> str | None:
    """Detecta bloqueos conocidos y retorna un reason estable.

    El comportamiento correcto ante login, verificacion de cuenta, captcha o 403
    es detener la ingesta de Portal. No intentamos evadir controles del sitio.
    """
    if status_code == 403:
        return "403_forbidden"

    text = html.lower()
    if any(marker in text for marker in _ACCOUNT_VERIFICATION_MARKERS):
        return "account_verification"
    if any(marker in text for marker in _CAPTCHA_MARKERS) or _looks_like_bot_challenge(html):
        return "captcha_or_block"
    if any(marker in text for marker in _LOGIN_MARKERS):
        return "login_detected"
    return None


def _log_portal_block(reason: str, url: str) -> None:
    labels = {
        "login_detected": "LOGIN DETECTADO",
        "account_verification": "ACCOUNT VERIFICATION DETECTADO",
        "captcha_or_block": "CAPTCHA/BLOCK DETECTADO",
        "403_forbidden": "403 FORBIDDEN",
    }
    _log.warning(
        "%s en PortalInmobiliario url=%s reason=%s. "
        "Portal queda marcado como blocked; no se intenta evadir el bloqueo.",
        labels.get(reason, "CAPTCHA/BLOCK DETECTADO"),
        url,
        reason,
    )
