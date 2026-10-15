from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

import httpx
import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.ports.uf_service import UFRateInfo
from infrastructure.db.ingestion_models import IngestionUFCalendar, IngestionPendingPrice, IngestionRun
from infrastructure.db.models import ListingORM
from services.ingestion_uf import IngestionRate, parse_calendar, refresh_calendar, resolve_ingestion_rate, annotate_pending
from services.ingestion_state import PendingPriceStore, ingestion_health, start_run, finish_run
from scripts.ingestion_launcher import summarize_process


def info(day=date(2026, 10, 15)):
    return UFRateInfo(Decimal("41162.73"), "sii.cl", rate_date=day, fetched_at=datetime.now(UTC))


def calendar_html():
    return '<table><h2>Octubre</h2><tr><th>15</th><td>41.162,73</td><th>16</th><td>41.168,03</td></tr></table><table><h2>Noviembre</h2><tr><th>9</th><td>41.295,47</td><th>10</th><td></td></tr></table>'


def raw(identity="uf-1", *, currency="UF"):
    return dict(source="yapo", external_id=identity, title="Departamento Independencia",
                url=f"https://www.yapo.cl/apartamentos/{identity}", comuna="independencia",
                property_type="apartment", m2=47 if currency == "UF" else 60, bedrooms=2, bathrooms=1, parking=1,
                price_uf="1520" if currency == "UF" else None,
                price_clp=None if currency == "UF" else 60000000,
                scraped_at=datetime(2026, 10, 15, 12, tzinfo=UTC),
                raw_metadata={"currency_original": currency, **({"price_clp_missing_reason": "missing_uf_rate"} if currency == "UF" else {})})


def test_calendar_keeps_prepublished_dates_and_ignores_blanks():
    rows = parse_calendar(calendar_html(), 2026)
    assert rows[date(2026, 11, 9)] == Decimal("41295.47")
    assert date(2026, 11, 10) not in rows


def test_calendar_rejects_conflicting_values():
    with pytest.raises(ValueError, match="conflicting"):
        parse_calendar(calendar_html()+calendar_html().replace("41.162,73", "41.999,00"), 2026)


async def test_calendar_persists_future_and_outage_uses_exact_dated_value(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=calendar_html())))
    assert (await refresh_calendar(factory, http, today=date(2026,10,15)))["calendar_days_saved"] == 3
    await http.aclose()
    no_network = SimpleNamespace(get=AsyncMock(side_effect=AssertionError("must not fetch")))
    resolved = await resolve_ingestion_rate(factory, no_network, today=date(2026, 11, 9))
    assert resolved.exact.rate_date == date(2026, 11, 9)
    no_network.get.assert_not_called()


async def test_outage_is_bounded_and_reference_does_not_become_exact(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(IngestionUFCalendar(date=date(2026,10,13), value=Decimal("41152.13"), source="sii.cl", fetched_at=datetime.now(UTC)))
        s.add(IngestionUFCalendar(date=date(2026,11,9), value=Decimal("41295.47"), source="sii.cl", fetched_at=datetime.now(UTC)))
        await s.commit()
    http = SimpleNamespace(get=AsyncMock(side_effect=httpx.ReadTimeout("private URL secret")))
    # Check actual bounded refresh with injected no-wait sleeper.
    result = await refresh_calendar(factory, http, today=date(2026,10,15), attempts=100, sleep=AsyncMock())
    assert http.get.await_count == 2 and result["errors"] == ["ReadTimeout", "ReadTimeout"]
    resolved = await resolve_ingestion_rate(factory, None, today=date(2026,10,15), refresh=False)
    assert resolved.exact is None and resolved.reference.rate_date == date(2026,10,13)
    pending = annotate_pending(raw(), resolved)
    assert pending["price_clp"] is None
    assert pending["raw_metadata"]["reference_uf_date"] == "2026-10-13"
    assert pending["raw_metadata"]["conversion_status"] == "pending"


async def test_pending_is_durable_idempotent_and_keeps_newest(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    queue = PendingPriceStore(factory, "yapo")
    item = annotate_pending(raw(), IngestionRate(None,None))
    await queue.hset("ignored", "uf-1", json.dumps(item, default=str))
    await queue.hset("ignored", "uf-1", json.dumps(item, default=str))
    old = dict(item, title="Old", scraped_at=datetime(2026,10,14,12,tzinfo=UTC))
    await queue.hset("ignored", "uf-1", json.dumps(old, default=str))
    recovered = await PendingPriceStore(factory, "yapo").hgetall("ignored")
    assert len(recovered) == 1 and json.loads(recovered["uf-1"])["title"] == item["title"]


async def test_pending_identity_mismatch_fails_instead_of_losing_original(engine):
    queue = PendingPriceStore(async_sessionmaker(engine), "yapo")
    with pytest.raises(ValueError, match="identity"):
        await queue.hset("ignored", "different", json.dumps(raw(), default=str))


async def test_source_health_age_errors_and_counters(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    for source in ("yapo", "portalinmobiliario"):
        run_id = await start_run(factory, source)
        await finish_run(factory, run_id, successful=True, counters={"inserted":2,"updated":3,"password":"no"})
    result = await ingestion_health(factory, now=now+timedelta(hours=24,seconds=10))
    assert result["status"] == "degraded"
    assert all(x["over_24h_without_success"] for x in result["sources"].values())
    assert result["sources"]["yapo"]["last_success_counters"] == {"inserted":2,"updated":3}
    failed = await start_run(factory,"yapo")
    await finish_run(factory,failed,successful=False,errors=[{"type":"ReadTimeout","stage":"search"}])
    state = await ingestion_health(factory)
    assert state["sources"]["yapo"]["status"] == "degraded"
    assert state["sources"]["yapo"]["last_run"]["errors"][0]["type"] == "ReadTimeout"


@pytest.mark.parametrize("code", [1, 75, 124])
@pytest.mark.parametrize("prefix", ["", "core.exceptions."])
def test_launcher_propagates_legacy_errors_without_secret(code, prefix):
    stderr='Traceback (most recent call last):\n  File "/app/services/uf_rate.py", line 18, in require_real_uf_rate\n'+prefix+'UFServiceError: UF real no disponible secret_password ssid=private\n'
    report=summarize_process(SimpleNamespace(returncode=code,stdout='',stderr=stderr))
    assert report["exit_code"] == code and report["runtime_error"]
    assert report["error"]["type"] == "UFServiceError"
    assert report["error"]["frames"] == [{"file":"uf_rate.py","line":18,"function":"require_real_uf_rate"}]
    assert "private" not in json.dumps(report) and "secret_password" not in json.dumps(report)


def test_launcher_structured_error_is_not_hidden_by_counters():
    stdout=json.dumps({"error":{"type":"ReadTimeout","stage":"uf","message":"password"}})+'\n'+json.dumps({"inserted":4,"updated":2,"cookie":"secret"})
    report=summarize_process(SimpleNamespace(returncode=1,stdout=stdout,stderr=''))
    assert report["counts"] == {"inserted":4,"updated":2}
    assert report["error"]["type"] == "ReadTimeout"
    assert "password" not in json.dumps(report) and "secret" not in json.dumps(report)


async def test_yapo_outage_completes_and_persists_originals_without_loss(engine, monkeypatch):
    from workers import scraper_job as job
    factory = async_sessionmaker(engine, expire_on_commit=False)
    items = [raw(),raw("clp-1",currency="CLP")]
    scraper = SimpleNamespace(source_name="yapo", scrape=AsyncMock(return_value=items),last_raw_count=2)
    store = PendingPriceStore(factory,"yapo")
    stats = await job.run_scraper_job(scraper, factory, pending_uf_store=store,
                 ingestion_resolution=IngestionRate(None,None), uf_info=None)
    assert stats.pending_uf == 1 and stats.inserted == 1 and stats.unexpected_errors == 0
    queued = await store.hgetall("scraper:yapo:pending_uf")
    assert json.loads(queued["uf-1"])["price_uf"] == "1520"
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(ListingORM)) == 1
        s.add(IngestionUFCalendar(date=date(2026,10,15),value=info().rate,source="sii.cl",fetched_at=datetime.now(UTC)))
        await s.commit()
    # Replay uses ORIGINAL observation day, without a live provider/current-day rate.
    empty=SimpleNamespace(source_name="yapo",scrape=AsyncMock(return_value=[]),last_raw_count=0)
    replay = await job.run_scraper_job(empty,factory,pending_uf_store=store,uf_info=None,
                                      ingestion_resolution=IngestionRate(None,None))
    assert replay.pending_uf_reprocessed == 1 and replay.inserted == 1
    assert not await store.hgetall("scraper:yapo:pending_uf")
    async with factory() as s:
        listing=await s.scalar(select(ListingORM).where(ListingORM.external_id=="uf-1"))
        assert listing.price_clp == Decimal(int(Decimal("1520")*info().rate))
        assert listing.raw_metadata["uf_rate_date"] == "2026-10-15"


async def test_portal_outage_completes_and_retains_original_prices(engine, monkeypatch):
    from scripts import portal_card_first as portal
    factory=async_sessionmaker(engine,expire_on_commit=False)
    target={"enabled":True,"operation":"venta","label":"Independencia","property_type":"apartment","base_url":"https://www.portalinmobiliario.com/venta/departamento/independencia-metropolitana"}
    card=dict(raw(),external_id="MLC99999901",raw_metadata={"currency_original":"UF","price_uf":"1520"})
    monkeypatch.setattr(portal,"PORTAL_TARGETS",[target])
    monkeypatch.setattr(portal,"get_settings",lambda:SimpleNamespace(portal_http_enabled=True,portal_geo_detail_budget=0))
    monkeypatch.setattr(portal,"build_portal_target_url",lambda t:t["base_url"])
    monkeypatch.setattr(portal,"classify_portal_page_state",lambda *a,**kw:"authenticated")
    monkeypatch.setattr(portal.PortalInmobiliarioScraper,"parse_listings_detailed",lambda *a,**kw:{"cards_detected":1,"items":[card]})
    client=SimpleNamespace(get=AsyncMock(return_value=httpx.Response(200,text='html')))
    result=await portal.run(apply=True,max_pages=1,max_details=0,pause_s=3,max_geo_details=0,
                       factory=factory,client=client,resolution=IngestionRate(None,None))
    assert result["pending_uf"] == 1 and result["raw_cards"] == 1
    async with factory() as s:
        queued=await s.scalar(select(IngestionPendingPrice))
        assert queued.source == "portalinmobiliario" and queued.payload["price_uf"] == "1520"
        assert queued.payload["price_clp"] is None
        run=await s.scalar(select(IngestionRun))
        assert run.successful and run.counters["pending_uf"] == 1


async def test_portal_exception_is_recorded_and_propagated(engine,monkeypatch):
    from scripts import portal_card_first as portal
    factory=async_sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(portal,"get_settings",lambda:SimpleNamespace(portal_http_enabled=True,portal_geo_detail_budget=0))
    monkeypatch.setattr(portal,"PORTAL_TARGETS",[{"enabled":True,"operation":"venta","base_url":"https://www.portalinmobiliario.com/venta/departamento/test","label":"test","property_type":"apartment"}])
    monkeypatch.setattr(portal,"build_portal_target_url",lambda t:t["base_url"])
    client=SimpleNamespace(get=AsyncMock(side_effect=httpx.ReadTimeout("sensitive data")))
    with pytest.raises(httpx.ReadTimeout):
        await portal.run(apply=True,max_pages=1,max_details=0,pause_s=3,max_geo_details=0,
                         factory=factory,client=client,resolution=IngestionRate(None,None))
    async with factory() as s:
        run=await s.scalar(select(IngestionRun))
        assert not run.successful and run.errors[0]["type"] == "ReadTimeout"
        assert "sensitive" not in json.dumps(run.errors)


def test_actual_host_launcher_returns_child_exit_and_saves_sanitized_error(tmp_path, monkeypatch, capsys):
    from pathlib import Path
    from scripts import run_portal_session as launcher
    meminfo = tmp_path/"meminfo"
    meminfo.write_text("MemAvailable: 2097152 kB\n")
    monkeypatch.setattr(launcher,"Path",lambda value: meminfo if value=="/proc/meminfo" else Path(value))
    monkeypatch.setattr(launcher,"SESSION",tmp_path)
    monkeypatch.setattr(launcher.shutil,"disk_usage",lambda root:SimpleNamespace(free=10*1024**3))
    monkeypatch.setattr(launcher.os,"getuid",lambda:1001,raising=False)
    monkeypatch.setattr(launcher.os,"getgid",lambda:1001,raising=False)
    monkeypatch.setattr(launcher.sys,"argv",["run_portal_session.py"])
    current={"NetworkSettings":{"Networks":{"review":{}}},"Config":{"Env":["PASSWORD=private"]},"Image":"sha256:review"}
    monkeypatch.setattr(launcher.subprocess,"check_output",lambda *a,**kw:json.dumps([current]).encode())
    child=SimpleNamespace(returncode=1,stdout=json.dumps({"error":{"type":"UFServiceError","stage":"uf","reason":"UF real no disponible"}}),stderr="PASSWORD=private")
    monkeypatch.setattr(launcher.subprocess,"run",lambda *a,**kw:child)
    assert launcher.main()==1
    stored=json.loads((tmp_path/"last_run.json").read_text())
    assert stored["runtime_error"] and stored["error"]["type"]=="UFServiceError"
    assert "private" not in json.dumps(stored) and "private" not in capsys.readouterr().out


async def test_endpoint_uses_ledger_and_reports_stale_sources(engine,monkeypatch):
    from api.v1.health import source_health
    import infrastructure.db.database as database
    factory=async_sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(database,"get_session_factory",lambda:factory)
    state=await source_health()
    assert state["status"]=="degraded"
    assert all(v["last_success_at"] is None for v in state["sources"].values())


async def test_replayed_original_is_not_converted_with_wrong_day(engine):
    from workers import scraper_job as job
    factory=async_sessionmaker(engine,expire_on_commit=False)
    store=PendingPriceStore(factory,"yapo")
    item=annotate_pending(raw(),IngestionRate(None,None))
    await store.hset("scraper:yapo:pending_uf","uf-1",json.dumps(item,default=str))
    async with factory() as session:
        session.add(IngestionUFCalendar(date=date(2026,10,16),value=Decimal("41168.03"),source="sii.cl",fetched_at=datetime.now(UTC)))
        await session.commit()
    scraper=SimpleNamespace(source_name="yapo",scrape=AsyncMock(return_value=[]),last_raw_count=0)
    stats=await job.run_scraper_job(scraper,factory,pending_uf_store=store,uf_info=info(date(2026,10,16)),ingestion_resolution=IngestionRate(None,None))
    assert stats.pending_uf==1 and stats.pending_uf_reprocessed==0
    assert "uf-1" in await store.hgetall("scraper:yapo:pending_uf")
