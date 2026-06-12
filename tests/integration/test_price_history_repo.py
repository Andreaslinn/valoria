from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from domain.ingestion.pipeline import process_listing
from infrastructure.db.models import ListingORM, PriceHistoryORM
from infrastructure.db.repositories import (
    SqlAlchemyListingRepository,
    SqlAlchemyPriceHistoryRepository,
    SqlAlchemyPropertyRepository,
)

BASE_AT = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)


async def test_price_series_for_new_listing_returns_single_initial_point(
    session: AsyncSession,
) -> None:
    listing = await process_listing(_raw(price_clp=180_000_000), **_repos(session))
    await session.commit()

    series = await SqlAlchemyPriceHistoryRepository(session).get_price_series_for_listing(
        listing.id
    )

    assert [(int(point.price_clp), _naive(point.observed_at)) for point in series] == [
        (180_000_000, _naive(BASE_AT))
    ]
    assert series[0].source == "yapo"
    assert series[0].source_url == "https://yapo.cl/price-history"


async def test_price_series_dedupes_first_change_initial_snapshot_duplicate(
    session: AsyncSession,
) -> None:
    listing = await process_listing(_raw(price_clp=180_000_000), **_repos(session))
    await session.commit()
    await process_listing(
        _raw(price_clp=170_000_000, scraped_at=BASE_AT + timedelta(days=3)),
        **_repos(session),
    )
    await session.commit()

    raw_history = (
        await session.execute(
            PriceHistoryORM.__table__.select().where(PriceHistoryORM.listing_id == listing.id)
        )
    ).all()
    series = await SqlAlchemyPriceHistoryRepository(session).get_price_series_for_listing(
        listing.id
    )

    assert len(raw_history) == 2
    assert [(int(point.price_clp), _naive(point.observed_at)) for point in series] == [
        (180_000_000, _naive(BASE_AT)),
        (170_000_000, _naive(BASE_AT + timedelta(days=3))),
    ]
    assert series[-1].point_type == "current"


async def test_price_series_reconstructs_two_successive_price_changes(
    session: AsyncSession,
) -> None:
    listing = await process_listing(_raw(price_clp=180_000_000), **_repos(session))
    await session.commit()
    await process_listing(
        _raw(price_clp=175_000_000, scraped_at=BASE_AT + timedelta(days=2)),
        **_repos(session),
    )
    await session.commit()
    await process_listing(
        _raw(price_clp=170_000_000, scraped_at=BASE_AT + timedelta(days=5)),
        **_repos(session),
    )
    await session.commit()

    series = await SqlAlchemyPriceHistoryRepository(session).get_price_series_for_listing(
        listing.id
    )

    assert [(int(point.price_clp), _naive(point.observed_at)) for point in series] == [
        (180_000_000, _naive(BASE_AT)),
        (175_000_000, _naive(BASE_AT + timedelta(days=2))),
        (170_000_000, _naive(BASE_AT + timedelta(days=5))),
    ]


async def test_price_series_includes_canonical_uf_when_available(
    session: AsyncSession,
) -> None:
    listing = await process_listing(
        _raw(
            external_id="price-history-uf",
            price_clp=120_250_000,
            price_uf=3250,
            raw_metadata={
                "currency_original": "UF",
                "price_uf": 3250,
                "uf_rate_used": "37000",
            },
        ),
        **_repos(session),
    )
    await session.commit()
    await process_listing(
        _raw(
            external_id="price-history-uf",
            price_clp=118_400_000,
            price_uf=3200,
            scraped_at=BASE_AT + timedelta(days=3),
            raw_metadata={
                "currency_original": "UF",
                "price_uf": 3200,
                "uf_rate_used": "37000",
            },
        ),
        **_repos(session),
    )
    await session.commit()

    series = await SqlAlchemyPriceHistoryRepository(session).get_price_series_for_listing(
        listing.id
    )

    assert [(point.price_uf, point.change_basis) for point in series] == [
        (Decimal("3250.00"), "uf_initial"),
        (Decimal("3200.00"), "uf"),
    ]


async def test_price_series_returns_current_point_when_listing_has_no_history(
    session: AsyncSession,
) -> None:
    listing = _listing_without_history()
    session.add(listing)
    await session.commit()

    series = await SqlAlchemyPriceHistoryRepository(session).get_price_series_for_listing(
        listing.id
    )

    assert len(series) == 1
    assert int(series[0].price_clp) == 150_000_000
    assert _naive(series[0].observed_at) == _naive(BASE_AT + timedelta(days=7))
    assert series[0].point_type == "current"


async def test_price_series_orders_chronologically_and_dedupes_exact_points(
    session: AsyncSession,
) -> None:
    listing = _listing_without_history(price_clp=150_000_000)
    session.add(listing)
    await session.flush()
    session.add_all(
        [
            _history(listing.id, 170_000_000, BASE_AT + timedelta(days=3)),
            _history(listing.id, 180_000_000, BASE_AT),
            _history(listing.id, 180_000_000, BASE_AT),
            _history(listing.id, 160_000_000, BASE_AT + timedelta(days=5)),
        ]
    )
    await session.commit()

    series = await SqlAlchemyPriceHistoryRepository(session).get_price_series_for_listing(
        listing.id
    )

    assert [(int(point.price_clp), _naive(point.observed_at)) for point in series] == [
        (180_000_000, _naive(BASE_AT)),
        (170_000_000, _naive(BASE_AT + timedelta(days=3))),
        (160_000_000, _naive(BASE_AT + timedelta(days=5))),
        (150_000_000, _naive(BASE_AT + timedelta(days=7))),
    ]


def _repos(session: AsyncSession) -> dict:
    return {
        "listing_repo": SqlAlchemyListingRepository(session),
        "property_repo": SqlAlchemyPropertyRepository(session),
        "price_history_repo": SqlAlchemyPriceHistoryRepository(session),
    }


def _raw(**overrides) -> dict:
    base = {
        "source": "yapo",
        "external_id": "price-history",
        "title": "Departamento 3 dormitorios en Nunoa",
        "comuna": "Nunoa",
        "property_type": "apartment",
        "m2": 75,
        "bedrooms": 3,
        "bathrooms": 2,
        "parking": 1,
        "price_clp": 180_000_000,
        "url": "https://yapo.cl/price-history",
        "scraped_at": BASE_AT,
        "raw_metadata": {},
    }
    base.update(overrides)
    return base


def _listing_without_history(*, price_clp: int = 150_000_000) -> ListingORM:
    scraped_at = BASE_AT + timedelta(days=7)
    return ListingORM(
        source="yapo",
        external_id="no-history",
        title="Departamento sin historial",
        comuna="nunoa",
        property_type="apartment",
        m2=75,
        bedrooms=3,
        bathrooms=2,
        parking=1,
        price_clp=Decimal(str(price_clp)),
        status="active",
        fingerprint=f"no-history-{price_clp}",
        scraped_at=scraped_at,
        last_seen_at=scraped_at,
        url="https://yapo.cl/no-history",
        raw_metadata={},
    )


def _history(listing_id: int, price_clp: int, observed_at: datetime) -> PriceHistoryORM:
    return PriceHistoryORM(
        listing_id=listing_id,
        price_clp=Decimal(str(price_clp)),
        observed_at=observed_at,
    )


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)
