"""Capability URLs for derived images; JWT endpoints retain their existing auth."""
import hashlib
import hmac
import re
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from api.deps import CurrentUser

from services.thumbnails import get_store, signature, signed_reference, ThumbnailRef, SIGNED_TTL

router = APIRouter(prefix='/thumbnails', tags=['thumbnails'])


@router.get('/{key}/reference', response_model=ThumbnailRef)
def renew_reference(key: str, current_user: CurrentUser):
    """Renew only an existing cache asset previously returned to this user.

    No source query, queue insertion, ingestion or listing refresh occurs here.
    """
    if not re.fullmatch(r'[a-f0-9]{64}\.webp', key):
        raise HTTPException(404, 'Image unavailable')
    store = get_store()
    with store.connection() as db:
        row = db.execute('''SELECT t.listing_id FROM thumbnails t
            JOIN memberships m ON m.listing_id=t.listing_id
            WHERE t.asset_key=? AND t.status='ready' AND m.owner=? AND m.last_seen>?
            LIMIT 1''', (key, str(current_user.id), time.time()-90*86400)).fetchone()
        if row:
            now = time.time()
            db.execute('UPDATE memberships SET last_seen=? WHERE listing_id=? AND owner=?',
                       (now, row['listing_id'], str(current_user.id)))
            db.execute('UPDATE thumbnails SET last_seen=? WHERE listing_id=?',
                       (now, row['listing_id']))
    ref = store.lookup(row['listing_id']) if row else None
    if not ref:
        raise HTTPException(404, 'Image unavailable')
    return signed_reference(ref)


@router.get('/{key}')
def asset(key: str, request: Request, expires: int = Query(...), sig: str = Query(...)):
    now = int(time.time())
    if (not re.fullmatch(r'[a-f0-9]{64}\.webp', key) or expires <= now
            or expires > now + SIGNED_TTL or not hmac.compare_digest(sig, signature(key, expires))):
        raise HTTPException(403, 'Invalid or expired image reference')
    try:
        body = (get_store().assets / key).read_bytes()
    except OSError:
        raise HTTPException(404, 'Image unavailable') from None
    digest = hashlib.sha256(body).hexdigest()
    if digest != key[:-5]:
        raise HTTPException(404, 'Image unavailable')
    headers = {'ETag': f'"{digest}"', 'Cache-Control': f'private, max-age={min(300, expires-now)}',
               'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer'}
    if request.headers.get('if-none-match') == headers['ETag']:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type='image/webp', headers=headers)
