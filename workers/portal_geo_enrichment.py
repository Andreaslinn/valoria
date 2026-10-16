"""Extra bounded detail stage of the existing Portal discovery loop; no timer/job."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from urllib.parse import urlsplit, urljoin

import httpx
from sqlalchemy import select

from domain.geocoding.source_quality import mlc, validate_context
from domain.geocoding.source_quality import evidence, assess
from infrastructure.db.models import ListingORM
from infrastructure.db.portal_geography import (
    apply_geography,
    apply_original_address,
    archived_evidence,
    candidate_evidence,
    claim,
    eligible,
    outcome,
)
from infrastructure.scrapers.portalinmobiliario import (
    classify_portal_detail_page_state,
    classify_portal_page_state,
    parse_listing_detail_portal,
)


def allowed_url(url, publication):
    """Never send server-side requests to a URL outside the configured source."""
    try:
        parts = urlsplit(url or "")
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and not parts.username
        and not parts.password
        and port in (None, 443)
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


def map_publication_points(html):
    """Map markers are geography only, never prices or individual-unit listings."""
    from bs4 import BeautifulSoup
    from infrastructure.scrapers.portalinmobiliario import _extract_nordic_initial_state
    state = _extract_nordic_initial_state(BeautifulSoup(html, "lxml")) or {}
    points = {}
    for result in (state.get("results") or [])[:100]:
        if not isinstance(result, dict):
            continue
        card = result.get("polycard") or {}
        meta = card.get("metadata") or {}
        publication = mlc(meta.get("id"))
        url = str(meta.get("url") or "")
        if not url.startswith("https://"):
            url = "https://" + url
        if not publication or not allowed_url(url, publication):
            continue
        ev = evidence(meta.get("latitude"), meta.get("longitude"),
                      publication_id=publication, source="portal:map_listing_point",
                      observed_at=datetime.now(UTC).isoformat())
        ev["source_url"] = url.split("#", 1)[0].split("?", 1)[0]
        ev["precision_original"] = {key: meta[key] for key in
            ("precision", "accuracy", "approximate", "radius") if key in meta}
        # Do not resolve conflicting duplicate markers by choosing one.
        if publication in points and points[publication].get("original") != ev["original"]:
            points[publication]["quality"] = {"status": "INVALID", "local_eligible": False,
                                              "reason": "source_map_components_conflict"}
        else:
            points.setdefault(publication, ev)
    return points


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
    map_response=None,
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
    # One rotating commune map GET replaces one of the existing five detail
    # requests. It can recover many existing publications without adding ads,
    # changing market freshness, or treating project "from" prices as unit prices.
    communes = ("providencia", "vitacura", "la_florida", "estacion_central", "san_miguel", "santiago")
    reference = now or datetime.now(UTC)
    comuna = communes[reference.date().toordinal() % len(communes)]
    if map_response is None:
        await limiter.wait()
    spent += 1
    stats["geo_map_requests"] += 1
    try:
        response = map_response if map_response is not None else await client.get("https://www.portalinmobiliario.com/venta/departamento/" +
            comuna.replace("_", "-") + "-metropolitana/_DisplayType_M", follow_redirects=False)
    except httpx.HTTPError:
        response = None
    if response is not None and response.status_code in (403, 429):
        stats["geo_stopped"] += 1
        stats["geo_map_blocked"] += 1
        return stats
    if response is not None and response.status_code == 200:
        if classify_portal_page_state(response.text, status_code=200) != "authenticated":
            stats["geo_stopped"] += 1
            stats["geo_map_unexpected_html"] += 1
            return stats
        points = map_publication_points(response.text)
        if points:
            async with session_factory() as session:
                rows = (await session.scalars(select(ListingORM).where(
                    ListingORM.source == "portalinmobiliario", ListingORM.status == "active",
                    ListingORM.property_type == "apartment", ListingORM.comuna == comuna).with_for_update(skip_locked=True))).all()
                for row in rows:
                    ev = points.get(mlc(row.external_id))
                    if not ev or assess(row.lat, row.lon)["status"] not in {"MISSING", "INVALID"}:
                        continue
                    result = await apply_geography(session, row, ev, origin="search_map")
                    stats["geo_map_" + result] += 1
                await session.commit()
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
            # Existing map points can still receive their original address from
            # detail; replay must not consume their slot forever.
            missing = assess(row.lat, row.lon)["status"] in {"MISSING", "INVALID"}
            ev = await archived_evidence(session, row) if missing else None
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
                # A canonical redirect is another HTTP request and consumes the
                # same five-request budget. Never follow login or another MLC.
                if response.status_code in (301, 302, 303, 307, 308):
                    redirected = urljoin(url, response.headers.get("location", ""))
                    if response.headers.get("location") and allowed_url(redirected, key) and spent < budget:
                        spent += 1
                        stats["geo_details_requested"] += 1
                        stats["geo_canonical_redirects"] += 1
                        await limiter.wait()
                        response = await client.get(redirected, follow_redirects=False)
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
            if detail:
                published = (detail.get("raw_metadata") or {}).get("published_fields")
                if published:
                    from infrastructure.db.published_fields import apply_published_fields
                    apply_published_fields(row, published)
                apply_original_address(row, (detail.get("raw_metadata") or {}).get("address_evidence"))
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
