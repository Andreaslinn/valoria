"""Durable source health and original-price queue, separate from listings/valuation."""
from __future__ import annotations

import json
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from infrastructure.db.ingestion_models import IngestionPendingPrice, IngestionRun

SOURCES = ("portalinmobiliario", "yapo")
COUNTERS = {"inserted", "updated", "known_unchanged", "skipped", "raw_cards", "unique_cards",
            "raw_cards_http", "valid_cards", "persisted_from_card", "persisted_from_detail",
            "pending_uf", "pending_uf_reprocessed", "validation_errors", "unexpected_errors",
            "blocked_or_captcha", "fetch_errors", "geo_stage_errors", "geo_blocked", "geo_stopped",
            "scraped", "raw_scraped", "discarded"}
COUNTERS.update({"published_detail_requested", "published_detail_captured", "published_detail_rejected"})


def safe_error(exc, *, stage="ingestion"):
    result = {"type": type(exc).__name__, "stage": stage,
              "frames": [{"file": Path(f.filename).name, "line": f.lineno, "function": f.name}
                         for f in traceback.extract_tb(exc.__traceback__)[-8:]]}
    # Known literal only; never serialize arbitrary exception text containing credentials/HTML.
    if type(exc).__name__ == "UFServiceError":
        result["reason"] = "UF real no disponible"
    if type(exc).__name__ == "PortalSessionExpired":
        result.update(code="PORTAL_SESSION_EXPIRED", reason="official_verification_required")
    return result


def clean_counters(values):
    return {k: int(v) for k, v in values.items()
            if k in COUNTERS and isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0}


async def start_run(factory, source):
    if source not in SOURCES:
        raise ValueError("unsupported_ingestion_source")
    async with factory() as s:
        row = IngestionRun(source=source, started_at=datetime.now(UTC), counters={}, errors=[])
        s.add(row)
        await s.commit()
        return row.id


async def finish_run(factory, run_id, *, successful, counters=None, errors=None):
    async with factory() as s:
        row = await s.get(IngestionRun, run_id)
        row.finished_at, row.successful = datetime.now(UTC), successful
        row.counters = clean_counters(counters or {})
        row.errors = errors or []
        await s.commit()


def utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


async def ingestion_health(factory, *, now=None):
    now = now or datetime.now(UTC)
    sources = {}
    async with factory() as s:
        for source in SOURCES:
            latest = await s.scalar(select(IngestionRun).where(IngestionRun.source == source)
                                    .order_by(IngestionRun.id.desc()).limit(1))
            success = await s.scalar(select(IngestionRun).where(IngestionRun.source == source,
                                  IngestionRun.successful.is_(True)).order_by(IngestionRun.id.desc()).limit(1))
            pending = await s.scalar(select(func.count()).select_from(IngestionPendingPrice)
                                     .where(IngestionPendingPrice.source == source))
            age = max(0, (now - utc(success.finished_at)).total_seconds()) if success else None
            stale = age is None or age > timedelta(hours=24).total_seconds()
            latest_failed = latest is not None and latest.successful is False
            hung = latest is not None and latest.finished_at is None and (now-utc(latest.started_at)).total_seconds() > 1200
            sources[source] = {
                "status": "degraded" if stale or latest_failed or hung or pending else "ok",
                "last_success_at": utc(success.finished_at).isoformat() if success else None,
                "age_seconds": round(age, 1) if age is not None else None,
                "over_24h_without_success": stale,
                "last_run": {"started_at": utc(latest.started_at).isoformat(),
                             "finished_at": utc(latest.finished_at).isoformat() if latest.finished_at else None,
                             "successful": latest.successful, "counters": latest.counters,
                             "errors": latest.errors} if latest else None,
                "last_success_counters": success.counters if success else None,
                "conversion_pending": pending,
                "alarms": sorted({error.get("code") for error in (latest.errors or [])
                                  if isinstance(error, dict) and error.get("code")}) if latest else [],
            }
    return {"status": "degraded" if any(v["status"] != "ok" for v in sources.values()) else "ok",
            "observed_at": now.isoformat(), "sources": sources}


class PendingPriceStore:
    """Redis hash-compatible adapter; original records survive Redis eviction/restarts."""
    def __init__(self, factory, source, legacy_redis=None):
        self.factory, self.source, self.legacy = factory, source, legacy_redis

    async def hset(self, key, identity, value):
        raw = json.loads(value)
        if raw.get("source") != self.source or str(raw.get("external_id")) != str(identity):
            raise ValueError("pending_identity_mismatch")
        observed = datetime.fromisoformat(raw["scraped_at"])
        async with self.factory() as s:
            row = await s.scalar(select(IngestionPendingPrice).where(
                IngestionPendingPrice.source == self.source, IngestionPendingPrice.external_id == str(identity)))
            if row is None:
                s.add(IngestionPendingPrice(source=self.source, external_id=str(identity), payload=raw, observed_at=observed))
            elif utc(observed) >= utc(row.observed_at):
                row.payload, row.observed_at = raw, observed
            await s.commit()

    async def hgetall(self, key):
        async with self.factory() as s:
            rows = (await s.scalars(select(IngestionPendingPrice).where(IngestionPendingPrice.source == self.source)
                                   .order_by(IngestionPendingPrice.observed_at).limit(100))).all()
        result = {r.external_id: json.dumps(r.payload) for r in rows}
        if self.legacy is not None:
            # Migrate only a bounded slice; originals remain in Redis until canonical persistence succeeds.
            async for identity, value in self.legacy.hscan_iter(key, count=100):
                identity = identity.decode() if isinstance(identity, bytes) else str(identity)
                if len(result) >= 100:
                    break
                result.setdefault(identity, value)
        return result

    async def hdel(self, key, identity):
        from sqlalchemy import delete
        async with self.factory() as s:
            await s.execute(delete(IngestionPendingPrice).where(IngestionPendingPrice.source == self.source,
                                                               IngestionPendingPrice.external_id == str(identity)))
            await s.commit()
        if self.legacy is not None:
            await self.legacy.hdel(key, identity)
