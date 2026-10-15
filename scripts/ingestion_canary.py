"""Oracle canary: one page/source, real extraction, simulated UF outage, scratch DB only."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.db.base import Base
from infrastructure.db import models  # noqa: F401
from infrastructure.db.ingestion_models import IngestionPendingPrice
from services.ingestion_state import clean_counters, ingestion_health, safe_error
from services.ingestion_uf import IngestionRate


class NoRedis:
    async def aclose(self):
        pass

    async def hscan_iter(self, *args, **kwargs):
        if False:
            yield None

    async def hdel(self, *args):
        return 0


async def run():
    # Reject accidentally writable production sessions or a production DB override.
    if os.environ.get("PORTAL_SESSION_READ_ONLY") != "1":
        raise RuntimeError("Canary requires read-only Portal session")
    os.environ["ENABLE_SCHEDULER"] = "false"
    from scripts import portal_card_first as portal
    from workers import scraper_job as yapo
    outage = IngestionRate(None, None, ("SimulatedUFOutage",))
    with tempfile.TemporaryDirectory(prefix="valoria-ingestion-canary-") as scratch:
        engine = create_async_engine("sqlite+aiosqlite:///" + str(Path(scratch)/"canary.sqlite"))
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            portal_report = await portal.run(apply=True, max_pages=1, max_details=0, pause_s=3,
                max_geo_details=0, max_targets=1, factory=factory, resolution=outage)
            # No live Redis, no production DB, no valuation calls; run the real Yapo persistence path.
            original_from_url = yapo.Redis.from_url
            yapo.Redis.from_url = lambda *args, **kwargs: NoRedis()
            try:
                yapo_report = await yapo.run_yapo_once(factory, max_pages=1, min_pause_s=3,
                                                      max_targets=1, resolution=outage)
            finally:
                yapo.Redis.from_url = original_from_url
            state = await ingestion_health(factory)
            pending = {}
            async with factory() as session:
                for source in ("portalinmobiliario", "yapo"):
                    pending[source] = await session.scalar(select(func.count()).select_from(IngestionPendingPrice)
                                                            .where(IngestionPendingPrice.source == source))
            assert portal_report.get("raw_cards",0) > 0 and portal_report.get("pending_uf",0) > 0
            assert not portal_report.get("blocked_or_captcha") and not portal_report.get("validation_errors")
            assert yapo_report.pending_uf > 0 and yapo_report.unexpected_errors == 0 and not yapo_report.blocked_or_captcha
            assert pending["portalinmobiliario"] == portal_report["pending_uf"]
            assert pending["yapo"] == yapo_report.pending_uf
            assert all(v["last_run"]["successful"] for v in state["sources"].values())
            # Exercise the proposed endpoint in-process, with scratch storage and no API startup.
            import infrastructure.db.database as database
            before = database.get_session_factory
            database.get_session_factory = lambda: factory
            try:
                from api.main import create_app
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url="http://canary") as http:
                    response = await http.get("/api/v1/health/ingestion")
                    assert response.status_code == 200 and response.json()["status"] == "degraded"
            finally:
                database.get_session_factory = before
            return {"passed": True, "uf_outage_simulated": True, "production_writes": False,
                    "limits": {"pages_per_source":1,"targets_per_source":1,"details":0,"geography":0,"pause_seconds":3},
                    "portal":clean_counters(portal_report),"yapo":clean_counters(asdict(yapo_report)),
                    "originals_durably_pending_in_scratch":pending,"health_endpoint":response.json()}
        finally:
            await engine.dispose()


def main():
    try:
        print(json.dumps(asyncio.run(run()),sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"passed":False,"error":safe_error(exc,stage="isolated_canary")}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
