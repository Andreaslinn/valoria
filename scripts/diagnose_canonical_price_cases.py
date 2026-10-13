"""Reproduce the two reported canonical-engine cases without database writes.

Run: python -m scripts.diagnose_canonical_price_cases
Uses today's existing UF snapshot; fails rather than persisting a fetched rate.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text

from core.entities.listing import Property
from domain.valuation.engines.canonical_comparables import ComparablesCanonicalEngine
from domain.valuation.engines.contracts import EngineContext, EngineRequest, EngineStatus
from infrastructure.db.database import get_session_factory
from infrastructure.db.repositories import SqlAlchemyListingRepository


async def main() -> None:
    cases = []
    async with get_session_factory()() as session:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        uf = (await session.execute(text("SELECT value_clp FROM uf_rates WHERE date=CURRENT_DATE"))).scalar_one()
        repo = SqlAlchemyListingRepository(session)
        for comuna, area, bedrooms, parking, published_uf in (
            ("santiago", 70, 2, 0, 2552), ("la_florida", 82, 3, 1, 4000),
        ):
            target = Property(
                id=None, comuna=comuna, m2=area, built_area_m2=area, usable_area_m2=area,
                bedrooms=bedrooms, bathrooms=2, parking=parking, property_type="apartment",
            )
            pool = await repo.find_active_in_comuna(comuna, property_type="apartment")
            result = ComparablesCanonicalEngine(name="comparables_canonical_outliers", variant="outliers").valuate(
                EngineRequest(published_price_provided=True), EngineContext(target=target, candidates=pool, uf_to_clp=uf),
            )
            if result.status != EngineStatus.OK:
                raise RuntimeError(f"{comuna}: {result.status}")
            debug = result.diagnostics["result"]
            base_clp = Decimal(str(debug["base_estimated_price_clp"]))
            final_clp = Decimal(str(result.estimated_price_clp))
            cases.append({
                "input": {"comuna": comuna, "usable_area_m2": area, "bedrooms": bedrooms,
                          "bathrooms": 2, "parking": parking, "published_uf": published_uf,
                          "coordinates": None, "other_fields": "unknown"},
                "pool_n": len(pool), "estimated_uf": result.estimated_price_uf,
                "ppm2_base": float(base_clp / uf / area), "ppm2_after_surface": float(final_clp / uf / area),
                "price_surface_factor": float(final_clp / base_clp),
                "surface_adjustment": debug["surface_adjustment"],
                "selected_ids": [item.listing_id for item in result.selected_comparables],
                "comparable_weights": debug["comparable_weights"],
                "exclusions": result.diagnostics["exclusions"],
            })
        await session.rollback()
    print(json.dumps({"snapshot_utc": datetime.now(UTC).isoformat(), "read_only": True,
                      "uf_rate": str(uf), "ppm2_unit": "UF/m2", "cases": cases}, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
