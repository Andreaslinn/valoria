"""Diagnostico rapido de listings persistidos."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402


@dataclass(frozen=True)
class ListingCounts:
    total: int
    active: int
    by_source: dict[str, int]
    last_scraped_at: datetime | None


async def collect_counts(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> ListingCounts:
    factory = session_factory or get_session_factory()
    async with factory() as session:
        total = await session.scalar(select(func.count()).select_from(ListingORM))
        active = await session.scalar(
            select(func.count()).select_from(ListingORM).where(ListingORM.status == "active")
        )
        source_rows = await session.execute(
            select(ListingORM.source, func.count())
            .group_by(ListingORM.source)
            .order_by(ListingORM.source)
        )
        last_scraped_at = await session.scalar(select(func.max(ListingORM.scraped_at)))

    return ListingCounts(
        total=int(total or 0),
        active=int(active or 0),
        by_source={source: int(count) for source, count in source_rows.all()},
        last_scraped_at=last_scraped_at,
    )


def print_counts(counts: ListingCounts) -> None:
    print("== AVM listings DB ==")
    print(f"total listings: {counts.total}")
    print(f"activos: {counts.active}")
    print("por fuente:")
    if counts.by_source:
        for source, count in counts.by_source.items():
            print(f"  {source}: {count}")
    else:
        print("  sin listings")
    last_seen = counts.last_scraped_at.isoformat() if counts.last_scraped_at else "sin capturas"
    print(f"ultima fecha de captura: {last_seen}")


async def main() -> int:
    try:
        counts = await collect_counts()
    except SQLAlchemyError as e:
        print("ERROR: no se pudo consultar la base de datos.")
        print(f"Detalle: {e}")
        return 2

    print_counts(counts)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(asyncio.run(main()))
