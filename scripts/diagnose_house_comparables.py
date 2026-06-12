"""Diagnostico rapido de comparables para tasacion de casas.

No modifica datos. Resume disponibilidad por property_type/comuna/superficies y
explica descartes para una tasacion objetivo.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constants import COMPARABLES_M2_TOLERANCE, COMPARABLES_MAX_DISTANCE_KM  # noqa: E402
from core.normalization.geocode_precision import canonical_geocode_precision  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402

_OUTLIER_MIN_PRICE_M2_CLP = Decimal("500000")
_OUTLIER_MAX_PRICE_M2_CLP = Decimal("20000000")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose house comparable availability.")
    parser.add_argument("--comuna", default="vitacura")
    parser.add_argument("--built-area-m2", type=float, default=140.0)
    parser.add_argument("--land-area-m2", type=float, default=300.0)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    async with get_session_factory()() as session:
        await print_availability(session, comuna=args.comuna)
        listings = list((await session.execute(select(ListingORM).where(ListingORM.status == "active"))).scalars())
        print_discard_reasons(
            listings,
            comuna=args.comuna,
            built_area_m2=args.built_area_m2,
            land_area_m2=args.land_area_m2,
        )
    return 0


async def print_availability(session, *, comuna: str) -> None:
    active_total = await session.scalar(
        select(func.count()).select_from(ListingORM).where(ListingORM.status == "active")
    )
    print("== Disponibilidad general ==")
    print(f"active_total\t{active_total}")

    print("\n== Activos por property_type ==")
    rows = await session.execute(
        text(
            """
            SELECT COALESCE(property_type, 'NULL') AS property_type, COUNT(*) AS n
            FROM listings
            WHERE status = 'active'
            GROUP BY property_type
            ORDER BY n DESC
            """
        )
    )
    for row in rows:
        print(f"{row.property_type}\t{row.n}")

    print("\n== Activos por comuna + property_type ==")
    rows = await session.execute(
        text(
            """
            SELECT comuna, COALESCE(property_type, 'NULL') AS property_type, COUNT(*) AS n
            FROM listings
            WHERE status = 'active'
            GROUP BY comuna, property_type
            ORDER BY comuna, property_type
            """
        )
    )
    for row in rows:
        print(f"{row.comuna}\t{row.property_type}\t{row.n}")

    print("\n== Salud de casas ==")
    metrics = {
        "houses_active": "property_type = 'house'",
        "houses_with_built_area": "property_type = 'house' AND built_area_m2 IS NOT NULL",
        "houses_with_land_area": "property_type = 'house' AND land_area_m2 IS NOT NULL",
        "houses_with_valid_price": "property_type = 'house' AND price_clp > 0",
        f"houses_in_{comuna}": "property_type = 'house' AND comuna = :comuna",
        f"houses_in_{comuna}_with_built_and_price": (
            "property_type = 'house' AND comuna = :comuna "
            "AND built_area_m2 IS NOT NULL AND price_clp > 0"
        ),
        f"houses_in_{comuna}_with_built_land_and_price": (
            "property_type = 'house' AND comuna = :comuna "
            "AND built_area_m2 IS NOT NULL AND land_area_m2 IS NOT NULL AND price_clp > 0"
        ),
    }
    for label, predicate in metrics.items():
        count = await session.scalar(
            text(f"SELECT COUNT(*) FROM listings WHERE status = 'active' AND {predicate}"),
            {"comuna": comuna},
        )
        print(f"{label}\t{count}")

    print("\n== Posible fallback historico ==")
    null_property_type = await session.scalar(
        text(
            """
            SELECT COUNT(*)
            FROM listings
            WHERE status = 'active'
              AND property_type IS NULL
            """
        )
    )
    suspicious = await session.scalar(
        text(
            """
            SELECT COUNT(*)
            FROM listings
            WHERE status = 'active'
              AND COALESCE(property_type, 'apartment') = 'apartment'
              AND lower(title) LIKE '%casa%'
            """
        )
    )
    suspicious_metadata = await session.scalar(
        text(
            """
            SELECT COUNT(*)
            FROM listings
            WHERE status = 'active'
              AND COALESCE(property_type, 'apartment') = 'apartment'
              AND lower(CAST(raw_metadata AS TEXT)) LIKE '%casa%'
            """
        )
    )
    print(f"active_rows_with_null_property_type\t{null_property_type}")
    print(f"active_apartment_rows_with_casa_in_title\t{suspicious}")
    print(f"active_apartment_rows_with_casa_in_raw_metadata\t{suspicious_metadata}")


def print_discard_reasons(
    listings: list[ListingORM],
    *,
    comuna: str,
    built_area_m2: float,
    land_area_m2: float | None,
) -> None:
    all_reasons = Counter()
    comuna_reasons = Counter()
    target_land = land_area_m2
    for listing in listings:
        reason = discard_reason(
            listing,
            comuna=comuna,
            built_area_m2=built_area_m2,
            land_area_m2=target_land,
        )
        all_reasons[reason] += 1
        if listing.comuna == comuna:
            comuna_reasons[reason] += 1

    print("\n== Descartes exclusivos: todos los activos ==")
    for reason, count in all_reasons.most_common():
        print(f"{reason}\t{count}")

    print(f"\n== Descartes exclusivos: activos en {comuna} ==")
    for reason, count in comuna_reasons.most_common():
        print(f"{reason}\t{count}")


def discard_reason(
    listing: ListingORM,
    *,
    comuna: str,
    built_area_m2: float,
    land_area_m2: float | None,
) -> str:
    if listing.comuna != comuna:
        return "comuna_mismatch"
    if (listing.property_type or "apartment") != "house":
        return "property_type_mismatch"
    if listing.price_clp is None or listing.price_clp <= 0:
        return "missing_price"
    candidate_built = listing.built_area_m2 or listing.usable_area_m2 or listing.m2
    if candidate_built is None or candidate_built <= 0:
        return "missing_built_area"
    if land_area_m2 is not None and listing.land_area_m2 is None:
        return "missing_land_area"
    min_built = built_area_m2 * (1.0 - COMPARABLES_M2_TOLERANCE)
    max_built = built_area_m2 * (1.0 + COMPARABLES_M2_TOLERANCE)
    if not min_built <= candidate_built <= max_built:
        return "area_out_of_range"
    if land_area_m2 is not None and listing.land_area_m2 is not None:
        min_land = land_area_m2 * (1.0 - COMPARABLES_M2_TOLERANCE)
        max_land = land_area_m2 * (1.0 + COMPARABLES_M2_TOLERANCE)
        if not min_land <= listing.land_area_m2 <= max_land:
            return "area_out_of_range"
    if _price_m2_is_outlier(listing.price_clp, candidate_built):
        return "outlier_price_m2"
    if _too_far_without_target_coords(listing):
        return "too_far"
    return "eligible"


def _price_m2_is_outlier(price_clp: Decimal, built_area_m2: float) -> bool:
    price_m2 = price_clp / Decimal(str(built_area_m2))
    return price_m2 < _OUTLIER_MIN_PRICE_M2_CLP or price_m2 > _OUTLIER_MAX_PRICE_M2_CLP


def _too_far_without_target_coords(listing: ListingORM) -> bool:
    # La UI de tasacion no manda coordenadas del target. Sin coords de target,
    # el filtro real tampoco descarta por distancia.
    _ = COMPARABLES_MAX_DISTANCE_KM
    if listing.lat is None or listing.lon is None:
        return False
    if canonical_geocode_precision(listing.geocode_precision) != "address":
        return False
    return False


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
