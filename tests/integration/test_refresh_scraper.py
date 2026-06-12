from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from domain.ingestion.pipeline import process_listing
from infrastructure.db.models import AlertORM, ListingORM, PriceHistoryORM, SavedListingORM, UserORM
from infrastructure.scrapers.base import RateLimiter
from workers.refresh_scraper import run_refresh_scraper, select_refresh_candidates

NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
OLD_SEEN = NOW - timedelta(days=60)


@pytest_asyncio.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _listing(
    *,
    external_id: str,
    url: str,
    source: str = "yapo",
    status: str = "active",
    last_seen_at: datetime = OLD_SEEN,
    last_refresh_attempted_at: datetime | None = None,
    fingerprint: str | None = None,
) -> ListingORM:
    return ListingORM(
        source=source,
        external_id=external_id,
        title="Departamento 3 dormitorios en Nunoa",
        url=url,
        comuna="nunoa",
        property_type="apartment",
        m2=75,
        bedrooms=3,
        bathrooms=2,
        parking=1,
        price_clp=Decimal("180000000"),
        status=status,
        fingerprint=fingerprint or f"fp-{external_id}",
        raw_metadata={},
        scraped_at=last_seen_at,
        last_seen_at=last_seen_at,
        last_refresh_attempted_at=last_refresh_attempted_at,
        created_at=last_seen_at - timedelta(days=10),
        updated_at=last_seen_at,
    )


def _raw_from_listing(listing) -> dict:
    return {
        "source": listing.source,
        "external_id": listing.external_id,
        "title": "Departamento 3 dormitorios en Nunoa",
        "comuna": "Nunoa",
        "property_type": "apartment",
        "m2": 75,
        "bedrooms": 3,
        "bathrooms": 2,
        "parking": 1,
        "price_clp": 180_000_000,
        "url": listing.url,
        "scraped_at": NOW,
        "raw_metadata": {},
    }


def _client(routes: dict[str, httpx.Response | Exception]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        result = routes[str(request.url)]
        if isinstance(result, Exception):
            raise result
        return result

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _insert(session_factory, *listings: ListingORM) -> None:
    async with session_factory() as session:
        session.add_all(listings)
        await session.commit()


async def _stored_listing(session_factory, external_id: str) -> ListingORM:
    async with session_factory() as session:
        return (
            await session.execute(select(ListingORM).where(ListingORM.external_id == external_id))
        ).scalar_one()


async def test_refresh_selection_prioritizes_watchlist(session_factory):
    watched = _listing(
        external_id="watched",
        url="https://www.yapo.cl/departamento-nunoa/watched",
        last_seen_at=OLD_SEEN,
        fingerprint="fp-watched",
    )
    recent = _listing(
        external_id="recent",
        url="https://www.yapo.cl/departamento-nunoa/recent",
        last_seen_at=NOW - timedelta(days=3),
        fingerprint="fp-recent",
    )
    async with session_factory() as session:
        session.add_all([watched, recent])
        await session.flush()
        user = UserORM(email="watcher@example.com", password_hash="hash")
        session.add(user)
        await session.flush()
        session.add(
            SavedListingORM(
                user_id=user.id,
                listing_id=watched.id,
                saved_price_clp=watched.price_clp,
                status="active",
                saved_at=NOW,
            )
        )
        await session.commit()

    candidates = await select_refresh_candidates(session_factory, limit=1, now=NOW)

    assert [candidate.external_id for candidate in candidates] == ["watched"]


async def test_refresh_selection_prioritizes_recent_before_old(session_factory):
    old = _listing(
        external_id="old",
        url="https://www.yapo.cl/departamento-nunoa/old",
        last_seen_at=NOW - timedelta(days=40),
        fingerprint="fp-old",
    )
    recent = _listing(
        external_id="recent",
        url="https://www.yapo.cl/departamento-nunoa/recent",
        last_seen_at=NOW - timedelta(days=5),
        fingerprint="fp-recent",
    )
    await _insert(session_factory, old, recent)

    candidates = await select_refresh_candidates(session_factory, limit=2, now=NOW)

    assert [candidate.external_id for candidate in candidates] == ["recent", "old"]


async def test_refresh_selection_skips_recently_refreshed_listing(session_factory):
    skipped = _listing(
        external_id="skip",
        url="https://www.yapo.cl/departamento-nunoa/skip",
        last_seen_at=NOW - timedelta(days=3),
        last_refresh_attempted_at=NOW - timedelta(hours=1),
        fingerprint="fp-skip",
    )
    selected = _listing(
        external_id="selected",
        url="https://www.yapo.cl/departamento-nunoa/selected",
        last_seen_at=NOW - timedelta(days=40),
        last_refresh_attempted_at=NOW - timedelta(hours=25),
        fingerprint="fp-selected",
    )
    await _insert(session_factory, skipped, selected)

    candidates = await select_refresh_candidates(session_factory, limit=10, now=NOW)

    assert [candidate.external_id for candidate in candidates] == ["selected"]


async def test_refresh_selection_filters_source_active_comuna_and_property_type(session_factory):
    wanted = _listing(
        external_id="wanted",
        url="https://www.yapo.cl/departamento-nunoa/wanted",
        source="yapo",
        status="active",
        fingerprint="fp-wanted",
    )
    wrong_source = _listing(
        external_id="wrong-source",
        url="https://www.portal.cl/departamento-nunoa/wrong-source",
        source="portalinmobiliario",
        status="active",
        fingerprint="fp-wrong-source",
    )
    wrong_type = _listing(
        external_id="wrong-type",
        url="https://www.yapo.cl/casa-nunoa/wrong-type",
        source="yapo",
        status="active",
        fingerprint="fp-wrong-type",
    )
    wrong_type.property_type = "house"
    inactive = _listing(
        external_id="inactive-filtered",
        url="https://www.yapo.cl/departamento-nunoa/inactive-filtered",
        source="yapo",
        status="inactive",
        fingerprint="fp-inactive-filtered",
    )
    await _insert(session_factory, wanted, wrong_source, wrong_type, inactive)

    candidates = await select_refresh_candidates(
        session_factory,
        limit=10,
        source="yapo",
        only_active=True,
        comuna="nunoa",
        property_type="apartment",
        now=NOW,
    )

    assert [candidate.external_id for candidate in candidates] == ["wanted"]


async def test_refresh_selection_does_not_select_removed_listings(session_factory):
    removed = _listing(
        external_id="removed",
        url="https://www.yapo.cl/departamento-nunoa/removed",
        status="removed",
        fingerprint="fp-removed",
    )
    active = _listing(
        external_id="active",
        url="https://www.yapo.cl/departamento-nunoa/active",
        fingerprint="fp-active",
    )
    await _insert(session_factory, removed, active)

    candidates = await select_refresh_candidates(session_factory, limit=10, now=NOW)

    assert [candidate.external_id for candidate in candidates] == ["active"]


async def test_refresh_processes_valid_url_and_calls_pipeline(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/1"
    await _insert(session_factory, _listing(external_id="1", url=url))
    calls = []

    async def fake_process(raw, **repos):
        calls.append((raw, repos))

    async with _client({url: httpx.Response(200, text="<html>ok</html>")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            parser=lambda listing, html: _raw_from_listing(listing),
            process_listing_fn=fake_process,
            now=NOW,
        )

    assert stats.selected == 1
    assert stats.fetched == 1
    assert stats.processed == 1
    assert len(calls) == 1
    assert calls[0][0]["raw_metadata"]["refresh_source"] == "direct_url"
    stored = await _stored_listing(session_factory, "1")
    assert stored.status == "active"
    assert stored.last_refresh_status == "ok"


async def test_refresh_respects_batch_limit(session_factory):
    urls = [f"https://www.yapo.cl/departamento-nunoa/{index}" for index in range(1, 4)]
    await _insert(
        session_factory,
        *[
            _listing(external_id=str(index), url=url, last_seen_at=OLD_SEEN + timedelta(days=index))
            for index, url in enumerate(urls, start=1)
        ],
    )
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, text="<html>ok</html>")

    async def fake_process(raw, **repos):
        return None

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            limit=2,
            rate_limiter=RateLimiter(0),
            parser=lambda listing, html: _raw_from_listing(listing),
            process_listing_fn=fake_process,
            now=NOW,
        )

    assert stats.selected == 2
    assert stats.processed == 2
    assert len(requested) == 2


async def test_refresh_404_marks_listing_removed(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/404"
    await _insert(session_factory, _listing(external_id="404", url=url))

    async with _client({url: httpx.Response(404, text="not found")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            uf_to_clp=Decimal("37000"),
            uf_rate_source="real",
            now=NOW,
        )

    stored = await _stored_listing(session_factory, "404")
    assert stats.not_found == 1
    assert stats.removed == 1
    assert stored.status == "removed"
    assert stored.last_refresh_status == "removed_404"
    assert stored.last_seen_at == OLD_SEEN.replace(tzinfo=None)


async def test_refresh_home_redirect_marks_listing_removed(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/302"
    await _insert(session_factory, _listing(external_id="302", url=url))

    async with _client(
        {url: httpx.Response(302, headers={"location": "https://www.yapo.cl/"})}
    ) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            uf_to_clp=Decimal("37000"),
            uf_rate_source="real",
            now=NOW,
        )

    stored = await _stored_listing(session_factory, "302")
    assert stats.redirects == 1
    assert stats.removed == 1
    assert stored.status == "removed"
    assert stored.last_refresh_status == "removed_redirect"


async def test_refresh_unexpected_html_does_not_mark_listing_inactive(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/bad-html"
    await _insert(session_factory, _listing(external_id="bad-html", url=url))

    async with _client({url: httpx.Response(200, text="<html>unexpected</html>")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            parser=lambda listing, html: None,
            now=NOW,
        )

    stored = await _stored_listing(session_factory, "bad-html")
    assert stats.parse_errors == 1
    assert stats.inactive == 0
    assert stored.status == "active"
    assert stored.last_refresh_status == "unexpected_html"


async def test_refresh_explicit_inactive_html_marks_listing_inactive(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/inactive-html"
    await _insert(session_factory, _listing(external_id="inactive-html", url=url))

    async with _client(
        {url: httpx.Response(200, text="<html>publicacion no disponible</html>")}
    ) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            parser=lambda listing, html: None,
            now=NOW,
        )

    stored = await _stored_listing(session_factory, "inactive-html")
    assert stats.parse_errors == 1
    assert stats.inactive == 1
    assert stored.status == "inactive"
    assert stored.last_refresh_status == "inactive_explicit"


async def test_refresh_timeout_does_not_change_status(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/timeout"
    await _insert(session_factory, _listing(external_id="timeout", url=url))

    async with _client({url: httpx.TimeoutException("timeout")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            now=NOW,
        )

    stored = await _stored_listing(session_factory, "timeout")
    assert stats.timeouts == 1
    assert stored.status == "active"
    assert stored.last_refresh_status == "timeout"
    assert stored.last_seen_at == OLD_SEEN.replace(tzinfo=None)


async def test_refresh_429_does_not_change_status(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/429"
    await _insert(session_factory, _listing(external_id="429", url=url))

    async with _client({url: httpx.Response(429, text="rate limited")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            now=NOW,
        )

    stored = await _stored_listing(session_factory, "429")
    assert stats.rate_limited == 1
    assert stored.status == "active"
    assert stored.last_refresh_status == "transient_429"
    assert stored.last_seen_at == OLD_SEEN.replace(tzinfo=None)


async def test_refresh_403_does_not_change_status(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/403"
    await _insert(session_factory, _listing(external_id="403", url=url))

    async with _client({url: httpx.Response(403, text="forbidden")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            now=NOW,
        )

    stored = await _stored_listing(session_factory, "403")
    assert stats.forbidden == 1
    assert stats.blocked_or_captcha == 1
    assert stored.status == "active"
    assert stored.last_refresh_status == "blocked_403"
    assert stored.last_seen_at == OLD_SEEN.replace(tzinfo=None)


async def test_refresh_500_does_not_change_status(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/500"
    await _insert(session_factory, _listing(external_id="500", url=url))

    async with _client({url: httpx.Response(500, text="server error")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            now=NOW,
        )

    stored = await _stored_listing(session_factory, "500")
    assert stats.server_errors == 1
    assert stored.status == "active"
    assert stored.last_refresh_status == "transient_5xx"
    assert stored.last_seen_at == OLD_SEEN.replace(tzinfo=None)


async def test_refresh_success_reactivates_inactive_listing(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/inactive"
    await _insert(session_factory, _listing(external_id="inactive", url=url, status="inactive"))

    async def fake_process(raw, **repos):
        return None

    async with _client({url: httpx.Response(200, text="<html>ok</html>")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            parser=lambda listing, html: _raw_from_listing(listing),
            process_listing_fn=fake_process,
            now=NOW,
        )

    stored = await _stored_listing(session_factory, "inactive")
    assert stats.processed == 1
    assert stored.status == "active"
    assert stored.last_refresh_status == "ok"


async def test_refresh_continues_when_one_url_fails(session_factory):
    bad_url = "https://www.yapo.cl/departamento-nunoa/404"
    good_url = "https://www.yapo.cl/departamento-nunoa/ok"
    await _insert(
        session_factory,
        _listing(external_id="bad", url=bad_url, fingerprint="fp-bad"),
        _listing(external_id="ok", url=good_url, fingerprint="fp-ok"),
    )
    calls = []

    async def fake_process(raw, **repos):
        calls.append(raw)

    async with _client(
        {
            bad_url: httpx.Response(404, text="not found"),
            good_url: httpx.Response(200, text="<html>ok</html>"),
        }
    ) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            parser=lambda listing, html: _raw_from_listing(listing),
            process_listing_fn=fake_process,
            now=NOW,
        )

    assert stats.not_found == 1
    assert stats.processed == 1
    assert len(calls) == 1
    assert calls[0]["external_id"] == "ok"


async def test_refresh_max_errors_stops_batch(session_factory):
    first_url = "https://www.yapo.cl/departamento-nunoa/error-1"
    second_url = "https://www.yapo.cl/departamento-nunoa/error-2"
    await _insert(
        session_factory,
        _listing(external_id="error-1", url=first_url, fingerprint="fp-error-1"),
        _listing(external_id="error-2", url=second_url, fingerprint="fp-error-2"),
    )
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(500, text="server error")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            max_errors=1,
            now=NOW,
        )

    assert stats.server_errors == 1
    assert len(requested) == 1


async def test_refresh_does_not_duplicate_existing_listing_with_real_pipeline(session_factory):
    url = "https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-nunoa/123"
    await _insert(session_factory, _listing(external_id="123", url=url, fingerprint="fp-original"))
    html = """
    <html>
      <head>
        <meta property="og:title" content="Departamento 3 dormitorios en Nunoa" />
        <meta name="description" content="75 m2, 3 dormitorios, 2 banos, 1 estacionamiento" />
      </head>
      <body>
        <h1>Departamento 3 dormitorios en Nunoa</h1>
        <p>$180.000.000</p>
        <p>75 m2 3 dormitorios 2 banos 1 estacionamiento</p>
      </body>
    </html>
    """

    async with _client({url: httpx.Response(200, text=html)}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            now=NOW,
        )

    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(ListingORM))
        listing = (await session.execute(select(ListingORM))).scalar_one()
        alerts = (await session.execute(select(AlertORM))).scalars().all()

    assert stats.processed == 1
    assert total == 1
    assert listing.external_id == "123"
    assert listing.status == "active"
    assert listing.last_seen_at != OLD_SEEN.replace(tzinfo=None)
    assert alerts == []


async def test_refresh_price_change_creates_price_history_and_metrics(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/price-change"
    await _insert(session_factory, _listing(external_id="price-change", url=url))

    async def lower_price(raw_listing, **repos):
        raw = dict(raw_listing)
        raw["price_clp"] = 160_000_000
        return await process_listing(raw, **repos)

    async with _client({url: httpx.Response(200, text="<html>ok</html>")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            parser=lambda listing, html: _raw_from_listing(listing),
            process_listing_fn=lower_price,
            now=NOW,
        )

    listing = await _stored_listing(session_factory, "price-change")
    async with session_factory() as session:
        history_count = await session.scalar(
            select(func.count(PriceHistoryORM.id)).where(PriceHistoryORM.listing_id == listing.id)
        )

    assert listing.price_clp == Decimal("160000000")
    assert stats.price_changes_detected == 1
    assert stats.price_drops_detected == 1
    assert stats.price_increases_detected == 0
    assert stats.price_history_points_created == 1
    assert history_count == 1


async def test_refresh_ignores_price_change_explained_by_uf_rate_artifact(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/uf-artifact"
    listing = _listing(external_id="uf-artifact", url=url, fingerprint="fp-uf-artifact")
    listing.price_clp = Decimal("132259985")
    listing.raw_metadata = {"price_uf": 3250.0}
    await _insert(session_factory, listing)

    def same_uf_with_different_rate(listing, html):
        raw = _raw_from_listing(listing)
        raw["price_uf"] = 3250.0
        raw["price_clp"] = 120_250_000
        raw["raw_metadata"] = {
            "price_uf": 3250.0,
            "price_conversion_source": "fallback",
            "uf_rate_used": "37000",
        }
        return raw

    async with _client({url: httpx.Response(200, text="<html>ok</html>")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            parser=same_uf_with_different_rate,
            now=NOW,
        )

    stored = await _stored_listing(session_factory, "uf-artifact")
    async with session_factory() as session:
        history_count = await session.scalar(
            select(func.count(PriceHistoryORM.id)).where(PriceHistoryORM.listing_id == stored.id)
        )

    assert stored.price_clp == Decimal("132259985")
    assert stored.raw_metadata["price_change_ignored_reason"] == "uf_rate_artifact"
    assert stats.price_changes_detected == 0
    assert stats.price_changes_ignored_uf_rate_artifact == 1
    assert stats.price_drops_detected == 0
    assert stats.price_history_points_created == 0
    assert stats.listings_with_price_uf == 1
    assert stats.listings_using_uf_fallback == 1
    assert history_count == 0


async def test_refresh_keeps_price_history_when_price_uf_changes(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/uf-real-change"
    listing = _listing(external_id="uf-real-change", url=url, fingerprint="fp-uf-real-change")
    listing.price_clp = Decimal("120250000")
    listing.raw_metadata = {"price_uf": 3250.0}
    await _insert(session_factory, listing)

    def changed_uf(listing, html):
        raw = _raw_from_listing(listing)
        raw["price_uf"] = 3200.0
        raw["price_clp"] = 118_400_000
        raw["raw_metadata"] = {
            "price_uf": 3200.0,
            "price_conversion_source": "real",
            "uf_rate_used": "37000",
        }
        return raw

    async with _client({url: httpx.Response(200, text="<html>ok</html>")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            parser=changed_uf,
            now=NOW,
        )

    stored = await _stored_listing(session_factory, "uf-real-change")
    async with session_factory() as session:
        history_count = await session.scalar(
            select(func.count(PriceHistoryORM.id)).where(PriceHistoryORM.listing_id == stored.id)
        )

    assert stored.price_clp == Decimal("118400000")
    assert stored.raw_metadata["price_uf"] == 3200.0
    assert stats.price_changes_detected == 1
    assert stats.price_changes_ignored_uf_rate_artifact == 0
    assert stats.price_history_points_created == 1
    assert history_count == 1


async def test_refresh_blocks_geocode_precision_downgrade_address_to_street(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/address-to-street"
    listing = _listing(external_id="address-to-street", url=url, fingerprint="fp-address-to-street")
    listing.geocode_precision = "address"
    listing.raw_metadata = {"address_label": "Av. Siempre Viva 123"}
    await _insert(session_factory, listing)

    async def downgrade_to_street(raw, **repos):
        session = repos["listing_repo"]._session
        row = await session.get(ListingORM, raw["raw_metadata"]["refresh_listing_id"])
        row.geocode_precision = "street"
        row.raw_metadata = {**row.raw_metadata, "street_hint": "Av. Siempre Viva"}
        await session.flush()
        return SimpleNamespace(id=row.id)

    async with _client({url: httpx.Response(200, text="<html>ok</html>")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            parser=lambda listing, html: _raw_from_listing(listing),
            process_listing_fn=downgrade_to_street,
            now=NOW,
        )

    stored = await _stored_listing(session_factory, "address-to-street")
    assert stored.geocode_precision == "address"
    assert stats.geocode_precision_downgrades == 0
    assert stats.geocode_precision_downgrades_blocked == 1
    assert stored.raw_metadata["refresh_geocode_precision_downgrade_blocked"] is True


async def test_refresh_blocks_geocode_precision_downgrade_street_to_comuna(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/street-to-comuna"
    listing = _listing(external_id="street-to-comuna", url=url, fingerprint="fp-street-to-comuna")
    listing.geocode_precision = "street"
    listing.raw_metadata = {"street_hint": "Av. Siempre Viva"}
    await _insert(session_factory, listing)

    async def downgrade_to_comuna(raw, **repos):
        session = repos["listing_repo"]._session
        row = await session.get(ListingORM, raw["raw_metadata"]["refresh_listing_id"])
        row.geocode_precision = "comuna"
        await session.flush()
        return SimpleNamespace(id=row.id)

    async with _client({url: httpx.Response(200, text="<html>ok</html>")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            parser=lambda listing, html: _raw_from_listing(listing),
            process_listing_fn=downgrade_to_comuna,
            now=NOW,
        )

    stored = await _stored_listing(session_factory, "street-to-comuna")
    assert stored.geocode_precision == "street"
    assert stats.geocode_precision_downgrades == 0
    assert stats.geocode_precision_downgrades_blocked == 1


async def test_refresh_invalid_low_price_does_not_create_price_history(session_factory):
    url = "https://www.yapo.cl/departamento-nunoa/low-price"
    await _insert(session_factory, _listing(external_id="low-price", url=url))

    def low_price_raw(listing, html):
        raw = _raw_from_listing(listing)
        raw["price_clp"] = 116_550
        return raw

    async with _client({url: httpx.Response(200, text="<html>ok</html>")}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            parser=low_price_raw,
            now=NOW,
        )

    listing = await _stored_listing(session_factory, "low-price")
    async with session_factory() as session:
        history_count = await session.scalar(
            select(func.count(PriceHistoryORM.id)).where(PriceHistoryORM.listing_id == listing.id)
        )

    assert stats.validation_errors == 1
    assert stats.price_changes_detected == 0
    assert stats.price_history_points_created == 0
    assert listing.price_clp == Decimal("180000000")
    assert history_count == 0


async def test_refresh_real_pipeline_processes_structured_detail_area(session_factory):
    url = "https://www.yapo.cl/bienes-raices-venta-de-propiedades-casas/casa-remodelada-estacion-central/26139896"
    await _insert(session_factory, _listing(external_id="26139896", url=url, fingerprint="fp-area"))
    html = """
    <html>
      <head><meta property="og:title" content="Casa remodelada en Estacion Central" /></head>
      <body>
        <h1>Casa remodelada en Estacion Central</h1>
        <div class="d3-property-info__price">$140.000.000</div>
        <div class="listing-location">Estación Central</div>
        <div class="d3-property-insight__attribute">
          <dt class="d3-property-insight__attribute-title">Precio</dt>
          <dd class="d3-property-insight__attribute-value">$140.000.000</dd>
        </div>
        <div class="d3-property-insight__attribute">
          <dt class="d3-property-insight__attribute-title">Dormitorios</dt>
          <dd class="d3-property-insight__attribute-value">3</dd>
        </div>
        <div class="d3-property-insight__attribute">
          <dt class="d3-property-insight__attribute-title">Baños</dt>
          <dd class="d3-property-insight__attribute-value">2</dd>
        </div>
        <div class="d3-property-insight__attribute">
          <dt class="d3-property-insight__attribute-title">Estacionamientos</dt>
          <dd class="d3-property-insight__attribute-value">4</dd>
        </div>
        <div class="d3-property-insight__attribute">
          <dt class="d3-property-insight__attribute-title">Área construida (m²)</dt>
          <dd class="d3-property-insight__attribute-value">150</dd>
        </div>
        <p>Precio/M² de construcción $933.333 M² totales ¡Pregunta al anunciante!</p>
      </body>
    </html>
    """

    async with _client({url: httpx.Response(200, text=html)}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            now=NOW,
        )

    listing = await _stored_listing(session_factory, "26139896")

    assert stats.processed == 1
    assert stats.validation_errors == 0
    assert listing.last_refresh_status == "ok"
    assert listing.price_clp == Decimal("140000000")
    assert listing.m2 == 150
    assert listing.built_area_m2 == 150


async def test_refresh_real_pipeline_processes_detail_uf_price(session_factory):
    url = "https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-san-diego/29273175"
    await _insert(session_factory, _listing(external_id="29273175", url=url, fingerprint="fp-uf"))
    html = """
    <html>
      <head><meta property="og:title" content="Departamento en San Diego" /></head>
      <body>
        <h1>Departamento en San Diego</h1>
        <div class="d3-property-info__price">UF973,00</div>
        <div class="listing-location">Santiago</div>
        <div class="d3-property-insight__attribute">
          <dt class="d3-property-insight__attribute-title">Dormitorios</dt>
          <dd class="d3-property-insight__attribute-value">1</dd>
        </div>
        <div class="d3-property-insight__attribute">
          <dt class="d3-property-insight__attribute-title">Baños</dt>
          <dd class="d3-property-insight__attribute-value">1</dd>
        </div>
        <div class="d3-property-insight__attribute">
          <dt class="d3-property-insight__attribute-title">Área construida (m²)</dt>
          <dd class="d3-property-insight__attribute-value">21</dd>
        </div>
      </body>
    </html>
    """

    async with _client({url: httpx.Response(200, text=html)}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            uf_to_clp=Decimal("37000"),
            uf_rate_source="real",
            now=NOW,
        )

    listing = await _stored_listing(session_factory, "29273175")

    assert stats.processed == 1
    assert stats.validation_errors == 0
    assert listing.last_refresh_status == "ok"
    assert listing.price_clp == Decimal("36001000")
    assert listing.m2 == 21
    assert listing.property_type == "apartment"


async def test_refresh_yapo_detail_without_uf_rate_does_not_use_fallback_silently(session_factory):
    url = "https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-san-diego-no-rate/29273176"
    await _insert(session_factory, _listing(external_id="29273176", url=url, fingerprint="fp-uf-no-rate"))
    html = """
    <html>
      <head><meta property="og:title" content="Departamento en San Diego" /></head>
      <body>
        <h1>Departamento en San Diego</h1>
        <div class="d3-property-info__price">UF973,00</div>
        <div class="d3-property-insight__attribute">
          <dt class="d3-property-insight__attribute-title">Área construida (m²)</dt>
          <dd class="d3-property-insight__attribute-value">21</dd>
        </div>
      </body>
    </html>
    """

    async with _client({url: httpx.Response(200, text=html)}) as http_client:
        stats = await run_refresh_scraper(
            session_factory,
            http_client=http_client,
            rate_limiter=RateLimiter(0),
            now=NOW,
        )

    listing = await _stored_listing(session_factory, "29273176")
    async with session_factory() as session:
        history_count = await session.scalar(
            select(func.count(PriceHistoryORM.id)).where(PriceHistoryORM.listing_id == listing.id)
        )

    assert stats.validation_errors == 1
    assert stats.price_changes_detected == 0
    assert stats.price_history_points_created == 0
    assert listing.price_clp == Decimal("180000000")
    assert history_count == 0
