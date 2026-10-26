"""Bounded card-first Portal discovery using the canonical write path."""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from config import get_settings
from config.comunas import is_known_comuna
from config.portal_targets import PORTAL_TARGETS
from infrastructure.db.database import get_session_factory
from infrastructure.db.repositories import SqlAlchemyListingRepository, SqlAlchemyPriceHistoryRepository, SqlAlchemyPropertyRepository
from infrastructure.scrapers.base import RateLimiter
from infrastructure.scrapers.portalinmobiliario import PortalInmobiliarioScraper, build_portal_page_url, classify_portal_detail_page_state, classify_portal_page_state, parse_listing_detail_portal, portal_dedupe_key
from scripts.portal_canary import PortalCanaryReject, _materially_changed, portal_detail_to_raw
from scripts.portal_http_dry_run import build_portal_target_url
from scripts.portal_smoke import DEFAULT_HEADERS
from domain.ingestion.data_cleaning import clean_listing
from domain.ingestion.pipeline import process_listing
from infrastructure.scrapers.coordinates import coordinate_pair
from services.ingestion_uf import resolve_ingestion_rate, annotate_pending
from services.ingestion_state import PendingPriceStore, start_run, finish_run, safe_error
from scripts.portal_session import portal_client


def _url(url: str, base: str) -> str:
    parts = urlsplit(urljoin(base, url))
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _card_raw(card: dict, target: dict, uf_rate: Decimal | None) -> dict:
    if target["operation"] != "venta":
        raise ValueError("rental")
    comuna = card.get("comuna")
    if not is_known_comuna(str(comuna or "")):
        raise ValueError("unknown_comuna")
    m2 = card.get("m2")
    if uf_rate is not None and (not isinstance(m2, (int, float)) or m2 <= 0):
        raise ValueError("missing_m2")
    external_id = card.get("external_id")
    if not external_id or not card.get("title") or not card.get("url"):
        raise ValueError("missing_identity")
    metadata = dict(card.get("raw_metadata") or {})
    currency = metadata.get("currency_original")
    if currency == "UF" and metadata.get("price_uf"):
        amount = Decimal(str(metadata["price_uf"]))
        if not amount.is_finite() or amount <= 0:
            raise ValueError("invalid_price")
        price_clp = int(amount * uf_rate) if uf_rate is not None else None
        if uf_rate is not None:
            metadata.update({"price_uf": metadata["price_uf"], "price_clp_provenance": "derived_from_uf_real_rate", "uf_rate_used": str(uf_rate)})
    elif currency == "CLP" and card.get("price_clp"):
        price_clp = int(card["price_clp"])
    else:
        raise ValueError("invalid_price")
    metadata.update({"portal_card_first": True, "portal_target": target["label"], "area_source": "card_generic"})
    raw = {"source": "portalinmobiliario", "external_id": str(external_id), "title": card["title"], "url": _url(str(card["url"]), target["base_url"]), "comuna": comuna, "property_type": target["property_type"], "m2": m2, "price_clp": price_clp, "scraped_at": datetime.now(UTC), "raw_metadata": metadata, "_source_evidence": card.get("_source_evidence")}
    if currency == "UF":
        raw["price_uf"] = str(metadata["price_uf"])
    for field in ("bedrooms", "bathrooms", "parking"):
        if card.get(field): raw[field] = card[field]
    lat, lon = coordinate_pair(card.get("lat"), card.get("lon"))
    ev = metadata.get("coordinates_evidence") or {}
    if lat is not None and ev.get("source_listing_id") == str(external_id):
        raw.update(lat=lat, lon=lon, geocode_precision=metadata.get("geocode_precision", "unknown"))
    return raw


async def _persist(raw: dict, stats: Counter, *, factory=None) -> None:
    factory = factory or get_session_factory()
    async with factory() as session:
        repo = SqlAlchemyListingRepository(session)
        cleaned = clean_listing(raw, allow_incomplete=True)
        existing = await repo.find_by_source_external_id(cleaned.source, cleaned.external_id or "")
        changed = existing is None or _materially_changed(existing, cleaned)
        await process_listing(raw, listing_repo=repo, property_repo=SqlAlchemyPropertyRepository(session), price_history_repo=SqlAlchemyPriceHistoryRepository(session), allow_incomplete=True)
        await session.commit()
    stats["inserted" if existing is None else "updated" if changed else "known_unchanged"] += 1


async def run(*, apply: bool, max_pages: int, max_details: int, pause_s: float,
              max_geo_details: int | None = None, max_targets: int | None = None,
              factory=None, client=None, resolution=None, ledger=True) -> dict:
    from contextlib import AsyncExitStack
    settings = get_settings()
    factory = factory or get_session_factory()
    stats = Counter()
    if not settings.portal_http_enabled:
        return {"portal_disabled": 1}
    if max_pages != 1 or not 0 <= max_details <= 5 or pause_s < 3:
        raise ValueError("discovery_budget_exceeded")
    geo_budget = settings.portal_geo_detail_budget if max_geo_details is None else max_geo_details
    if not 0 <= geo_budget <= 5:
        raise ValueError("geo_budget_exceeded")
    run_id = await start_run(factory, "portalinmobiliario") if apply and ledger else None
    errors = []
    incomplete, fetched = [], {}
    pending = PendingPriceStore(factory, "portalinmobiliario")
    try:
        async with AsyncExitStack() as stack:
            if client is None:
                client = await stack.enter_async_context(portal_client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=30.0))
            if resolution is None:
                uf_http = await stack.enter_async_context(httpx.AsyncClient())
                resolution = await resolve_ingestion_rate(factory, uf_http)
            uf_info = resolution.exact
            uf_rate = uf_info.rate if uf_info else None
            stats["uf_provider_errors"] = len(resolution.errors)
            limiter = RateLimiter(max(3.0, pause_s))
            seen = set()

            async def accept(raw, current_resolution=resolution):
                if raw.get("price_clp") is None:
                    raw = annotate_pending(raw, current_resolution)
                    if apply:
                        await pending.hset("scraper:portalinmobiliario:pending_uf", str(raw["external_id"]), json.dumps(raw, default=str))
                    stats["pending_uf"] += 1
                    return
                if apply:
                    if uf_info and raw.get("price_uf"):
                        raw["raw_metadata"].update(uf_rate_source=uf_info.source, uf_rate_date=uf_info.rate_date.isoformat())
                    await _persist(raw, stats, factory=factory)
                    await pending.hdel("scraper:portalinmobiliario:pending_uf", str(raw["external_id"]))

            targets = [t for t in PORTAL_TARGETS if t["enabled"] and t["operation"] == "venta"]
            if max_targets is not None:
                if not 1 <= max_targets <= len(targets):
                    raise ValueError("invalid_target_budget")
                targets = targets[:max_targets]
            for target in targets:
                for page in range(1, max_pages + 1):
                    await limiter.wait()
                    response = await client.get(build_portal_page_url(build_portal_target_url(target), page))
                    stats["raw_cards_http"] += 1
                    if response.status_code != 200 or classify_portal_page_state(response.text, status_code=response.status_code) != "authenticated":
                        stats["blocked_or_captcha"] += 1
                        errors.append({"type": "PortalAccessError", "stage": "search", "http_status": response.status_code})
                        return dict(stats)
                    report = PortalInmobiliarioScraper.parse_listings_detailed(response.text, uf_to_clp=uf_rate)
                    stats["raw_cards"] += report["cards_detected"]
                    for card in report["items"]:
                        key = portal_dedupe_key(source="portalinmobiliario", external_id=card.get("external_id"), url=card.get("url"))
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        stats["unique_cards"] += 1
                        try:
                            raw = _card_raw(card, target, uf_rate)
                        except ValueError:
                            stats["card_incomplete"] += 1
                            incomplete.append((target, card))
                            continue
                        stats["valid_cards"] += 1
                        try:
                            await accept(raw)
                            stats["persisted_from_card" if apply else "card_complete"] += 1
                        except Exception as exc:
                            import traceback
                            traceback.print_exc()
                            stats["validation_errors"] += 1
                            errors.append(safe_error(exc, stage="card_persist"))
            for target, card in incomplete[:max_details]:
                await limiter.wait()
                stats["details_requested"] += 1
                response = await client.get(_url(str(card.get("url") or ""), target["base_url"]))
                from domain.geocoding.source_quality import mlc
                fetched[mlc(card.get("external_id"))] = response
                if response.status_code in (403, 429):
                    stats["blocked_or_captcha"] += 1
                    errors.append({"type": "PortalAccessError", "stage": "detail", "http_status": response.status_code})
                    return dict(stats)
                if classify_portal_detail_page_state(response.text, status_code=response.status_code) != "detail":
                    continue
                detail = parse_listing_detail_portal(response.text, str(response.url))
                try:
                    raw = portal_detail_to_raw(detail, target, uf_info=uf_info)
                except PortalCanaryReject as exc:
                    if str(exc) != "missing_real_uf_rate":
                        stats["detail_rejected"] += 1
                        continue
                    # A valid original UF detail is durable even without a convertible CLP price.
                    candidate = dict(detail, m2=detail.get("usable_area_m2") or detail.get("built_area_m2") or detail.get("total_area_m2"))
                    candidate["raw_metadata"] = dict(detail.get("raw_metadata") or {}, currency_original="UF", price_uf=detail.get("price_uf"))
                    raw = _card_raw(candidate, target, None)
                await accept(raw)
                stats["persisted_from_detail" if apply else "detail_valid"] += 1
            if apply:
                queued = await pending.hgetall("scraper:portalinmobiliario:pending_uf")
                for identity, payload in queued.items():
                    if identity in seen:
                        continue
                    raw = json.loads(payload)
                    from zoneinfo import ZoneInfo
                    observed = datetime.fromisoformat(raw["scraped_at"])
                    observed_day = observed.astimezone(ZoneInfo("America/Santiago")).date()
                    resolved = await resolve_ingestion_rate(factory, client, today=observed_day, refresh=False)
                    if resolved.exact is None:
                        continue
                    raw["scraped_at"] = observed
                    raw["price_clp"] = int(Decimal(str(raw["price_uf"])) * resolved.exact.rate)
                    metadata = raw["raw_metadata"]
                    for key in ("price_clp_missing_reason", "conversion_status", "reference_uf_rate", "reference_uf_date", "provisional_price_clp"):
                        metadata.pop(key, None)
                    metadata.update(price_clp_provenance="derived_from_uf_real_rate", uf_rate_used=str(resolved.exact.rate), uf_rate_date=observed_day.isoformat(), uf_rate_source=resolved.exact.source)
                    await _persist(raw, stats, factory=factory)
                    await pending.hdel("scraper:portalinmobiliario:pending_uf", identity)
                    stats["pending_uf_reprocessed"] += 1
            if apply and geo_budget:
                from workers.portal_geo_enrichment import enrich_geography
                await enrich_geography(session_factory=factory, client=client, limiter=limiter, budget=geo_budget,
                    fetched=fetched, stats=stats, max_attempts=settings.portal_geo_max_attempts,
                    cooldown_hours=settings.portal_geo_cooldown_hours)
                if stats["geo_stopped"]:
                    errors.append({"type": "PortalAccessError", "stage": "geography"})
        return dict(stats)
    except Exception as exc:
        errors.append(safe_error(exc, stage="portal_run"))
        raise
    finally:
        if run_id is not None:
            success = not errors and not stats["blocked_or_captcha"] and stats["raw_cards"] > 0
            await finish_run(factory, run_id, successful=success, counters=stats, errors=errors)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--max-details", type=int, default=5)
    parser.add_argument("--max-geo-details", type=int, default=None)
    parser.add_argument("--max-targets", type=int, default=None)
    parser.add_argument("--pause-s", type=float, default=3.0)
    args = parser.parse_args()
    try:
        report = asyncio.run(run(apply=args.apply, max_pages=args.max_pages, max_details=args.max_details,
            pause_s=args.pause_s, max_geo_details=args.max_geo_details, max_targets=args.max_targets))
        print(json.dumps(report, sort_keys=True))
        return 1 if report.get("blocked_or_captcha") or report.get("geo_stopped") or report.get("validation_errors") or not report.get("raw_cards") else 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(json.dumps({"error": safe_error(exc, stage="portal_entrypoint")}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
