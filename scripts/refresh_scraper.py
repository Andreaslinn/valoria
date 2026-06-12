"""Manual entrypoint for the minimal refresh scraper.

Usage:
    python scripts/refresh_scraper.py --limit 100 --stale-days 30
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
from redis.asyncio import Redis
from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_settings  # noqa: E402
from config.constants import (  # noqa: E402
    SCRAPER_HTTP_TIMEOUT_SEC,
    SCRAPER_MIN_REQUEST_INTERVAL_SEC,
    SCRAPER_USER_AGENT,
)
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402
from infrastructure.external.uf_client import UFClient  # noqa: E402
from infrastructure.scrapers.base import RateLimiter  # noqa: E402
from services.uf_rate import require_real_uf_rate  # noqa: E402
from workers.refresh_scraper import (  # noqa: E402
    DEFAULT_REFRESH_COOLDOWN_HOURS,
    DEFAULT_REFRESH_LIMIT,
    DEFAULT_REFRESH_STALE_DAYS,
    RefreshStats,
    count_refresh_candidates,
    run_refresh_scraper,
    select_refresh_candidates,
)


@dataclass(frozen=True)
class RefreshTraceability:
    active_with_last_refresh_attempted_at: int
    max_last_refresh_attempted_at: datetime | None


@dataclass(frozen=True)
class RefreshUFResolution:
    rate: Decimal | None
    source: str


@dataclass(frozen=True)
class RefreshRunSummary:
    mode: str
    source: str
    limit: int
    stale_days: int
    cooldown_hours: int
    order: str
    stats: RefreshStats
    traceability_before: RefreshTraceability
    traceability_after: RefreshTraceability

    @property
    def attempts_realized(self) -> int:
        if self.mode == "dry-run":
            return 0
        return self.stats.selected

    @property
    def http_errors(self) -> int:
        return (
            self.stats.forbidden
            + self.stats.rate_limited
            + self.stats.server_errors
            + self.stats.unexpected_http
            + self.stats.unexpected_errors
            + self.stats.blocked_or_captcha
        )

    @property
    def traceability_delta(self) -> int:
        return (
            self.traceability_after.active_with_last_refresh_attempted_at
            - self.traceability_before.active_with_last_refresh_attempted_at
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh old active listings by direct URL.")
    parser.add_argument("--source", default="yapo")
    parser.add_argument("--only-active", action="store_true")
    parser.add_argument("--include-inactive", action="store_true")
    parser.add_argument("--only-missing-coordinates", action="store_true")
    parser.add_argument("--comuna")
    parser.add_argument("--property-type", choices=["apartment", "house"])
    parser.add_argument("--limit", type=int, default=DEFAULT_REFRESH_LIMIT)
    parser.add_argument("--stale-days", type=int, default=DEFAULT_REFRESH_STALE_DAYS)
    parser.add_argument("--cooldown-hours", type=int, default=DEFAULT_REFRESH_COOLDOWN_HOURS)
    parser.add_argument("--sleep", type=float, default=SCRAPER_MIN_REQUEST_INTERVAL_SEC)
    parser.add_argument(
        "--order",
        choices=["oldest_seen", "oldest_refresh", "random", "watchlist_first"],
        default="watchlist_first",
    )
    parser.add_argument("--max-errors", type=int)
    parser.add_argument("--stop-on-block", action="store_true")
    parser.add_argument("--examples", type=int, default=0)
    parser.add_argument(
        "--output-report",
        help="Optional report base path. Writes .json and .md files without changing scraper data.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only select candidates and report DB traceability without fetching URLs.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


async def collect_refresh_traceability(session_factory) -> RefreshTraceability:
    async with session_factory() as session:
        stmt = select(
            func.count(ListingORM.id),
            func.max(ListingORM.last_refresh_attempted_at),
        ).where(
            ListingORM.status == "active",
            ListingORM.last_refresh_attempted_at.is_not(None),
        )
        count, max_attempted_at = (await session.execute(stmt)).one()

    return RefreshTraceability(
        active_with_last_refresh_attempted_at=int(count or 0),
        max_last_refresh_attempted_at=max_attempted_at,
    )


async def run_refresh_once(
    args: argparse.Namespace,
    *,
    session_factory=None,
    http_client: httpx.AsyncClient | None = None,
) -> RefreshRunSummary:
    resolved_session_factory = session_factory or get_session_factory()
    before = await collect_refresh_traceability(resolved_session_factory)

    if args.dry_run:
        candidates_total = await count_refresh_candidates(
            resolved_session_factory,
            stale_days=args.stale_days,
            cooldown_hours=args.cooldown_hours,
            source=args.source,
            only_active=args.only_active,
            include_inactive=args.include_inactive,
            only_missing_coordinates=args.only_missing_coordinates,
            comuna=args.comuna,
            property_type=args.property_type,
        )
        candidates = await select_refresh_candidates(
            resolved_session_factory,
            limit=args.limit,
            stale_days=args.stale_days,
            cooldown_hours=args.cooldown_hours,
            source=args.source,
            only_active=args.only_active,
            include_inactive=args.include_inactive,
            only_missing_coordinates=args.only_missing_coordinates,
            comuna=args.comuna,
            property_type=args.property_type,
            order=args.order,
        )
        stats = RefreshStats(
            source=args.source,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            candidates_total=candidates_total,
            selected=len(candidates),
        )
        _record_dry_run_dimensions(stats, candidates)
    elif http_client is not None:
        stats = await _run_worker(args, resolved_session_factory, http_client)
    else:
        async with httpx.AsyncClient(
            timeout=SCRAPER_HTTP_TIMEOUT_SEC,
            headers={"User-Agent": SCRAPER_USER_AGENT},
            follow_redirects=False,
        ) as managed_http_client:
            stats = await _run_worker(args, resolved_session_factory, managed_http_client)

    after = await collect_refresh_traceability(resolved_session_factory)
    return RefreshRunSummary(
        mode="dry-run" if args.dry_run else "run",
        source=args.source,
        limit=args.limit,
        stale_days=args.stale_days,
        cooldown_hours=args.cooldown_hours,
        order=args.order,
        stats=stats,
        traceability_before=before,
        traceability_after=after,
    )


async def _run_worker(args: argparse.Namespace, session_factory, http_client: httpx.AsyncClient):
    uf_resolution = await _resolve_refresh_uf_rate(args, http_client)
    return await run_refresh_scraper(
        session_factory,
        http_client=http_client,
        limit=args.limit,
        stale_days=args.stale_days,
        cooldown_hours=args.cooldown_hours,
        rate_limiter=RateLimiter(max(0.0, float(args.sleep))),
        source=args.source,
        only_active=args.only_active,
        include_inactive=args.include_inactive,
        only_missing_coordinates=args.only_missing_coordinates,
        comuna=args.comuna,
        property_type=args.property_type,
        order=args.order,
        max_errors=args.max_errors,
        stop_on_block=args.stop_on_block,
        examples=args.examples,
        uf_to_clp=uf_resolution.rate,
        uf_rate_source=uf_resolution.source,
    )


async def _resolve_refresh_uf_rate(
    args: argparse.Namespace,
    http_client: httpx.AsyncClient,
) -> RefreshUFResolution:
    if str(args.source or "").strip().lower() != "yapo":
        return RefreshUFResolution(rate=None, source="not_applicable")

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    try:
        client = UFClient(api_url=settings.uf_api_url, http_client=http_client, redis=redis)
        info = await require_real_uf_rate(client)
    except Exception as exc:
        logging.getLogger(__name__).warning("No se pudo resolver UF real para refresh: %s", exc)
        return RefreshUFResolution(rate=None, source="missing")
    finally:
        await redis.aclose()

    return RefreshUFResolution(rate=info.rate, source=info.source)


def print_summary(summary: RefreshRunSummary) -> None:
    stats = summary.stats
    print("== AVM refresh scraper job: resumen ==")
    print(f"fuente: {summary.source}")
    print(f"mode\t{summary.mode}")
    print(f"scheduler_required\t{False}")
    if stats.started_at is not None:
        print(f"started_at: {stats.started_at.isoformat()}")
    if stats.finished_at is not None:
        print(f"finished_at: {stats.finished_at.isoformat()}")
    print(f"duration_sec: {stats.duration_sec}")
    if stats.stage_durations_sec:
        print("stage_durations_sec:")
        for stage, duration in sorted(stats.stage_durations_sec.items()):
            print(f"  {stage}: {duration}")
    print(f"limit\t{summary.limit}")
    print(f"stale_days\t{summary.stale_days}")
    print(f"cooldown_hours\t{summary.cooldown_hours}")
    print(f"order\t{summary.order}")
    print(f"candidates_total\t{stats.candidates_total}")
    print(f"selected_total\t{stats.selected}")
    print(f"selected_candidates\t{stats.selected}")
    print(f"attempts_realized\t{summary.attempts_realized}")
    print(f"attempted\t{stats.attempted}")
    print(f"refreshed_ok\t{stats.refreshed_ok}")
    print(f"ok\t{stats.processed}")
    print(f"validos\t{stats.valid}")
    print(f"actualizados\t{stats.updated}")
    print(f"sin_cambios\t{stats.unchanged}")
    print(f"saltados\t{stats.skipped}")
    print(f"invalidos_criticos\t{stats.critical_invalid}")
    print(f"http_errors\t{summary.http_errors}")
    print(f"timeouts\t{stats.timeouts}")
    print(f"removed\t{stats.removed}")
    print(f"inactive\t{stats.inactive}")
    print(f"inactive_detected\t{stats.inactive}")
    print(f"reactivated\t{stats.reactivated}")
    print(f"price_changes_detected\t{stats.price_changes_detected}")
    print(f"price_changes_ignored_uf_rate_artifact\t{stats.price_changes_ignored_uf_rate_artifact}")
    print(f"price_drops_detected\t{stats.price_drops_detected}")
    print(f"price_increases_detected\t{stats.price_increases_detected}")
    print(f"m2_changes_detected\t{stats.m2_changes_detected}")
    print(f"bedrooms_changes_detected\t{stats.bedrooms_changes_detected}")
    print(f"bathrooms_changes_detected\t{stats.bathrooms_changes_detected}")
    print(f"address_changes_detected\t{stats.address_changes_detected}")
    print(f"geocode_precision_upgrades\t{stats.geocode_precision_upgrades}")
    print(f"geocode_precision_downgrades\t{stats.geocode_precision_downgrades}")
    print(f"geocode_precision_downgrades_blocked\t{stats.geocode_precision_downgrades_blocked}")
    print(f"price_history_points_created\t{stats.price_history_points_created}")
    print(f"uf_rate_used\t{stats.uf_rate_used or 'none'}")
    print(f"uf_rate_source\t{stats.uf_rate_source or 'unknown'}")
    print(f"listings_with_price_uf\t{stats.listings_with_price_uf}")
    print(f"listings_using_uf_fallback\t{stats.listings_using_uf_fallback}")
    print("alerts_created\t0")
    print("alerts_skipped\t0")
    print("alerts_note\talerts_job corre aparte")
    print(f"fetched\t{stats.fetched}")
    print(f"http_404\t{stats.not_found}")
    print(f"http_403\t{stats.forbidden}")
    print(f"http_429\t{stats.rate_limited}")
    print(f"http_5xx\t{stats.server_errors}")
    print(f"not_found\t{stats.not_found}")
    print(f"redirects\t{stats.redirects}")
    print(f"rate_limited\t{stats.rate_limited}")
    print(f"server_errors\t{stats.server_errors}")
    print(f"parse_errors\t{stats.parse_errors}")
    print(f"validation_errors\t{stats.validation_errors}")
    print(f"unexpected_http\t{stats.unexpected_http}")
    print(f"unexpected_errors\t{stats.unexpected_errors}")
    print(f"blocked_or_captcha\t{stats.blocked_or_captcha}")
    print(f"comuna_detected\t{_comuna_detected(stats)}")
    print(f"comuna_unknown\t{_comuna_unknown(stats)}")
    print(f"comuna_detection_rate_pct\t{_comuna_detection_rate(stats):.1f}")
    _print_mapping("por_comuna", stats.by_comuna)
    _print_flat_mapping("por_property_type", stats.by_property_type)
    _print_flat_mapping("por_geocode_precision", stats.by_geocode_precision)
    _print_flat_mapping("geocode_precision_before", stats.geocode_precision_before)
    _print_flat_mapping("geocode_precision_after", stats.geocode_precision_after)
    _print_flat_mapping("geocode_precision_transitions", stats.geocode_precision_transitions)
    _print_flat_mapping("razones", stats.reason_counts)
    print("health:")
    print(f"  status: {'warning' if _health_warnings(stats) else 'ok'}")
    for warning in _health_warnings(stats):
        print(f"  warning: {warning}")
    if stats.examples:
        print("examples:")
        for example in stats.examples:
            print(f"  - {example}")
    print(
        "traceability_before_active_with_last_refresh_attempted_at\t"
        f"{summary.traceability_before.active_with_last_refresh_attempted_at}"
    )
    print(
        "traceability_after_active_with_last_refresh_attempted_at\t"
        f"{summary.traceability_after.active_with_last_refresh_attempted_at}"
    )
    print(
        "traceability_delta_active_with_last_refresh_attempted_at\t"
        f"{summary.traceability_delta}"
    )
    print(
        "traceability_after_max_last_refresh_attempted_at\t"
        f"{_format_datetime(summary.traceability_after.max_last_refresh_attempted_at)}"
    )


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "none"
    return value.isoformat()


def write_report(summary: RefreshRunSummary, output_report: str | None) -> tuple[Path, Path] | None:
    if not output_report:
        return None
    base = Path(output_report)
    json_path = base if base.suffix == ".json" else base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _summary_payload(summary)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(_summary_markdown(payload), encoding="utf-8")
    return json_path, md_path


def _summary_payload(summary: RefreshRunSummary) -> dict:
    stats = summary.stats
    return {
        "mode": summary.mode,
        "source": summary.source,
        "limit": summary.limit,
        "stale_days": summary.stale_days,
        "cooldown_hours": summary.cooldown_hours,
        "order": summary.order,
        "stats": stats.__dict__,
        "attempts_realized": summary.attempts_realized,
        "traceability_delta": summary.traceability_delta,
    }


def _summary_markdown(payload: dict) -> str:
    stats = payload["stats"]
    lines = [
        "# AVM Refresh Scraper Report",
        "",
        f"- Mode: `{payload['mode']}`",
        f"- Source: `{payload['source']}`",
        f"- Candidates total: {stats.get('candidates_total', 0)}",
        f"- Selected total: {stats.get('selected', 0)}",
        f"- Attempted: {stats.get('attempted', 0)}",
        f"- Refreshed OK: {stats.get('refreshed_ok', 0)}",
        f"- Updated: {stats.get('updated', 0)}",
        f"- Unchanged: {stats.get('unchanged', 0)}",
        f"- Price changes detected: {stats.get('price_changes_detected', 0)}",
        f"- Blocked or captcha: {stats.get('blocked_or_captcha', 0)}",
        "",
        "## Reasons",
        "",
    ]
    reasons = stats.get("reason_counts") or {}
    lines.extend(f"- {key}: {value}" for key, value in sorted(reasons.items()))
    return "\n".join(lines) + "\n"


def _record_dry_run_dimensions(stats: RefreshStats, candidates: list) -> None:
    for listing in candidates:
        comuna = str(getattr(listing, "comuna", None) or "unknown")
        values = stats.by_comuna.setdefault(comuna, {"selected": 0})
        values["selected"] = values.get("selected", 0) + 1
        _increment(stats.by_property_type, str(getattr(listing, "property_type", None) or "unknown"))
        _increment(stats.by_geocode_precision, str(getattr(listing, "geocode_precision", None) or "unknown"))


def _comuna_detected(stats: RefreshStats) -> int:
    return sum(values.get("selected", 0) for comuna, values in stats.by_comuna.items() if comuna != "unknown")


def _comuna_unknown(stats: RefreshStats) -> int:
    return stats.by_comuna.get("unknown", {}).get("selected", 0)


def _comuna_detection_rate(stats: RefreshStats) -> float:
    total = _comuna_detected(stats) + _comuna_unknown(stats)
    return 0.0 if total == 0 else _comuna_detected(stats) / total * 100


def _health_warnings(stats: RefreshStats) -> list[str]:
    warnings = []
    if stats.blocked_or_captcha:
        warnings.append("Se detectaron bloqueos, captcha o rate limiting.")
    if stats.geocode_precision_downgrades:
        warnings.append("Se detectaron downgrades de geocode_precision; revisar guardrails.")
    if stats.geocode_precision_downgrades_blocked:
        warnings.append("Se bloquearon downgrades de geocode_precision durante refresh.")
    if stats.validation_errors:
        warnings.append("Hubo errores de validacion del pipeline.")
    return warnings


def _print_mapping(label: str, values: dict[str, dict[str, int]]) -> None:
    if not values:
        return
    print(f"{label}:")
    for key, row in sorted(values.items()):
        metrics = " ".join(f"{metric}={value}" for metric, value in sorted(row.items()))
        print(f"  {key}: {metrics}")


def _print_flat_mapping(label: str, values: dict[str, int]) -> None:
    if not values:
        return
    print(f"{label}:")
    for key, value in sorted(values.items()):
        print(f"  {key}: {value}")


def _increment(target: dict[str, int], key: str) -> None:
    target[key] = target.get(key, 0) + 1


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=str(args.log_level).upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    summary = await run_refresh_once(args)
    print_summary(summary)
    artifacts = write_report(summary, args.output_report)
    if artifacts is not None:
        json_path, md_path = artifacts
        print(f"report_json\t{json_path}")
        print(f"report_md\t{md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
