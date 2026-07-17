"""Controlled Portal HTTP canary, dry-run by default.

The command reuses the bounded Portal runner and the canonical ingestion
pipeline. It is intentionally manual: it does not register scheduler work.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_settings  # noqa: E402
from config.portal_targets import PortalTarget  # noqa: E402
from core.ports.uf_service import UFRateInfo  # noqa: E402
from domain.ingestion.data_cleaning import clean_listing  # noqa: E402
from domain.ingestion.deduplication import make_fingerprint  # noqa: E402
from domain.ingestion.pipeline import process_listing  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.repositories import (  # noqa: E402
    SqlAlchemyListingRepository,
    SqlAlchemyPriceHistoryRepository,
    SqlAlchemyPropertyRepository,
)
from infrastructure.external.uf_client import UFClient  # noqa: E402
from scripts.portal_http_dry_run import PortalHttpDryRun  # noqa: E402
from scripts.portal_smoke import DEFAULT_HEADERS  # noqa: E402
from services.uf_rate import require_real_uf_rate  # noqa: E402

DEFAULT_REPORT_PATH = ROOT / "reports" / "portal_canary_latest.json"


class PortalCanaryReject(ValueError):
    """A detail is valid Portal data but cannot enter the current AVM contract."""


def _sanitized_persistence_error(exc: Exception) -> dict[str, Any]:
    """Return auditable DB error facts without leaking connection details."""
    result: dict[str, Any] = {"exception": type(exc).__name__}
    if isinstance(exc, DBAPIError):
        origin = exc.orig
        result["driver_exception"] = type(origin).__name__
        result["sqlstate"] = getattr(origin, "sqlstate", None)
        message = str(origin).replace("\n", " ")
        result["message"] = message[:500]
    return result


@dataclass(frozen=True)
class CanaryUFResolution:
    info: UFRateInfo | None
    error: str | None = None


def _database_endpoint(database_url: str) -> dict[str, str | int | None]:
    parsed = urlsplit(database_url)
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "database": parsed.path.lstrip("/") or None,
    }


async def preflight_database(*, settings: Any, session_factory=None) -> tuple[bool, dict[str, str | int | None], str | None]:
    """Verify the configured local DB before any Portal HTTP request.

    The returned error deliberately omits the connection URL and credentials.
    """
    endpoint = _database_endpoint(str(settings.database_url))
    try:
        factory = session_factory or get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        return True, endpoint, None
    except Exception as exc:  # noqa: BLE001 - sanitize external driver details
        return False, endpoint, f"{type(exc).__name__}: database connection unavailable"


def _db_unavailable_report(endpoint: dict[str, str | int | None], error: str) -> dict[str, Any]:
    return {
        "source": "portalinmobiliario",
        "mode": "apply",
        "status": "db_unavailable",
        "apply_requested": True,
        "persisted": False,
        "database": endpoint,
        "database_error": error,
        "metrics": {
            "pages_requested": 0,
            "cards_detected": 0,
            "publications_unique": 0,
            "details_requested": 0,
            "details_ok": 0,
            "details_failed": 0,
            "blocks": 0,
        },
        "canary": {
            "accepted_rm": 0, "details_downloaded": 0, "inserted": 0,
            "updated": 0, "unchanged": 0, "apply_duplicates": 0,
            "rejected": {}, "errors": {"db_unavailable": 1},
        },
    }


def _valid_coordinates(metadata: dict[str, Any]) -> tuple[float | None, float | None]:
    """Keep only parser coordinates that are valid decimal degrees.

    The Portal state may serialize decimal coordinates without their separator;
    those values are not evidence and must not make an otherwise valid listing
    fail the ingestion contract.
    """
    try:
        lat = float(metadata.get("lat"))
        lon = float(metadata.get("lon"))
    except (TypeError, ValueError):
        return None, None
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None, None


def portal_detail_to_raw(
    detail: dict[str, Any],
    target: PortalTarget,
    *,
    uf_info: UFRateInfo | None,
) -> dict[str, Any]:
    """Map an accepted Portal detail into the existing clean_listing contract."""
    if target["operation"] != "venta":
        raise PortalCanaryReject("operation_out_of_pipeline_scope")
    if detail.get("state") != "detail" or not detail.get("external_id"):
        raise PortalCanaryReject("invalid_detail_identity")
    if not detail.get("comuna"):
        raise PortalCanaryReject("unknown_comuna")

    currency = str(detail.get("currency_original") or detail.get("price_currency") or "").upper()
    raw_metadata = dict(detail.get("raw_metadata") or {})
    raw_metadata.update(
        {
            "accepted_rm": True,
            "portal_target": target["label"],
            "portal_operation": target["operation"],
            "currency_original": currency,
            "price_uf": detail.get("price_uf"),
        }
    )
    parking_value = detail.get("parking")
    try:
        parking = int(parking_value) if parking_value is not None else 0
    except (TypeError, ValueError):
        parking = 0
        raw_metadata["parking_rejection_reason"] = "not_an_integer"
        raw_metadata["parking_raw_rejected"] = str(parking_value)
    if not 0 <= parking <= 100:
        raw_metadata["parking_rejection_reason"] = "out_of_range"
        raw_metadata["parking_raw_rejected"] = str(parking_value)
        parking = 0
    if currency == "UF":
        if uf_info is None:
            raw_metadata["price_clp_provenance"] = "not_converted_missing_real_uf_rate"
            raise PortalCanaryReject("missing_real_uf_rate")
        derived = detail.get("price_clp_derived")
        if derived is None:
            derived = int(Decimal(str(detail["price_uf"])) * uf_info.rate)
        raw_metadata.update(
            {
                "price_clp_derived": int(derived),
                "price_clp_provenance": "derived_from_uf_real_rate",
                "uf_rate_used": str(uf_info.rate),
                "uf_rate_source": uf_info.source,
                "uf_rate_cache_hit": uf_info.cache_hit,
                "uf_rate_stale": getattr(uf_info, "is_stale", False),
            }
        )
        price_clp = int(derived)
    elif currency == "CLP":
        price_clp = detail.get("price_clp_published") or detail.get("price_clp")
        if price_clp is None:
            raise PortalCanaryReject("missing_published_clp_price")
        raw_metadata["price_clp_provenance"] = "published"
    else:
        raise PortalCanaryReject("unsupported_price_currency")

    m2 = detail.get("usable_area_m2") or detail.get("built_area_m2") or detail.get("total_area_m2")
    lat, lon = _valid_coordinates(raw_metadata)
    return {
        "source": "portalinmobiliario",
        "external_id": str(detail["external_id"]),
        "title": detail.get("title"),
        "comuna": detail.get("comuna"),
        "location": detail.get("location"),
        "description": detail.get("description"),
        "property_type": target["property_type"],
        "m2": m2,
        "usable_area_m2": detail.get("usable_area_m2"),
        "built_area_m2": detail.get("built_area_m2"),
        "land_area_m2": detail.get("land_area_m2"),
        "bedrooms": detail.get("bedrooms") or 0,
        "bathrooms": detail.get("bathrooms") or 0,
        "parking": parking,
        "price_clp": price_clp,
        "url": detail.get("canonical_url") or detail.get("url"),
        "lat": lat,
        "lon": lon,
        "scraped_at": datetime.now(UTC),
        "raw_metadata": raw_metadata,
    }


def _materially_changed(existing: Any, cleaned: Any) -> bool:
    fields = ("title", "comuna", "property_type", "m2", "bedrooms", "bathrooms", "parking", "url", "price_uf", "price_currency")
    if any(getattr(existing, field) != getattr(cleaned, field) for field in fields):
        return True
    return existing.price.clp != cleaned.price.clp


async def resolve_real_uf_rate(settings: Any, http_client: httpx.AsyncClient) -> CanaryUFResolution:
    redis = Redis.from_url(settings.redis_url)
    try:
        client = UFClient(api_url=settings.uf_api_url, http_client=http_client, redis=redis)
        return CanaryUFResolution(info=await require_real_uf_rate(client))
    except Exception as exc:  # noqa: BLE001 - report, never silently substitute
        return CanaryUFResolution(info=None, error=f"{type(exc).__name__}: {exc}")
    finally:
        await redis.aclose()


async def run_canary(
    *,
    apply: bool,
    max_details: int,
    max_pages_per_target: int,
    pause_s: float,
    session_factory=None,
    settings: Any | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if apply:
        database_ok, endpoint, database_error = await preflight_database(
            settings=settings,
            session_factory=session_factory,
        )
        if not database_ok:
            return _db_unavailable_report(endpoint, database_error or "database unavailable")
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=30.0)
    try:
        uf_resolution = await resolve_real_uf_rate(settings, client)
        runner = PortalHttpDryRun(
            client=client,
            max_details=max_details,
            max_pages_per_target=max_pages_per_target,
            pause_s=pause_s,
            uf_to_clp=uf_resolution.info.rate if uf_resolution.info else None,
        )
        result = await runner.run_with_records()
    finally:
        if owns_client:
            await client.aclose()

    report = dict(result.report)
    report.update(
        {
            "mode": "apply" if apply else "dry_run",
            "apply_requested": bool(apply),
            "persisted": False,
            "portal_http_enabled_config": bool(settings.portal_http_enabled),
            "uf_rate": str(uf_resolution.info.rate) if uf_resolution.info else None,
            "uf_rate_source": uf_resolution.info.source if uf_resolution.info else None,
            "uf_rate_cache_hit": uf_resolution.info.cache_hit if uf_resolution.info else None,
            "uf_rate_error": uf_resolution.error,
        }
    )
    stats = {
        "accepted_rm": len(result.accepted), "details_downloaded": result.report["metrics"]["details_ok"],
        "inserted": 0, "updated": 0, "unchanged": 0, "apply_duplicates": 0,
        "rejected": {}, "errors": {}, "error_details": [],
    }
    for row in result.accepted:
        target, detail = row["target"], row["detail"]
        try:
            raw = portal_detail_to_raw(detail, target, uf_info=uf_resolution.info)
            cleaned = clean_listing(raw)
        except PortalCanaryReject as exc:
            stats["rejected"][str(exc)] = stats["rejected"].get(str(exc), 0) + 1
            continue
        except Exception as exc:  # noqa: BLE001
            reason = f"transform:{type(exc).__name__}"
            stats["errors"][reason] = stats["errors"].get(reason, 0) + 1
            continue
        if not apply:
            continue
        try:
            resolved_factory = session_factory or get_session_factory()
            async with resolved_factory() as session:
                stage = "lookup_existing"
                try:
                    listing_repo = SqlAlchemyListingRepository(session)
                    existing = await listing_repo.find_by_source_external_id(cleaned.source, cleaned.external_id or "")
                    if existing is None:
                        existing = await listing_repo.find_by_fingerprint(make_fingerprint(cleaned))
                        if existing is not None:
                            stats["apply_duplicates"] += 1
                    changed = existing is None or _materially_changed(existing, cleaned)
                    stage = "process_listing"
                    await process_listing(
                        raw,
                        listing_repo=listing_repo,
                        property_repo=SqlAlchemyPropertyRepository(session),
                        price_history_repo=SqlAlchemyPriceHistoryRepository(session),
                    )
                    stage = "commit"
                    await session.commit()
                except Exception as exc:
                    await session.rollback()
                    raise RuntimeError(stage) from exc
                if existing is None:
                    stats["inserted"] += 1
                elif changed:
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1
        except Exception as exc:  # noqa: BLE001 - individual transaction is isolated
            cause = exc.__cause__ or exc
            error_type = type(cause).__name__
            stats["errors"][error_type] = stats["errors"].get(error_type, 0) + 1
            error_detail = _sanitized_persistence_error(cause)
            error_detail.update(
                {
                    "source": cleaned.source,
                    "external_id": cleaned.external_id,
                    "url": raw.get("url"),
                    "stage": str(exc) if exc.__cause__ is not None else "session_setup",
                }
            )
            stats["error_details"].append(error_detail)
    report["canary"] = stats
    report["persisted"] = bool(stats["inserted"] or stats["updated"] or stats["unchanged"])
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Manual Portal HTTP canary; dry-run unless --apply.")
    parser.add_argument("--apply", action="store_true", help="Persist accepted sale listings via process_listing.")
    parser.add_argument("--max-details", type=int, default=settings.portal_http_max_details)
    parser.add_argument("--max-pages-per-target", type=int, default=settings.portal_http_max_pages_per_target)
    parser.add_argument("--pause-s", type=float, default=1.0)
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    report = asyncio.run(run_canary(
        apply=args.apply, max_details=min(args.max_details, 50),
        max_pages_per_target=min(args.max_pages_per_target, 2), pause_s=max(args.pause_s, 0.0),
    ))
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"metrics": report["metrics"], "canary": report["canary"], "uf_rate": report["uf_rate"], "uf_rate_source": report["uf_rate_source"]}, ensure_ascii=False, indent=2))
    print(f"report={path}")
    return 0 if not report.get("stopped_reason") and not report["canary"]["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
