"""Bounded card-first Portal discovery using the canonical write path."""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from redis.asyncio import Redis

from config import get_settings
from config.comunas import is_known_comuna
from config.portal_targets import PORTAL_TARGETS
from infrastructure.db.database import get_session_factory
from infrastructure.db.repositories import SqlAlchemyListingRepository, SqlAlchemyPriceHistoryRepository, SqlAlchemyPropertyRepository
from infrastructure.external.uf_client import UFClient
from infrastructure.scrapers.base import RateLimiter
from infrastructure.scrapers.portalinmobiliario import PortalInmobiliarioScraper, build_portal_page_url, classify_portal_detail_page_state, classify_portal_page_state, parse_listing_detail_portal, portal_dedupe_key, validate_portal_rm_location
from scripts.portal_canary import PortalCanaryReject, _materially_changed, portal_detail_to_raw
from scripts.portal_http_dry_run import build_portal_target_url
from scripts.portal_smoke import DEFAULT_HEADERS
from domain.ingestion.data_cleaning import clean_listing
from domain.ingestion.pipeline import process_listing
from infrastructure.scrapers.coordinates import coordinate_pair
from services.uf_rate import require_real_uf_rate


def _url(url: str, base: str) -> str:
    parts = urlsplit(urljoin(base, url))
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _card_raw(card: dict, target: dict, uf_rate: Decimal) -> dict:
    if target["operation"] != "venta":
        raise ValueError("rental")
    comuna = card.get("comuna")
    if not is_known_comuna(str(comuna or "")):
        raise ValueError("unknown_comuna")
    m2 = card.get("m2")
    if not isinstance(m2, (int, float)) or m2 <= 0:
        raise ValueError("missing_m2")
    external_id = card.get("external_id")
    if not external_id or not card.get("title") or not card.get("url"):
        raise ValueError("missing_identity")
    metadata = dict(card.get("raw_metadata") or {})
    currency = metadata.get("currency_original")
    if currency == "UF" and metadata.get("price_uf"):
        price_clp = int(Decimal(str(metadata["price_uf"])) * uf_rate)
        metadata.update({"price_uf": metadata["price_uf"], "price_clp_provenance": "derived_from_uf_real_rate", "uf_rate_used": str(uf_rate)})
    elif currency == "CLP" and card.get("price_clp"):
        price_clp = int(card["price_clp"])
    else:
        raise ValueError("invalid_price")
    metadata.update({"portal_card_first": True, "portal_target": target["label"], "area_source": "card_generic"})
    raw = {"source": "portalinmobiliario", "external_id": str(external_id), "title": card["title"], "url": _url(str(card["url"]), target["base_url"]), "comuna": comuna, "property_type": target["property_type"], "m2": m2, "price_clp": price_clp, "scraped_at": datetime.now(UTC), "raw_metadata": metadata, "_source_evidence": card.get("_source_evidence")}
    for field in ("bedrooms", "bathrooms", "parking"):
        if card.get(field): raw[field] = card[field]
    lat, lon = coordinate_pair(card.get("lat"), card.get("lon"))
    ev = metadata.get("coordinates_evidence") or {}
    if lat is not None and ev.get("source_listing_id") == str(external_id):
        raw.update(lat=lat, lon=lon, geocode_precision=metadata.get("geocode_precision", "unknown"))
    return raw


async def _persist(raw: dict, stats: Counter) -> None:
    factory = get_session_factory()
    async with factory() as session:
        repo = SqlAlchemyListingRepository(session)
        cleaned = clean_listing(raw, allow_incomplete=True)
        existing = await repo.find_by_source_external_id(cleaned.source, cleaned.external_id or "")
        changed = existing is None or _materially_changed(existing, cleaned)
        await process_listing(raw, listing_repo=repo, property_repo=SqlAlchemyPropertyRepository(session), price_history_repo=SqlAlchemyPriceHistoryRepository(session), allow_incomplete=True)
        await session.commit()
    stats["inserted" if existing is None else "updated" if changed else "known_unchanged"] += 1


async def run(*, apply: bool, max_pages: int, max_details: int, pause_s: float, max_geo_details: int | None = None) -> dict:
    settings = get_settings(); stats = Counter(); incomplete = []; fetched = {}
    if not settings.portal_http_enabled:
        return {"portal_disabled": 1}
    geo_budget = settings.portal_geo_detail_budget if max_geo_details is None else max_geo_details
    if not 0 <= geo_budget <= 5:
        raise ValueError("geo budget must be between 0 and 5")
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=30.0) as client:
        redis = Redis.from_url(settings.redis_url)
        try: uf_rate = (await require_real_uf_rate(UFClient(api_url=settings.uf_api_url, http_client=client, redis=redis))).rate
        finally: await redis.aclose()
        limiter = RateLimiter(max(3.0, pause_s)); seen = set()
        for target in PORTAL_TARGETS:
            for page in range(1, max_pages + 1):
                await limiter.wait(); response = await client.get(build_portal_page_url(build_portal_target_url(target), page)); stats["raw_cards_http"] += 1
                if response.status_code in (403,429): stats["blocked_or_captcha"] += 1; stats[f"http_{response.status_code}"] += 1; return dict(stats)
                if response.status_code != 200 or classify_portal_page_state(response.text, status_code=response.status_code) != "authenticated": stats["blocked_or_captcha"] += 1; return dict(stats)
                report = PortalInmobiliarioScraper.parse_listings_detailed(response.text, uf_to_clp=uf_rate); stats["raw_cards"] += report["cards_detected"]
                for card in report["items"]:
                    key = portal_dedupe_key(source="portalinmobiliario", external_id=card.get("external_id"), url=card.get("url"))
                    if not key or key in seen: continue
                    seen.add(key); stats["unique_cards"] += 1
                    try: raw = _card_raw(card, target, uf_rate); stats["card_complete"] += 1
                    except ValueError as exc:
                        if str(exc) == "rental": stats["skipped"] += 1; continue
                        stats["card_incomplete"] += 1; incomplete.append((target, card)); continue
                    stats["valid_cards"] += 1
                    if apply:
                        try: await _persist(raw, stats); stats["persisted_from_card"] += 1
                        except Exception: stats["validation_errors"] += 1
        for target, card in incomplete[:max_details]:
            await limiter.wait(); stats["details_requested"] += 1; response = await client.get(_url(str(card.get("url") or ""), target["base_url"]))
            from domain.geocoding.source_quality import mlc
            fetched[mlc(card.get("external_id"))] = response
            if response.status_code in (403,429): stats["blocked_or_captcha"] += 1; stats[f"http_{response.status_code}"] += 1; return dict(stats)
            if response.status_code != 200 or classify_portal_detail_page_state(response.text, status_code=response.status_code) != "detail": continue
            detail = parse_listing_detail_portal(response.text, str(response.url))
            try: raw = portal_detail_to_raw(detail, target, uf_info=type("U", (), {"rate": uf_rate, "source": "live", "cache_hit": False, "is_stale": False})())
            except (PortalCanaryReject, Exception): continue
            if apply:
                try: await _persist(raw, stats); stats["persisted_from_detail"] += 1
                except Exception: stats["validation_errors"] += 1
        if apply and geo_budget:
            from workers.portal_geo_enrichment import enrich_geography
            try:
                await enrich_geography(session_factory=get_session_factory(), client=client,
                    limiter=limiter, budget=geo_budget, fetched=fetched, stats=stats,
                    max_attempts=settings.portal_geo_max_attempts,
                    cooldown_hours=settings.portal_geo_cooldown_hours)
            except Exception as exc:
                # Discovery has already committed. Log only class, never raw evidence.
                stats["geo_stage_errors"] += 1
                import logging
                logging.getLogger(__name__).error("Portal geo stage failed error_type=%s", type(exc).__name__)
    return dict(stats)


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--apply", action="store_true"); parser.add_argument("--max-pages", type=int, default=1); parser.add_argument("--max-details", type=int, default=5); parser.add_argument("--max-geo-details", type=int, default=None); parser.add_argument("--pause-s", type=float, default=3.0); args=parser.parse_args()
    report=asyncio.run(run(apply=args.apply,max_pages=args.max_pages,max_details=min(args.max_details,5),pause_s=args.pause_s,max_geo_details=args.max_geo_details)); print(json.dumps(report,sort_keys=True)); return 1 if report.get("blocked_or_captcha") else 0

if __name__ == "__main__": raise SystemExit(main())
