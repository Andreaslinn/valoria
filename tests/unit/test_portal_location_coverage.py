from datetime import date, timedelta
import json

from config.portal_targets import (
    PORTAL_TARGETS, DAILY_DISCOVERY_TARGET_BUDGET,
    PRIORITY_APARTMENT_TARGETS, discovery_targets,
)


def test_missing_sale_apartment_communes_are_covered_every_day():
    for offset in range(6):
        selected = discovery_targets(day=date(2026, 10, 15) + timedelta(days=offset))
        assert len(selected) == DAILY_DISCOVERY_TARGET_BUDGET == 8
        assert len({t["label"] for t in selected}) == 8
        assert all(t["enabled"] and t["operation"] == "venta" for t in selected)
        assert PRIORITY_APARTMENT_TARGETS <= {t["label"] for t in selected}
        assert all(t["property_type"] == "apartment" for t in selected[:6])


def test_existing_sale_coverage_is_not_starved_by_new_targets():
    covered = {t["label"] for offset in range(3)
               for t in discovery_targets(day=date(2026, 10, 15) + timedelta(days=offset))}
    assert covered == {t["label"] for t in PORTAL_TARGETS
                       if t["enabled"] and t["operation"] == "venta"}


def test_original_location_and_address_are_bound_without_invented_accuracy():
    from infrastructure.scrapers.portalinmobiliario import parse_listing_detail_portal
    state = {"id": "MLC1938092725", "components": {"location_and_points": {
        "id": "location_and_points", "map_info": {
            "location": {"latitude": "-33.4331049", "longitude": "-70.601649"},
            "item_address": "Av. Los Leones 1500, Providencia",
            "item_location": "Providencia, RM (Metropolitana)", "zoom": "16"}}}}
    html = '<h1>Departamento</h1><script id="__NORDIC_RENDERING_CTX__">' + json.dumps({
        "appProps": {"pageProps": {"initialState": state}}}) + '</script>'
    detail = parse_listing_detail_portal(html, 'https://www.portalinmobiliario.com/MLC-1938092725')
    meta = detail["raw_metadata"]
    assert detail["location"] == "Av. Los Leones 1500, Providencia"
    assert detail["comuna"] == "Providencia"
    assert meta["address_evidence"]["source_listing_id"] == "MLC-1938092725"
    assert meta["coordinates_evidence"]["original"]["lat"] == "-33.4331049"
    assert meta["coordinates_quality"]["status"] == "UNCERTAIN"
    assert meta["geocode_precision"] == "unknown"
    assert meta["building_candidate"]["certified_building"] is False


def test_building_candidate_requires_street_number_and_commune():
    from domain.ingestion.location_evidence import candidate_building_key as key
    assert key('Av. Los Leones 1500, Providencia', 'Providencia') == key('AV LOS LEONES 1500', 'providencia')
    assert key('Av Los Leones 1500', 'Santiago') != key('Av Los Leones 1500', 'Providencia')
    for address in ['Providencia', 'Los Leones s/n', 'Los Leones 1500-1600',
                    'Los Leones 1500 depto 3', 'Esquina Los Leones 1500']:
        assert key(address, 'Providencia') is None


def test_map_markers_are_identity_bound_and_never_certify_accuracy():
    from workers.portal_geo_enrichment import map_publication_points
    def result(identity, url, lat):
        return {"polycard": {"metadata": {"id": identity, "url": url,
            "latitude": lat, "longitude": "-70.69"}, "components": [{
                "price": {"current_price": {"value": 2715}, "prefix": {"text": "Desde"}}}]}}
    state = {"results": [
        result('MLC123456789', 'portalinmobiliario.com/MLC-123456789', '-33.45'),
        result('MLC987654321', 'portalinmobiliario.com/MLC-123456789', '-33.45'),
        result('MLC333333333', 'evil.example/MLC-333333333', '-33.45')]}
    html='<script id="__NORDIC_RENDERING_CTX__">'+json.dumps({
        "appProps": {"pageProps": {"initialState": state}}})+'</script>'
    points = map_publication_points(html)
    assert set(points) == {'MLC-123456789'}
    assert points['MLC-123456789']['precision'] == 'unknown'
    assert points['MLC-123456789']['quality']['status'] == 'UNCERTAIN'
    assert 'price' not in json.dumps(points)


async def test_geo_application_keeps_prices_area_and_freshness(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from infrastructure.db import portal_geography as geo
    from domain.geocoding.source_quality import evidence
    row=SimpleNamespace(source='portalinmobiliario',status='active',external_id='MLC-123456789',
        id=42,comuna='providencia',lat=None,lon=None,geocode_precision='comuna',raw_metadata={},
        price_clp=100000000,price_uf=2500,m2=70,last_seen_at=datetime(2026,10,15,tzinfo=UTC))
    before=(row.price_clp,row.price_uf,row.m2,row.last_seen_at)
    ev=evidence('-33.4331049','-70.601649',publication_id=row.external_id,
        source='portal:location_and_points.map_info.location')
    ev['address_evidence']={'original':'Av. Los Leones 1500, Providencia',
                            'source_listing_id':row.external_id,'source':ev['source']}
    monkeypatch.setattr(geo,'append_observation',AsyncMock())
    assert await geo.apply_geography(SimpleNamespace(flush=AsyncMock()),row,ev)=='enriched'
    assert (row.price_clp,row.price_uf,row.m2,row.last_seen_at)==before
    assert row.geocode_precision=='unknown'
    assert row.raw_metadata['building_candidate']['certified_building'] is False
    assert row.raw_metadata['address_evidence']['original']=='Av. Los Leones 1500, Providencia'


async def test_map_and_redirects_share_five_request_budget(engine, monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import httpx
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from infrastructure.db.models import ListingORM
    from workers import portal_geo_enrichment as worker
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async with factory() as s:
        for i in range(6):
            identity=f'MLC-{123456780+i}'
            s.add(ListingORM(source='portalinmobiliario',external_id=identity,title='Departamento',
                url=f'https://www.portalinmobiliario.com/{identity}',comuna='santiago',
                property_type='apartment',m2=70,bedrooms=2,bathrooms=1,parking=0,
                price_clp=100000000,fingerprint=identity,status='active',raw_metadata={},
                scraped_at=datetime.now(UTC),last_seen_at=datetime.now(UTC)))
        await s.commit()
    calls=[]
    async def get(url,**kwargs):
        calls.append(url)
        assert kwargs.get('follow_redirects') is False
        if '_DisplayType_M' in url:return httpx.Response(200,text='<html></html>')
        if '?canonical=1' not in url:
            return httpx.Response(301,headers={'location':url+'?canonical=1'})
        return httpx.Response(200,text='<h1>Departamento</h1>')
    monkeypatch.setattr(worker,'classify_portal_page_state',lambda *a,**kw:'authenticated')
    monkeypatch.setattr(worker,'classify_portal_detail_page_state',lambda *a,**kw:'detail')
    stats=await worker.enrich_geography(session_factory=factory,client=SimpleNamespace(get=get),
        limiter=SimpleNamespace(wait=AsyncMock()),budget=5)
    assert len(calls)==5
    assert stats['geo_map_requests']==1
    assert stats['geo_details_requested']==4
    assert stats['geo_canonical_redirects']==2


def test_redirect_targets_reject_login_different_identity_and_external_hosts():
    from workers.portal_geo_enrichment import allowed_url
    for url in ('https://www.portalinmobiliario.com/login',
                'https://www.portalinmobiliario.com/MLC-987654321',
                'https://evil.example/MLC-123456789',
                'https://www.portalinmobiliario.com:invalid/MLC-123456789',
                'https://www.portalinmobiliario.com:444/MLC-123456789'):
        assert not allowed_url(url,'MLC-123456789')


def test_coverage_excludes_unknown_invalid_and_centroid_points():
    from scripts.audit_location_coverage import summarize
    rows=[]
    for i, (precision, lat, lon) in enumerate([
            ('unknown', -33.4, -70.6), ('comuna', -33.4, -70.6),
            ('address', 0, 0), ('street', None, None), ('address', -33.4, -70.6)]):
        rows.append(dict(comuna='providencia',source='yapo',external_id=str(i),
            geocode_precision=precision,lat=lat,lon=lon,address_label='Los Leones 1500'))
    summary=summarize(rows)
    combined=summary['combined'][0]
    assert combined['active']==5 and combined['usable']==1
    assert combined['usable_pct']==20 and not combined['exit_passed']
    assert combined['candidate_buildings_two_plus']==1


def test_original_address_survives_missing_map_coordinates():
    from infrastructure.scrapers.portalinmobiliario import parse_listing_detail_portal
    state={'id':'MLC123456789','components':{'location_and_points':{
        'id':'location_and_points','map_info':{'item_address':'Los Leones 1500, Providencia'}}}}
    html='<h1>Departamento</h1><script id="__NORDIC_RENDERING_CTX__">'+json.dumps({
        'appProps':{'pageProps':{'initialState':state}}})+'</script>'
    result=parse_listing_detail_portal(html,'https://www.portalinmobiliario.com/MLC-123456789')
    assert result['raw_metadata']['address_evidence']['original']=='Los Leones 1500, Providencia'
    assert result['raw_metadata']['coordinates_quality']['status']=='MISSING'
    assert result['raw_metadata']['building_candidate']['certified_building'] is False


def test_address_recovery_rejects_conflicting_commune_and_clears_stale_key():
    from types import SimpleNamespace
    from infrastructure.db.portal_geography import apply_original_address
    row=SimpleNamespace(external_id='MLC-123456789',comuna='providencia',raw_metadata={
        'building_candidate':{'key':'stale'}})
    ev={'original':'Los Leones 1500, Santiago','source_listing_id':row.external_id,
        'source':'portal:location_and_points.map_info.item_address'}
    assert not apply_original_address(row,ev)
    assert row.raw_metadata['building_candidate']['key']=='stale'
    ev['original']='Los Leones, Providencia'
    assert apply_original_address(row,ev)
    assert 'building_candidate' not in row.raw_metadata
