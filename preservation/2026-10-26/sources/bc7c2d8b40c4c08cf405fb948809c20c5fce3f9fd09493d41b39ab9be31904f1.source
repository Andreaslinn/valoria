"""Orquestador de scraping y entrypoint CLI para desarrollo local."""
from __future__ import annotations

import argparse
import json
import asyncio
import logging
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.ports.uf_service import UFService, UFRateInfo
from services.yapo_price import YapoPendingUF, prepare_yapo_price
from services.ingestion_uf import resolve_ingestion_rate, annotate_pending
from services.ingestion_state import PendingPriceStore, start_run, finish_run, safe_error
from config import get_settings  # noqa: E402
from config.constants import (  # noqa: E402
    LISTING_STALE_DAYS,
    SCRAPER_HTTP_TIMEOUT_SEC,
    SCRAPER_MIN_REQUEST_INTERVAL_SEC,
    SCRAPER_USER_AGENT,
    YAPO_MAX_PAGES_HARD_LIMIT,
    YAPO_TARGETS,
)
from core.entities.listing import Listing  # noqa: E402
from core.exceptions import UnknownComunaError, ValidationError  # noqa: E402
from domain.ingestion.data_cleaning import clean_listing  # noqa: E402
from domain.ingestion.deduplication import make_fingerprint  # noqa: E402
from domain.ingestion.pipeline import geocode_precision_rank, process_listing  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.repositories import (  # noqa: E402
    SqlAlchemyListingRepository,
    SqlAlchemyPriceHistoryRepository,
    SqlAlchemyPropertyRepository,
)
from infrastructure.scrapers.base import RateLimiter, ScraperBase, ScraperResult  # noqa: E402
from infrastructure.scrapers.yapo import YapoScraper  # noqa: E402
from workers.rejection_logging import rejection_record

_log = logging.getLogger(__name__)

PersistStatus = Literal["inserted", "updated", "skipped"]
_MAX_UNKNOWN_COMUNA_SAMPLES = 20
_SCRAPE_STAGE_TIMEOUT_SEC = 180
_PERSIST_ITEM_TIMEOUT_SEC = 20
_PERSIST_MAX_ATTEMPTS = 2
_COMUNA_DROP_THRESHOLD_PCT = 35.0
_GEOCODE_UNKNOWN_INCREASE_THRESHOLD_PCT = 20.0


@dataclass(frozen=True)
class UnknownComunaSample:
    source: str | None
    external_id: str | None
    title: str | None
    location_text: str | None
    address: str | None
    description_snippet: str | None
    comuna_raw: str | None
    extraction_attempts: list[dict[str, Any]]
    url: str | None


@dataclass
class JobStats:
    source: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_sec: float = 0.0
    stage_durations_sec: dict[str, float] = field(default_factory=dict)
    scraped: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    incomplete_saved: int = 0
    discarded: int = 0
    critical_invalid: int = 0
    validation_errors: int = 0
    unexpected_errors: int = 0
    pending_uf: int = 0
    pending_uf_reprocessed: int = 0
    published_detail_requested: int = 0
    published_detail_captured: int = 0
    published_detail_rejected: int = 0
    blocked_or_captcha: int = 0
    fetch_errors: int = 0
    price_drop_alerts_created: int = 0
    price_drop_alerts_skipped: int = 0
    raw_scraped: int = 0
    comuna_detected: int = 0
    comuna_unknown: int = 0
    comuna_detected_from_title: int = 0
    comuna_detected_from_location: int = 0
    comuna_detected_from_description: int = 0
    comuna_detected_from_alias: int = 0
    comuna_detected_from_partial_match: int = 0
    outside_rm_candidates: int = 0
    rm_scope_count: int = 0
    general_scope_count: int = 0
    by_target: dict[str, dict[str, int]] = field(default_factory=dict)
    by_comuna: dict[str, dict[str, int]] = field(default_factory=dict)
    by_property_type: dict[str, int] = field(default_factory=dict)
    by_geocode_precision: dict[str, int] = field(default_factory=dict)
    geocode_precision_before: dict[str, int] = field(default_factory=dict)
    geocode_precision_after: dict[str, int] = field(default_factory=dict)
    active_before: dict[str, dict[str, int]] = field(default_factory=dict)
    active_after: dict[str, dict[str, int]] = field(default_factory=dict)
    geocode_precision_transitions: dict[str, int] = field(default_factory=dict)
    geocode_fallbacks: dict[str, int] = field(default_factory=dict)
    health_warnings: list[str] = field(default_factory=list)
    reason_counts: dict[str, int] = None  # type: ignore[assignment]
    unknown_comuna_samples: list[UnknownComunaSample] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.reason_counts is None:
            self.reason_counts = {}

    @property
    def valid(self) -> int:
        return self.inserted + self.updated + self.skipped

    @property
    def processed(self) -> int:
        """Compatibilidad con tests/callers existentes: filas insertadas o actualizadas."""
        return self.inserted + self.updated

    @property
    def success_rate(self) -> float:
        if self.scraped == 0:
            return 0.0
        return self.valid / self.scraped


@dataclass(frozen=True)
class PersistOutcome:
    listing: Listing
    status: PersistStatus
    previous_geocode_precision: str | None = None


async def run_scraper_job(
    scraper: ScraperBase,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    mark_stale: bool = False,
    pending_uf_store: Any = None,
    uf_info: UFRateInfo | None = None,
    ingestion_resolution=None,
) -> JobStats:
    """Corre un scraper y persiste sus resultados via process_listing."""
    job_started_monotonic = time.monotonic()
    started_at = datetime.now(UTC)
    _log_event("scraper_job_started", source=scraper.source_name, started_at=started_at.isoformat())
    active_before = await _active_dimension_counts(session_factory)
    scrape_started = time.monotonic()
    raw_results: list[ScraperResult] = await asyncio.wait_for(
        scraper.scrape(),
        timeout=_SCRAPE_STAGE_TIMEOUT_SEC,
    )
    scrape_duration = time.monotonic() - scrape_started
    stats = JobStats(
        source=scraper.source_name,
        started_at=started_at,
        scraped=len(raw_results),
        raw_scraped=int(getattr(scraper, "last_raw_count", len(raw_results))),
        active_before=active_before,
        geocode_precision_before=active_before.get("geocode_precision", {}),
        stage_durations_sec={"scrape": _round_duration(scrape_duration)},
    )
    stats.blocked_or_captcha = int(getattr(scraper, "last_blocked_or_captcha_count", 0))
    stats.fetch_errors = int(getattr(scraper, "last_fetch_error_count", 0))
    _init_target_stats(stats, scraper, raw_results)

    replay_ids = set()
    if pending_uf_store is not None and (uf_info is not None or isinstance(pending_uf_store, PendingPriceStore)):
        queued = await pending_uf_store.hgetall("scraper:yapo:pending_uf")
        fresh_ids = {str(raw.get("external_id")) for raw in raw_results}
        for key, value in list(queued.items())[:100]:
            identity = key.decode() if isinstance(key, bytes) else str(key)
            if identity in fresh_ids:
                replay_ids.add(identity)
                continue
            try:
                saved = json.loads(value)
                if saved.get("source") != "yapo" or str(saved.get("external_id")) != identity:
                    raise ValueError("pending identity mismatch")
                saved["scraped_at"] = datetime.fromisoformat(saved["scraped_at"])
                raw_results.append(saved)
                replay_ids.add(identity)
            except (ValueError, KeyError, TypeError):
                stats.unexpected_errors += 1
                _log.error("Invalid pending UF record retained: %s", identity)
    persist_started = time.monotonic()
    for raw in raw_results:
        try:
            effective_info = uf_info
            if isinstance(pending_uf_store, PendingPriceStore) and str(raw.get("external_id")) in replay_ids:
                from zoneinfo import ZoneInfo
                observed_day = raw["scraped_at"].astimezone(ZoneInfo("America/Santiago")).date()
                resolved = await resolve_ingestion_rate(session_factory, None, today=observed_day, refresh=False)
                effective_info = resolved.exact
            raw = prepare_yapo_price(raw, effective_info)
        except YapoPendingUF:
            raw = annotate_pending(raw, ingestion_resolution)
            if pending_uf_store is None:
                raise  # Never silently discard a valid original UF price.
            await pending_uf_store.hset(
                "scraper:yapo:pending_uf", str(raw["external_id"]),
                json.dumps(raw, default=str, ensure_ascii=False),
            )
            stats.pending_uf += 1
            continue
        outcome = await _persist_one_with_retries(raw, session_factory)
        if outcome is None:
            if _is_validation_failure(raw):
                stats.validation_errors += 1
                stats.critical_invalid += 1
                stats.discarded += 1
                _count_reasons(stats, raw.get("__discard_reason__"))
            else:
                stats.unexpected_errors += 1
                stats.discarded += 1
            continue

        if str(raw.get("external_id")) in replay_ids:
            stats.pending_uf_reprocessed += 1
        if pending_uf_store is not None and raw.get("source") == "yapo":
            await pending_uf_store.hdel("scraper:yapo:pending_uf", str(raw["external_id"]))
        if outcome.status == "inserted":
            stats.inserted += 1
        elif outcome.status == "updated":
            stats.updated += 1
        else:
            stats.skipped += 1
        _count_target_outcome(stats, outcome)
        _count_listing_dimensions(stats, outcome)
        _count_geocode_transition(stats, outcome)
        if outcome.listing.status == "incomplete":
            stats.incomplete_saved += 1
            _count_reasons(stats, outcome.listing.raw_metadata.get("data_quality_warnings", []))
        if "unknown_comuna" in _quality_warnings(outcome.listing.raw_metadata):
            stats.comuna_unknown += 1
            _maybe_add_unknown_comuna_sample(stats, raw, outcome.listing.raw_metadata)
        else:
            stats.comuna_detected += 1
            _count_comuna_detection_strategy(stats, outcome.listing.raw_metadata)
        if outcome.listing.raw_metadata.get("outside_rm_candidate") is True:
            stats.outside_rm_candidates += 1
    stats.stage_durations_sec["persist"] = _round_duration(time.monotonic() - persist_started)

    # A bounded discovery page is not evidence that an existing listing was
    # removed. Only an explicit detail refresh may transition a listing.
    if mark_stale:
        stale_started = time.monotonic()
        await _mark_stale_listings(session_factory)
        stats.stage_durations_sec["mark_stale"] = _round_duration(time.monotonic() - stale_started)
    active_after = await _active_dimension_counts(session_factory)
    stats.active_after = active_after
    stats.geocode_precision_after = active_after.get("geocode_precision", {})
    stats.finished_at = datetime.now(UTC)
    stats.duration_sec = _round_duration(time.monotonic() - job_started_monotonic)
    stats.health_warnings = _detect_health_warnings(stats)
    _log_health_summary(stats)

    _log.info(
        "Job terminado: source=%s total_raw=%d total_unique=%d valid=%d inserted=%d updated=%d "
        "skipped=%d val_errors=%d unexp_errors=%d price_drop_alerts_created=%d "
        "price_drop_alerts_skipped=%d comuna_detected=%d comuna_unknown=%d "
        "comuna_detection_rate_pct=%.1f comuna_detected_from_title=%d "
        "comuna_detected_from_location=%d comuna_detected_from_description=%d "
        "comuna_detected_from_alias=%d comuna_detected_from_partial_match=%d "
        "outside_rm_candidates=%d rm_scope_count=%d general_scope_count=%d by_target=%s",
        scraper.source_name,
        stats.raw_scraped,
        stats.scraped,
        stats.valid,
        stats.inserted,
        stats.updated,
        stats.skipped,
        stats.validation_errors,
        stats.unexpected_errors,
        stats.price_drop_alerts_created,
        stats.price_drop_alerts_skipped,
        stats.comuna_detected,
        stats.comuna_unknown,
        _comuna_detection_rate(stats),
        stats.comuna_detected_from_title,
        stats.comuna_detected_from_location,
        stats.comuna_detected_from_description,
        stats.comuna_detected_from_alias,
        stats.comuna_detected_from_partial_match,
        stats.outside_rm_candidates,
        stats.rm_scope_count,
        stats.general_scope_count,
        stats.by_target,
    )
    return stats


class _ResolvedUF(UFService):
    """Reuse the verified rate for this run without a second provider request."""
    def __init__(self, info: UFRateInfo):
        self.info = info

    async def get_current_rate(self):
        return self.info.rate

    async def get_current_rate_info(self):
        return self.info


async def _run_yapo_once(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    *,
    max_pages: int | None = None,
    min_pause_s: float = 0.0,
    max_targets: int | None = None,
    resolution=None,
) -> JobStats:
    """Construye Yapo con dependencias reales y ejecuta una pasada local."""
    settings = get_settings()
    session_factory = session_factory or get_session_factory()

    async with httpx.AsyncClient(
        timeout=SCRAPER_HTTP_TIMEOUT_SEC,
        headers={"User-Agent": SCRAPER_USER_AGENT},
        follow_redirects=True,
    ) as http:
        redis = Redis.from_url(settings.redis_url)
        try:
            resolution = resolution or await resolve_ingestion_rate(session_factory, http)
            uf_info = resolution.exact
            targets = _targets_for_run(max_pages=max_pages)
            if max_targets is not None:
                if not 1 <= max_targets <= len(targets):
                    raise ValueError("invalid_target_budget")
                targets = targets[:max_targets]
            scraper = YapoScraper(
                http_client=http,
                rate_limiter=RateLimiter(
                    min_interval=max(SCRAPER_MIN_REQUEST_INTERVAL_SEC, min_pause_s)
                ),
                targets=targets,
                uf_service=_ResolvedUF(uf_info) if uf_info is not None else None,
            )
            stats = await run_scraper_job(scraper, session_factory, mark_stale=False,
                pending_uf_store=PendingPriceStore(session_factory, "yapo", legacy_redis=redis),
                uf_info=uf_info, ingestion_resolution=resolution)
            if not stats.blocked_or_captcha and not stats.fetch_errors:
                from workers.published_detail_enrichment import enrich_yapo_details
                await enrich_yapo_details(session_factory, http, scraper._rate, budget=5, stats=stats)
            return stats
        finally:
            await redis.aclose()


async def run_yapo_once(session_factory=None, *, max_pages=None, min_pause_s=0.0, max_targets=None, resolution=None):
    from dataclasses import asdict
    factory = session_factory or get_session_factory()
    run_id = await start_run(factory, "yapo")
    try:
        stats = await _run_yapo_once(factory, max_pages=max_pages, min_pause_s=min_pause_s,
                                    max_targets=max_targets, resolution=resolution)
    except Exception as exc:
        await finish_run(factory, run_id, successful=False, errors=[safe_error(exc, stage="yapo_run")])
        raise
    errors = []
    if stats.unexpected_errors:
        errors.append({"type": "PersistenceErrors", "stage": "yapo_persist", "count": stats.unexpected_errors})
    if stats.blocked_or_captcha:
        errors.append({"type": "YapoAccessError", "stage": "search", "count": stats.blocked_or_captcha})
    if stats.fetch_errors:
        errors.append({"type": "SourceFetchErrors", "stage": "search", "count": stats.fetch_errors})
    await finish_run(factory, run_id, successful=not errors and stats.raw_scraped > 0,
                     counters=asdict(stats), errors=errors)
    return stats


def print_job_start(source: str) -> None:
    print("== AVM scraper job: inicio ==")
    print(f"Fuente principal: {source}")


def print_job_summary(stats: JobStats) -> None:
    print("== AVM scraper job: resumen ==")
    print(f"fuente: {stats.source or 'desconocida'}")
    if stats.started_at is not None:
        print(f"started_at: {stats.started_at.isoformat()}")
    if stats.finished_at is not None:
        print(f"finished_at: {stats.finished_at.isoformat()}")
    print(f"duration_sec: {stats.duration_sec}")
    if stats.stage_durations_sec:
        print("stage_durations_sec:")
        for stage, duration in sorted(stats.stage_durations_sec.items()):
            print(f"  {stage}: {duration}")
    print(f"encontrados_raw: {stats.raw_scraped or stats.scraped}")
    print(f"encontrados_unicos: {stats.scraped}")
    print(f"encontrados: {stats.scraped}")
    print(f"validos: {stats.valid}")
    print(f"insertados: {stats.inserted}")
    print(f"actualizados: {stats.updated}")
    print(f"duplicados/saltados: {stats.skipped}")
    print(f"incompletos_guardados: {stats.incomplete_saved}")
    print(f"invalidos_criticos: {stats.critical_invalid}")
    print(f"descartados: {stats.discarded}")
    print(f"errores: {stats.validation_errors + stats.unexpected_errors}")
    print(f"errores_validacion: {stats.validation_errors}")
    print(f"errores_inesperados: {stats.unexpected_errors}")
    print(f"pendientes_tasa_uf: {stats.pending_uf}")
    print(f"pendientes_uf_reprocesados: {stats.pending_uf_reprocessed}")
    print(f"alertas_rebaja_creadas: {stats.price_drop_alerts_created}")
    print(f"alertas_rebaja_omitidas: {stats.price_drop_alerts_skipped}")
    print(f"comuna_detected: {stats.comuna_detected}")
    print(f"comuna_unknown: {stats.comuna_unknown}")
    print(f"comuna_detection_rate_pct: {_comuna_detection_rate(stats):.1f}")
    print(f"comuna_detected_from_title: {stats.comuna_detected_from_title}")
    print(f"comuna_detected_from_location: {stats.comuna_detected_from_location}")
    print(f"comuna_detected_from_description: {stats.comuna_detected_from_description}")
    print(f"comuna_detected_from_alias: {stats.comuna_detected_from_alias}")
    print(f"comuna_detected_from_partial_match: {stats.comuna_detected_from_partial_match}")
    print(f"outside_rm_candidates: {stats.outside_rm_candidates}")
    print(f"rm_scope_count: {stats.rm_scope_count}")
    print(f"general_scope_count: {stats.general_scope_count}")
    if stats.by_target:
        print("by_target:")
        for label, values in sorted(stats.by_target.items()):
            print(
                f"  {label}: raw={values.get('raw', 0)} unique={values.get('unique', 0)} "
                f"inserted={values.get('inserted', 0)} updated={values.get('updated', 0)} "
                f"skipped={values.get('skipped', 0)} detected={values.get('detected', 0)} "
                f"unknown={values.get('unknown', 0)} outside_rm={values.get('outside_rm', 0)}"
            )
    if stats.by_comuna:
        print("por_comuna:")
        for comuna, values in sorted(stats.by_comuna.items()):
            print(
                f"  {comuna}: total={values.get('total', 0)} inserted={values.get('inserted', 0)} "
                f"updated={values.get('updated', 0)} skipped={values.get('skipped', 0)} "
                f"incomplete={values.get('incomplete', 0)}"
            )
    if stats.by_property_type:
        print("por_property_type:")
        for property_type, count in sorted(stats.by_property_type.items()):
            print(f"  {property_type}: {count}")
    if stats.by_geocode_precision:
        print("por_geocode_precision:")
        for precision, count in sorted(stats.by_geocode_precision.items()):
            print(f"  {precision}: {count}")
    if stats.geocode_precision_before or stats.geocode_precision_after:
        print("geocode_precision_before:")
        for precision, count in sorted(stats.geocode_precision_before.items()):
            print(f"  {precision}: {count}")
        print("geocode_precision_after:")
        for precision, count in sorted(stats.geocode_precision_after.items()):
            print(f"  {precision}: {count}")
    if stats.geocode_precision_transitions:
        print("geocode_precision_transitions:")
        for transition, count in sorted(stats.geocode_precision_transitions.items()):
            print(f"  {transition}: {count}")
    if stats.geocode_fallbacks:
        print("geocode_fallbacks:")
        for precision, count in sorted(stats.geocode_fallbacks.items()):
            print(f"  {precision}: {count}")
    print("health:")
    print(f"  status: {'warning' if stats.health_warnings else 'ok'}")
    if stats.health_warnings:
        for warning in stats.health_warnings:
            print(f"  warning: {warning}")
    if stats.active_before or stats.active_after:
        print("active_before_by_source:")
        for source, count in sorted(stats.active_before.get("source", {}).items()):
            print(f"  {source}: {count}")
        print("active_after_by_source:")
        for source, count in sorted(stats.active_after.get("source", {}).items()):
            print(f"  {source}: {count}")

    if stats.scraped == 0:
        print("Yapo no devolvio resultados en esta corrida.")
    elif stats.valid == 0:
        print("Yapo devolvio resultados, pero ninguno paso la validacion del pipeline.")
    if stats.reason_counts:
        print("razones:")
        for reason, count in sorted(stats.reason_counts.items()):
            print(f"  {reason}: {count}")
    if stats.unknown_comuna_samples:
        print("=== UNKNOWN COMUNA SAMPLE ===")
        for index, sample in enumerate(stats.unknown_comuna_samples, start=1):
            print(f"[{index}]")
            print(f"title: {sample.title or ''}")
            print(f"location_text: {sample.location_text or ''}")
            print(f"address: {sample.address or ''}")
            print(f"description: {sample.description_snippet or ''}")
            print(f"comuna_raw: {sample.comuna_raw or ''}")
            print(f"url: {sample.url or ''}")
            if sample.extraction_attempts:
                print("extraction_attempts:")
                for attempt in sample.extraction_attempts:
                    print(
                        "  "
                        f"{attempt.get('source')}: "
                        f"text={attempt.get('text')!r} "
                        f"normalized={attempt.get('normalized_text')!r} "
                        f"strategy={attempt.get('match_strategy')!r} "
                        f"value={attempt.get('match_value')!r}"
                    )


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    print_job_start("yapo")
    try:
        stats = await run_yapo_once(max_pages=args.max_pages)
    except SQLAlchemyError as e:
        print("ERROR: no se pudo conectar o escribir en la base de datos.")
        print(f"Detalle: {e}")
        return 2
    except httpx.HTTPError as e:
        print("ERROR: Yapo no pudo descargarse correctamente.")
        print(f"Detalle: {e}")
        return 3
    except Exception as e:
        print("ERROR: el scraper job fallo antes de completar.")
        print(f"Detalle: {type(e).__name__}: {e}")
        return 1

    print_job_summary(stats)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ejecuta scraper Yapo AVM.")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help=(
            "Override opcional de páginas por target Yapo. "
            f"Por defecto usa YAPO_TARGETS; límite duro {YAPO_MAX_PAGES_HARD_LIMIT}."
        ),
    )
    args, _ = parser.parse_known_args(argv)
    if args.max_pages is not None:
        args.max_pages = max(1, min(args.max_pages, YAPO_MAX_PAGES_HARD_LIMIT))
    return args


_VALIDATION_FLAG = "__validation_failure__"


async def _persist_one_with_retries(
    raw: ScraperResult,
    session_factory: async_sessionmaker[AsyncSession],
) -> PersistOutcome | None:
    for attempt in range(1, _PERSIST_MAX_ATTEMPTS + 1):
        try:
            return await asyncio.wait_for(
                _persist_one(raw, session_factory),
                timeout=_PERSIST_ITEM_TIMEOUT_SEC,
            )
        except (TimeoutError, SQLAlchemyError) as e:
            _log_event(
                "persist_retryable_error",
                source=raw.get("source"),
                external_id=raw.get("external_id"),
                attempt=attempt,
                max_attempts=_PERSIST_MAX_ATTEMPTS,
                error_type=type(e).__name__,
                error=str(e),
            )
            if attempt >= _PERSIST_MAX_ATTEMPTS:
                _log.exception("Persistencia agotó retries para listing=%r", raw.get("external_id"))
                return None
            await asyncio.sleep(0.5 * attempt)
    return None


async def _persist_one(
    raw: ScraperResult,
    session_factory: async_sessionmaker[AsyncSession],
) -> PersistOutcome | None:
    async with session_factory() as session:
        repos = _build_repos(session)
        try:
            cleaned = clean_listing(dict(raw), allow_incomplete=True)
            fingerprint = make_fingerprint(cleaned)
            existing = await _find_existing_for_raw(repos["listing_repo"], cleaned, fingerprint)
            previous_geocode_precision = existing.geocode_precision if existing is not None else None
            status: PersistStatus = "inserted"
            if existing is not None:
                status = "updated" if _has_material_changes(existing, cleaned) else "skipped"

            listing = await process_listing(dict(raw), **repos, allow_incomplete=True)
            await session.commit()
            return PersistOutcome(
                listing=listing,
                status=status,
                previous_geocode_precision=previous_geocode_precision,
            )
        except IntegrityError:
            await session.rollback()
            _log.exception(
                "IntegrityError persistiendo listing source=%r external_id=%r; reintentando como update.",
                raw.get("source"),
                raw.get("external_id"),
            )
            try:
                listing = await process_listing(dict(raw), **repos, allow_incomplete=True)
                await session.commit()
                return PersistOutcome(listing=listing, status="updated")
            except Exception:
                await session.rollback()
                _log.exception("Reintento post-IntegrityError falló para listing: %r", raw.get("external_id"))
                return None
        except (ValidationError, UnknownComunaError) as e:
            await session.rollback()
            _log.warning("listing_validation_rejected %s", json.dumps(rejection_record(raw, e), ensure_ascii=True, allow_nan=False))
            raw[_VALIDATION_FLAG] = True  # type: ignore[typeddict-unknown-key]
            raw["__discard_reason__"] = _classify_discard_reason(e)  # type: ignore[typeddict-unknown-key]
            return None
        except SQLAlchemyError:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            _log.exception("Error inesperado persistiendo listing: %r", raw.get("external_id"))
            return None


def _is_validation_failure(raw: ScraperResult) -> bool:
    return bool(raw.get(_VALIDATION_FLAG))  # type: ignore[typeddict-item]


def _has_material_changes(existing: Listing, cleaned: Any) -> bool:
    return any(
        (
            cleaned.price.clp != existing.price.clp,
            cleaned.title != existing.title,
            cleaned.url != existing.url,
            cleaned.comuna != existing.comuna,
            cleaned.property_type != existing.property_type,
            cleaned.m2 != existing.m2,
            cleaned.built_area_m2 != existing.built_area_m2,
            cleaned.land_area_m2 != existing.land_area_m2,
            cleaned.usable_area_m2 != existing.usable_area_m2,
            cleaned.bedrooms != existing.bedrooms,
            cleaned.bathrooms != existing.bathrooms,
            cleaned.parking != existing.parking,
            _would_update_coordinates(existing, cleaned),
            _would_update_geocode_precision(existing, cleaned),
            cleaned.raw_metadata.get("data_quality_warnings") != existing.raw_metadata.get("data_quality_warnings"),
        )
    )


def _would_update_geocode_precision(existing: Listing, cleaned: Any) -> bool:
    if cleaned.geocode_precision is None:
        return False
    if _would_replace_weak_card_text_hint(existing, cleaned):
        return cleaned.geocode_precision != existing.geocode_precision
    if geocode_precision_rank(cleaned.geocode_precision) < geocode_precision_rank(existing.geocode_precision):
        return False
    return cleaned.geocode_precision != existing.geocode_precision


def _would_update_coordinates(existing: Listing, cleaned: Any) -> bool:
    if cleaned.coordinates is None or cleaned.coordinates == existing.coordinates:
        return False
    if existing.coordinates is None:
        return True
    return geocode_precision_rank(cleaned.geocode_precision) >= geocode_precision_rank(existing.geocode_precision)


def _would_replace_weak_card_text_hint(existing: Listing, cleaned: Any) -> bool:
    if existing.geocode_precision != "address":
        return False
    if existing.raw_metadata.get("geocode_precision_reason") != "card_text":
        return False
    if cleaned.raw_metadata.get("geocode_precision_reason") == "card_text":
        return False
    return cleaned.geocode_precision in {"comuna", "unknown"}


async def _find_existing_for_raw(
    listing_repo: SqlAlchemyListingRepository,
    cleaned: Any,
    fingerprint: str,
) -> Listing | None:
    if cleaned.external_id is not None:
        existing = await listing_repo.find_by_source_external_id(cleaned.source, cleaned.external_id)
        if existing is not None:
            return existing
    return await listing_repo.find_by_fingerprint(fingerprint)


async def _active_geocode_precision_counts(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, int]:
    return (await _active_dimension_counts(session_factory)).get("geocode_precision", {})


async def _active_dimension_counts(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, dict[str, int]]:
    try:
        async with session_factory() as session:
            repo = SqlAlchemyListingRepository(session)
            listings = await repo.list_active(limit=None)
    except Exception:
        _log.exception("No se pudo contar dimensiones activas; el job continua.")
        return {}
    counts: dict[str, Counter[str]] = {
        "source": Counter(),
        "comuna": Counter(),
        "property_type": Counter(),
        "geocode_precision": Counter(),
    }
    for listing in listings:
        counts["source"][listing.source or "unknown"] += 1
        counts["comuna"][listing.comuna or "unknown"] += 1
        counts["property_type"][listing.property_type or "unknown"] += 1
        counts["geocode_precision"][listing.geocode_precision or "unknown"] += 1
    return {name: dict(counter) for name, counter in counts.items()}


def _targets_for_run(*, max_pages: int | None) -> list[dict[str, Any]]:
    if max_pages is None:
        return [dict(target) for target in YAPO_TARGETS]
    return [{**target, "max_pages": max_pages} for target in YAPO_TARGETS]


def _init_target_stats(
    stats: JobStats,
    scraper: ScraperBase,
    raw_results: list[ScraperResult],
) -> None:
    target_stats = getattr(scraper, "last_target_stats", [])
    for target in target_stats:
        label = str(getattr(target, "label", "unknown"))
        stats.by_target.setdefault(label, {})
        stats.by_target[label]["raw"] = int(getattr(target, "raw_count", 0))
        stats.by_target[label]["unique"] = int(getattr(target, "unique_count", 0))

    for raw in raw_results:
        metadata = raw.get("raw_metadata")
        raw_metadata = metadata if isinstance(metadata, dict) else {}
        label = str(raw_metadata.get("target_label") or "unknown")
        scope = str(raw_metadata.get("target_scope") or "")
        stats.by_target.setdefault(label, {})
        stats.by_target[label]["unique"] = stats.by_target[label].get("unique", 0) + (
            0 if "unique" in stats.by_target[label] and target_stats else 1
        )
        if scope == "rm":
            stats.rm_scope_count += 1
        elif scope == "general":
            stats.general_scope_count += 1


def _count_target_outcome(stats: JobStats, outcome: PersistOutcome) -> None:
    label = str(outcome.listing.raw_metadata.get("target_label") or "unknown")
    target = stats.by_target.setdefault(label, {})
    target[outcome.status] = target.get(outcome.status, 0) + 1
    if "unknown_comuna" in _quality_warnings(outcome.listing.raw_metadata):
        target["unknown"] = target.get("unknown", 0) + 1
    else:
        target["detected"] = target.get("detected", 0) + 1
    if outcome.listing.raw_metadata.get("outside_rm_candidate") is True:
        target["outside_rm"] = target.get("outside_rm", 0) + 1


def _count_listing_dimensions(stats: JobStats, outcome: PersistOutcome) -> None:
    listing = outcome.listing
    comuna = listing.comuna or "unknown"
    comuna_counts = stats.by_comuna.setdefault(comuna, {})
    comuna_counts["total"] = comuna_counts.get("total", 0) + 1
    comuna_counts[outcome.status] = comuna_counts.get(outcome.status, 0) + 1
    if listing.status == "incomplete":
        comuna_counts["incomplete"] = comuna_counts.get("incomplete", 0) + 1

    property_type = listing.property_type or "unknown"
    stats.by_property_type[property_type] = stats.by_property_type.get(property_type, 0) + 1

    precision = listing.geocode_precision or "unknown"
    stats.by_geocode_precision[precision] = stats.by_geocode_precision.get(precision, 0) + 1


def _count_geocode_transition(stats: JobStats, outcome: PersistOutcome) -> None:
    before = outcome.previous_geocode_precision or "unknown"
    after = outcome.listing.geocode_precision or "unknown"
    if before != after:
        transition = f"{before}->{after}"
        stats.geocode_precision_transitions[transition] = stats.geocode_precision_transitions.get(transition, 0) + 1
        if geocode_precision_rank(after) > geocode_precision_rank(before):
            _log.info(
                "geocode_precision upgrade listing_id=%s external_id=%s %s",
                outcome.listing.id,
                outcome.listing.external_id,
                transition,
            )
    if after in {"comuna", "comuna_centroid", "unknown"}:
        stats.geocode_fallbacks[after] = stats.geocode_fallbacks.get(after, 0) + 1


def _count_reasons(stats: JobStats, reasons: Any) -> None:
    if isinstance(reasons, str):
        reasons = [reasons]
    if not isinstance(reasons, list):
        return
    counts = Counter(str(reason) for reason in reasons)
    for reason, count in counts.items():
        stats.reason_counts[reason] = stats.reason_counts.get(reason, 0) + count


def _quality_warnings(raw_metadata: dict[str, Any]) -> list[str]:
    warnings = raw_metadata.get("data_quality_warnings", [])
    return list(warnings) if isinstance(warnings, list) else []


def _count_comuna_detection_strategy(stats: JobStats, raw_metadata: dict[str, Any]) -> None:
    source = raw_metadata.get("comuna_extraction_source")
    if source == "title":
        stats.comuna_detected_from_title += 1
    elif source == "location":
        stats.comuna_detected_from_location += 1
    elif source == "description":
        stats.comuna_detected_from_description += 1

    strategy = raw_metadata.get("comuna_match_strategy")
    if strategy == "alias":
        stats.comuna_detected_from_alias += 1
    elif strategy == "partial_match":
        stats.comuna_detected_from_partial_match += 1


def _maybe_add_unknown_comuna_sample(
    stats: JobStats,
    raw: ScraperResult,
    raw_metadata: dict[str, Any],
) -> None:
    if len(stats.unknown_comuna_samples) >= _MAX_UNKNOWN_COMUNA_SAMPLES:
        return
    stats.unknown_comuna_samples.append(_unknown_comuna_sample(raw, raw_metadata))


def _unknown_comuna_sample(
    raw: ScraperResult,
    raw_metadata: dict[str, Any],
) -> UnknownComunaSample:
    return UnknownComunaSample(
        source=_optional_str(raw.get("source")),
        external_id=_optional_str(raw.get("external_id")),
        title=_optional_str(raw.get("title")),
        location_text=_first_text(raw, raw_metadata, ("location_text", "location", "comuna")),
        address=_first_text(raw, raw_metadata, ("address", "address_label")),
        description_snippet=_snippet(_first_text(raw, raw_metadata, ("description", "descripcion")), max_chars=120),
        comuna_raw=_optional_str(raw_metadata.get("comuna_raw")),
        extraction_attempts=_safe_attempts(raw_metadata.get("comuna_extraction_attempts")),
        url=_optional_str(raw.get("url")),
    )


def _first_text(
    raw: ScraperResult,
    raw_metadata: dict[str, Any],
    keys: tuple[str, ...],
) -> str | None:
    metadata = raw.get("raw_metadata")
    raw_meta = metadata if isinstance(metadata, dict) else {}
    for key in keys:
        value = _optional_str(raw.get(key))  # type: ignore[typeddict-item]
        if value:
            return value
        value = _optional_str(raw_metadata.get(key))
        if value:
            return value
        value = _optional_str(raw_meta.get(key))
        if value:
            return value
    return None


def _safe_attempts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _snippet(value: str | None, *, max_chars: int) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _comuna_detection_rate(stats: JobStats) -> float:
    total = stats.comuna_detected + stats.comuna_unknown
    if total == 0:
        return 0.0
    return round(stats.comuna_detected / total * 100, 1)


def _detect_health_warnings(stats: JobStats) -> list[str]:
    warnings: list[str] = []
    if stats.raw_scraped == 0:
        warnings.append("scraper_zero_raw_results")
    if stats.scraped == 0:
        warnings.append("scraper_zero_unique_results")
    if stats.raw_scraped > 0 and stats.valid == 0:
        warnings.append("pipeline_zero_valid_results")
    if stats.raw_scraped >= 50 and stats.processed == 0:
        warnings.append("no_insert_or_update_despite_raw_results")

    before_unknown = stats.geocode_precision_before.get("unknown", 0)
    after_unknown = stats.geocode_precision_after.get("unknown", 0)
    unknown_delta = after_unknown - before_unknown
    unknown_threshold = max(10, int(before_unknown * (_GEOCODE_UNKNOWN_INCREASE_THRESHOLD_PCT / 100)))
    if unknown_delta > unknown_threshold:
        warnings.append(f"geocode_unknown_increase before={before_unknown} after={after_unknown} delta={unknown_delta}")

    before_comunas = stats.active_before.get("comuna", {})
    after_comunas = stats.active_after.get("comuna", {})
    for comuna, before_count in sorted(before_comunas.items()):
        if before_count < 8:
            continue
        after_count = after_comunas.get(comuna, 0)
        drop_pct = (before_count - after_count) / before_count * 100
        if drop_pct >= _COMUNA_DROP_THRESHOLD_PCT:
            warnings.append(
                f"comuna_active_drop comuna={comuna} before={before_count} after={after_count} drop_pct={drop_pct:.1f}"
            )
    return warnings


def _log_health_summary(stats: JobStats) -> None:
    _log_event(
        "scraper_job_health",
        source=stats.source,
        status="warning" if stats.health_warnings else "ok",
        warnings=stats.health_warnings,
        duration_sec=stats.duration_sec,
        raw=stats.raw_scraped,
        unique=stats.scraped,
        inserted=stats.inserted,
        updated=stats.updated,
        skipped=stats.skipped,
        validation_errors=stats.validation_errors,
        by_property_type=stats.by_property_type,
        by_geocode_precision=stats.by_geocode_precision,
        stage_durations_sec=stats.stage_durations_sec,
    )


def _log_event(event: str, **fields: Any) -> None:
    payload = " ".join(f"{key}={value!r}" for key, value in fields.items())
    _log.info("event=%s %s", event, payload)


def _round_duration(value: float) -> float:
    return round(float(value), 3)


def _classify_discard_reason(exc: Exception) -> str:
    msg = str(exc)
    if "missing_price" in msg or "price_clp" in msg:
        return "missing_price"
    if "invalid_url" in msg or "url" in msg:
        return "invalid_url"
    if "m2" in msg:
        return "missing_m2"
    if "Comuna desconocida" in msg or "comuna" in msg:
        return "unknown_comuna"
    return "critical_invalid"


async def _mark_stale_listings(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    stale_days: int = LISTING_STALE_DAYS,
) -> int:
    try:
        async with session_factory() as session:
            repo = SqlAlchemyListingRepository(session)
            count = await repo.mark_stale_listings(stale_days=stale_days)
            await session.commit()
            _log.info(
                "Marked %d listings as stale (not seen in %d days)",
                count,
                stale_days,
            )
            return count
    except Exception:
        _log.exception("No se pudieron marcar listings stale; el scraping queda completado.")
        return 0


def _build_repos(session: AsyncSession) -> dict[str, Any]:
    return {
        "listing_repo": SqlAlchemyListingRepository(session),
        "property_repo": SqlAlchemyPropertyRepository(session),
        "price_history_repo": SqlAlchemyPriceHistoryRepository(session),
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(asyncio.run(main()))
