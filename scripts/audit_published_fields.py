"""Validate fresh Oracle observations in an isolated SQLite canonical schema.

Input JSONL is acquired over the scraper clients, never from a source API
substitute. This utility cannot connect to production: its only engine is an
in-memory SQLite database. Network acquisition and the frozen valuation check
are separate, read-only steps. Full descriptions stay in private audit input.
"""
from __future__ import annotations

import asyncio
import csv
import json
import random
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.db.base import Base
from infrastructure.db.models import ListingORM
from infrastructure.db.published_fields import apply_published_fields
from infrastructure.scrapers.published_fields import portal_fields, yapo_fields

AUDIT_COLUMNS = 'source,id,comuna,url,checked_at,address_original,useful_original,total_original,built_original,floor_original,age_original,useful_structured,total_structured,floor_structured,age_structured,address_number,address_range,address_zero,address_reference,apartment_number,useful,total,coordinates,precision_declared,floor,age,lat,lon,useful_description,total_description,floor_description,age_description,address_description'.split(',')


def identity(value):
    return ''.join(c for c in str(value) if c.isdigit())


def extract(record):
    inputs = record['inputs']
    if record['source'] == 'yapo':
        fields = yapo_fields(inputs['item'], description_origin='yapo.audit.resolved_detail_description')
    else:
        fields = portal_fields(inputs, inputs['components'], record['id'])
    if fields is not None:
        fields['observed_at'] = record['checked_at']
    return fields


def observations(lines):
    latest = {}
    for record in lines:
        event = record.get('event')
        if event not in {'detail', 'detail_recheck'}:
            continue
        key = (record['source'], record['id'])
        if event == 'detail':
            assert key not in latest, ('duplicate_initial_observation', key)
        else:
            assert key in latest, ('recheck_without_initial_observation', key)
        latest[key] = record
    return list(latest.values())


def csv_row(record, fields, *, stage, original=None):
    row = {key: None for key in AUDIT_COLUMNS}
    row.update(source=record['source'], id=record['id'], comuna=record.get('comuna'),
               url=record['url'], checked_at=record['checked_at'], stage=stage,
               existed_in_production=original is not None)
    if fields:
        provenance = fields.get('provenance') or {}
        def structured(key):
            path = provenance.get(key, '')
            return bool(path and 'description' not in path)
        row.update(address_original=fields['address_raw'], useful=fields['useful_area_m2'] is not None,
                   total=fields['total_area_m2'] is not None, built_original=fields.get('constructed_area_m2_raw'),
                   useful_structured=structured('useful_area_m2'), total_structured=structured('total_area_m2'),
                   floor_structured=structured('floor'), age_structured=structured('age_years') or structured('construction_year'),
                   useful_original=fields.get('useful_area_m2_raw') if structured('useful_area_m2') else '',
                   total_original=fields.get('total_area_m2_raw') if structured('total_area_m2') else '',
                   floor_original=fields.get('floor_raw') if structured('floor') else '',
                   age_original=fields.get('age_years_raw') if structured('age_years') else fields.get('construction_year_raw') if structured('construction_year') else '',
                   floor=fields['floor'] is not None or fields.get('floor_raw') is not None,
                   age=any(fields.get(k) is not None for k in ('age_years','construction_year','construction_year_description')),
                   lat=fields['latitude'], lon=fields['longitude'], coordinates=fields['latitude'] is not None,
                   precision_declared=fields['coordinates_precision'] not in {None, 'unknown'},
                   address_number=fields['address_number'] not in {None,'0'}, address_range=fields['address_range'] is not None,
                   address_zero=fields['address_number']=='0', address_reference=fields['address_type'] in {'intersection','no_number'},
                   apartment_number=fields['apartment_number'] is not None,
                   useful_description=fields.get('useful_area_m2_description_raw',''),
                   total_description=fields.get('total_area_m2_description_raw',''),
                   floor_description=fields.get('floor_raw') if not structured('floor') else '',
                   age_description=fields.get('construction_year_description_raw',''),
                   address_description=fields.get('address_description_raw'))
        row.update({'published_' + k: v for k, v in fields.items() if k not in {'originals', 'provenance', 'rejected'}})
        row.update(published_provenance=fields['provenance'], published_originals=fields['originals'],
                   published_rejected=fields['rejected'])
    if original:
        row.update({f'legacy_{k}': original.get(k) for k in ('m2', 'built_area_m2', 'usable_area_m2', 'lat', 'lon')})
        row['legacy_area_source'] = (original.get('raw_metadata') or {}).get('area_source')
    return row


async def validate(records, cache, *, minimum=200):
    records = observations(records)
    counts = Counter(r['source'] for r in records)
    assert all(counts[s] >= minimum for s in ('yapo', 'portalinmobiliario')), counts
    assert len({(r['source'], r['id']) for r in records}) == len(records)
    db = {(r['source'], identity(r['external_id'])): r for r in cache if r['event'] == 'db_before'}
    cards = {identity(r['external_id']): r for r in cache if r['event'] == 'fresh_card'}
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    results, export = [], []
    try:
        # Five observations per commit: the same bounded detail batch size.
        for offset in range(0, len(records), 5):
            async with factory() as session:
                for record in records[offset:offset+5]:
                    key = (record['source'], identity(record['id']))
                    original = db.get(key)
                    if original:
                        commerce = original
                        price = original['price_clp']
                    elif record['source'] == 'yapo':
                        from infrastructure.scrapers.yapo_modern import adapt_item
                        commerce = adapt_item(record['inputs']['item'], scraped_at=datetime.now(UTC), uf_to_clp=Decimal('41162.73'))
                        assert commerce is not None, key
                        price = commerce['price_clp']
                    else:
                        commerce = cards.get(key[1])
                        assert commerce is not None, ('fresh_source_price_missing', key)
                        price = commerce.get('price_clp')
                        if not price:
                            price = Decimal(str((commerce.get('raw_metadata') or {})['price_uf'])) * Decimal('41162.73')
                    assert price and Decimal(str(price)) > 0, key
                    fields = extract(record)
                    assert fields is not None, key
                    # Commercial columns are cloned only to test the actual ORM
                    # field-update path; this phase never revalues/reprices them.
                    row = ListingORM(source=record['source'], external_id=record['id'],
                        title=commerce['title'], url=record['url'], comuna=commerce.get('comuna') or record.get('comuna') or '',
                        property_type='apartment', m2=commerce.get('m2'),
                        built_area_m2=commerce.get('built_area_m2'), usable_area_m2=commerce.get('usable_area_m2'),
                        bedrooms=commerce.get('bedrooms') or 0, bathrooms=commerce.get('bathrooms') or 0,
                        parking=commerce.get('parking') or 0, price_clp=Decimal(str(price)),
                        fingerprint=f"audit:{record['source']}:{record['id']}", status='active',
                        raw_metadata=dict(commerce.get('raw_metadata') or {}),
                        scraped_at=datetime.now(UTC), last_seen_at=datetime.now(UTC))
                    before_price, before_m2 = row.price_clp, row.m2
                    assert apply_published_fields(row, fields)
                    assert (row.price_clp, row.m2) == (before_price, before_m2)
                    session.add(row)
                    await session.flush()
                    await session.refresh(row)
                    persisted = row.raw_metadata['published_fields']
                    assert persisted == fields, key
                    assert row.built_area_m2 == fields['constructed_area_m2']
                    assert row.usable_area_m2 == fields['useful_area_m2']
                    export.append(csv_row(record, (original or {}).get('raw_metadata', {}).get('published_fields'), stage='before', original=original))
                    after = csv_row(record, persisted, stage='after', original=original)
                    after['valuation_m2_kind'] = row.raw_metadata['valuation_m2_kind']
                    export.append(after)
                    results.append({k: record[k] for k in ('source', 'id', 'url', 'checked_at')} | {'fields': persisted})
                await session.commit()
        async with factory() as session:
            stored = (await session.scalars(select(ListingORM))).all()
            persisted_counts = Counter(row.source for row in stored)
            assert persisted_counts == counts
        randomizer = random.Random(20261016)
        holdout = []
        for source in ('yapo', 'portalinmobiliario'):
            holdout.extend(randomizer.sample([r for r in records if r['source'] == source], 30))
        return {'counts': dict(counts), 'persisted_counts': dict(persisted_counts),
                'isolated_database': True, 'production_writes': 0, 'commercial_values_unchanged': True}, results, export, holdout
    finally:
        await engine.dispose()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('acquisition', type=Path)
    parser.add_argument('price_cache', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    read = lambda path: [json.loads(line) for line in path.read_text(encoding='utf8').splitlines()]
    proof, results, export, holdout = asyncio.run(validate(read(args.acquisition), read(args.price_cache)))
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in [('persistence-proof.json', proof), ('persisted-fields.json', results), ('random-60-private-review.json', holdout)]:
        (args.output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    columns = AUDIT_COLUMNS + sorted(set().union(*(r.keys() for r in export)) - set(AUDIT_COLUMNS))
    with (args.output/'before-after.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in export:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    print(json.dumps(proof))


if __name__ == '__main__':
    main()
