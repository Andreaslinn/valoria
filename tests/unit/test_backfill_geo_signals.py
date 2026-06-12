from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from infrastructure.db.models import ListingORM
from scripts.backfill_geo_signals import run_backfill


def _listing(**overrides) -> ListingORM:
    now = datetime.now(UTC)
    values = {
        "source": "yapo",
        "external_id": "geo-1",
        "title": "Departamento Av. Macul 3198",
        "url": "https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-av-macul-3198/1",
        "comuna": "macul",
        "property_type": "apartment",
        "m2": 50.0,
        "bedrooms": 2,
        "bathrooms": 1,
        "parking": 0,
        "price_clp": Decimal("100000000"),
        "status": "active",
        "fingerprint": "geo-1",
        "raw_metadata": {"location_text": "Macul", "existing_key": "keep"},
        "scraped_at": now,
        "last_seen_at": now,
    }
    values.update(overrides)
    return ListingORM(**values)


@pytest.mark.asyncio
async def test_backfill_dry_run_does_not_write_db(session: AsyncSession, engine: AsyncEngine) -> None:
    session.add(_listing())
    await session.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    output_dir = Path(".tmp") / "test_geo_signal_dry_run"

    report = await run_backfill(
        limit=1,
        only_active=True,
        output_dir=output_dir,
        session_factory=factory,
    )

    session.expire_all()
    refreshed = (await session.execute(select(ListingORM))).scalar_one()
    assert "geo_signal_candidates" not in refreshed.raw_metadata
    assert report["summary"]["new_candidates_detected"] >= 1
    assert (output_dir / "geo_signal_recovery_latest.json").exists()
    assert (output_dir / "geo_signal_recovery_latest.md").exists()


@pytest.mark.asyncio
async def test_backfill_apply_updates_only_raw_metadata(session: AsyncSession, engine: AsyncEngine) -> None:
    session.add(_listing(lat=None, lon=None, geocode_precision="comuna"))
    await session.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    output_dir = Path(".tmp") / "test_geo_signal_apply"

    await run_backfill(
        apply=True,
        limit=1,
        only_active=True,
        output_dir=output_dir,
        session_factory=factory,
    )

    session.expire_all()
    refreshed = (await session.execute(select(ListingORM))).scalar_one()
    assert refreshed.lat is None
    assert refreshed.lon is None
    assert refreshed.geocode_precision == "comuna"
    assert refreshed.raw_metadata["existing_key"] == "keep"
    assert refreshed.raw_metadata["geo_signal_candidates"]
