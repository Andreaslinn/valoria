import json
from datetime import date, datetime, UTC
from decimal import Decimal
from pathlib import Path
from dataclasses import replace
import pytest
from core.ports.uf_service import UFRateInfo
from core.exceptions import UFServiceError, ValidationError
from domain.ingestion.data_cleaning import clean_listing
from services.yapo_price import prepare_yapo_price, YapoPendingUF
from workers.scraper_job import run_scraper_job

# Actual provider response /api/uf/29-09-2026, fetched during the audit.
RATE = UFRateInfo(rate=Decimal("41049.01"), source="mindicador.cl", rate_date=date(2026,9,29))

def rows():
    data=json.loads((Path(__file__).parents[1]/"fixtures/yapo_normalization_20260929.json").read_text(encoding="utf-8"))
    result=[]
    for item in data["rows"]:
        raw=item["raw"]
        raw["scraped_at"]=datetime.fromisoformat(raw["scraped_at"])
        result.append(raw)
    return result


def test_reproduce_exact_captured_errors_then_normalize_same_twenty():
    errors=[]
    for raw in rows():
        try:clean_listing(raw,allow_incomplete=True)
        except ValidationError as e:errors.append(str(e))
    assert errors == ["price_clp 0 bajo el minimo (10000000)"] * 15
    assert len(rows()) == 20
    for raw in rows():
        prepared=prepare_yapo_price(raw,RATE)
        clean=clean_listing(prepared,allow_incomplete=True)
        assert clean.price.clp >= 10000000
        if raw["price_uf"] is not None:
            assert clean.price.clp == int(Decimal(str(raw["price_uf"]))*RATE.rate)
            assert prepared["raw_metadata"]["uf_rate_source"] == "mindicador.cl"
        else:
            assert prepared == raw
        for field in ("lat","lon","bedrooms","bathrooms","m2","comuna"):
            assert prepared[field] == raw[field]


def test_pending_keeps_original_unchanged():
    raw=rows()[0];before=json.dumps(raw,default=str)
    with pytest.raises(YapoPendingUF):prepare_yapo_price(raw)
    assert json.dumps(raw,default=str)==before


@pytest.mark.parametrize("rate",[replace(RATE,is_stale=True),replace(RATE,is_fallback=True),replace(RATE,rate=Decimal("37000"))])
def test_no_fabricated_or_stale_rate(rate):
    with pytest.raises(UFServiceError):prepare_yapo_price(rows()[0],rate)


def test_bad_clp_still_rejected():
    raw=rows()[3];raw["price_clp"]=1975
    with pytest.raises(ValidationError):clean_listing(prepare_yapo_price(raw,RATE),allow_incomplete=True)


class Store:
    def __init__(self):self.data={}
    async def hset(self,key,field,value):self.data[field]=value
    async def hdel(self,key,field):self.data.pop(field,None)
    async def hgetall(self,key):return dict(self.data)


@pytest.mark.asyncio
async def test_worker_retains_missing_uf_without_invalidating_listings(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    class Scraper:
        source_name="yapo"
        async def scrape(self):return [r for r in rows() if r["price_uf"] is not None]
    store=Store()
    stats=await run_scraper_job(Scraper(),async_sessionmaker(engine,expire_on_commit=False),pending_uf_store=store)
    assert stats.pending_uf == 15
    assert stats.validation_errors == stats.discarded == 0
    assert len(store.data)==15
    assert json.loads(store.data['31911818'])["price_uf"]==9950


@pytest.mark.asyncio
async def test_same_twenty_can_persist_with_verified_conversion(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    class Scraper:
        source_name="yapo"
        async def scrape(self):return [prepare_yapo_price(r,RATE) for r in rows()]
    store=Store()
    for raw in rows():
        if raw["price_uf"] is not None:store.data[raw["external_id"]]=json.dumps(raw,default=str)
    stats=await run_scraper_job(Scraper(),async_sessionmaker(engine,expire_on_commit=False),pending_uf_store=store)
    assert stats.inserted == 20
    assert stats.discarded == stats.validation_errors == stats.unexpected_errors == 0
    assert store.data == {}


@pytest.mark.asyncio
async def test_pending_reprocessed_without_rediscovery_or_http(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    class NoNewListings:
        source_name="yapo"
        async def scrape(self):return []
    store=Store()
    raw=rows()[0]
    store.data[raw["external_id"]]=json.dumps(raw,default=str)
    stats=await run_scraper_job(NoNewListings(),async_sessionmaker(engine,expire_on_commit=False),pending_uf_store=store,uf_info=RATE)
    assert stats.inserted == stats.pending_uf_reprocessed == 1
    assert stats.unexpected_errors == 0
    assert store.data == {}
