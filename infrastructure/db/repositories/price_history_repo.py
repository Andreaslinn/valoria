"""Repositorio SQLAlchemy para snapshots de precio."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.ports.price_history_repo import PriceHistoryRepository
from infrastructure.db.models import ListingORM, PriceHistoryORM


@dataclass(frozen=True)
class PriceSeriesPoint:
    observed_at: datetime
    price_clp: Decimal
    price_uf: Decimal | None = None
    price_currency: str | None = None
    change_basis: str | None = None
    is_artifact: bool = False
    artifact_reason: str | None = None
    source: str | None = None
    source_url: str | None = None
    point_type: str = "historical"


class SqlAlchemyPriceHistoryRepository(PriceHistoryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        listing_id: int,
        price_clp: Decimal,
        observed_at: datetime,
        price_uf: Decimal | None = None,
        price_clp_snapshot: Decimal | None = None,
        price_currency: str | None = None,
        uf_rate_used: Decimal | None = None,
        change_basis: str | None = None,
        is_artifact: bool = False,
        artifact_reason: str | None = None,
    ) -> None:
        entry = PriceHistoryORM(
            listing_id=listing_id,
            price_clp=price_clp,
            price_uf=price_uf,
            price_clp_snapshot=price_clp_snapshot or price_clp,
            price_currency=price_currency,
            uf_rate_used=uf_rate_used,
            change_basis=change_basis,
            is_artifact=is_artifact,
            artifact_reason=artifact_reason,
            observed_at=observed_at,
        )
        self._session.add(entry)
        await self._session.flush()

    async def get_price_series_for_listing(self, listing_id: int) -> list[PriceSeriesPoint]:
        """Return a clean chronological price series for one listing.

        Price history stores previous prices on transitions, while ListingORM
        keeps the current price. This reader combines both shapes without
        changing the write path.
        """
        listing = await self._session.get(ListingORM, listing_id)
        stmt = (
            select(PriceHistoryORM)
            .where(PriceHistoryORM.listing_id == listing_id)
            .order_by(PriceHistoryORM.observed_at.asc(), PriceHistoryORM.id.asc())
        )
        history = (await self._session.execute(stmt)).scalars().all()
        points = [
            PriceSeriesPoint(
                observed_at=row.observed_at,
                price_clp=row.price_clp_snapshot or row.price_clp,
                price_uf=row.price_uf,
                price_currency=row.price_currency,
                change_basis=row.change_basis,
                is_artifact=bool(row.is_artifact),
                artifact_reason=row.artifact_reason,
                source=listing.source if listing is not None else None,
                source_url=listing.url if listing is not None else None,
                point_type="historical",
            )
            for row in history
        ]
        if listing is not None and listing.price_clp is not None and listing.scraped_at is not None:
            points.append(
                PriceSeriesPoint(
                    observed_at=listing.scraped_at,
                    price_clp=listing.price_clp,
                    price_uf=listing.price_uf,
                    price_currency=listing.price_currency,
                    change_basis=(listing.price_currency or "").lower() or None,
                    source=listing.source,
                    source_url=listing.url,
                    point_type="current",
                )
            )
        return _dedupe_exact_points(points)


def _dedupe_exact_points(points: list[PriceSeriesPoint]) -> list[PriceSeriesPoint]:
    seen: set[tuple[datetime, Decimal, Decimal | None]] = set()
    deduped: list[PriceSeriesPoint] = []
    for point in sorted(points, key=lambda item: _datetime_key(item.observed_at)):
        key = (_datetime_key(point.observed_at), point.price_clp, point.price_uf)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(point)
    return deduped


def _datetime_key(value: datetime) -> datetime:
    return value.replace(tzinfo=None)
