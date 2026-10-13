"""Exercise the real API route against a private frozen listing snapshot.

No database access, no authentication credentials, no usage writes. Suitable for
an isolated candidate container with network disabled before approval to deploy.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from api.v1.valuations import ValuationRequest, valuate
from core.ports.uf_service import UFRateInfo
from scripts.diagnose_valuation_path import restore_listing
from services.release_guard import verify_canonical_response, verify_release_tree
from services.valuation import ValuationService


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    root = Path(__file__).resolve().parents[1]
    source_check = verify_release_tree(root) if (root/"release-manifest.json").exists() else None
    rate = Decimal(snapshot["uf"])
    class FixedUF:
        async def get_current_rate(self):
            return rate
        async def get_current_rate_info(self):
            return UFRateInfo(rate=rate, source="frozen_production_snapshot", is_fallback=False,
                              rate_date=date.fromisoformat(snapshot["uf_date"]))
    output = []
    for case in snapshot["cases"]:
        pool = [restore_listing(row) for row in case["pool"]]
        class SnapshotRepo:
            def __init__(self, rows):
                self.rows = rows
            async def find_active_in_comuna(self, *args, **kwargs):
                return self.rows
        service = ValuationService(listing_repo=SnapshotRepo(pool), uf_service=FixedUF(), final_price_policy="canonical_only")
        result = await valuate(current_user=SimpleNamespace(id=None), payload=ValuationRequest(**case["payload"]),
                               service=service, session=None)
        payload = result.model_dump(mode="json")
        verify_canonical_response(payload)
        debug = payload["valuation_debug"]
        visible = payload["comparables"]
        aggregate_ppm2 = sum(row["price_uf"] for row in visible) / sum(
            row.get("usable_area_m2") or row.get("built_area_m2") or row["m2"] for row in visible)
        output.append({"comuna": case["payload"]["comuna"],
                       "before_uf": case["route_response"]["estimated_price_uf"],
                       "candidate_uf": payload["estimated_price_uf"],
                       "canonical_snapshot_reference_uf": case["engines"][0]["estimated_price_uf"],
                       "visible_aggregate_uf_m2": aggregate_ppm2,
                       "weighted_uf_m2": debug["ppm2_base"],
                       "response": payload})
    print(json.dumps({"status":"passed", "database_access":False,
                      "release_source_check":source_check, "cases":output}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
