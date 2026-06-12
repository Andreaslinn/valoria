"""Lookup seguro de publicaciones por URL para prellenar tasaciones."""
from __future__ import annotations

import ipaddress
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import get_settings
from domain.ingestion.data_cleaning import CleanedListing, clean_listing
from infrastructure.db.mappers import listing_from_orm
from infrastructure.db.models import ListingORM
from infrastructure.scrapers.yapo import parse_listing_from_url as parse_yapo_listing_from_url

LookupStatus = str
ListingLookup = Callable[[str], Awaitable[Any | None]]

_TIMEOUT_SEC = 12.0
_SUPPORTED_YAPO_HOSTS = {"yapo.cl", "www.yapo.cl"}
_BLOCKED_HOSTS = {"localhost", "0.0.0.0"}
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ListingUrlLookupResult:
    status: LookupStatus
    listing_data: dict[str, Any]
    warnings: list[str]
    source: str | None
    url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def lookup_listing_url(
    url: str,
    *,
    listing_lookup: ListingLookup | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> ListingUrlLookupResult:
    validation_error = validate_public_listing_url(url)
    if validation_error is not None:
        return _result(validation_error, url=url, source=None, warnings=[validation_error])

    source = detect_source(url)
    if source is None:
        return _result("unsupported_source", url=url, source=None, warnings=["Fuente aún no soportada"])

    lookup = listing_lookup or _find_existing_listing_by_url
    try:
        existing = await lookup(url)
    except Exception as e:
        # Streamlit calls this service through asyncio.run(). SQLAlchemy/asyncpg
        # pooled connections can be tied to a prior event loop, so a lookup
        # failure must not prevent the URL parser fallback from running.
        _log.warning("Existing listing lookup failed for url=%s: %s", url, e)
        existing = None
    if existing is not None:
        return _result(
            "found_existing",
            url=url,
            source=source,
            listing_data=listing_to_form_data(existing),
        )

    raw = await _parse_raw_listing_from_url(url, source=source, http_client=http_client)
    if raw is None:
        return _result("failed", url=url, source=source, warnings=["No se pudo parsear la publicación"])
    try:
        parsed = clean_listing(dict(raw), allow_incomplete=True)
    except Exception:
        return _result(
            "partial",
            url=url,
            source=source,
            listing_data=raw_to_form_data(raw),
            warnings=_warnings_for_raw(raw),
        )

    return _result(
        "parsed_new" if _has_minimum_fields(parsed) else "partial",
        url=url,
        source=source,
        listing_data=cleaned_to_form_data(parsed),
        warnings=_warnings_for_cleaned(parsed),
    )


async def parse_listing_from_url(
    url: str,
    *,
    source: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> CleanedListing | None:
    raw = await _parse_raw_listing_from_url(url, source=source, http_client=http_client)
    if raw is None:
        return None
    try:
        return clean_listing(dict(raw), allow_incomplete=True)
    except Exception:
        return None


async def _parse_raw_listing_from_url(
    url: str,
    *,
    source: str | None,
    http_client: httpx.AsyncClient | None,
) -> dict[str, Any] | None:
    source = source or detect_source(url)
    if source != "yapo":
        return None

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=_TIMEOUT_SEC, follow_redirects=True)
    try:
        return await parse_yapo_listing_from_url(url, http_client=client)
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if owns_client:
            await client.aclose()


def detect_source(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    if host in _SUPPORTED_YAPO_HOSTS or host.endswith(".yapo.cl"):
        return "yapo"
    return None


def validate_public_listing_url(url: str) -> str | None:
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "invalid_url"
    host = (parsed.hostname or "").strip().lower()
    if host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        return "invalid_url"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
        return "invalid_url"
    return None


def listing_to_form_data(listing: Any) -> dict[str, Any]:
    return {
        "listing_id": getattr(listing, "id", None),
        "title": getattr(listing, "title", None),
        "comuna": getattr(listing, "comuna", None),
        "property_type": getattr(listing, "property_type", None) or "unknown",
        "m2": getattr(listing, "m2", None),
        "built_area_m2": getattr(listing, "built_area_m2", None) or getattr(listing, "m2", None),
        "land_area_m2": getattr(listing, "land_area_m2", None),
        "usable_area_m2": getattr(listing, "usable_area_m2", None),
        "dormitorios": getattr(listing, "bedrooms", 0),
        "banos": getattr(listing, "bathrooms", 0),
        "estacionamientos": getattr(listing, "parking", 0),
        "precio_publicado_clp": int(getattr(getattr(listing, "price", None), "clp", 0) or 0),
        "source": getattr(listing, "source", None),
        "url": getattr(listing, "url", None),
    }


def cleaned_to_form_data(cleaned: CleanedListing) -> dict[str, Any]:
    return listing_to_form_data(cleaned)


def raw_to_form_data(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "comuna": raw.get("comuna") or raw.get("location_text"),
        "title": raw.get("title"),
        "property_type": raw.get("property_type") or "unknown",
        "m2": raw.get("m2") or None,
        "built_area_m2": raw.get("built_area_m2") or raw.get("m2") or None,
        "land_area_m2": raw.get("land_area_m2"),
        "usable_area_m2": raw.get("usable_area_m2"),
        "dormitorios": raw.get("bedrooms") or 0,
        "banos": raw.get("bathrooms") or 0,
        "estacionamientos": raw.get("parking") or 0,
        "precio_publicado_uf": raw.get("price_uf") or None,
        "precio_publicado_clp": raw.get("price_clp") or None,
        "source": raw.get("source"),
        "url": raw.get("url"),
    }


async def _find_existing_listing_by_url(url: str) -> Any | None:
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        echo=(settings.log_level == "DEBUG"),
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    try:
        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        async with session_factory() as session:
            stmt = select(ListingORM).where(ListingORM.url == url)
            orm = (await session.execute(stmt)).scalar_one_or_none()
            return listing_from_orm(orm) if orm is not None else None
    finally:
        await engine.dispose()


def _has_minimum_fields(cleaned: CleanedListing) -> bool:
    return bool(
        cleaned.comuna
        and cleaned.comuna != "unknown"
        and cleaned.property_type
        and cleaned.property_type != "unknown"
        and cleaned.m2
        and cleaned.price.clp > 0
    )


def _warnings_for_cleaned(cleaned: CleanedListing) -> list[str]:
    warnings = list(cleaned.quality_warnings)
    if cleaned.property_type == "unknown":
        warnings.append("missing_property_type")
    if not cleaned.m2:
        warnings.append("missing_m2")
    if cleaned.price.clp <= 0:
        warnings.append("missing_price")
    return sorted(set(warnings))


def _warnings_for_raw(raw: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if not raw.get("comuna"):
        warnings.append("missing_comuna")
    if not raw.get("property_type") or raw.get("property_type") == "unknown":
        warnings.append("missing_property_type")
    if not raw.get("m2"):
        warnings.append("missing_m2")
    if not raw.get("price_clp") and not raw.get("price_uf"):
        warnings.append("missing_price")
    return warnings


def _result(
    status: LookupStatus,
    *,
    url: str,
    source: str | None,
    listing_data: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> ListingUrlLookupResult:
    return ListingUrlLookupResult(
        status=status,
        listing_data=listing_data or {},
        warnings=warnings or [],
        source=source,
        url=url,
    )
