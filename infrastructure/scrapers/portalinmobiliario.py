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

import json
import logging
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, TypedDict
from urllib.parse import urljoin, urlsplit, urlunsplit

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
_MLC_ANY_RE = re.compile(r"\b(MLC)-?(\d+)\b", re.IGNORECASE)

# Marcadores del bot-challenge de Akamai. Cuando el servidor sospecha que
# somos bot, devuelve una shell ~5kb con este script en vez del HTML real.
_BOT_CHALLENGE_MARKERS = ("_bmc", "verifyChallenge", "continue-button")
_BOT_CHALLENGE_MAX_SIZE = 50_000
_LOGIN_MARKERS = ("login", "iniciar sesion", "iniciar sesión", "mercadolibre.com/jms")
_ACCOUNT_VERIFICATION_MARKERS = ("account-verification", "account verification", "verifica tu cuenta")
_CAPTCHA_MARKERS = ("captcha", "recaptcha", "hcaptcha", "verifyChallenge", "_bmc", "continue-button")

ScraperRunStatus = Literal["experimental", "blocked"]
PortalPageState = Literal[
    "homepage",
    "login_page",
    "authenticated",
    "captcha_visible",
    "verification_visible",
    "blocked",
    "unexpected",
]
PortalDetailState = Literal[
    "detail",
    "login_page",
    "captcha_visible",
    "verification_visible",
    "blocked",
    "unexpected",
]


class PortalScrapeReport(TypedDict):
    source: str
    status: ScraperRunStatus
    reason: str | None
    items: list[ScraperResult]


class PortalParseDiscard(TypedDict):
    reason: str
    title: str | None
    url: str | None


class PortalParseReport(TypedDict):
    cards_detected: int
    items: list[ScraperResult]
    discarded: list[PortalParseDiscard]


class PortalListingDetail(TypedDict, total=False):
    source: str
    state: PortalDetailState
    external_id: str | None
    title: str | None
    price_currency: str | None
    currency_original: str | None
    price_amount: float | int | None
    price_uf: float | None
    price_clp: int | None
    price_clp_published: int | None
    price_clp_displayed: int | None
    price_clp_derived: int | None
    uf_rate_used: float | None
    usable_area_m2: float | None
    built_area_m2: float | None
    total_area_m2: float | None
    land_area_m2: float | None
    bedrooms: int | None
    bathrooms: int | None
    parking: int | None
    common_expenses_clp: int | None
    description: str | None
    comuna: str | None
    location: str | None
    seller: str | None
    canonical_url: str | None
    url: str
    raw_metadata: dict[str, Any]


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
        return PortalInmobiliarioScraper.parse_listings_detailed(
            html,
            uf_to_clp=uf_to_clp,
        )["items"]

    @staticmethod
    def parse_listings_detailed(
        html: str,
        *,
        uf_to_clp: Decimal | None = None,
    ) -> PortalParseReport:
        block_reason = detect_block_reason(html)
        if block_reason is not None:
            _log_portal_block(block_reason, "<parser>")
            return {"cards_detected": 0, "items": [], "discarded": []}

        soup = BeautifulSoup(html, "lxml")
        items = soup.select("li.ui-search-layout__item")
        scraped_at = datetime.now(timezone.utc)
        results: list[ScraperResult] = []
        discarded: list[PortalParseDiscard] = []

        for item in items:
            try:
                parsed, reason = _parse_item(item, scraped_at=scraped_at, uf_to_clp=uf_to_clp)
            except Exception as e:  # noqa: BLE001
                _log.debug("Item portal descartado por parsing error: %s", e)
                discarded.append(_discard("parse_error", item))
                continue
            if parsed is not None:
                results.append(parsed)
            elif reason is not None:
                discarded.append(_discard(reason, item))

        return {
            "cards_detected": len(items),
            "items": results,
            "discarded": discarded,
        }


# ─────────────────────────────────────────────────────────
#  Helpers de parsing
# ─────────────────────────────────────────────────────────
def _parse_item(
    item: Tag, *, scraped_at: datetime, uf_to_clp: Decimal | None
) -> tuple[ScraperResult | None, str | None]:
    # Título + link — el <a> puede tener clase `poly-component__title` o
    # `poly-component__link` según el layout (SSR vs hidratado SPA).
    link = _find_title_link(item)
    if link is None:
        return None, "missing_title_link"
    href = link.get("href")
    title = link.get_text(strip=True)
    if not title:
        return None, "missing_title"

    # Precio: get_text sobre el contenedor aplana tanto el layout simple
    # ("UF 12.400") como el nested (andes-money-amount__currency-symbol
    # + andes-money-amount__fraction → "UF 12.400" concatenado).
    price_el = item.select_one(".poly-component__price")
    if price_el is None:
        return None, "missing_price"
    price_text = _normalize_price_text(price_el.get_text(" ", strip=True))
    parsed_price = parse_price_text(price_text)
    if parsed_price is None:
        return None, "invalid_price"
    currency, amount = parsed_price
    price_clp = to_clp(currency, amount, uf_to_clp=uf_to_clp)

    # Atributos: m², bedrooms, bathrooms, parking. El último ítem puede
    # contener la comuna (layout hidratado).
    attrs = _parse_attributes(item)

    # Comuna: preferimos .poly-component__location (layout SSR), con fallback
    # al último ítem de la lista de atributos.
    comuna = _comuna_from_location(item) or attrs.get("comuna")
    if not comuna:
        return None, "missing_comuna"

    seller = _text(item.select_one("span.poly-component__seller"))
    highlight = _text(item.select_one("span.poly-component__float-highlight"))
    external_id = _extract_mlc_id(href)

    raw_metadata: dict = {"currency_original": currency}
    if currency == "UF":
        raw_metadata["price_uf"] = float(amount)
        if price_clp is None:
            raw_metadata["price_clp_missing_reason"] = "missing_uf_rate"
            raw_metadata["price_clp_provenance"] = "not_converted"
        else:
            raw_metadata["price_clp_provenance"] = "converted"
            raw_metadata["uf_rate_used"] = float(uf_to_clp) if uf_to_clp is not None else None
    else:
        raw_metadata["price_clp_provenance"] = "published"
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
        "price_clp": int(price_clp) if price_clp is not None else 0,
        "url": href,
        "lat": None,
        "lon": None,
        "scraped_at": scraped_at,
        "raw_metadata": raw_metadata,
    }, None


def _find_title_link(item: Tag) -> Tag | None:
    for link in item.select("a.poly-component__title"):
        if link.get_text(strip=True):
            return link
    for link in item.select("a.poly-component__link"):
        if link.get_text(strip=True):
            return link
    for link in item.select("a[href*='MLC']"):
        if link.get_text(strip=True):
            return link
    return None


def _normalize_price_text(text: str) -> str:
    return re.sub(r"^\s*desde\s*", "", text or "", flags=re.IGNORECASE).strip()


def _discard(reason: str, item: Tag) -> PortalParseDiscard:
    link = _find_title_link(item)
    fallback_link = item.select_one("a[href]")
    chosen = link or fallback_link
    return {
        "reason": reason,
        "title": link.get_text(strip=True) if link else None,
        "url": str(chosen.get("href")) if chosen else None,
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
    for li in item.select("li.poly-attributes-list__item, li.poly-attributes_list__item"):
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
    token = m.group(0)
    if not any(char.isdigit() for char in token):
        return None
    try:
        return _parse_measure_number(token)
    except ValueError:
        return None


def _parse_measure_number(token: str) -> float:
    if "," in token:
        return float(token.replace(".", "").replace(",", "."))
    if token.count(".") == 1:
        integer_part, decimal_part = token.split(".", 1)
        if len(decimal_part) <= 2:
            return float(token)
    return float(token.replace(".", ""))


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
    if status_code == 429:
        return "rate_limited"

    state = classify_portal_page_state(html, status_code=status_code)
    if state == "verification_visible":
        return "account_verification"
    if state == "captcha_visible":
        return "captcha_or_block"
    if state == "login_page":
        return "login_detected"
    return None


def classify_portal_page_state(html: str, *, status_code: int | None = None) -> PortalPageState:
    """Classify Portal HTML without treating passive scripts as visible CAPTCHA.

    Browser smoke tests add a stricter Playwright-visible pass. This pure HTML
    fallback deliberately ignores generic captcha words inside scripts/resources.
    """
    if status_code in {403, 429}:
        return "blocked"

    soup = BeautifulSoup(html or "", "lxml")
    text = _visible_text(soup)
    normalized_text = _normalize_spaces(text.lower())

    if _has_visible_captcha_markup(soup) or _has_visible_captcha_text(normalized_text):
        return "captcha_visible"
    if _has_visible_verification_text(normalized_text):
        return "verification_visible"
    if _has_results(html):
        return "authenticated"
    if _looks_like_login_page(soup, normalized_text):
        return "login_page"
    if _looks_like_homepage(soup, normalized_text):
        return "homepage"
    return "unexpected"


def extract_portal_detail_urls(
    html: str,
    *,
    base_url: str = "https://www.portalinmobiliario.com",
    limit: int = 2,
) -> list[str]:
    """Extract at most ``limit`` listing detail URLs from a results page."""
    if limit <= 0:
        return []
    soup = BeautifulSoup(html, "lxml")
    urls: list[str] = []
    seen: set[str] = set()
    for link in soup.select(
        "li.ui-search-layout__item a.poly-component__title, "
        "li.ui-search-layout__item a.poly-component__link"
    ):
        href = str(link.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(base_url, href)
        parsed = urlsplit(absolute)
        if "portalinmobiliario.com" not in parsed.netloc and "mercadolibre.cl" not in parsed.netloc:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        urls.append(absolute)
        if len(urls) >= limit:
            break
    return urls


_PORTAL_PAGE_OFFSET_RE = re.compile(r"_Desde_\d+$", re.IGNORECASE)


def build_portal_page_url(url: str, page: int, *, page_size: int = 48) -> str:
    """Build a Portal result-page URL without changing the target scope.

    Portal uses ``_Desde_<one-based offset>`` in the path. The first page is
    the target URL itself; the helper deliberately does not invent query
    parameters or broaden a comuna target.
    """
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    parts = urlsplit(url)
    path = _PORTAL_PAGE_OFFSET_RE.sub("", parts.path.rstrip("/"))
    if page > 1:
        path = f"{path}_Desde_{((page - 1) * page_size) + 1}"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def portal_dedupe_key(*, source: str, external_id: str | None, url: str | None) -> str | None:
    """Stable in-run key: source+external id, with canonical URL fallback."""
    if external_id:
        return f"source_external:{source}|{external_id.upper()}"
    if url:
        parts = urlsplit(url)
        canonical = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
        return f"url:{canonical}"
    return None


def validate_portal_rm_location(detail: PortalListingDetail) -> Literal[
    "accepted_rm", "unknown_comuna", "outside_rm"
]:
    """Accept only communes in the project's canonical RM catalogue.

    ``config.comunas`` is intentionally the sole catalogue. A listing without
    a recognised comuna is rejected instead of guessing from a neighbourhood
    or target URL. An explicit non-metropolitan region is labelled separately.
    """
    comuna = _clean_text(detail.get("comuna"))
    if comuna and is_known_comuna(comuna):
        return "accepted_rm"
    location = _strip_accents(
        " ".join(
            str(value or "")
            for value in (detail.get("location"), detail.get("canonical_url"), detail.get("url"))
        )
    ).lower()
    if "region" in location and "metropolitana" not in location:
        return "outside_rm"
    return "unknown_comuna"


def apply_portal_uf_conversion(
    detail: PortalListingDetail,
    *,
    uf_to_clp: Decimal | None,
) -> PortalListingDetail:
    """Record a runner-side UF conversion without relabelling the source price."""
    if detail.get("currency_original") != "UF" or detail.get("price_uf") is None or uf_to_clp is None:
        return detail
    converted = Decimal(str(detail["price_uf"])) * uf_to_clp
    detail["price_clp_derived"] = int(converted)
    detail["uf_rate_used"] = float(uf_to_clp)
    detail["raw_metadata"]["price_clp_derived"] = int(converted)
    detail["raw_metadata"]["uf_rate_used"] = float(uf_to_clp)
    detail["raw_metadata"]["price_clp_derived_provenance"] = "runner_uf_conversion"
    return detail


def parse_listing_detail_portal(html: str, url: str) -> PortalListingDetail:
    """Parse a Portal detail page fetched over HTTP.

    Data sources are applied in this order: JSON-LD, embedded Nordic state,
    metadata, and finally visible DOM text.
    """
    soup = BeautifulSoup(html or "", "lxml")
    state = classify_portal_detail_page_state(html)
    detail: PortalListingDetail = {
        "source": "portalinmobiliario",
        "state": state,
        "external_id": _extract_mlc_id(url),
        "title": None,
        "price_currency": None,
        "currency_original": None,
        "price_amount": None,
        "price_uf": None,
        "price_clp": None,
        "price_clp_published": None,
        "price_clp_displayed": None,
        "price_clp_derived": None,
        "uf_rate_used": None,
        "usable_area_m2": None,
        "built_area_m2": None,
        "total_area_m2": None,
        "land_area_m2": None,
        "bedrooms": None,
        "bathrooms": None,
        "parking": None,
        "common_expenses_clp": None,
        "description": None,
        "comuna": None,
        "location": None,
        "seller": None,
        "canonical_url": _canonical_url(soup) or url,
        "url": url,
        "raw_metadata": {"sources": []},
    }

    _apply_json_ld_detail(detail, soup)
    state_data = _extract_nordic_initial_state(soup)
    if state_data:
        _apply_embedded_state_detail(detail, state_data)
    _apply_meta_detail(detail, soup)
    _apply_dom_detail(detail, soup)

    canonical = detail.get("canonical_url") or url
    if not detail.get("external_id"):
        detail["external_id"] = _extract_mlc_id(str(canonical)) or _extract_mlc_id(str(detail.get("url")))
    if detail.get("location") and not detail.get("comuna"):
        detail["comuna"] = _find_known_comuna(str(detail["location"]))

    return detail


def classify_portal_detail_page_state(html: str, *, status_code: int | None = None) -> PortalDetailState:
    if status_code in {403, 429}:
        return "blocked"
    soup = BeautifulSoup(html or "", "lxml")
    if _has_detail_positive_evidence(soup):
        return "detail"
    text = _normalize_spaces(_visible_text(soup).lower())
    if _has_visible_captcha_markup(soup) or _has_visible_captcha_text(text):
        return "captcha_visible"
    if _has_visible_verification_text(text):
        return "verification_visible"
    if _looks_like_login_page(soup, text):
        return "login_page"
    return "unexpected"


def _has_detail_positive_evidence(soup: BeautifulSoup) -> bool:
    if soup.select_one("script[type='application/ld+json']"):
        for obj in _json_ld_objects(soup):
            if isinstance(obj, dict) and obj.get("@type") == "Product" and (obj.get("offers") or obj.get("productID")):
                return True
    if _extract_nordic_initial_state(soup):
        return True
    has_title = soup.select_one("h1") is not None
    has_price = soup.select_one(".andes-money-amount, .ui-pdp-price, [class*='price']") is not None
    canonical = _canonical_url(soup)
    return bool(has_title and (has_price or (canonical and "/venta/" in canonical)))


def _apply_json_ld_detail(detail: PortalListingDetail, soup: BeautifulSoup) -> None:
    for obj in _json_ld_objects(soup):
        if not isinstance(obj, dict) or obj.get("@type") != "Product":
            continue
        _set_if_missing(detail, "title", _clean_text(obj.get("name")))
        external_id = _normalize_mlc_id(obj.get("productID") or obj.get("sku"))
        _set_if_missing(detail, "external_id", external_id)
        offers = obj.get("offers")
        if isinstance(offers, dict):
            currency = _portal_currency(offers.get("priceCurrency"))
            amount = _decimal_from_any(offers.get("price"))
            if currency and amount is not None:
                _set_price(detail, currency, amount)
            _set_if_missing(detail, "canonical_url", _clean_text(offers.get("url")))
        detail["raw_metadata"]["sources"].append("json_ld")
        break


def _apply_embedded_state_detail(detail: PortalListingDetail, state: dict[str, Any]) -> None:
    _set_if_missing(detail, "external_id", _normalize_mlc_id(state.get("id")))
    components = _components_by_id(state.get("components"))

    header = components.get("header")
    if isinstance(header, dict):
        _set_if_missing(detail, "title", _clean_text(header.get("title")))
        link_label = header.get("link_label")
        if isinstance(link_label, dict):
            label_text = _clean_text((link_label.get("label") or {}).get("text"))
            if label_text and "publicado" in _strip_accents(label_text).lower():
                values = ((link_label.get("label") or {}).get("values") or {})
                action = values.get("action")
                if isinstance(action, dict):
                    _set_if_missing(detail, "seller", _clean_text((action.get("label") or {}).get("text")))

    price = components.get("price")
    if isinstance(price, dict):
        price_obj = price.get("price")
        if isinstance(price_obj, dict):
            currency = _portal_currency(price_obj.get("currency_id") or price_obj.get("currency_symbol"))
            amount = _decimal_from_any(price_obj.get("value"))
            if currency and amount is not None:
                _set_price(detail, currency, amount)
        for subtitle in price.get("subtitles") or []:
            if not isinstance(subtitle, dict):
                continue
            for value in ((subtitle.get("values") or {}).values()):
                if isinstance(value, dict):
                    currency = _portal_currency(value.get("currency_id") or value.get("currency_symbol"))
                    amount = _decimal_from_any(value.get("value"))
                    if currency == "CLP" and amount is not None:
                        clp_amount = int(amount)
                        # Portal renders this as a secondary equivalence for UF
                        # listings. Keep the legacy price_clp field, but never
                        # present it as the originally published currency.
                        if detail.get("currency_original") == "UF":
                            detail["price_clp"] = clp_amount
                            detail["price_clp_displayed"] = clp_amount
                            detail["raw_metadata"]["price_clp_provenance"] = "displayed_secondary"
                        else:
                            detail["price_clp"] = clp_amount
                            detail["price_clp_published"] = clp_amount
                            detail["raw_metadata"]["price_clp_provenance"] = "published"

    seller = components.get("seller_profile") or state.get("seller_profile")
    if isinstance(seller, dict):
        seller_title = (((seller.get("seller_name") or {}).get("title") or {}).get("text"))
        _set_if_missing(detail, "seller", _clean_text(seller_title))
        for info in seller.get("bottom_extra_info") or []:
            title = _clean_text(((info.get("title") or {}).get("text")) if isinstance(info, dict) else None)
            subtitles = info.get("subtitles") if isinstance(info, dict) else None
            if title and "codigo" in _strip_accents(title).lower() and subtitles:
                code = _clean_text(subtitles[0].get("text") if isinstance(subtitles[0], dict) else None)
                if code:
                    detail["raw_metadata"]["property_code"] = code

    location = components.get("location")
    if isinstance(location, dict):
        rows = location.get("content_rows") or []
        for row in rows:
            if isinstance(row, dict):
                value = _clean_text(((row.get("title") or {}).get("text")))
                if value:
                    _set_if_missing(detail, "location", value)
                    break
        map_location = ((location.get("map_info") or {}).get("location") or {})
        if map_location:
            detail["raw_metadata"]["lat"] = _decimal_string(map_location.get("latitude"))
            detail["raw_metadata"]["lon"] = _decimal_string(map_location.get("longitude"))

    tech = components.get("technical_specifications")
    if isinstance(tech, dict):
        _apply_specs(detail, tech.get("specs") or [])

    highlighted = components.get("highlighted_specs_res")
    if isinstance(highlighted, dict):
        labels = []
        for attr in highlighted.get("attributes") or highlighted.get("content_rows") or []:
            if isinstance(attr, dict):
                value = _clean_text(((attr.get("label") or {}).get("text")))
                if value:
                    labels.append(value)
                    _apply_attribute_text(detail, value)
        if labels:
            detail["raw_metadata"]["highlighted_specs"] = labels

    models = components.get("quotable_models")
    if isinstance(models, dict):
        model_labels: list[str] = []
        for model in models.get("models") or []:
            if not isinstance(model, dict):
                continue
            for attr in model.get("attributes") or []:
                if not isinstance(attr, dict):
                    continue
                value = _clean_text(((attr.get("label") or {}).get("text")))
                if value:
                    model_labels.append(value)
                    _apply_attribute_text(detail, value)
        if model_labels:
            detail["raw_metadata"]["model_specs"] = model_labels

    description = components.get("description")
    if isinstance(description, dict):
        _set_if_missing(detail, "description", _clean_text(description.get("content")))

    breadcrumb = state.get("breadcrumb") or {}
    crumbs = breadcrumb.get("itemListElement") if isinstance(breadcrumb, dict) else None
    if isinstance(crumbs, list):
        names = [
            _clean_text(((crumb.get("item") or {}).get("name")) if isinstance(crumb, dict) else None)
            for crumb in crumbs
        ]
        for name in reversed([name for name in names if name]):
            if is_known_comuna(name):
                _set_if_missing(detail, "comuna", name)
                break
        detail["raw_metadata"]["breadcrumbs"] = names

    detail["raw_metadata"]["sources"].append("embedded_state")


def _apply_meta_detail(detail: PortalListingDetail, soup: BeautifulSoup) -> None:
    _set_if_missing(detail, "canonical_url", _canonical_url(soup))
    og_title = _meta_content(soup, 'meta[property="og:title"]')
    if og_title:
        if not detail.get("title"):
            detail["title"] = og_title.split(" - UF ")[0].split(" - $")[0].strip()
        if not detail.get("price_currency"):
            parsed = parse_price_text(_normalize_price_text(og_title.rsplit(" - ", 1)[-1]))
            if parsed:
                _set_price(detail, parsed[0], parsed[1])
    _set_if_missing(detail, "description", _meta_content(soup, 'meta[name="description"]'))
    if og_title or _meta_content(soup, 'meta[name="description"]'):
        detail["raw_metadata"]["sources"].append("metadata")


def _apply_dom_detail(detail: PortalListingDetail, soup: BeautifulSoup) -> None:
    h1 = soup.select_one("h1")
    _set_if_missing(detail, "title", _clean_text(h1.get_text(" ", strip=True)) if h1 else None)
    text = _visible_text(soup)
    if not detail.get("price_currency"):
        match = re.search(r"(UF\s*[\d.,]+|\$\s*[\d.,]+)", text, flags=re.IGNORECASE)
        if match:
            parsed = parse_price_text(_normalize_price_text(match.group(1)))
            if parsed:
                _set_price(detail, parsed[0], parsed[1])
    for chunk in re.split(r"\s{2,}|\n", text):
        _apply_attribute_text(detail, chunk)
    if h1 or text:
        detail["raw_metadata"]["sources"].append("dom")


def _json_ld_objects(soup: BeautifulSoup) -> list[Any]:
    out: list[Any] = []
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list):
            out.extend(obj)
        else:
            out.append(obj)
    return out


def _extract_nordic_initial_state(soup: BeautifulSoup) -> dict[str, Any] | None:
    script = soup.select_one("script#__NORDIC_RENDERING_CTX__")
    if script is None:
        return None
    raw = script.string or script.get_text()
    try:
        data = json.loads(_extract_first_json_object(raw))
    except (ValueError, json.JSONDecodeError):
        return None
    state = (((data.get("appProps") or {}).get("pageProps") or {}).get("initialState"))
    return state if isinstance(state, dict) else None


def _extract_first_json_object(raw: str) -> str:
    start = raw.find("{")
    if start < 0:
        raise ValueError("no json object")
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(raw)):
        char = raw[idx]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw[start : idx + 1]
    raise ValueError("unterminated json object")


def _components_by_id(components: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            comp_id = value.get("id")
            if isinstance(comp_id, str):
                out.setdefault(comp_id, value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(components)
    return out


def _apply_specs(detail: PortalListingDetail, specs: list[Any]) -> None:
    raw_specs: dict[str, str] = {}
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        for attr in spec.get("attributes") or []:
            if not isinstance(attr, dict):
                continue
            label = _clean_text(attr.get("id") or attr.get("name") or attr.get("title"))
            text = _clean_text(attr.get("text") or _nested_value_text(attr))
            if not text:
                continue
            if label:
                raw_specs[label] = text
                _apply_labeled_attribute(detail, label, text)
            else:
                _apply_attribute_text(detail, text)
    if raw_specs:
        detail["raw_metadata"]["technical_specs"] = raw_specs


def _apply_labeled_attribute(detail: PortalListingDetail, label: str, text: str) -> None:
    normalized = _strip_accents(label).lower()
    if "util" in normalized:
        _set_if_missing(detail, "usable_area_m2", _first_number(text))
        detail["raw_metadata"]["usable_area_raw"] = text
    elif "constru" in normalized:
        _set_if_missing(detail, "built_area_m2", _first_number(text))
        detail["raw_metadata"]["built_area_raw"] = text
    elif "total" in normalized:
        _set_if_missing(detail, "total_area_m2", _first_number(text))
        detail["raw_metadata"]["total_area_raw"] = text
    elif "terreno" in normalized:
        _set_if_missing(detail, "land_area_m2", _first_number(text))
        detail["raw_metadata"]["land_area_raw"] = text
    elif "dorm" in normalized or "habit" in normalized:
        _set_if_missing(detail, "bedrooms", _max_int(text))
        detail["raw_metadata"]["bedrooms_raw"] = text
    elif "bano" in normalized:
        _set_if_missing(detail, "bathrooms", _max_int(text))
        detail["raw_metadata"]["bathrooms_raw"] = text
    elif "estacionamiento" in normalized or "cocher" in normalized:
        _set_parking_if_valid(detail, text)
    elif "gasto" in normalized:
        _set_if_missing(detail, "common_expenses_clp", _money_int(text))
        detail["raw_metadata"]["common_expenses_raw"] = text


def _apply_attribute_text(detail: PortalListingDetail, text: str) -> None:
    clean = _clean_text(text)
    if not clean:
        return
    normalized = _strip_accents(clean).lower()
    if "m2" in normalized or "m²" in clean or "metros" in normalized:
        if "util" in normalized:
            _set_if_missing(detail, "usable_area_m2", _first_number(clean))
            detail["raw_metadata"].setdefault("usable_area_raw", clean)
        elif "total" in normalized:
            _set_if_missing(detail, "total_area_m2", _first_number(clean))
            detail["raw_metadata"].setdefault("total_area_raw", clean)
        elif "terreno" in normalized:
            _set_if_missing(detail, "land_area_m2", _first_number(clean))
            detail["raw_metadata"].setdefault("land_area_raw", clean)
        else:
            _set_if_missing(detail, "usable_area_m2", _first_number(clean))
            detail["raw_metadata"].setdefault("usable_area_raw", clean)
    if "dorm" in normalized or "habit" in normalized:
        _set_if_missing(detail, "bedrooms", _max_int(clean))
        detail["raw_metadata"].setdefault("bedrooms_raw", clean)
    if "bano" in normalized:
        _set_if_missing(detail, "bathrooms", _max_int(clean))
        detail["raw_metadata"].setdefault("bathrooms_raw", clean)
    if "estacionamiento" in normalized or "cocher" in normalized:
        _set_parking_if_valid(detail, clean)
    if "gasto" in normalized and "comun" in normalized:
        _set_if_missing(detail, "common_expenses_clp", _money_int(clean))
        detail["raw_metadata"].setdefault("common_expenses_raw", clean)


def _set_price(detail: PortalListingDetail, currency: str, amount: Decimal) -> None:
    detail["price_currency"] = currency
    detail["currency_original"] = currency
    detail["price_amount"] = int(amount) if amount == amount.to_integral_value() else float(amount)
    if currency == "UF":
        detail["price_uf"] = float(amount)
        detail["raw_metadata"]["price_clp_provenance"] = "not_converted"
    elif currency == "CLP":
        clp_amount = int(amount)
        detail["price_clp"] = clp_amount
        detail["price_clp_published"] = clp_amount
        detail["raw_metadata"]["price_clp_provenance"] = "published"


def _portal_currency(value: Any) -> str | None:
    raw = str(value or "").upper()
    if raw in {"CLF", "UF"}:
        return "UF"
    if raw in {"CLP", "$"}:
        return "CLP"
    return None


def _canonical_url(soup: BeautifulSoup) -> str | None:
    link = soup.select_one("link[rel='canonical']")
    if link and link.get("href"):
        return str(link.get("href"))
    return _meta_content(soup, 'meta[property="og:url"]')


def _meta_content(soup: BeautifulSoup, selector: str) -> str | None:
    tag = soup.select_one(selector)
    if tag is None:
        return None
    return _clean_text(tag.get("content"))


def _set_if_missing(target: dict[str, Any], key: str, value: Any) -> None:
    if target.get(key) in (None, "") and value not in (None, ""):
        target[key] = value


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = _normalize_spaces(str(value))
    return text or None


def _decimal_from_any(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    return parse_spanish_number_safe(str(value))


def _decimal_string(value: Any) -> str | None:
    parsed = _decimal_from_any(value)
    return str(parsed) if parsed is not None else None


def parse_spanish_number_safe(value: str) -> Decimal | None:
    parsed = parse_price_text(value)
    if parsed is not None:
        return parsed[1]
    number = _NUMBER_RE.search(value)
    if number is None:
        return None
    try:
        return Decimal(number.group(0).replace(".", "").replace(",", "."))
    except Exception:  # noqa: BLE001
        return None


def _money_int(text: str) -> int | None:
    parsed = parse_price_text(_normalize_price_text(text))
    if parsed is not None:
        return int(parsed[1])
    number = parse_spanish_number_safe(text)
    return int(number) if number is not None else None


def _max_int(text: str) -> int | None:
    numbers = [
        int(float(n.replace(".", "").replace(",", ".")))
        for n in _NUMBER_RE.findall(text)
        if any(char.isdigit() for char in n)
    ]
    if not numbers:
        if "estudio" in _strip_accents(text).lower():
            return 0
        return None
    return max(numbers)


def _set_parking_if_valid(detail: PortalListingDetail, text: str) -> None:
    """Accept only a plausible parking count from an attribute-like text.

    Detail DOM fallbacks can contain the whole page after a note about parking,
    including the publication id.  That id is not a parking count and must not
    reach the integer database column as one.
    """
    value = _max_int(text)
    if value is None:
        return
    if 0 <= value <= 100:
        _set_if_missing(detail, "parking", value)
        detail["raw_metadata"].setdefault("parking_raw", text)
        return
    detail["raw_metadata"].setdefault("parking_raw_rejected", text)
    detail["raw_metadata"].setdefault("parking_rejection_reason", "out_of_range")


def _nested_value_text(value: dict[str, Any]) -> str | None:
    values = value.get("values")
    if not isinstance(values, dict):
        return None
    for child in values.values():
        if isinstance(child, dict):
            text = _clean_text(child.get("text"))
            if text:
                return text
    return None


def _normalize_mlc_id(value: Any) -> str | None:
    if value is None:
        return None
    match = _MLC_ANY_RE.search(str(value))
    if not match:
        return None
    return f"MLC-{match.group(2)}"


def _strip_accents(value: str) -> str:
    return (
        value.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("Á", "A")
        .replace("É", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Ú", "U")
        .replace("ñ", "n")
        .replace("Ñ", "N")
    )


def _has_results(html: str) -> bool:
    soup = BeautifulSoup(html or "", "lxml")
    return bool(soup.select_one("li.ui-search-layout__item .poly-card, li.ui-search-layout__item a.poly-component__title"))


def _visible_text(soup: BeautifulSoup) -> str:
    for hidden in soup.select("script, style, noscript, template, [hidden], [aria-hidden='true']"):
        hidden.decompose()
    return soup.get_text(" ", strip=True)


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _is_hidden_tag(tag: Tag) -> bool:
    if tag.has_attr("hidden"):
        return True
    if str(tag.get("aria-hidden", "")).lower() == "true":
        return True
    style = str(tag.get("style", "")).replace(" ", "").lower()
    return "display:none" in style or "visibility:hidden" in style or "opacity:0" in style


def _has_visible_captcha_markup(soup: BeautifulSoup) -> bool:
    for tag in soup.select("iframe, div, section, form"):
        if _is_hidden_tag(tag):
            continue
        value = " ".join(
            str(tag.get(attr, ""))
            for attr in ("src", "id", "class", "title", "name", "data-testid")
        ).lower()
        if any(marker in value for marker in ("recaptcha", "hcaptcha", "captcha")):
            return True
    return False


def _has_visible_captcha_text(text: str) -> bool:
    patterns = (
        "completa la verificacion",
        "completa la verificación",
        "verifica que eres humano",
        "verify you are human",
        "complete the captcha",
        "resolver el captcha",
    )
    return any(pattern in text for pattern in patterns)


def _has_visible_verification_text(text: str) -> bool:
    patterns = (
        "verifica tu cuenta",
        "verificacion telefonica",
        "verificación telefónica",
        "codigo de verificacion",
        "código de verificación",
        "account verification",
        "account-verification",
        "mfa",
    )
    return any(pattern in text for pattern in patterns)


def _looks_like_login_page(soup: BeautifulSoup, text: str) -> bool:
    if soup.select_one("input[type='password'], input[name='password']"):
        return True
    login_text = any(marker in text for marker in ("iniciar sesion", "iniciar sesión", "ingresa a tu cuenta"))
    has_email = soup.select_one("input[type='email'], input[name='email'], input[name='login']") is not None
    login_links = soup.select_one("a[href*='login'], a[href*='/lgz/'], a[href*='mercadolibre.com/jms']") is not None
    return login_text and (has_email or login_links)


def _looks_like_homepage(soup: BeautifulSoup, text: str) -> bool:
    if soup.select_one("body") is None:
        return False
    homepage_text = any(
        marker in text
        for marker in (
            "portal inmobiliario",
            "propiedades",
            "comprar",
            "arrendar",
        )
    )
    has_search = soup.select_one("input[type='search'], input[placeholder*='Buscar'], form[action*='search']") is not None
    return homepage_text or has_search


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
