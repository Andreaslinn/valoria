"""Derived presentation cache. Never fetch images in an API request."""
from __future__ import annotations

import asyncio
from functools import lru_cache
import hashlib
import hmac
import logging
import os
from pathlib import Path
import time

from pydantic import BaseModel, Field
from sqlalchemy import select

from config import get_settings
from infrastructure.db.models import ListingORM
from infrastructure.thumbnails.pipeline import Context, Store

log = logging.getLogger(__name__)
ASSET_PREFIX = '/api/v1/thumbnails/'
SIGNED_TTL = 3600


class ThumbnailRef(BaseModel):
    url: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    bytes: int = Field(gt=0)
    hash: str = Field(pattern=r'^[a-f0-9]{64}$')


def signature(key: str, expires: int) -> str:
    secret = get_settings().jwt_secret_key.encode()
    return hmac.new(secret, f'thumbnail-v1:{key}:{expires}'.encode(), hashlib.sha256).hexdigest()


def signed_reference(ref: dict) -> ThumbnailRef:
    key = ref['hash'] + '.webp'
    expires = int(time.time()) + SIGNED_TTL
    return ThumbnailRef(**{**ref, 'url': f'{ASSET_PREFIX}{key}?expires={expires}&sig={signature(key, expires)}'})


@lru_cache(maxsize=1)
def get_store() -> Store:
    return Store(Path(os.environ.get('THUMBNAIL_STORAGE_ROOT', 'data/thumbnails')))


async def close_store() -> None:
    if get_store.cache_info().currsize:
        await asyncio.to_thread(get_store().close)
        get_store.cache_clear()


def source_payload(listing) -> dict:
    metadata = listing.raw_metadata or {}
    return {**metadata, 'listing_id': listing.id, 'source': listing.source,
            'raw_metadata': metadata, '_source_evidence': metadata.get('_source_evidence', {})}


async def resolve(session, listing_ids, *, owner: int, surface: str, listings=None) -> dict[int, ThumbnailRef | None]:
    """One source query (zero if already loaded), one cache transaction, no downloads."""
    ids = list(dict.fromkeys(i for i in listing_ids if isinstance(i, int) and not isinstance(i, bool) and i > 0))
    result = dict.fromkeys(ids)
    if not ids:
        return result
    try:
        if listings is None:
            listings = (await session.execute(select(ListingORM).where(ListingORM.id.in_(ids)))).scalars().all()
        payloads = [source_payload(item) for item in listings if item.id in result]
        refs = await asyncio.to_thread(get_store().request_many, payloads, Context(surface, True, True, str(owner)))
        for lid, ref in refs.items():
            if ref is not None:
                result[lid] = signed_reference(ref)
    except Exception:
        # An unavailable cache/source query must not hide a valid publication.
        log.warning('thumbnail_enrichment_degraded', exc_info=True)
    return result
