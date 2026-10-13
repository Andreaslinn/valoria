"""Extra bounded detail stage of the existing Portal discovery loop; no timer/job."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select

from domain.geocoding.source_quality import mlc, validate_context
from infrastructure.db.models import ListingORM
from infrastructure.db.portal_geography import (
    apply_geography,
    archived_evidence,
    candidate_evidence,
    claim,
    eligible,
    outcome,
)
from infrastructure.scrapers.portalinmobiliario import (
    classify_portal_detail_page_state,
    parse_listing_detail_portal,
)


def allowed_url(url, publication):
    """Never send server-side requests to a URL outside the configured source."""
    parts = urlsplit(url or "")
    return (
        parts.scheme == "https"
        and not parts.username
        and not parts.password
        and parts.hostname
        in {
            "www.portalinmobiliario.com",
            "portalinmobiliario.com",
            "www.mercadolibre.cl",
            "articulo.mercadolibre.cl",
        }
        and mlc(url) == mlc(publication)
        and mlc(publication) is not None
    )


async def enrich_geography(
    *,
    session_factory,
    client,
    limiter,
    budget=0,
    max_attempts=3,
    cooldown_hours=24,
    now=None,
    fetched=None,
    stats=None,
):
    stats = stats if stats is not None else Counter()
    if budget <= 0:
        return stats
    budget = min(int(budget), 5)
    max_attempts = max(1, min(int(max_attempts), 3))
    cooldown_hours = max(24, cooldown_hours)
    fetched = fetched if fetched is not None else {}
    spent = 0
    cursor = 0
    # Keyset scan avoids starvation behind exhausted older rows. One row locked at
    # a time; only brief DB transactions, never a lock across network I/O.
    while True:
        reference = now or datetime.now(UTC)
        async with session_factory() as session:
            row = await session.scalar(
                select(ListingORM)
                .where(
                    ListingORM.source == "portalinmobiliario",
                    ListingORM.status == "active",
                    ListingORM.id > cursor,
                )
                .order_by(ListingORM.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                break
            cursor = row.id
            if not eligible(row):
                continue
            ev = await archived_evidence(session, row)
            if ev:
                result = await apply_geography(
                    session, row, ev, recovered_at=reference, origin="archive"
                )
                if result == "recovered":
                    stats["geo_recovered_archive"] += 1
                    await outcome(session, row, result)
                    await session.commit()
                    continue
            key = mlc(row.external_id)
            if not allowed_url(row.url, row.external_id):
                stats["geo_invalid_url"] += 1
                continue
            if key not in fetched and spent >= budget:
                continue
            if not await claim(
                session,
                row,
                now=reference,
                max_attempts=max_attempts,
                cooldown_hours=cooldown_hours,
            ):
                continue
            listing_id, url = row.id, row.url
            await session.commit()
        if key in fetched:
            response = fetched[key]
            stats["geo_reused_detail_response"] += 1
        else:
            spent += 1
            stats["geo_details_requested"] += 1
            await limiter.wait()
            try:
                response = await client.get(url, follow_redirects=False)
            except httpx.HTTPError:
                response = None
            fetched[key] = response
        stop = False
        detail = None
        if response is None:
            result = "http_error"
        elif response.status_code in (403, 429):
            result, stop = "blocked", True
        elif response.status_code != 200:
            result = f"http_{response.status_code}"
        elif (
            classify_portal_detail_page_state(response.text, status_code=response.status_code)
            != "detail"
        ):
            result, stop = "unexpected_html", True
        else:
            try:
                detail = parse_listing_detail_portal(response.text, url)
                result = "missing"
            except (ValueError, TypeError, KeyError):
                result = "parse_error"
        async with session_factory() as session:
            row = await session.scalar(
                select(ListingORM).where(ListingORM.id == listing_id).with_for_update()
            )
            ev = candidate_evidence(detail or {})
            if ev:
                ev = validate_context(ev, row.comuna)
                result = await apply_geography(
                    session, row, ev, recovered_at=reference, acquisition=detail
                )
            await outcome(
                session, row, result, max_attempts=max_attempts, evidence=ev, acquisition=detail
            )
            await session.commit()
        stats["geo_" + result] += 1
        if stop:
            stats["geo_stopped"] += 1
            break
    return stats
