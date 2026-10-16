"""Five-detail Yapo refresh inside its existing scheduled process, no new timer."""
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select

from infrastructure.db.models import ListingORM
from infrastructure.db.published_fields import apply_published_fields, record_detail_attempt
from infrastructure.scrapers.yapo import parse_listing_detail


async def enrich_yapo_details(factory, client, limiter, *, budget=5, stats=None):
    if not 0 <= budget <= 5:
        raise ValueError('yapo_detail_budget_exceeded')
    details = {'requested': 0, 'updated': 0, 'rejected': 0}
    async with factory() as session:
        observed = ListingORM.raw_metadata['published_fields']['observed_at'].as_string()
        candidates = (await session.scalars(select(ListingORM).where(
            ListingORM.source == 'yapo', ListingORM.status == 'active',
            ListingORM.property_type == 'apartment',
        ).order_by(ListingORM.raw_metadata['published_detail_attempted_at'].as_string().asc().nulls_first(),
                   observed.asc().nulls_first(), ListingORM.id).limit(budget))).all()
        candidates = [(row.id, row.external_id, row.url) for row in candidates]
    for row_id, external_id, url in candidates:
        await record_detail_attempt(factory, 'yapo', external_id)
        parts = urlsplit(url or '')
        if parts.scheme != 'https' or parts.hostname not in {'www.yapo.cl', 'yapo.cl'} or parts.username or parts.password:
            details['rejected'] += 1
            continue
        await limiter.wait()
        details['requested'] += 1
        try:
            response = await client.get(url, follow_redirects=False)
        except httpx.HTTPError:
            if stats is not None:
                stats.fetch_errors += 1
            break
        if response.status_code in {403, 429}:
            if stats is not None:
                stats.blocked_or_captcha += 1
            break
        if response.status_code != 200:
            details['rejected'] += 1
            continue  # No redirect budget, login solving or extra request.
        from bs4 import BeautifulSoup
        from infrastructure.scrapers.yapo_modern import payload_items
        primary = next((item for item in payload_items(BeautifulSoup(response.text, 'lxml'))
                        if str(item.get('id')) == str(external_id)), None)
        if primary is None or primary.get('active') is False or primary.get('rent') is True:
            if primary is None:
                from infrastructure.scrapers.yapo_modern import classify_page
                if classify_page(response.text, status_code=200) in {'challenge', 'http_blocked'}:
                    if stats is not None:
                        stats.blocked_or_captcha += 1
                    break
            details['rejected'] += 1
            continue
        parsed = parse_listing_detail(response.text, url=url, uf_to_clp=None)
        fields = (parsed or {}).get('raw_metadata', {}).get('published_fields')
        if fields is None:
            details['rejected'] += 1
            continue
        async with factory() as session:
            row = await session.get(ListingORM, row_id)
            if row is not None and apply_published_fields(row, fields):
                details['updated'] += 1
                await session.commit()
    if stats is not None:
        stats.published_detail_requested = details['requested']
        stats.published_detail_captured = details['updated']
        stats.published_detail_rejected = details['rejected']
        for key, value in details.items():
            stats.reason_counts['published_detail_' + key] = value
    return details
