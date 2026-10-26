from datetime import UTC, datetime
import json
from collections import Counter
import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy import select
from infrastructure.db.models import ListingORM
from domain.ingestion.published_fields import empty_fields
from infrastructure.scrapers.discovery_fields import portal_search_fields
from workers.discovery_admission import DiscoveryAdmission, DiscoveryAccessBlocked
from scripts.portal_session import PortalSessionExpired
from services.ingestion_state import safe_error


class Limiter:
    def __init__(self): self.calls = 0
    async def wait(self): self.calls += 1


def html(state):
    return '<h1>Departamento</h1><script id="__NORDIC_RENDERING_CTX__">' + json.dumps({'appProps': {'pageProps': {'initialState': state}}}) + '</script>'


def test_card_labels_keep_scalar_range_generic_and_coordinates_distinct():
    results = []
    for i, text in enumerate(['42,6 m² útiles', '22 - 42 m² útiles', '80 m²', '45 m² totales']):
        results.append({'polycard': {'metadata': {'id': 'MLC' + str(100+i), 'domain_id': 'DEVELOPMENT' if i==1 else 'APARTMENT', 'latitude': -33.4, 'longitude': -70.6},
            'components': [{'type': 'attributes_list', 'attributes_list': {'texts': [text]}}]}})
    fields = portal_search_fields(html({'results': results}))
    assert fields['MLC-100']['useful_area_m2'] == 42.6
    assert fields['MLC-100']['provenance']['useful_area_m2'] == 'portal.search.polycard.attributes_list.texts'
    assert fields['MLC-101']['useful_area_m2'] is None
    assert fields['MLC-101']['useful_area_m2_range'] == [22,42]
    assert fields['MLC-101']['source_is_project']
    assert fields['MLC-102']['useful_area_m2'] is None
    assert fields['MLC-102']['total_area_m2'] is None
    assert fields['MLC-103']['total_area_m2'] == 45
    assert fields['MLC-100']['coordinates_precision'] == 'unknown'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,location,error,code', [
    (302,'https://www.portalinmobiliario.com/gz/account-verification',PortalSessionExpired,'PORTAL_SESSION_EXPIRED'),
    (403,None,DiscoveryAccessBlocked,'PORTAL_ACCESS_BLOCKED'),
    (429,None,DiscoveryAccessBlocked,'PORTAL_ACCESS_BLOCKED'),
])
async def test_access_denial_is_not_followed_or_retried(engine,status,location,error,code):
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(status,headers={'Location':location} if location else {})
    limiter=Limiter()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        admission=DiscoveryAdmission(async_sessionmaker(engine),client,limiter)
        with pytest.raises(error) as caught:
            await admission.capture({'source':'portalinmobiliario','external_id':'100','property_type':'apartment','comuna':'santiago','url':'https://www.portalinmobiliario.com/MLC-100'},referer='https://www.portalinmobiliario.com/venta/departamento/santiago-metropolitana')
    assert len(requests)==limiter.calls==1
    assert requests[0].headers['referer'].endswith('santiago-metropolitana')
    assert safe_error(caught.value)['code']==code


@pytest.mark.asyncio
async def test_only_new_scoped_individual_apartments_are_eligible(engine):
    admission=DiscoveryAdmission(async_sessionmaker(engine),None,None)
    raw={'source':'portalinmobiliario','external_id':'100','property_type':'apartment','comuna':'Santiago','raw_metadata':{}}
    assert await admission.is_new(raw)
    assert not await admission.is_new({**raw,'property_type':'house'})
    assert not await admission.is_new({**raw,'comuna':'Colina'})
    assert not await admission.is_new({**raw,'raw_metadata':{'published_fields':{'source_is_project':True}}})


@pytest.mark.asyncio
async def test_fresh_detail_uses_card_useful_and_keeps_commercial_columns(engine):
    factory=async_sessionmaker(engine,expire_on_commit=False)
    fields=empty_fields('portalinmobiliario','100',stage='card')
    fields['useful_area_m2']=42.6
    fields['provenance']['useful_area_m2']='portal.search.polycard.attributes_list.texts'
    raw={'source':'portalinmobiliario','external_id':'100','property_type':'apartment','comuna':'santiago','url':'https://www.portalinmobiliario.com/MLC-100','raw_metadata':{'published_fields':fields}}
    async with factory() as session:
        session.add(ListingORM(source=raw['source'],external_id='100',title='Departamento',url=raw['url'],comuna='santiago',property_type='apartment',m2=45,price_clp=100000000,bedrooms=1,bathrooms=1,parking=0,status='active',fingerprint='100',raw_metadata={},scraped_at=datetime.now(UTC),last_seen_at=datetime.now(UTC)))
        await session.commit()
    state={'id':'MLC100','components':{'technical_specifications':{'id':'technical_specifications','specs':[{'attributes':[{'id':'Superficie útil','text':'42.6 m²'},{'id':'Superficie total','text':'45 m²'},{'id':'Número de piso de la unidad','text':'5'}]}]}}}
    requests=[]
    def respond(request):requests.append(request);return httpx.Response(200,text=html(state))
    limiter=Limiter()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        admission=DiscoveryAdmission(factory,client,limiter)
        assert not await admission.is_new(raw)
        assert await admission.capture(raw)
    assert len(requests)==limiter.calls==1
    async with factory() as session:
        row=await session.scalar(select(ListingORM))
        assert row.m2==45 and row.price_clp==100000000
        assert row.raw_metadata['published_fields']['useful_area_m2']==42.6
        assert row.raw_metadata['published_fields']['total_area_m2']==45
        assert row.raw_metadata['published_fields']['floor']==5
        assert row.raw_metadata['published_fields']['provenance']['useful_area_m2'].startswith('portal.search.')


@pytest.mark.asyncio
async def test_cycle_deadline_defers_without_extra_request(engine):
    stats=Counter()
    admission=DiscoveryAdmission(async_sessionmaker(engine),None,None,seconds=-1,stats=stats)
    assert not await admission.capture({'source':'yapo','external_id':'100','property_type':'apartment','comuna':'santiago'})
    assert stats['same_day_deferred_deadline']==1


@pytest.mark.asyncio
async def test_discovery_does_not_reopen_an_admission_in_backfill(engine,monkeypatch):
    from types import SimpleNamespace
    from decimal import Decimal
    from services.ingestion_uf import IngestionRate
    from core.ports.uf_service import UFRateInfo
    from scripts import portal_card_first as portal
    factory=async_sessionmaker(engine,expire_on_commit=False)
    target={'enabled':True,'operation':'venta','property_type':'apartment','label':'santiago_sale_apartment','base_url':'https://www.portalinmobiliario.com','comuna':'Santiago'}
    monkeypatch.setattr(portal,'PORTAL_TARGETS',[target])
    monkeypatch.setattr(portal,'get_settings',lambda:SimpleNamespace(portal_http_enabled=True,portal_geo_detail_budget=0))
    monkeypatch.setattr(portal,'RateLimiter',lambda interval:Limiter())
    monkeypatch.setattr(portal,'classify_portal_page_state',lambda *args,**kwargs:'authenticated')
    fields=empty_fields('portalinmobiliario','100',stage='card');fields['useful_area_m2']=42.6
    card={'external_id':'100','title':'Departamento','comuna':'Santiago','m2':45,'price_clp':100000000,'url':'https://www.portalinmobiliario.com/MLC-100','raw_metadata':{'currency_original':'CLP','published_fields':fields}}
    monkeypatch.setattr(portal.PortalInmobiliarioScraper,'parse_listings_detailed',lambda *args,**kwargs:{'cards_detected':1,'items':[card]})
    state={'id':'MLC100','components':{'technical_specifications':{'id':'technical_specifications','specs':[{'attributes':[{'id':'Superficie total','text':'45 m²'}]}]}}}
    requests=[]
    def response(request):
        requests.append(str(request.url))
        assert len(requests)<=2,'Discovery reopened the same newly captured ad'
        return httpx.Response(200,text=html(state))
    info=UFRateInfo(rate=Decimal('41168.03'),source='test')
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result=await portal.run(apply=True,max_pages=1,max_details=5,max_geo_details=0,pause_s=3,factory=factory,client=client,resolution=IngestionRate(info,info),enrich_admissions=True)
    assert len(requests)==2
    assert result['same_day_detail_captured']==1
    assert result.get('details_requested',0)==0
    assert result['published_detail_requested']==1


@pytest.mark.asyncio
async def test_large_admission_batch_keeps_only_four_html_responses(engine):
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async with factory() as session:
        for identity in range(100,106):
            session.add(ListingORM(source='portalinmobiliario',external_id=str(identity),title='Departamento',url=f'https://www.portalinmobiliario.com/MLC-{identity}',comuna='santiago',property_type='apartment',m2=45,price_clp=100000000,bedrooms=1,bathrooms=1,parking=0,status='active',fingerprint=str(identity),raw_metadata={},scraped_at=datetime.now(UTC),last_seen_at=datetime.now(UTC)))
        await session.commit()
    def response(request):
        identity=request.url.path.rsplit('-',1)[-1]
        return httpx.Response(200,text=html({'id':'MLC'+identity,'components':{'technical_specifications':{'id':'technical_specifications','specs':[{'attributes':[{'id':'Superficie total','text':'45 m²'}]}]}}}))
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        admission=DiscoveryAdmission(factory,client,Limiter())
        for identity in range(100,106):
            assert await admission.capture({'source':'portalinmobiliario','external_id':str(identity),'property_type':'apartment','comuna':'santiago','url':f'https://www.portalinmobiliario.com/MLC-{identity}'})
        assert admission.captured==6
        assert len(admission.visited)==6
        assert len(admission.fetched)==4


@pytest.mark.asyncio
@pytest.mark.parametrize('currency', ['UF', '$', None])
async def test_yapo_job_initializes_plain_dict_admission_counters(engine, currency):
    from workers.scraper_job import run_scraper_job
    factory=async_sessionmaker(engine,expire_on_commit=False)
    raw={'source':'yapo','external_id':'100','title':'Departamento Santiago','url':'https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/depto/100','comuna':'Santiago','property_type':'apartment','m2':37,'price_clp':100000000,'bedrooms':1,'bathrooms':1,'parking':0,'scraped_at':datetime.now(UTC),'raw_metadata':{}}
    item={'id':'100','link':raw['url'],'title':'Departamento','active':True,'rent':False,'square':'37','lotSize':'40','floor':'19','age':'2008','exactAddress':'Calle A 123','location':{'lat':0,'lon':0,'locality':'Santiago'},'price':{'amount':{'value':'2000'},'currency':{'symbol':'UF'}}}
    item['price']['currency']['symbol'] = currency
    record='1:'+json.dumps({'item':item})+'\n'
    body='<script>self.__next_f.push('+json.dumps([1,record])+')</script>'
    class Scraper:
        source_name='yapo'
        async def scrape(self):return [raw]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,text=body))) as client:
        scraper=Scraper();scraper._http=client;scraper._rate=Limiter()
        stats=await run_scraper_job(scraper,factory,enrich_admissions=True)
    assert stats.reason_counts['same_day_new_apartments']==1
    assert stats.reason_counts['same_day_detail_captured']==1
    async with factory() as session:
        row = await session.scalar(select(ListingORM))
        assert row.price_clp == 100000000 and row.m2 == 37
        assert row.raw_metadata['published_fields']['constructed_area_m2'] == 37
        assert row.raw_metadata['published_fields']['floor'] == 19
