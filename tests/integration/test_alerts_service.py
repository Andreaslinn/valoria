from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from domain.alerts.price_drop_detector import detect_price_drop_from_history
from infrastructure.db.models import ListingORM, PriceHistoryORM
from services.alerts import detect_price_drops, detect_price_drops_with_stats

NOW = datetime.now(UTC)


@pytest.mark.asyncio
async def test_detect_price_drops_returns_active_listing_drop(session: AsyncSession) -> None:
    dropped = _listing("active-drop", status="active", scraped_at=NOW, price_clp=90_000_000)
    inactive = _listing("inactive-drop", status="removed", scraped_at=NOW)
    thin = _listing("thin", status="active", scraped_at=NOW)
    old = _listing("old-drop", status="active", scraped_at=NOW - timedelta(days=45))
    session.add_all([dropped, inactive, thin, old])
    await session.flush()
    session.add_all(
        [
            _price(dropped.id, 100_000_000, NOW - timedelta(days=1)),
            _price(inactive.id, 100_000_000, NOW - timedelta(days=2)),
            _price(inactive.id, 90_000_000, NOW - timedelta(days=1)),
            _price(thin.id, 100_000_000, NOW - timedelta(days=1)),
            _price(old.id, 100_000_000, NOW - timedelta(days=46)),
            _price(old.id, 90_000_000, NOW - timedelta(days=45)),
        ]
    )
    await session.commit()

    drops = await detect_price_drops(session, threshold_pct=5.0, lookback_days=30)

    assert len(drops) == 1
    assert drops[0]["listing_id"] == dropped.id
    assert drops[0]["previous_price_clp"] == 100_000_000
    assert drops[0]["new_price_clp"] == 90_000_000
    assert drops[0]["drop_pct"] == 10.0
    assert drops[0]["detected_at"].replace(tzinfo=UTC) == NOW

    result = await detect_price_drops_with_stats(session, threshold_pct=5.0, lookback_days=30)
    assert result.listings_evaluated == 2
    assert len(result.drops) == 1


@pytest.mark.asyncio
async def test_detect_price_drops_matches_legacy_per_listing_lookup(session: AsyncSession) -> None:
    listings = [
        _listing("drop", status="active", scraped_at=NOW, price_clp=90_000_000),
        _listing("stable", status="active", scraped_at=NOW, price_clp=100_000_000),
        _listing("thin", status="active", scraped_at=NOW, price_clp=100_000_000),
        _listing("old", status="active", scraped_at=NOW - timedelta(days=90), price_clp=80_000_000),
    ]
    session.add_all(listings)
    await session.flush()
    session.add_all(
        [
            _price(listings[0].id, 110_000_000, NOW - timedelta(days=3)),
            _price(listings[0].id, 100_000_000, NOW - timedelta(days=1)),
            _price(listings[1].id, 90_000_000, NOW - timedelta(days=1)),
            _price(listings[2].id, 100_000_000, NOW - timedelta(days=1)),
            _price(listings[3].id, 100_000_000, NOW - timedelta(days=91)),
        ]
    )
    await session.commit()

    optimized = await detect_price_drops(session, threshold_pct=5.0, lookback_days=365)
    legacy = await _legacy_detect_price_drops(session, threshold_pct=5.0, lookback_days=365)

    assert _drop_summary(optimized) == _drop_summary(legacy)


@pytest.mark.asyncio
async def test_detect_price_drops_handles_many_listings_without_query_growth(
    engine: AsyncEngine,
    session: AsyncSession,
) -> None:
    listings = [
        _listing(
            f"scale-{index}",
            status="active",
            scraped_at=NOW,
            price_clp=90_000_000 if index % 5 == 0 else 100_000_000,
        )
        for index in range(150)
    ]
    session.add_all(listings)
    await session.flush()
    expected_drops = 0
    for index, listing in enumerate(listings):
        if index % 3 == 0:
            continue
        if index % 5 == 0:
            session.add(_price(listing.id, 100_000_000, NOW - timedelta(days=1)))
            expected_drops += 1
        else:
            session.add(_price(listing.id, 90_000_000, NOW - timedelta(days=1)))
    await session.commit()

    select_statements: list[str] = []

    def record_select(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record_select)
    try:
        drops = await detect_price_drops(session, threshold_pct=5.0, lookback_days=30)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_select)

    assert len(drops) == expected_drops
    assert len(select_statements) <= 2


@pytest.mark.asyncio
async def test_detect_price_drops_uses_uf_canonical_basis(session: AsyncSession) -> None:
    listing = _listing(
        "uf-drop",
        status="active",
        scraped_at=NOW,
        price_clp=118_400_000,
        price_currency="UF",
        price_uf=3200,
    )
    session.add(listing)
    await session.flush()
    session.add(
        _price(
            listing.id,
            120_250_000,
            NOW - timedelta(days=1),
            price_currency="UF",
            price_uf=3250,
            change_basis="uf",
        )
    )
    await session.commit()

    drops = await detect_price_drops(session, threshold_pct=1.0, lookback_days=30)

    assert len(drops) == 1
    assert drops[0]["previous_price_uf"] == 3250.0
    assert drops[0]["new_price_uf"] == 3200.0
    assert drops[0]["price_currency"] == "UF"
    assert drops[0]["change_basis"] == "uf"


@pytest.mark.asyncio
async def test_detect_price_drops_ignores_uf_rate_only_change(session: AsyncSession) -> None:
    listing = _listing(
        "uf-rate-only",
        status="active",
        scraped_at=NOW,
        price_clp=120_250_000,
        price_currency="UF",
        price_uf=3250,
    )
    session.add(listing)
    await session.flush()
    session.add(
        _price(
            listing.id,
            132_259_985,
            NOW - timedelta(days=1),
            price_currency="UF",
            price_uf=3250,
            change_basis="uf",
        )
    )
    await session.commit()

    drops = await detect_price_drops(session, threshold_pct=1.0, lookback_days=30)

    assert drops == []


@pytest.mark.asyncio
async def test_detect_price_drops_excludes_price_history_artifact(session: AsyncSession) -> None:
    listing = _listing(
        "uf-artifact",
        status="active",
        scraped_at=NOW,
        price_clp=120_250_000,
        price_currency="UF",
        price_uf=3250,
    )
    session.add(listing)
    await session.flush()
    session.add(
        _price(
            listing.id,
            132_259_985,
            NOW - timedelta(days=1),
            price_currency="UF",
            price_uf=3250,
            change_basis="uf_rate_artifact",
            is_artifact=True,
        )
    )
    await session.commit()

    drops = await detect_price_drops(session, threshold_pct=1.0, lookback_days=30)

    assert drops == []


@pytest.mark.asyncio
async def test_detect_price_drops_ignores_legacy_unrecoverable_uf(session: AsyncSession) -> None:
    listing = _listing(
        "legacy-unrecoverable",
        status="active",
        scraped_at=NOW,
        price_clp=120_250_000,
        price_currency="UF",
        price_uf_source="legacy_unrecoverable",
    )
    session.add(listing)
    await session.flush()
    session.add(
        _price(
            listing.id,
            132_259_985,
            NOW - timedelta(days=1),
            price_currency="UF",
            change_basis="legacy_uf_unknown",
        )
    )
    await session.commit()

    drops = await detect_price_drops(session, threshold_pct=1.0, lookback_days=30)

    assert drops == []


def _listing(
    fingerprint: str,
    *,
    status: str,
    scraped_at: datetime,
    price_clp: int = 100_000_000,
    price_currency: str | None = None,
    price_uf: int | None = None,
    price_uf_source: str | None = None,
) -> ListingORM:
    return ListingORM(
        source="yapo",
        external_id=fingerprint,
        title=f"Listing {fingerprint}",
        comuna="nunoa",
        m2=70.0,
        bedrooms=2,
        bathrooms=2,
        parking=1,
        price_clp=Decimal(str(price_clp)),
        price_uf=Decimal(str(price_uf)) if price_uf is not None else None,
        price_currency=price_currency,
        price_uf_source=price_uf_source,
        status=status,
        fingerprint=fingerprint,
        scraped_at=scraped_at,
        last_seen_at=scraped_at,
        raw_metadata={},
    )


def _price(
    listing_id: int,
    price_clp: int,
    observed_at: datetime,
    *,
    price_currency: str | None = None,
    price_uf: int | None = None,
    change_basis: str | None = None,
    is_artifact: bool = False,
) -> PriceHistoryORM:
    return PriceHistoryORM(
        listing_id=listing_id,
        price_clp=Decimal(str(price_clp)),
        price_clp_snapshot=Decimal(str(price_clp)),
        price_uf=Decimal(str(price_uf)) if price_uf is not None else None,
        price_currency=price_currency,
        change_basis=change_basis,
        is_artifact=is_artifact,
        observed_at=observed_at,
    )


async def _legacy_detect_price_drops(
    session: AsyncSession,
    *,
    threshold_pct: float,
    lookback_days: int,
) -> list[dict]:
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    listing_rows = (
        await session.execute(
            select(ListingORM.id, ListingORM.source, ListingORM.price_clp, ListingORM.scraped_at)
            .where(ListingORM.status == "active")
            .where(ListingORM.scraped_at >= cutoff)
            .order_by(ListingORM.scraped_at.desc())
        )
    ).all()
    drops = []
    for listing_id, source, current_price_clp, scraped_at in listing_rows:
        history_rows = (
            await session.execute(
                select(PriceHistoryORM.price_clp, PriceHistoryORM.observed_at)
                .where(PriceHistoryORM.listing_id == listing_id)
                .order_by(PriceHistoryORM.observed_at.desc())
                .limit(2)
            )
        ).all()
        detected = detect_price_drop_from_history(
            [
                {"price_clp": current_price_clp, "observed_at": scraped_at},
                *[
                    {"price_clp": row.price_clp, "observed_at": row.observed_at}
                    for row in history_rows
                ],
            ],
            threshold_pct=threshold_pct,
        )
        if detected is not None:
            drops.append({"listing_id": int(listing_id), "source": str(source), **detected})
    return drops


def _drop_summary(drops: list[dict]) -> list[tuple[int, int, int, float]]:
    return [
        (
            int(drop["listing_id"]),
            int(drop["previous_price_clp"]),
            int(drop["new_price_clp"]),
            float(drop["drop_pct"]),
        )
        for drop in drops
    ]
