from datetime import UTC, datetime

import pytest

from domain.ingestion.pipeline import process_listing
from infrastructure.db.repositories import SqlAlchemyListingRepository, SqlAlchemyPropertyRepository, SqlAlchemyPriceHistoryRepository
from infrastructure.scrapers.published_fields import yapo_fields


@pytest.mark.asyncio
async def test_explicit_areas_persist_and_card_does_not_erase_detail(session):
    repos=dict(listing_repo=SqlAlchemyListingRepository(session),
               property_repo=SqlAlchemyPropertyRepository(session),
               price_history_repo=SqlAlchemyPriceHistoryRepository(session))
    item=dict(id='33014082',square=37,lotSize=37,age=2008,floor=19,
              location={'lat':0,'lon':0},exactAddress='Irarrazaval 5091')
    facts=yapo_fields(item)
    raw=dict(source='yapo',external_id='33014082',title='Departamento en Ñuñoa',
             comuna='nunoa',property_type='apartment',m2=37,price_clp=100_000_000,
             bedrooms=1,bathrooms=1,url='https://www.yapo.cl/apartamento/33014082',
             scraped_at=datetime.now(UTC),raw_metadata={'published_fields':facts,'area_source':'yapo_payload.square'})
    saved=await process_listing(raw,**repos)
    await session.commit()
    assert saved.m2==37
    assert saved.built_area_m2==37
    assert saved.usable_area_m2 is None

    assert saved.raw_metadata['published_fields']['total_area_m2']==37
    assert saved.raw_metadata['valuation_m2_kind']=='constructed'
    card=yapo_fields({'id':'33014082','square':37},stage='card')
    saved=await process_listing({**raw,'raw_metadata':{'published_fields':card}},**repos)
    await session.commit()
    assert saved.raw_metadata['published_fields']['floor']==19
    assert saved.raw_metadata['published_fields']['construction_year']==2008
    assert saved.raw_metadata['published_card_fields']['stage']=='card'
    changed_card=yapo_fields({'id':'33014082','square':40},stage='card')
    saved=await process_listing({**raw,'m2':40,'raw_metadata':{'published_fields':changed_card}},**repos)
    await session.commit()
    assert saved.built_area_m2==40
    assert saved.raw_metadata['published_fields']['constructed_area_m2']==40
    assert saved.raw_metadata['published_fields']['floor']==19
    assert saved.raw_metadata['published_fields']['field_observed_at']['floor']==facts['observed_at']
    assert saved.raw_metadata['published_detail_fields']['constructed_area_m2']==37
    assert saved.raw_metadata['built_area_parse_source']=='yapo.square'
    assert 'usable_area_parse_source' not in saved.raw_metadata
    # A later full detail with a missing field must reflect absence, not impute
    # it or leave the old year masquerading as the latest source observation.
    fresh=yapo_fields({'id':'33014082','square':37})
    saved=await process_listing({**raw,'raw_metadata':{'published_fields':fresh}},**repos)
    await session.commit()
    assert saved.raw_metadata['published_fields']['construction_year'] is None
    assert saved.usable_area_m2 is None


@pytest.mark.asyncio
async def test_session_alarm_degrades_source_health(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from services.ingestion_state import start_run, finish_run, safe_error, ingestion_health
    from scripts.portal_session import PortalSessionExpired
    import infrastructure.db.ingestion_models  # register ledger tables
    from infrastructure.db.base import Base
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    run_id=await start_run(factory,'portalinmobiliario')
    await finish_run(factory,run_id,successful=False,errors=[safe_error(PortalSessionExpired('secret'))])
    source=(await ingestion_health(factory))['sources']['portalinmobiliario']
    assert source['status']=='degraded'
    assert source['alarms']==['PORTAL_SESSION_EXPIRED']
    assert 'secret' not in str(source)
