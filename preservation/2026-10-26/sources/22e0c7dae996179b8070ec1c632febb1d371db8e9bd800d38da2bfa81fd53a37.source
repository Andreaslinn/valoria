"""Read-only snapshot of stored CLP versus native UF for active source listings.

Run inside the configured backend: python -m scripts.diagnose_canonical_price_basis
No ORM writes, UF cache writes, credentials, or individual listing data are emitted.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from sqlalchemy import text

from infrastructure.db.database import get_session_factory


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def summarize(rows, uf_rate: Decimal) -> dict:
    output = {}
    for source in ("yapo", "portalinmobiliario"):
        active = [row for row in rows if row[0] == source]
        valid = [row for row in active if row[1] is not None and row[2] is not None and row[1] > 0 and row[2] > 0]
        ratios = [Decimal(str(row[1])) / (Decimal(str(row[2])) * uf_rate) for row in valid]
        values = [float(value) for value in ratios]
        outside = sum(value < Decimal("0.97") or value > Decimal("1.03") for value in ratios)
        output[source] = {
            "active_n": len(active), "n": len(valid), "excluded_missing_or_nonpositive_n": len(active) - len(valid),
            "p5": percentile(values, 0.05), "median": percentile(values, 0.5), "p95": percentile(values, 0.95),
            "outside_0_97_to_1_03_n": outside,
            "outside_0_97_to_1_03_pct": 100 * outside / len(valid) if valid else None,
        }
    return output


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uf-rate", type=Decimal, help="Explicit dated rate for reproducible snapshots")
    parser.add_argument("--uf-date", help="Required date when supplying --uf-rate")
    args = parser.parse_args()
    if args.uf_rate is not None:
        if not args.uf_rate.is_finite() or args.uf_rate <= 0 or not args.uf_date:
            parser.error("--uf-rate must be positive and accompanied by --uf-date")
        rate, rate_date, rate_source = args.uf_rate, args.uf_date, "explicit_dated_rate"
    else:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get("https://mindicador.cl/api/uf")
            response.raise_for_status()
            latest = response.json()["serie"][0]
            rate, rate_date, rate_source = Decimal(str(latest["valor"])), latest["fecha"], "mindicador.cl/api/uf"
        if not rate.is_finite() or rate <= 0:
            raise ValueError("Invalid current UF rate")
    async with get_session_factory()() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        rows = (await session.execute(text(
            "SELECT source, price_clp, price_uf FROM listings "
            "WHERE status='active' AND source IN ('yapo','portalinmobiliario')"
        ))).all()
        result = summarize(rows, rate)
        await session.rollback()
    print(json.dumps({
        "snapshot_utc": datetime.now(UTC).isoformat(), "read_only": True,
        "uf_rate": str(rate), "uf_date": rate_date, "uf_source": rate_source,
        "ratio": "price_clp / (price_uf * current_uf_rate)",
        "percentile_method": "linear interpolation at (n-1)*p", "sources": result,
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
