"""Data quality checks for persisted listings."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, or_, select

from audits.registry import CheckResult, register_check
from config.constants import MAX_M2, MIN_M2
from infrastructure.db.database import get_session_factory
from infrastructure.db.models import ListingORM

MIN_PRICE_M2_CLP = Decimal("200000")
MAX_PRICE_M2_CLP = Decimal("20000000")


@register_check
async def check_listing_data_quality() -> CheckResult:
    try:
        async with get_session_factory()() as session:
            total = await session.scalar(select(func.count()).select_from(ListingORM)) or 0
            missing_price = await session.scalar(
                select(func.count())
                .select_from(ListingORM)
                .where(or_(ListingORM.price_clp.is_(None), ListingORM.price_clp <= 0))
            ) or 0
            missing_m2 = await session.scalar(
                select(func.count())
                .select_from(ListingORM)
                .where(or_(ListingORM.m2.is_(None), ListingORM.m2 <= 0))
            ) or 0
            absurd_m2 = await session.scalar(
                select(func.count())
                .select_from(ListingORM)
                .where(or_(ListingORM.m2 < MIN_M2, ListingORM.m2 > MAX_M2))
            ) or 0

            rows = (
                await session.execute(
                    select(ListingORM.price_clp, ListingORM.m2).where(
                        ListingORM.price_clp > 0,
                        ListingORM.m2 > 0,
                    )
                )
            ).all()
    except Exception as e:
        return {
            "name": "listing_data_quality",
            "status": "ERROR",
            "message": "No se pudo evaluar calidad de listings por falla de DB.",
            "details": {"error": str(e)},
        }

    bad_price_m2 = 0
    for price_clp, m2 in rows:
        ppm2 = Decimal(str(price_clp)) / Decimal(str(m2))
        if ppm2 < MIN_PRICE_M2_CLP or ppm2 > MAX_PRICE_M2_CLP:
            bad_price_m2 += 1

    bad_total = missing_price + missing_m2 + absurd_m2 + bad_price_m2
    status = "OK"
    if total == 0:
        status = "WARNING"
    elif bad_total > 0:
        status = "WARNING"

    return {
        "name": "listing_data_quality",
        "status": status,
        "message": "Listings sin anomalias criticas." if status == "OK" else "Se detectaron posibles problemas de datos.",
        "details": {
            "total_listings": total,
            "missing_price": _with_pct(missing_price, total),
            "missing_m2": _with_pct(missing_m2, total),
            "absurd_m2": _with_pct(absurd_m2, total),
            "price_m2_out_of_range": _with_pct(bad_price_m2, total),
            "price_m2_range_clp": {
                "min": int(MIN_PRICE_M2_CLP),
                "max": int(MAX_PRICE_M2_CLP),
            },
        },
    }


def _with_pct(count: int, total: int) -> dict[str, float | int]:
    pct = round((count / total) * 100, 2) if total else 0.0
    return {"count": count, "pct": pct}
