import json
import sqlite3
from pathlib import Path

import pytest
from services.sii.closing_address import AddressIndex, SCHEMA,parse_address
from services.sii.local_geography import (LocalGeography, block_fallback, locate_osm,
    osm_anchors, street_matches, write_geography)


def role(rol,street='SAMOTRACIA',number='2071',unit=None,source=9):
    return dict(rol=rol,comuna=15160,block=int(rol.split('-')[1]),street=street,number=number,
                unit=unit,tower=None,raw=f'{street} {number}',kind='casa',year=1979,area=226,source=source)


def index_at(path,rows):
    with sqlite3.connect(path/'address-index.sqlite') as db:
        db.executescript(SCHEMA)
        db.executemany('INSERT INTO role VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',[tuple(r.values()) for r in rows])


def element(num,lat=-33.38,lon=-70.56,id=1,street='Samotracia'):
    return dict(type='node',id=id,lat=lat,lon=lon,tags={'addr:street':street,'addr:housenumber':str(num)})


def test_normalization_and_ambiguity(tmp_path):
    a=parse_address('AV BICENTENARIO 4063 DPD 81')
    assert (a.street,a.number,a.unit,a.tower)==('BICENTENARIO','4063','81','D')
    a=parse_address('SAN FELIX 1585 D 32')
    assert (a.street,a.number,a.unit,a.tower)==('SAN FELIX','1585','32','D')
    assert parse_address('SAN FELIX 1585 32').number is None
    rows=[role('15160-1-1','L TROMBER','5631'),role('15160-2-1','SAMOTRACIA','2071','1'),
          role('15160-2-2','SAMOTRACIA','2071','2')]
    index_at(tmp_path,rows)
    idx=AddressIndex(tmp_path/'address-index.sqlite')
    try:
        assert idx.resolve(15160,'Laura Tromben 5631')['candidates'][0]['rol']=='15160-1-1'
        assert idx.resolve(15160,'Samotracia 2071')['status']=='building'
        assert LocalGeography(tmp_path).nearby(address='Samotracia 2071')['status']=='ambiguous'
        assert idx.resolve(15160,'Av. Samotracia 2071 depto 2')['role']['rol']=='15160-2-2'
        assert idx.resolve(15160,'Samotracia 2071 piso 2')['status']=='ambiguous'
        assert idx.resolve(15160,'Samotracia 2071 depto 99')['status']=='ambiguous'
    finally:
        idx.close()
    assert len(street_matches('SANTA ANA',{'SANTA ANNA','SANTA ANAS'}))==2


def test_geocoding_guards_and_provenance():
    rows=[role('15160-1-1',number='2071'),role('15160-1-2',number='2073'),
          role('15160-1-3',number='3001')]
    data={'elements':[element(2071),element(2075,lat=-33.3805,id=2)]}
    located=locate_osm(rows,data,'hash')
    assert located[rows[0]['rol']]['method']=='osm_direct'
    assert located[rows[1]['rol']]['method']=='osm_interpolated'
    assert located[rows[1]['rol']]['evidence']['anchor_numbers']==(2071,2075)
    block_fallback(rows,located)
    assert located[rows[2]['rol']]['method']=='block_median'
    assert located[rows[2]['rol']]['precision_m']>=100
    bad={'elements':[element(2071),element(2071,lat=-33.40,id=3)]}
    assert not locate_osm(rows,bad,'hash')
    assert not locate_osm([role('15160-1-4',number='2072')],data,'hash') # parity
    far={'elements':[element(2071),element(2075,lat=-33.40,id=2)]}
    assert not locate_osm([rows[1]],far,'hash')


def test_nearby_offline_temporal_self_stale_and_radius(tmp_path,monkeypatch):
    import socket
    monkeypatch.setattr(socket,'create_connection',lambda *a,**k:pytest.fail('network at query time'))
    rows=[role('15160-1-1'),role('15160-1-2',number='2073'),role('15160-1-3',number='2075')]
    index_at(tmp_path,rows)
    loc=locate_osm(rows,{'elements':[element(2071),element(2073,lat=-33.3805,id=2),element(2075,lat=-33.381,id=3)]},'hash')
    loc[rows[2]['rol']]['source_id']=8
    sales=[dict(raw_id=n,rol=rol,date=date,kind='casa',uf=10000,area=200,year=1980,building='b')
           for n,rol,date in [(1,rows[0]['rol'],'2024-01-01'),(2,rows[1]['rol'],'2024-01-01'),
                              (3,rows[1]['rol'],'2027-01-01'),(4,rows[2]['rol'],'2024-01-01')]]
    path=tmp_path/'geography.sqlite'
    write_geography(path,loc,sales,{})
    svc=LocalGeography(tmp_path)
    result=svc.nearby(rol='1-1',as_of='2026-10-25')
    assert [s['raw_id'] for s in result['sales']]==[2]
    assert 50 < result['sales'][0]['distance_m'] < 60
    assert svc.nearby(rol='1-1',radius_m=10)['total']==0
    with pytest.raises(ValueError): svc.nearby(rol='1-1',radius_m=float('nan'))
    # A rebuild replaces the generation, including removed/stale coordinates.
    write_geography(path,{},sales,{})
    assert svc.nearby(rol='1-1')['status']=='unlocated'


@pytest.mark.asyncio
async def test_endpoint_auth_flag_and_validation(monkeypatch):
    import httpx
    from fastapi import FastAPI
    from types import SimpleNamespace
    from api import deps
    from api.v1.tasar import router
    app=FastAPI()
    app.include_router(router,prefix='/api/v1')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        monkeypatch.setenv('sii_closing_layer','true')
        assert (await client.post('/api/v1/tasar/nearby-sales',json={'rol':'1-1'})).status_code==401
        app.dependency_overrides[deps._resolve_current_user]=lambda:SimpleNamespace(id=1)
        assert (await client.post('/api/v1/tasar/nearby-sales',json={'radius_m':-1})).status_code==422
        outside=await client.post('/api/v1/tasar/nearby-sales',json={'comuna':'nunoa','rol':'1-1'})
        assert outside.json()['status']=='outside_coverage'
        monkeypatch.setenv('sii_closing_layer','false')
        assert (await client.post('/api/v1/tasar/nearby-sales',json={'rol':'1-1'})).status_code==404
