"""Scraper para yapo.cl.

Selectores verificados contra la estructura real del sitio (abril 2026):
    Contenedor:    div.d3-ad-tile
    Título:        h2.d3-ad-tile__title
    Ubicación:     .d3-ad-tile__location span
    Precio:        .d3-ad-tile__price   (puede venir en CLP "$260.000.000"
                                         o UF "UF8.200,00")
    Detalles:      ul.d3-ad-tile__details li  (sin labels — orden posicional:
                                               m², dormitorios, baños, estac.)
    Link detalle:  a.d3-ad-tile__description[href]
    External ID:   último segmento numérico del href

Notas:
    · Yapo muestra resultados nacionales. Comunas fuera del catálogo caen
      en validación del pipeline — es el comportamiento correcto.
    · Si el precio viene en UF y no hay UFService disponible, la card se
      descarta (mejor perder el dato que persistir un precio incorrecto).
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NotRequired, TypedDict
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup, Tag

from config.comunas import is_known_comuna, normalize_comuna
from config.constants import (
    MIN_SALE_PRICE_CLP,
    PROPERTY_TYPES,
    RM_COMUNA_ALIASES,
    YAPO_MAX_PAGES,
    YAPO_MAX_PAGES_HARD_LIMIT,
    YAPO_SEARCH_BASE_URL,
    YAPO_TARGETS,
)
from core.ports.uf_service import UFService
from domain.geocoding.geo_signals import enrich_raw_metadata_with_geo_signals
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
_URL_ID_RE = re.compile(r"/(\d+)(?:/|\?|#|$)")
_PAGE_SUFFIX_RE = re.compile(r"\.\d+$")
_SLOT_ORDER = ("bedrooms", "bathrooms", "parking")
_STREET_MARKERS = r"calle|av\.?|avenida|pasaje|camino|diagonal"
_EXPLICIT_STREET_RE = re.compile(
    rf"\b({_STREET_MARKERS})\s+([A-Za-zÁÉÍÓÚÑáéíóúñ. ]{{2,60}})(?:\s+(\d{{1,5}}))?",
    re.IGNORECASE,
)
_INTERSECTION_RE = re.compile(
    r"\b([A-Za-zÁÉÍÓÚÑáéíóúñ. ]{3,45})\s+(?:/|con|esquina)\s+"
    r"([A-Za-zÁÉÍÓÚÑáéíóúñ. ]{3,45})\b",
    re.IGNORECASE,
)
_METRO_RE = re.compile(
    r"\b(?:a\s+pasos\s+de\s+|cerca\s+de\s+|sector\s+)?(?:metro|estaci[oó]n)\s+"
    r"([A-Za-zÁÉÍÓÚÑáéíóúñ ]{2,45})",
    re.IGNORECASE,
)
_DETAIL_LOCATION_NOISE = {
    "estrategica",
    "estrategico",
    "excelente",
    "oportunidad",
    "amplia",
    "amplio",
    "comoda",
    "comodo",
    "central",
    "ubicacion",
    "sector",
    "venta",
    "departamento",
    "depto",
    "dpto",
}
_ALIAS_TO_CANONICAL_COMUNA = {
    alias: normalize_comuna(canonical)
    for alias, canonical in RM_COMUNA_ALIASES.items()
}
_KNOWN_STREET_SNIPPETS = (
    "Antonio Varas",
    "Fray Camilo Henriquez",
    "Fray Camilo Henríquez",
    "Blest Gana",
    "Lord Cochrane",
    "Portugal",
    "Santa Isabel",
    "Vicuña Mackenna",
    "Vicuna Mackenna",
    "Pedro de Valdivia",
    "Irarrazaval",
    "Irarrázaval",
    "San Martín",
    "San Martin",
    "Cal y Canto",
    "Los Leones",
    "Tobalaba",
    "Manquehue",
    "Escuela Militar",
)
_TITLE_STOP_WORDS = {
    "departamento",
    "depto",
    "dpto",
    "venta",
    "vende",
    "oportunidad",
    "comuna",
    "dormitorio",
    "dorm",
    "bano",
    "baño",
    "estacionamiento",
    "bodega",
    "uf",
}


class YapoTarget(TypedDict):
    label: str
    query: str
    scope: str
    max_pages: int
    property_type: str
    search_base_url: NotRequired[str]


@dataclass(frozen=True)
class YapoTargetStats:
    label: str
    scope: str
    raw_count: int = 0
    unique_count: int = 0


class YapoScraper(ScraperBase):
    source_name = "yapo"

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        rate_limiter: RateLimiter,
        start_urls: Iterable[str] = (),
        targets: Iterable[dict[str, Any]] | None = None,
        uf_service: UFService | None = None,
        max_pages: int = YAPO_MAX_PAGES,
    ) -> None:
        self._http = http_client
        self._rate = rate_limiter
        self._targets = _normalize_targets(targets, start_urls=start_urls, max_pages=max_pages)
        self._uf_service = uf_service
        self._max_pages = _clamp_max_pages(max_pages)
        self.last_raw_count = 0
        self.last_unique_count = 0
        self.last_target_stats: list[YapoTargetStats] = []

    async def scrape(self) -> list[ScraperResult]:
        uf_rate = await self._resolve_uf_rate()

        self.last_raw_count = 0
        self.last_unique_count = 0
        self.last_target_stats = []
        results: list[ScraperResult] = []
        seen_keys: set[str] = set()
        for target in self._targets:
            target_raw_count = 0
            target_unique_count = 0
            previous_page_keys: set[str] | None = None
            target_max_pages = _clamp_max_pages(target["max_pages"])
            for page in range(1, target_max_pages + 1):
                page_url = build_page_url(build_target_url(target), page)
                try:
                    html = await self._fetch(page_url)
                except httpx.HTTPError as e:
                    _log.warning(
                        "No se pudo descargar target=%s scope=%s url=%s: %s",
                        target["label"],
                        target["scope"],
                        page_url,
                        e,
                    )
                    break

                page_results = self.parse_listings(html, uf_to_clp=uf_rate)
                for item in page_results:
                    _add_target_metadata(item, target)
                page_keys = {_dedupe_key(item) for item in page_results}
                raw_count = len(page_results)
                self.last_raw_count += raw_count
                target_raw_count += raw_count
                if raw_count == 0:
                    _log.info(
                        "YapoScraper target=%s scope=%s page=%d url=%s scraped_count=0 unique_count=0",
                        target["label"],
                        target["scope"],
                        page,
                        page_url,
                    )
                    break
                if previous_page_keys is not None and page_keys and page_keys <= previous_page_keys:
                    _log.info(
                        "YapoScraper target=%s scope=%s page=%d url=%s scraped_count=%d "
                        "unique_count=0 repeated_previous=true",
                        target["label"],
                        target["scope"],
                        page,
                        page_url,
                        raw_count,
                    )
                    break

                page_unique = 0
                for item in page_results:
                    key = _dedupe_key(item)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    results.append(item)
                    page_unique += 1
                    target_unique_count += 1
                previous_page_keys = page_keys
                _log.info(
                    "YapoScraper target=%s scope=%s page=%d url=%s scraped_count=%d unique_count=%d",
                    target["label"],
                    target["scope"],
                    page,
                    page_url,
                    raw_count,
                    page_unique,
                )
            self.last_target_stats.append(
                YapoTargetStats(
                    label=target["label"],
                    scope=target["scope"],
                    raw_count=target_raw_count,
                    unique_count=target_unique_count,
                )
            )

        self.last_unique_count = len(results)
        _log.info(
            "YapoScraper: total_raw=%d total_unique=%d",
            self.last_raw_count,
            self.last_unique_count,
        )
        return results

    async def _resolve_uf_rate(self) -> Decimal | None:
        if self._uf_service is None:
            return None
        try:
            return await self._uf_service.get_current_rate()
        except Exception as e:
            _log.warning("No se pudo resolver UF: %s. Cards en UF se descartarán.", e)
            return None

    async def _fetch(self, url: str) -> str:
        await self._rate.wait()

        async def _do() -> str:
            resp = await self._http.get(url)
            resp.raise_for_status()
            return resp.text

        return await with_retry(_do)

    # ─────────────────────────────────────────────────────
    #  Parser puro — testeable sin network ni UFService
    # ─────────────────────────────────────────────────────
    @staticmethod
    def parse_listings(
        html: str,
        *,
        uf_to_clp: Decimal | None = None,
    ) -> list[ScraperResult]:
        """Extrae listings de una página de yapo.cl.

        Args:
            html: HTML crudo de la página de resultados.
            uf_to_clp: tasa UF vigente para convertir precios en UF. Si es
                None, las cards cotizadas en UF se descartan.
        """
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("div.d3-ad-tile")
        scraped_at = datetime.now(UTC)
        results: list[ScraperResult] = []

        for card in cards:
            try:
                parsed = _parse_card(card, scraped_at=scraped_at, uf_to_clp=uf_to_clp)
            except Exception as e:
                _log.debug("Card yapo descartada por parsing error: %s", e)
                continue
            if parsed is not None:
                results.append(parsed)

        return results


# ─────────────────────────────────────────────────────────
#  Helpers de parsing
# ─────────────────────────────────────────────────────────
def _parse_card(
    card: Tag, *, scraped_at: datetime, uf_to_clp: Decimal | None
) -> ScraperResult | None:
    # Selector laxo: la clase `d3-ad-tile__title` puede estar en <h2> o <span>
    # según el layout que renderice yapo. Matcheamos por clase para sobrevivir
    # el cambio.
    title = _text(card.select_one(".d3-ad-tile__title"))
    location_parts = [_text(span) for span in card.select(".d3-ad-tile__location span")]
    location_parts = [part for part in location_parts if part]
    comuna = location_parts[0] if location_parts else ""
    price_text = _text(card.select_one(".d3-ad-tile__price"))
    link = card.select_one("a.d3-ad-tile__description")
    href = link.get("href") if link else None

    if not (title and comuna and price_text):
        return None

    # Precio: detectar moneda, convertir UF→CLP si aplica.
    parsed_price = parse_price_text(price_text)
    if parsed_price is None:
        return None
    currency, amount = parsed_price
    price_clp = to_clp(currency, amount, uf_to_clp=uf_to_clp)
    if price_clp is None:
        # UF sin tasa disponible → descartamos en lugar de inventar.
        return None

    attrs = _parse_details(card.select("li.d3-ad-tile__details-item"))

    external_id = _extract_id_from_url(href)
    seller = _text(card.select_one(".d3-ad-tile__seller span"))
    reduction = _text(card.select_one(".d3-ad-tile__price-reduction"))
    hallmark = _text(card.select_one(".d3-ad-tile__hallmark"))

    location_text = ", ".join(location_parts) if location_parts else comuna
    raw_metadata: dict = {
        "currency_original": currency,
        "category": "departamentos",
        "location_text": location_text,
        "location": location_text,
    }
    if len(location_parts) > 1:
        raw_metadata["neighborhood"] = location_parts[1]
    if seller:
        raw_metadata["seller"] = seller
    if reduction:
        raw_metadata["price_reduction"] = reduction
    if hallmark:
        raw_metadata["hallmark"] = hallmark
    _add_location_hint_metadata(
        raw_metadata,
        title=title,
        href=href,
        card_text=card.get_text(" ", strip=True),
    )

    return {
        "source": "yapo",
        "external_id": external_id,
        "title": title,
        "comuna": comuna,
        "property_type": "apartment",
        "m2": attrs.get("m2", 0),
        "bedrooms": int(attrs.get("bedrooms", 0)),
        "bathrooms": int(attrs.get("bathrooms", 0)),
        "parking": int(attrs.get("parking", 0)),
        "price_clp": int(price_clp),
        "url": _absolute_url(href),
        "lat": None,
        "lon": None,
        "scraped_at": scraped_at,
        "raw_metadata": raw_metadata,
    }


async def parse_listing_from_url(
    url: str,
    *,
    http_client: httpx.AsyncClient,
) -> ScraperResult | None:
    """Descarga y parsea una publicacion Yapo puntual para prellenar tasacion."""
    resp = await http_client.get(url)
    resp.raise_for_status()
    return parse_listing_detail(resp.text, url=url)


def parse_listing_detail(
    html: str,
    *,
    url: str,
    uf_to_clp: Decimal | None = None,
) -> ScraperResult | None:
    """Parser best-effort de pagina detalle Yapo.

    Es deliberadamente tolerante: si faltan campos, retorna lo disponible y
    deja que `clean_listing(..., allow_incomplete=True)` marque warnings.
    """
    soup = BeautifulSoup(html, "lxml")
    title = _first_meta_content(soup, ("og:title", "twitter:title")) or _text(soup.select_one("h1"))
    if not title and soup.title is not None:
        title = soup.title.get_text(" ", strip=True)
    title = _clean_detail_title(title)
    page_text = soup.get_text(" ", strip=True)
    price_clp, price_uf = _extract_detail_price(soup, page_text, uf_to_clp=uf_to_clp)

    property_type = _infer_yapo_property_type(url, title, page_text)
    details = _parse_detail_attributes(soup, page_text, property_type=property_type)
    location_text = _extract_detail_location(soup, page_text, url=url, title=title)
    raw_metadata: dict[str, Any] = {
        "category": "casas" if property_type == "house" else "departamentos",
        "location_text": location_text,
        "location": location_text,
        "description": _first_meta_content(soup, ("description", "og:description")) or "",
    }
    if price_uf is not None:
        raw_metadata["price_uf"] = price_uf
    _add_location_hint_metadata(raw_metadata, title=title, href=url, card_text=page_text, detail_text=page_text)

    if not (title or price_clp or location_text):
        return None
    return {
        "source": "yapo",
        "external_id": _extract_id_from_url(url),
        "title": title or "Publicacion Yapo",
        "comuna": location_text or "",
        "property_type": property_type,
        "m2": details.get("m2", 0),
        "built_area_m2": details.get("built_area_m2"),
        "land_area_m2": details.get("land_area_m2"),
        "usable_area_m2": details.get("usable_area_m2"),
        "bedrooms": int(details.get("bedrooms", 0)),
        "bathrooms": int(details.get("bathrooms", 0)),
        "parking": int(details.get("parking", 0)),
        "price_clp": price_clp or 0,
        "price_uf": price_uf,
        "url": _absolute_url(url),
        "lat": None,
        "lon": None,
        "scraped_at": datetime.now(UTC),
        "raw_metadata": raw_metadata,
    }


def _parse_details(items: list[Tag]) -> dict[str, float]:
    """Parsea la lista de atributos (SVG + número sin label).

    Convención de yapo: el primero con "m²" es la superficie; los demás
    van en orden bedrooms → bathrooms → parking.
    """
    out: dict[str, float] = {}
    remaining: list[Tag] = []

    for li in items:
        text = li.get_text(" ", strip=True)
        if "m²" in text or " m2" in text.lower():
            num = _first_number(text)
            if num is not None:
                out["m2"] = num
        else:
            remaining.append(li)

    if "m2" not in out and remaining:
        first_num = _first_number(remaining[0].get_text(" ", strip=True))
        if first_num is not None and first_num >= 10:
            out["m2"] = first_num
            remaining = remaining[1:]

    for slot, li in zip(_SLOT_ORDER, remaining, strict=False):
        num = _first_number(li.get_text(" ", strip=True))
        if num is not None:
            out[slot] = num

    return out


def _first_meta_content(soup: BeautifulSoup, names: tuple[str, ...]) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag is not None:
            content = tag.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def _clean_detail_title(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" -|")


def _extract_price_text(text: str) -> str:
    for match in re.finditer(r"(?:UF\s*[\d.,]+|\$\s*[\d.,]+)", text, re.IGNORECASE):
        if _price_match_looks_like_price_per_m2(text, match.start(), match.end()):
            continue
        return match.group(0)
    return ""


def _extract_detail_price(
    soup: BeautifulSoup,
    page_text: str,
    *,
    uf_to_clp: Decimal | None,
) -> tuple[int | None, float | None]:
    for candidate, currency_hint in _detail_price_candidates(soup, page_text):
        price_clp, price_uf = _parse_detail_price(
            candidate,
            currency_hint=currency_hint,
            uf_to_clp=uf_to_clp,
        )
        if price_clp is not None or price_uf is not None:
            return price_clp, price_uf
    return None, None


def _detail_price_candidates(soup: BeautifulSoup, page_text: str) -> list[tuple[str, str | None]]:
    candidates: list[tuple[str, str | None]] = []
    visible = _extract_price_text(page_text)
    if visible:
        candidates.append((visible, None))

    meta_amount = _first_meta_content(soup, ("product:price:amount", "og:price:amount"))
    meta_currency = _first_meta_content(soup, ("product:price:currency", "og:price:currency"))
    if meta_amount:
        candidates.append((meta_amount, meta_currency or None))

    for selector in ('[itemprop="price"]', '[class*=price]', '[data-testid*=price]'):
        tag = soup.select_one(selector)
        if tag is None:
            continue
        content = tag.get("content")
        text = content if isinstance(content, str) and content.strip() else tag.get_text(" ", strip=True)
        if text:
            candidates.append((text, None))

    candidates.extend(_json_ld_price_candidates(soup))
    return candidates


def _json_ld_price_candidates(soup: BeautifulSoup) -> list[tuple[str, str | None]]:
    candidates: list[tuple[str, str | None]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.get_text(strip=True) or "{}")
        except json.JSONDecodeError:
            continue
        for item in _flatten_json_ld(payload):
            if not isinstance(item, dict):
                continue
            offers = item.get("offers")
            offer_items = offers if isinstance(offers, list) else [offers]
            for offer in offer_items:
                if not isinstance(offer, dict):
                    continue
                price = offer.get("price") or offer.get("lowPrice")
                if price is None:
                    continue
                currency = offer.get("priceCurrency")
                candidates.append((str(price), str(currency) if currency else None))
    return candidates


def _flatten_json_ld(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return [item for group in payload for item in _flatten_json_ld(group)]
    if isinstance(payload, dict) and isinstance(payload.get("@graph"), list):
        return payload["@graph"]
    return [payload]


def _parse_detail_price(
    value: str,
    *,
    currency_hint: str | None,
    uf_to_clp: Decimal | None,
) -> tuple[int | None, float | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    currency = (currency_hint or "").strip().upper()
    if currency in {"UF", "CLF"} and not text.lower().startswith("uf"):
        text = f"UF {text}"
    elif currency in {"CLP", "CL$"} and not text.startswith("$"):
        text = f"${text}"

    parsed = parse_price_text(text)
    if parsed is None:
        return None, None

    parsed_currency, amount = parsed
    if parsed_currency == "UF":
        price_clp = to_clp(parsed_currency, amount, uf_to_clp=uf_to_clp)
        if price_clp is None:
            return None, float(amount)
        if price_clp < MIN_SALE_PRICE_CLP:
            return None, None
        return int(price_clp), float(amount)

    price_clp = int(to_clp(parsed_currency, amount, uf_to_clp=None) or 0)
    if price_clp < MIN_SALE_PRICE_CLP:
        return None, None
    return price_clp, None


def _parse_detail_attributes(soup: BeautifulSoup, text: str, *, property_type: str) -> dict[str, float]:
    attrs = _parse_structured_detail_attributes(soup, property_type=property_type)
    if property_type == "house":
        land_area = _extract_land_area_from_text(text)
        if land_area is not None:
            attrs.setdefault("land_area_m2", land_area)
    m2_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:m²|m2|mts2|metros)", text, re.IGNORECASE)
    if m2_match and "m2" not in attrs and not _m2_match_looks_like_price_per_m2(
        text,
        m2_match.start(),
        m2_match.end(),
        property_type=property_type,
    ):
        parsed_m2 = _first_area_number(m2_match.group(0))
        if parsed_m2 is not None and 10 <= parsed_m2 <= 1000:
            attrs["m2"] = parsed_m2
            if property_type != "house":
                attrs.setdefault("built_area_m2", parsed_m2)
    bedrooms = re.search(r"(\d+)\s*(?:dormitorios?|dorm\.?|habitaciones?)", text, re.IGNORECASE)
    bathrooms = re.search(r"(\d+)\s*(?:baños?|banos?|baths?)", text, re.IGNORECASE)
    parking = re.search(r"(\d+)\s*(?:estacionamientos?|parking)", text, re.IGNORECASE)
    if bedrooms:
        attrs.setdefault("bedrooms", float(bedrooms.group(1)))
    if bathrooms:
        attrs.setdefault("bathrooms", float(bathrooms.group(1)))
    if parking:
        attrs.setdefault("parking", float(parking.group(1)))
    return attrs


def _extract_land_area_from_text(text: str) -> float | None:
    patterns = (
        r"\b(?:terreno|sitio|lote)(?:\s+de)?\s+(\d{1,3}(?:[.,]\d{3})+(?:,\d+)?|\d{2,5}(?:,\d+)?)\s*(?:mÂ²|m2|mts2|metros)?\b",
        r"\b(\d{1,3}(?:[.,]\d{3})+(?:,\d+)?|\d{2,5}(?:,\d+)?)\s*(?:mÂ²|m2|mts2|metros)?\s+(?:de\s+)?(?:terreno|sitio|lote)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        parsed = _parse_area_number(match.group(1))
        if parsed is not None and parsed > 0:
            return parsed
    return None


def _parse_structured_detail_attributes(soup: BeautifulSoup, *, property_type: str) -> dict[str, float]:
    attrs: dict[str, float] = {}
    for item in soup.select(".d3-property-insight__attribute"):
        label = _text(
            item.select_one(
                ".d3-property-insight__attribute-title, dt, [class*=attribute-title]"
            )
        )
        value = _text(
            item.select_one(
                ".d3-property-insight__attribute-value, dd, [class*=attribute-value]"
            )
        )
        if label and value:
            _apply_detail_attribute(attrs, label=label, value=value, property_type=property_type)
    return attrs


def _apply_detail_attribute(attrs: dict[str, float], *, label: str, value: str, property_type: str) -> None:
    normalized = _normalize_detail_label(label)
    if _is_price_per_m2_label(normalized):
        return

    number = _first_area_number(value)
    if number is None:
        return

    if _is_built_area_label(normalized):
        attrs.setdefault("built_area_m2", number)
        attrs.setdefault("m2", number)
    elif _is_usable_area_label(normalized):
        attrs.setdefault("usable_area_m2", number)
        attrs.setdefault("built_area_m2", number)
        attrs.setdefault("m2", number)
    elif _is_total_area_label(normalized):
        attrs.setdefault("land_area_m2", number)
        if property_type != "house" and "terreno" not in normalized:
            attrs.setdefault("m2", number)
    elif "dormitorio" in normalized or "habitacion" in normalized:
        attrs["bedrooms"] = number
    elif "bano" in normalized or "banos" in normalized or "bath" in normalized:
        attrs["bathrooms"] = number
    elif "estacionamiento" in normalized or "estacionamientos" in normalized or "parking" in normalized:
        attrs["parking"] = number


def _normalize_detail_label(value: str) -> str:
    no_accents = "".join(
        ch
        for ch in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(ch) != "Mn"
    )
    text = no_accents.replace("m 2", "m2").replace("m²", "m2")
    text = re.sub(r"[^a-z0-9/\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_price_per_m2_label(normalized: str) -> bool:
    return "precio" in normalized and ("m2" in normalized or "metro" in normalized)


def _is_built_area_label(normalized: str) -> bool:
    return any(
        token in normalized
        for token in (
            "area construida",
            "m2 construidos",
            "superficie construida",
            "construidos",
            "construida",
        )
    )


def _is_usable_area_label(normalized: str) -> bool:
    return any(token in normalized for token in ("area util", "m2 utiles", "superficie util"))


def _is_total_area_label(normalized: str) -> bool:
    return any(
        token in normalized
        for token in ("m2 totales", "m totales", "area total", "superficie total", "terreno")
    )


def _m2_match_looks_like_price_per_m2(text: str, start: int, end: int, *, property_type: str) -> bool:
    before = _normalize_detail_label(text[max(0, start - 60):start])
    after = _normalize_detail_label(text[end:min(len(text), end + 32)])
    if _is_price_per_m2_label(before) or before.rstrip().endswith("$") or after.startswith("totales"):
        return True
    if property_type == "house" and (
        "terreno" in before
        or after.startswith(("terreno", "de terreno", "sitio", "de sitio", "lote", "de lote"))
    ):
        return True
    return False


def _price_match_looks_like_price_per_m2(text: str, start: int, end: int) -> bool:
    before = _normalize_detail_label(text[max(0, start - 80):start])
    after = _normalize_detail_label(text[end:min(len(text), end + 40)])
    return _is_price_per_m2_label(before) or after.startswith(("m2", "metro", "metros"))


def _first_area_number(text: str) -> float | None:
    m = _NUMBER_RE.search(text)
    if not m:
        return None
    return _parse_area_number(m.group(0))


def _parse_area_number(value: str) -> float | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    if "." in cleaned and "," in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]) and len(parts[0]) <= 3:
            cleaned = "".join(parts)
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]) and len(parts[0]) <= 3:
            cleaned = "".join(parts)
        else:
            cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_detail_location(soup: BeautifulSoup, text: str, *, url: str, title: str) -> str:
    for candidate in (_slug_text_from_href(url), title):
        comuna = _find_known_comuna_in_text(candidate)
        if comuna:
            return comuna

    for selector in ("[class*=location]", "[class*=ubicacion]", "[data-testid*=location]"):
        candidate = _text(soup.select_one(selector))
        comuna = _find_known_comuna_in_text(candidate)
        if comuna:
            return comuna

    match = re.search(r"(?:Comuna|Ubicación|Ubicacion)\s*:?\s*([A-Za-zÁÉÍÓÚÑáéíóúñ ]{3,40})", text)
    if match:
        comuna = _find_known_comuna_in_text(match.group(1))
        if comuna:
            return comuna
    return ""


def _find_known_comuna_in_text(value: str | None) -> str | None:
    if not value:
        return None
    normalized = _normalize_hint(value)
    if not normalized or normalized in _DETAIL_LOCATION_NOISE:
        return None
    if is_known_comuna(normalized):
        return normalize_comuna(normalized)

    padded = f" {normalized} "
    matches: list[tuple[int, str]] = []
    for alias, canonical in _ALIAS_TO_CANONICAL_COMUNA.items():
        alias_normalized = _normalize_hint(alias)
        if alias_normalized and f" {alias_normalized} " in padded:
            matches.append((len(alias_normalized), canonical))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def _add_location_hint_metadata(
    raw_metadata: dict[str, Any],
    *,
    title: str,
    href: str | None,
    card_text: str,
    detail_text: str | None = None,
) -> None:
    raw_metadata.update(
        enrich_raw_metadata_with_geo_signals(
            raw_metadata,
            title=title,
            url=href,
            card_text=card_text,
            detail_text=detail_text,
        )
    )
    hint, source = _extract_location_hint(title=title, href=href, card_text=card_text)
    if hint is None:
        raw_metadata["geocode_precision"] = "comuna" if raw_metadata.get("location_text") else "unknown"
        raw_metadata["geocode_precision_reason"] = "location_text_only" if raw_metadata.get("location_text") else "no_location_signal"
        return
    raw_metadata["address_label"] = hint
    raw_metadata["street_hint"] = hint
    raw_metadata["geocode_precision"] = "address"
    raw_metadata["geocode_precision_reason"] = source


def _extract_location_hint(*, title: str, href: str | None, card_text: str) -> tuple[str | None, str]:
    candidates = [
        ("title", title, True),
        ("url", _slug_text_from_href(href), True),
        ("card_text", card_text, False),
    ]
    for source, value, allow_intersection in candidates:
        hint = _extract_address_like_text(value, allow_intersection=allow_intersection)
        if hint is not None:
            return hint, source
    return None, ""


def _extract_address_like_text(value: str | None, *, allow_intersection: bool) -> str | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", value).strip(" ,.-")

    explicit = _EXPLICIT_STREET_RE.search(text)
    if explicit is not None:
        hint = _clean_location_hint(explicit.group(0))
        if _is_usable_hint(hint):
            return hint

    if allow_intersection:
        intersection = _extract_intersection_hint(text)
        if intersection is not None:
            return intersection

    metro = _METRO_RE.search(text)
    if metro is not None:
        station = _clean_location_hint(metro.group(1))
        if station:
            return f"Metro {station}"

    normalized = _normalize_hint(text)
    for snippet in _KNOWN_STREET_SNIPPETS:
        if _normalize_hint(snippet) in normalized:
            return snippet
    return None


def _extract_intersection_hint(text: str) -> str | None:
    for match in _INTERSECTION_RE.finditer(text):
        left = _clean_intersection_side(match.group(1))
        right = _clean_intersection_side(match.group(2))
        if _is_usable_hint(left) and _is_usable_hint(right):
            return f"{left} y {right}"
    return None


def _clean_intersection_side(value: str) -> str:
    marker = _EXPLICIT_STREET_RE.search(value)
    if marker is not None:
        return _clean_location_hint(marker.group(0))
    words = [
        word
        for word in re.split(r"\s+", _clean_location_hint(value))
        if _normalize_hint(word) not in _TITLE_STOP_WORDS
    ]
    return " ".join(words[-4:]).strip(" ,.-/")


def _clean_location_hint(value: str) -> str:
    value = re.split(
        r"\b(en venta|venta|vende|depto|dpto|departamento|dormitorio|dorm|baño|bano|estac)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return re.sub(r"\s+", " ", value).strip(" ,.-/")


def _is_usable_hint(value: str) -> bool:
    normalized = _normalize_hint(value)
    words = [word for word in normalized.split() if word not in _TITLE_STOP_WORDS and not word.isdigit()]
    return bool(words) and len(normalized) >= 3


def _slug_text_from_href(href: str | None) -> str:
    if not href:
        return ""
    path = urlsplit(href).path
    if not path:
        return ""
    slug = path.rstrip("/").split("/")[-2] if _extract_id_from_url(href) else path.rstrip("/").split("/")[-1]
    return slug.replace("-", " ")


def _normalize_hint(value: str) -> str:
    no_accents = "".join(
        ch
        for ch in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(ch) != "Mn"
    )
    no_punct = re.sub(r"[^a-z0-9. ]+", " ", no_accents)
    return re.sub(r"\s+", " ", no_punct).strip()


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


def _extract_id_from_url(url: str | None) -> str | None:
    """'/bienes.../slug/31672033' → '31672033'."""
    if not url:
        return None
    m = _URL_ID_RE.search(url)
    return m.group(1) if m else None


def _absolute_url(url: str | None) -> str | None:
    if url is None:
        return None
    if url.startswith("http"):
        return url
    return f"https://www.yapo.cl{url}"


def build_page_url(url: str, page: int) -> str:
    if page < 1:
        raise ValueError("page must be >= 1")
    parts = urlsplit(url)
    path = _PAGE_SUFFIX_RE.sub("", parts.path)
    if page > 1:
        path = f"{path}.{page}"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def build_target_url(target: YapoTarget) -> str:
    base_url = target.get("search_base_url") or YAPO_SEARCH_BASE_URL
    parts = urlsplit(base_url)
    query_params = parse_qs(parts.query, keep_blank_values=True)
    query_params["q"] = [target["query"]]
    query = urlencode(query_params, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _dedupe_key(item: ScraperResult) -> str:
    external_id = item.get("external_id")
    if external_id:
        return f"source_external:{item.get('source', 'yapo')}|{external_id}"
    url = item.get("url")
    if url:
        return f"url:{url}"
    return f"fallback:{item.get('title')}|{item.get('comuna')}|{item.get('price_clp')}"


def _clamp_max_pages(max_pages: int) -> int:
    return max(1, min(int(max_pages), YAPO_MAX_PAGES_HARD_LIMIT))


def _normalize_targets(
    targets: Iterable[dict[str, Any]] | None,
    *,
    start_urls: Iterable[str],
    max_pages: int,
) -> tuple[YapoTarget, ...]:
    if targets is not None:
        return tuple(_normalize_target(target) for target in targets)
    urls = tuple(start_urls)
    if urls:
        return tuple(
            {
                "label": f"legacy_{index}",
                "query": _query_from_url(url),
                "scope": "general",
                "max_pages": _clamp_max_pages(max_pages),
                "property_type": "apartment",
            }
            for index, url in enumerate(urls, start=1)
        )
    return tuple(_normalize_target(target) for target in YAPO_TARGETS)


def _normalize_target(target: dict[str, Any]) -> YapoTarget:
    label = str(target["label"])
    query = str(target["query"])
    scope = str(target["scope"])
    max_pages = _clamp_max_pages(int(target["max_pages"]))
    normalized: YapoTarget = {
        "label": label,
        "query": query,
        "scope": scope,
        "max_pages": max_pages,
        "property_type": _normalize_target_property_type(target.get("property_type")),
    }
    search_base_url = str(target.get("search_base_url") or "").strip()
    if search_base_url:
        normalized["search_base_url"] = search_base_url
    return normalized


def _normalize_target_property_type(value: Any) -> str:
    text = str(value or "apartment").strip().lower()
    return text if text in PROPERTY_TYPES else "apartment"


def _infer_yapo_property_type(*values: str | None) -> str:
    for value in values:
        tokens = set(_normalize_hint(value or "").split())
        if tokens & {"departamento", "departamentos", "depto", "dpto", "apartamento", "apartamentos"}:
            return "apartment"
        if tokens & {"casa", "casas"}:
            return "house"
    return "apartment"


def _query_from_url(url: str) -> str:
    query_params = parse_qs(urlsplit(url).query)
    query_values = query_params.get("q")
    if not query_values:
        return "keyword.departamentos venta"
    return query_values[0]


def _add_target_metadata(item: ScraperResult, target: YapoTarget) -> None:
    raw_metadata = item.get("raw_metadata")
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    property_type = _normalize_target_property_type(target.get("property_type"))
    metadata["target_label"] = target["label"]
    metadata["target_scope"] = target["scope"]
    metadata["target_query"] = target["query"]
    metadata["target_property_type"] = property_type
    metadata["category"] = "casas" if property_type == "house" else metadata.get("category", "departamentos")
    item["property_type"] = property_type
    item["raw_metadata"] = metadata
