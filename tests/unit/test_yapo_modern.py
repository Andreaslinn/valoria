"""Offline modern Yapo contracts: sanitized actual Chrome capture + boundary cases."""
import copy
import json
from decimal import Decimal
from pathlib import Path
import httpx
import pytest
from bs4 import BeautifulSoup
from infrastructure.scrapers.yapo import YapoScraper, parse_listing_detail, build_page_url, YapoBlockedError
from infrastructure.scrapers.yapo_modern import payload_items, classify_page, YapoStructureError
from infrastructure.scrapers.base import RateLimiter
from domain.ingestion.data_cleaning import clean_listing

FIXTURE = Path(__file__).parents[1] / "fixtures/yapo_modern_results_sanitized.html"
UF = Decimal("40000")


def capture():
    return FIXTURE.read_text(encoding="utf-8")


def source_item():
    return copy.deepcopy(payload_items(BeautifulSoup(capture(), "lxml"), search_only=True)[0])


def page(items, *, total=None, extra=None):
    root = {"initialResults": {"data": items, "metadata": {"total": len(items) if total is None else total, "page": 1}}, "recommendations": extra}
    record = "11:" + json.dumps(root) + "\n"
    return "<script>self.__next_f.push(" + json.dumps([1, record]) + ")</script>"


def parse(html):
    return YapoScraper.parse_listings(html, uf_to_clp=UF)


def test_actual_twenty_listing_capture_contract():
    rows = parse(capture())
    assert len(rows) == 20
    row = next(r for r in rows if r["external_id"] == "32919337")
    assert row["source"] == "yapo"
    assert row["url"].endswith("/32919337")
    assert row["title"] == "Departamento Venta 3D 1B San Pablo Metro Gruta de Lourdes"
    assert row["price_clp"] == 62000000
    assert row["raw_metadata"]["currency_original"] == "CLP"
    assert row["comuna"] == "Región Metropolitana, Quinta Normal"
    assert (row["bedrooms"], row["bathrooms"], row["m2"]) == (3, 1, 46)
    assert row["built_area_m2"] == 46
    assert row["usable_area_m2"] is None
    assert row["land_area_m2"] is None  # apartment total area is not land
    assert row["raw_metadata"]["source_total_area_m2"] == 48
    assert row["property_type"] == "apartment"
    assert row["raw_metadata"]["property_subtype"] == "Apartamento"
    assert row["raw_metadata"]["main_image_url"].startswith("https://photos.encuentra24.com/")
    assert (row["lat"], row["lon"]) == (None, None)
    assert "location_source" not in row["raw_metadata"]


def test_actual_uf_and_coordinates_survive_normalization():
    row = next(r for r in parse(capture()) if r["external_id"] == "32986232")
    assert row["price_uf"] == 3355
    assert row["price_clp"] == 3355 * UF
    assert row["raw_metadata"]["currency_original"] == "UF"
    assert (row["lat"], row["lon"]) == (-33.415874, -70.66536)
    assert row["raw_metadata"]["location_source"] == "yapo_search_payload"
    cleaned = clean_listing(row)
    assert (cleaned.coordinates.lat, cleaned.coordinates.lon) == (row["lat"], row["lon"])


@pytest.mark.parametrize("pair", [(None,None), (0,0), (91,20), (1,181), ("NaN",10), (10,float("inf")), (False,2), (-33,None)])
def test_missing_invalid_and_sentinel_coordinates(pair):
    item = source_item(); item["location"].update(lat=pair[0], lon=pair[1])
    row = parse(page([item]))[0]
    assert (row["lat"], row["lon"]) == (None,None)
    assert row["price_clp"] == 62000000


def test_house_land_and_usable_remain_separate():
    item = source_item(); item.update(link="/bienes-raices-venta-de-propiedades-casas/casa/32919337", subCategoryType="Casa", square="150", lotSize="450", usableArea="140")
    row = parse(page([item]))[0]
    assert row["property_type"] == "house"
    assert (row["built_area_m2"],row["land_area_m2"],row["usable_area_m2"]) == (150,450,140)


def test_no_fabricated_uf_conversion():
    rows = YapoScraper.parse_listings(capture())
    uf = next(r for r in rows if r["external_id"] == "32986232")
    assert uf["price_clp"] == 0
    assert uf["price_uf"] == 3355


DOM = '<a class="item-card-link" href="/bienes-raices-venta-de-propiedades-apartamentos/depto/123"><h3 class="card_title">Depto</h3><span class="card_price">UF 3.355</span><p class="card_subtitle">Independencia</p><span class="card_spec">2 Dormitorios</span><span class="card_spec">1 Baños</span><span class="card_spec">47,7 m²</span><img class="card_image" src="https://example.org/photo.jpg"></a>'


def test_modern_dom_fallback():
    row = parse(DOM)[0]
    assert row["external_id"] == "123"
    assert (row["bedrooms"],row["bathrooms"],row["m2"]) == (2,1,47.7)
    assert row["price_uf"] == 3355
    assert row["raw_metadata"]["parser_source"] == "yapo_search_dom"


def test_payload_wins_over_visual_card_without_duplication():
    item = source_item(); item.update(id="123",link="/bienes-raices-venta-de-propiedades-apartamentos/depto/123")
    rows = parse(page([item]) + DOM)
    assert len(rows) == 1 and rows[0]["price_clp"] == 62000000


def test_related_records_do_not_enter_results():
    other=source_item();other.update(id="999",link="/bienes-raices-venta-de-propiedades-apartamentos/related/999")
    rows=parse(page([source_item()],extra=[other]))
    assert [r["external_id"] for r in rows] == ["32919337"]


def test_pagination_preserves_query():
    url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos?q=keyword.departamentos+venta"
    assert build_page_url(url,2) == url.replace("apartamentos?","apartamentos.2?")


@pytest.mark.parametrize("html", [page([]), '<h1>No se encontraron resultados</h1>'])
def test_confirmed_empty(html):
    assert classify_page(html) == "empty"
    assert parse(html) == []


@pytest.mark.parametrize("html", ['<html></html>', '<script>self.__next_f.push(BROKEN)</script>', page([],total=20), '<h1>Unexpected redesign</h1>'])
def test_unknown_is_not_empty(html):
    assert classify_page(html) == "unknown"
    with pytest.raises(YapoStructureError): parse(html)


def test_normal_recaptcha_is_not_a_challenge():
    html=capture()+'<script id="google-recaptcha-v3" src="https://example.org/recaptcha.js"></script>'
    assert classify_page(html) == "results"
    assert len(parse(html)) == 20


@pytest.mark.parametrize("html", ['<title>Un momento…</title>', '<form id="challenge-form"></form>', '<h1>Verify you are human</h1>'])
def test_specific_challenge_markers(html):
    assert classify_page(html) == "challenge"
    with pytest.raises(YapoBlockedError): parse(html)


@pytest.mark.parametrize("status", [403,429])
@pytest.mark.asyncio
async def test_http_block_stops_after_one_request(status):
    calls=[]
    def handler(request):
        calls.append(str(request.url));return httpx.Response(status,text=capture())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scraper=YapoScraper(http_client=client,rate_limiter=RateLimiter(0),max_pages=1)
        assert await scraper.scrape() == []
    assert len(calls) == 1
    assert classify_page(capture(),status_code=status) == "http_blocked"


def test_detail_ignores_other_property_payload_and_global_attributes():
    other=source_item()
    html=page([other])+'<h1>Casa propia</h1><div>999 m² 9 dormitorios 9 baños</div>'+DOM
    row=parse_listing_detail(html,url="https://www.yapo.cl/bienes-raices-venta-de-propiedades-casas/propia/777")
    assert row["external_id"] == "777"
    assert row["m2"] == row["bedrooms"] == row["bathrooms"] == 0
    assert row["price_clp"] == 0


def test_flight_record_split_across_script_chunks():
    html=page([source_item()]); soup=BeautifulSoup(html,"lxml")
    text=soup.script.string
    chunk=json.loads(text[len("self.__next_f.push("):-1])[1]
    split=len(chunk)//2
    html=''.join('<script>self.__next_f.push('+json.dumps([1,part])+')</script>' for part in (chunk[:split],chunk[split:]))
    assert parse(html)[0]["external_id"] == "32919337"


@pytest.mark.parametrize('text', ['Descripción Ñuñoa\nTerraza ✓', 'line one\nline two\n', ''])
def test_flight_length_delimited_text_does_not_swallow_next_payload(text):
    from infrastructure.scrapers.yapo_modern import payload_items
    record = 'af:T' + format(len(text.encode('utf-8')), 'x') + ',' + text
    record += 'b0:' + json.dumps({'item': source_item()}, ensure_ascii=False) + '\n'
    split = len(record) // 2
    body = ''.join('<script>self.__next_f.push(' + json.dumps([1, part]) + ')</script>'
                   for part in (record[:split], record[split:]))
    assert payload_items(BeautifulSoup(body, 'lxml'))[0]['id'] == '32919337'


def test_pocuro_distinct_houm_references_do_not_share_fingerprint():
    from domain.ingestion.deduplication import make_fingerprint
    items=[]
    for identity, reference in [('32982982','176619'), ('32747182','176620')]:
        value=source_item()
        value.update(id=identity, title='Departamento en Avenida Pocuro', square='84', lotSize='84',
            rooms='2', bathrooms='2', parking='0', description='[VEN] ID HOUM: '+reference,
            link='/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-avenida-pocuro/'+identity,
            location={'locality':'Región Metropolitana, Providencia','lat':-33.435883,'lon':-70.60571})
        items.append(value)
    rows=parse(page(items))
    assert [v['raw_metadata']['source_property_reference']['value'] for v in rows]==['176619','176620']
    assert make_fingerprint(clean_listing(rows[0])) != make_fingerprint(clean_listing(rows[1]))
    same=copy.deepcopy(rows[0]);same['external_id']='99999999';same['url']=same['url'].replace('32982982','99999999')
    assert make_fingerprint(clean_listing(rows[0])) == make_fingerprint(clean_listing(same))


@pytest.mark.asyncio
async def test_modern_coordinates_and_metadata_persist_in_existing_columns(session):
    from domain.ingestion.pipeline import process_listing
    from infrastructure.db.repositories import (SqlAlchemyListingRepository,
        SqlAlchemyPropertyRepository, SqlAlchemyPriceHistoryRepository)
    from infrastructure.db.models import ListingORM
    from sqlalchemy import select
    raw = next(row for row in parse(capture()) if row["external_id"] == "32986232")
    await process_listing(raw, listing_repo=SqlAlchemyListingRepository(session),
        property_repo=SqlAlchemyPropertyRepository(session),
        price_history_repo=SqlAlchemyPriceHistoryRepository(session))
    await session.commit()
    saved = (await session.execute(select(ListingORM))).scalar_one()
    assert (saved.lat, saved.lon) == (raw["lat"], raw["lon"])
    assert saved.raw_metadata["location_source"] == "yapo_search_payload"
    assert saved.price_clp == 3355 * UF
