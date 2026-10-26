"""Abstracciones compartidas entre scrapers.

Responsabilidades:
    · Contrato `ScraperBase` — cada sitio implementa `.scrape() -> list[dict]`.
    · `ScraperResult` TypedDict — forma que esperan los dicts para el pipeline.
    · `RateLimiter` — asegura un intervalo mínimo entre requests (polite scraping).
    · `with_retry` — reintenta con backoff exponencial en fallas transitorias.

Lo que NO incluye (por diseño):
    · Rotación de proxies, User-Agents falsos, evasión de CAPTCHA. Esto es
      scraping educado: si el sitio bloquea, esperamos y reintentamos; si
      bloquea de forma persistente, corregimos el comportamiento o paramos.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, TypedDict, TypeVar

import httpx

_log = logging.getLogger(__name__)

T = TypeVar("T")


class ScraperResult(TypedDict, total=False):
    """Forma del dict que cada scraper produce.

    Compatible con `domain.ingestion.clean_listing`. Los tipos son laxos
    (`str | float | int`) porque el pipeline los normaliza.
    """

    source: str
    external_id: str | None
    title: str
    comuna: str
    property_type: str
    m2: float | int | str
    built_area_m2: float | int | str
    land_area_m2: float | int | str
    usable_area_m2: float | int | str
    bedrooms: int | str
    bathrooms: int | str
    parking: int | str
    price_clp: int | str
    url: str | None
    lat: float | None
    lon: float | None
    scraped_at: datetime
    raw_metadata: dict


class ScraperBase(ABC):
    """Contrato mínimo de un scraper. Cada sitio extiende esto."""

    source_name: str  # debe coincidir con un valor de LISTING_SOURCES

    @abstractmethod
    async def scrape(self) -> list[ScraperResult]:
        """Devuelve todos los listings recolectados en esta corrida."""


# ─────────────────────────────────────────────────────────
#  Rate limiting
# ─────────────────────────────────────────────────────────
class RateLimiter:
    """Asegura un intervalo mínimo entre llamadas a `wait()`.

    No es thread-safe: se asume uso dentro de un mismo event loop.
    """

    def __init__(self, min_interval: float) -> None:
        if min_interval < 0:
            raise ValueError(f"min_interval debe ser ≥ 0: {min_interval}")
        self._min_interval = min_interval
        self._last_ts: float | None = None

    async def wait(self) -> None:
        """Bloquea hasta que haya pasado `min_interval` desde el último `wait()`."""
        now = time.monotonic()
        if self._last_ts is not None:
            elapsed = now - self._last_ts
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
        self._last_ts = time.monotonic()


# ─────────────────────────────────────────────────────────
#  Retry con backoff exponencial
# ─────────────────────────────────────────────────────────
async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple[type[BaseException], ...] = (httpx.HTTPError,),
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> T:
    """Intenta ejecutar `fn()` hasta `max_attempts` veces con backoff 1s → 2s → 4s…

    Args:
        fn: coroutine factory sin argumentos (ej: `lambda: client.get(url)`).
        max_attempts: número total de intentos (debe ser ≥ 1).
        base_delay: delay del primer retry.
        exceptions: tipos que activan retry. Otras excepciones se propagan.
        sleep: inyectable para testing (normalmente `asyncio.sleep`).
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts debe ser ≥ 1: {max_attempts}")

    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except exceptions as e:
            last_exc = e
            if attempt == max_attempts:
                _log.warning("Retry agotado tras %d intentos: %s", max_attempts, e)
                raise
            delay = base_delay * (2 ** (attempt - 1))
            _log.info("Intento %d/%d falló (%s); esperando %.1fs", attempt, max_attempts, e, delay)
            await sleep(delay)

    # Inaccesible: el loop retorna o re-eleva. Satisface al type checker.
    assert last_exc is not None
    raise last_exc


# ─────────────────────────────────────────────────────────
#  Parseo de precios CLP / UF (compartido entre scrapers)
# ─────────────────────────────────────────────────────────
Currency = Literal["CLP", "UF"]

_UF_PREFIX_RE = re.compile(r"^\s*uf\s*", re.IGNORECASE)


def parse_spanish_number(s: str) -> Decimal | None:
    """Parsea un número con notación española: '.' miles, ',' decimales.

    Ejemplos:
        '180.000.000'   → 180000000
        '12.400'        → 12400
        '12.400,50'     → 12400.50
        '8.200,00'      → 8200
    """
    cleaned = s.strip()
    if not cleaned:
        return None
    try:
        if "," in cleaned:
            integer_part, decimal_part = cleaned.rsplit(",", 1)
            integer_clean = integer_part.replace(".", "")
            return Decimal(f"{integer_clean}.{decimal_part}")
        return Decimal(cleaned.replace(".", ""))
    except InvalidOperation:
        return None


def parse_price_text(text: str) -> tuple[Currency, Decimal] | None:
    """Detecta moneda y monto en un string como '$260.000.000' o 'UF8.200,00'.

    Retorna None si no se puede parsear.
    """
    raw = text.strip()
    if not raw:
        return None

    # UF: prefijo "UF" seguido (opcionalmente con espacio) del número.
    if _UF_PREFIX_RE.match(raw):
        num_part = _UF_PREFIX_RE.sub("", raw)
        amount = parse_spanish_number(num_part)
        if amount is None:
            return None
        return ("UF", amount)

    # CLP: puede o no traer "$" delante. Asumimos CLP si no hay prefijo UF.
    no_dollar = raw.replace("$", "").strip()
    amount = parse_spanish_number(no_dollar)
    if amount is None:
        return None
    return ("CLP", amount)


def to_clp(
    currency: Currency,
    amount: Decimal,
    *,
    uf_to_clp: Decimal | None,
) -> Decimal | None:
    """Normaliza un monto a CLP. Si es UF y no hay tasa, retorna None."""
    if currency == "CLP":
        return amount
    # currency == "UF"
    if uf_to_clp is None:
        return None
    return amount * uf_to_clp
