import json
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from domain.ingestion.published_fields import address, coordinates, empty_fields, area_kind, description_fields
from infrastructure.scrapers.published_fields import portal_fields, yapo_fields
from scripts.portal_session import detect_session_expiry, PortalSessionExpired, portal_client
from services.ingestion_state import safe_error


@pytest.mark.parametrize('case', json.loads((Path(__file__).parents[1]/'fixtures/published_fields_audit_20261015.json').read_text(encoding='utf8')), ids=lambda r:r['id'])
def test_minimal_live_source_fixtures_against_oct15_audit(case):
    if case['source']=='yapo':
        actual=yapo_fields(case['inputs']['item'])
    else:
        actual=portal_fields(case['inputs'],case['inputs']['components'],case['id'])
    for key, expected in case['expected'].items():
        assert actual[key]==expected,(case['id'],key)


@pytest.mark.parametrize('identity,useful,total,floor,age,raw,lat,lon', [
    ('1778189475',50.7,53.6,6,2,'Av. Vicuña Mackenna 6633, La Florida',-33.5161428,-70.6065972),
    ('2247746657',42,45,5,11,'Alcalde Pedro Alarcón 600 - 900, San Miguel',-33.4872423,-70.64524),
    ('4578391212',32,32,None,9,'Metro Ecuador',-33.4535575,-70.6991662),
])
def test_portal_audit_cases(identity,useful,total,floor,age,raw,lat,lon):
    attributes=[{'id':'Superficie útil','text':f'{useful} m²'},
                {'id':'Superficie total','text':f'{total} m²'},
                {'id':'Antigüedad','text':f'{age} años'},
                {'id':'Cantidad de pisos','text':'20'},
                {'id':'Departamentos por piso','text':'15'}]
    if floor is not None:attributes.append({'id':'Número de piso de la unidad','text':str(floor)})
    comp={'technical_specifications':{'specs':[{'attributes':attributes}]},
          'location_and_points':{'map_info':{'item_address':raw,'location':{'latitude':lat,'longitude':lon},'zoom':16}},
          'description':{'content':'Unidad en piso 10.' if floor is None else ''}}
    fields=portal_fields({'id':'MLC'+identity},comp,identity)
    assert (fields['useful_area_m2'],fields['total_area_m2'])==(useful,total)
    assert fields['constructed_area_m2'] is None
    assert fields['floor']==(floor if floor is not None else 10)
    assert fields['age_years']==age
    assert (fields['latitude'],fields['longitude'])==(lat,lon)
    assert fields['coordinates_precision']=='unknown'
    assert fields['apartment_number'] is None
    assert fields['address_raw']==raw
    if identity=='2247746657':assert fields['address_range']==['600','900']
    if identity=='4578391212':assert fields['street'] is None


@pytest.mark.parametrize('identity,square,total,year,floor,lat,lon,raw,description', [
    ('33000977',109,120,2003,4,-33.4391162,-70.6036636,'Providencia, Santiago, Metropolitana De Santiago','Superficie útil: 109 m²'),
    ('33014082',37,37,2008,19,0,0,'Irarrazaval 5091',''),
    ('33003203',77,77,2026,None,-33.5253705,-70.5985391,'Avenida Vicuña Mackenna','Año de construcción: 2012'),
])
def test_yapo_audit_cases(identity,square,total,year,floor,lat,lon,raw,description):
    item=dict(id=identity,square=square,lotSize=total,age=year,floor=floor,
              exactAddress=raw,description='$21',location={'lat':lat,'lon':lon,
              'address':'Av del valle 787, Piso 2 oficinas 202 y 203, Ciudad Empresarial, Huechuraba.'})
    soup=BeautifulSoup('<script type="application/ld+json">'+json.dumps({'@type':'Product','description':description})+'</script>','lxml')
    fields=yapo_fields(item,soup)
    assert fields['constructed_area_m2']==square
    assert fields['total_area_m2']==total
    assert fields['useful_area_m2']==(109 if identity=='33000977' else None)
    assert fields['construction_year']==year
    assert fields['floor']==floor
    assert fields['apartment_number'] is None
    assert fields['address_raw']==raw
    assert fields['coordinates_precision']==('unknown' if lat else None)
    if identity=='33003203':
        assert fields['construction_year_description']==2012
        assert fields['construction_year_conflict']
        assert fields['address_number'] is None
        assert fields['street']=='Avenida Vicuña Mackenna'
    if identity=='33014082':assert fields['latitude'] is fields['longitude'] is None


def test_identity_binding_and_absence():
    assert portal_fields({'id':'MLC12'},{},'13') is None
    fields=yapo_fields({'id':'1'})
    assert fields['constructed_area_m2'] is fields['useful_area_m2'] is fields['floor'] is None
    assert fields['age_years'] is None


def test_invalid_coordinates_and_office_address():
    fields=empty_fields('yapo','1')
    coordinates(fields,0,0,'yapo.location')
    address(fields,'Av del valle 787, Piso 2 oficinas 202 y 203, Ciudad Empresarial, Huechuraba.','yapo.location.address')
    assert fields['latitude'] is fields['longitude'] is fields['street'] is fields['address_raw'] is None
    assert fields['floor'] is fields['apartment_number'] is None


def test_generic_area_is_not_useful():
    assert area_kind({'m2':70,'raw_metadata':{'area_source':'card_generic'}})=='generic'
    assert area_kind({'m2':109,'raw_metadata':{'published_fields':{'constructed_area_m2':109,'useful_area_m2':109}}})=='constructed'


def test_description_intersection_and_floor_are_not_office_or_unit():
    fields=empty_fields('yapo','33000977')
    address(fields,'Providencia, Santiago, Metropolitana De Santiago','yapo.exactAddress')
    description_fields(fields,'Ubicación Premium: Calle Ricardo Lyon, entre Bustos y Av. Francisco de Bilbao. Entorno tranquilo.','description')
    assert fields['address_raw']=='Providencia, Santiago, Metropolitana De Santiago'
    assert fields['address_description_raw']=='Calle Ricardo Lyon, entre Bustos y Av. Francisco de Bilbao'
    assert fields['street']=='Calle Ricardo Lyon'
    assert fields['address_type']=='intersection'
    assert fields['apartment_number'] is None


def test_native_range_floor_preserved_without_inventing_number():
    fields=yapo_fields({'id':'1','floor':'60 +'})
    assert fields['floor'] is None
    assert fields['floor_raw']=='60 +'


def test_apartments_per_floor_is_not_floor():
    fields=empty_fields('yapo','1')
    description_fields(fields,'Departamentos por piso 15. Edificio de 20 pisos.','description')
    assert fields['floor'] is None
    assert fields['apartment_number'] is None


def test_explicit_description_variants_and_conflicting_surfaces():
    fields=yapo_fields({'id':'1','square':'64','lotSize':'68','age':'2024'})
    description_fields(fields,'Superficie construida de 64.03 m² y superficie total de 68.67 m². 71 m² de superficie útil. Piso ocho. Su construcción es del año 2018.','description')
    assert fields['constructed_area_m2']==64
    assert fields['constructed_area_m2_description']==64.03
    assert fields['total_area_m2']==68
    assert fields['total_area_m2_description']==68.67
    assert fields['useful_area_m2']==71
    assert fields['floor']==8
    assert fields['construction_year_description']==2018
    assert fields['construction_year_conflict']


@pytest.mark.parametrize('raw,kind,street,number,span', [
    ('Llanquihue, 6000 - 6300','range','Llanquihue',None,['6000','6300']),
    ('Av. Alberto Hurtado/obispo Javier Vásquez','intersection','Av. Alberto Hurtado',None,None),
    ('Entre El Virrey Y Calle Galicia','intersection','El Virrey',None,None),
    ('Vitacura / Departamento Familiar / 130m2 Totales','no_number',None,None,None),
])
def test_live_address_formats(raw,kind,street,number,span):
    fields=empty_fields('portalinmobiliario','1')
    address(fields,raw,'portal.map_info.item_address')
    assert fields['address_raw']==raw
    assert fields['address_type']==kind
    assert fields['street']==street
    assert fields['address_number']==number
    assert fields['address_range']==span


def test_highlighted_generic_m2_is_not_useful():
    state={'id':'MLC1'}
    comp={'highlighted_specs_res':{'attributes':[{'label':{'text':'80 m²'}}]}}
    assert portal_fields(state,comp,'1')['useful_area_m2'] is None
    comp['highlighted_specs_res']['attributes'][0]['label']['text']='80 m² totales'
    fields=portal_fields(state,comp,'1')
    assert fields['useful_area_m2'] is None
    assert fields['total_area_m2']==80
    assert not fields['technical_table_observed']


@pytest.mark.asyncio
async def test_invalid_session_stops_before_following_and_is_visible_in_ledger(monkeypatch,caplog):
    monkeypatch.delenv('PORTAL_SESSION_FILE',raising=False)
    urls=[]
    def respond(request):
        urls.append(str(request.url))
        return httpx.Response(302,headers={'location':'https://www.portalinmobiliario.com/gz/account-verification?secret=never_log'})
    with pytest.raises(PortalSessionExpired) as caught:
        async with portal_client(transport=httpx.MockTransport(respond),follow_redirects=True) as client:
            await client.get('https://www.portalinmobiliario.com/MLC-123_JM')
    assert len(urls)==1
    assert 'PORTAL_SESSION_EXPIRED' in caplog.text
    assert 'never_log' not in caplog.text
    assert safe_error(caught.value)['code']=='PORTAL_SESSION_EXPIRED'


@pytest.mark.asyncio
async def test_normal_canonical_redirect_is_not_session_alarm():
    await detect_session_expiry(httpx.Response(302,headers={'location':'https://www.portalinmobiliario.com/MLC-123-foo_JM'}))
