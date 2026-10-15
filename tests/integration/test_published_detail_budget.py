import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from infrastructure.db.models import ListingORM
from workers.published_detail_enrichment import enrich_yapo_details


@pytest.mark.asyncio
async def test_yapo_detail_rotation_never_exceeds_five_or_reprices(engine):
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async with factory() as session:
        for identity in range(100,106):
            session.add(ListingORM(source='yapo',external_id=str(identity),title='Departamento',
                url=f'https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/depto/{identity}',
                comuna='santiago',property_type='apartment',m2=37,built_area_m2=37,usable_area_m2=37,
                bedrooms=1,bathrooms=1,parking=0,price_clp=100_000_000,status='active',
                fingerprint=str(identity),raw_metadata={},scraped_at=datetime.now(UTC),last_seen_at=datetime.now(UTC)))
        await session.commit()
    requests=[]
    def response(request):
        identity=request.url.path.rsplit('/',1)[-1];requests.append(identity)
        item=dict(id=identity,link=request.url.path,title='Departamento',active=True,rent=False,
            square='37',lotSize='40',floor='19',age='2008',exactAddress='Calle A 123',
            location={'lat':0,'lon':0,'locality':'Santiago'},
            price={'amount':{'value':'2000'},'currency':{'symbol':'UF'}})
        record='1:'+json.dumps({'item':item})+'\n'
        return httpx.Response(200,text='<script>self.__next_f.push('+json.dumps([1,record])+')</script>')
    class Limiter:
        calls=0
        async def wait(self):self.calls+=1
    limiter=Limiter()
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result=await enrich_yapo_details(factory,client,limiter,budget=5)
    assert result=={'requested':5,'updated':5,'rejected':0}
    assert len(requests)==limiter.calls==5
    async with factory() as session:
        rows=(await session.scalars(select(ListingORM).order_by(ListingORM.id))).all()
        assert all(row.price_clp==100_000_000 and row.m2==37 for row in rows)
        assert all(row.usable_area_m2 is None for row in rows[:5])
        assert all(row.raw_metadata['published_fields']['floor']==19 for row in rows[:5])
        assert 'published_fields' not in rows[-1].raw_metadata
    requests.clear()
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        await enrich_yapo_details(factory,client,limiter,budget=1)
    assert requests==['105']  # Previously unvisited ads are not starved.


@pytest.mark.asyncio
async def test_detail_budget_cannot_be_raised(engine):
    with pytest.raises(ValueError,match='budget_exceeded'):
        await enrich_yapo_details(async_sessionmaker(engine),None,None,budget=6)
