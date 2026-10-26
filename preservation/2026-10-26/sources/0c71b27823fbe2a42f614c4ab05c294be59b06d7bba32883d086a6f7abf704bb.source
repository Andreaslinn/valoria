"""Capture new admissions inside discovery; stop source-wide on access denial."""
import logging
import time
from collections import Counter
from urllib.parse import urljoin, urlsplit
from sqlalchemy import select
from infrastructure.db.models import ListingORM
from infrastructure.db.published_fields import apply_published_fields
from domain.ingestion.published_fields import merge_card_fields
from scripts.portal_session import PortalSessionExpired

COMMUNES = {'santiago', 'nunoa', 'providencia', 'las_condes', 'vitacura', 'la_florida', 'san_miguel', 'estacion_central'}


class DiscoveryAccessBlocked(RuntimeError):
    pass


class DiscoveryAdmission:
    def __init__(self, factory, client, limiter, *, stats=None, seconds=600):
        self.factory, self.client, self.limiter = factory, client, limiter
        self.stats = stats if stats is not None else Counter()
        for key in ('same_day_new_apartments', 'same_day_detail_requests', 'same_day_detail_captured',
                    'same_day_detail_rejected', 'same_day_deferred_deadline', 'blocked_or_captcha'):
            self.stats.setdefault(key, 0)
        self.deadline = time.monotonic() + seconds
        self.requested = self.captured = 0
        self.fetched = {}
        self.visited = set()

    async def has_incomplete_alias(self, raw):
        from infrastructure.db.models import ListingObservationORM
        from config.comunas import normalize_comuna
        if raw.get('property_type') != 'apartment' or normalize_comuna(raw.get('comuna', '')) not in COMMUNES:
            return False
        async with self.factory() as session:
            row = await session.scalar(select(ListingORM).where(ListingORM.source == raw['source'], ListingORM.external_id == str(raw['external_id'])))
            if row is None:
                return False
            facts = (row.raw_metadata or {}).get('published_detail_fields') or (row.raw_metadata or {}).get('published_fields') or {}
            if facts.get('stage') in ('detail', 'merged'):
                return False
            return await session.scalar(select(ListingObservationORM.observation_id).where(
                ListingObservationORM.listing_id == row.id, ListingObservationORM.source == row.source,
                ListingObservationORM.external_id != str(raw['external_id'])).limit(1)) is not None

    async def is_new(self, raw):
        from config.comunas import normalize_comuna
        if raw.get('property_type') != 'apartment' or normalize_comuna(raw.get('comuna', '')) not in COMMUNES:
            return False
        if raw.get('raw_metadata', {}).get('published_fields', {}).get('source_is_project'):
            return False
        async with self.factory() as session:
            return await session.scalar(select(ListingORM.id).where(ListingORM.source == raw['source'], ListingORM.external_id == str(raw['external_id']))) is None

    async def capture(self, raw, *, referer=None, comuna=None):
        from config.comunas import normalize_comuna
        if raw.get('property_type') != 'apartment' or normalize_comuna(comuna or raw.get('comuna', '')) not in COMMUNES:
            return False
        if time.monotonic() >= self.deadline:
            self.stats['same_day_deferred_deadline'] += 1
            return False
        source, identity = raw['source'], str(raw['external_id'])
        url = raw.get('url') or ''
        from workers.portal_geo_enrichment import allowed_url
        if source == 'portalinmobiliario':
            if not allowed_url(url, 'MLC-' + ''.join(c for c in identity if c.isdigit())):
                return False
        elif urlsplit(url).hostname not in {'www.yapo.cl', 'yapo.cl'} or urlsplit(url).scheme != 'https':
            return False
        headers = {'Referer': referer} if referer else {}
        for attempt in range(2 if source == 'portalinmobiliario' else 1):
            await self.limiter.wait()
            self.requested += 1
            self.stats['same_day_detail_requests'] += 1
            response = await self.client.get(url, headers=headers, follow_redirects=False)
            destination = urljoin(url, response.headers.get('location', ''))
            if response.status_code == 302 and ('/gz/account-verification' in destination or '/login' in destination):
                logging.getLogger(__name__).error('PORTAL_SESSION_EXPIRED reason=http_302_account_verification')
                raise PortalSessionExpired('http_302_account_verification')
            if response.status_code in (403, 429):
                self.stats['blocked_or_captcha'] += 1
                logging.getLogger(__name__).error('PORTAL_ACCESS_BLOCKED status=%d', response.status_code)
                raise DiscoveryAccessBlocked('source_access_denied')
            if source == 'portalinmobiliario' and attempt == 0 and response.status_code in (301, 302, 303, 307, 308) and allowed_url(destination, 'MLC-' + ''.join(c for c in identity if c.isdigit())):
                url = destination
                continue
            break
        if response.status_code != 200:
            self.stats['same_day_detail_rejected'] += 1
            return False
        if source == 'portalinmobiliario':
            from domain.geocoding.source_quality import mlc
            key = mlc('MLC-' + ''.join(c for c in identity if c.isdigit()))
            self.visited.add(key)
            # Keep the old geography cache bounded: full Portal HTML is large.
            if len(self.fetched) < 4:
                self.fetched[key] = response
        if source == 'portalinmobiliario':
            from infrastructure.scrapers.portalinmobiliario import parse_listing_detail_portal
            parsed = parse_listing_detail_portal(response.text, url=url)
        else:
            # Original property fields do not depend on price/currency validity.
            # Bind the detail payload to this ID, excluding recommendations.
            from bs4 import BeautifulSoup
            from infrastructure.scrapers.yapo_modern import payload_items
            from infrastructure.scrapers.published_fields import yapo_fields
            soup = BeautifulSoup(response.text, 'lxml')
            item = next((item for item in payload_items(soup) if str(item.get('id')) == identity), None)
            parsed = {'raw_metadata': {'published_fields': yapo_fields(item, soup)}} if item else None
        fields = (parsed or {}).get('raw_metadata', {}).get('published_fields')
        if fields is None or (source == 'portalinmobiliario' and not fields.get('technical_table_observed')):
            self.stats['same_day_detail_rejected'] += 1
            return False
        card = raw.get('raw_metadata', {}).get('published_fields')
        if card and card.get('version') == 1:
            fields = merge_card_fields(fields, card)
            fields['stage'] = 'detail'
            fields['discovery_card_fields'] = card
        async with self.factory() as session:
            row = await session.scalar(select(ListingORM).where(ListingORM.source == source, ListingORM.external_id == identity))
            if row is None or not apply_published_fields(row, fields):
                return False
            await session.commit()
        self.captured += 1
        self.stats['same_day_detail_captured'] += 1
        return True
