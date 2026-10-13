"""Offline replay of a read-only production listing snapshot, without database access.

Snapshot format: {uf, uf_date, cases:[{payload, pool:[dataclass Listing objects],
engines, consensus_raw, consensus_selected, route_response}]}.
Keep full listing snapshots private; output contains only engine results and IDs.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from core.entities.listing import Listing, Property
from core.value_objects.location import Coordinates
from core.value_objects.price import Price
from domain.valuation.engines.canonical_comparables import ComparablesCanonicalEngine
from domain.valuation.engines.consensus_orchestrator import run_beta_consensus
from domain.valuation.engines.contracts import EngineContext, EngineRequest
from domain.valuation.engines.legacy_comparables import ComparablesLegacyEngine
from domain.valuation.engines.registry import experimental_engine_registry
from services.valuation_debug import engine_trace


def restore_listing(row: dict) -> Listing:
    values = dict(row)
    values["price"] = Price(clp=Decimal(str(values["price"]["clp"])))
    if values.get("price_uf") is not None:
        values["price_uf"] = Decimal(str(values["price_uf"]))
    if values.get("coordinates"):
        values["coordinates"] = Coordinates(**values["coordinates"])
    for key in ("scraped_at", "last_seen_at", "last_refresh_attempted_at"):
        if values.get(key):
            values[key] = datetime.fromisoformat(values[key])
    return Listing(**values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    uf = Decimal(snapshot["uf"])
    output = []
    for case in snapshot["cases"]:
        payload = case["payload"]
        area = payload["built_area_m2"] or payload["usable_area_m2"] or payload["m2"]
        target = Property(id=None, comuna=payload["comuna"], m2=area, built_area_m2=area,
                          usable_area_m2=payload["usable_area_m2"], property_type=payload["property_type"],
                          bedrooms=payload["dormitorios"] or 0, bathrooms=payload["banos"] or 0,
                          parking=payload["estacionamientos"] or 0)
        pool = [restore_listing(row) for row in case["pool"]]
        context = EngineContext(target=target, candidates=pool, uf_to_clp=uf)
        request = EngineRequest(published_price_provided=True)
        engines = [ComparablesCanonicalEngine(name="comparables_canonical_outliers", variant="outliers"),
                   ComparablesLegacyEngine()]
        local = [engine.valuate(request, context) for engine in engines]
        registry = experimental_engine_registry()
        for name in ("microzone_geo_v1", "hedonic_baseline_v1", "market_trends_v1"):
            local.append(registry.get(name).valuate(request, context))
        consensus = run_beta_consensus(target=target, candidates=pool, uf_to_clp=uf, published_price_provided=True)
        production_by_name = {row["engine_name"]: row for row in case["engines"] + case["consensus_raw"]}
        comparison = []
        for result in local:
            prod = production_by_name[result.engine_name]
            local_ids = sorted(item.listing_id for item in result.selected_comparables if item.listing_id is not None)
            prod_ids = sorted(item["listing_id"] for item in prod["selected_comparables"] if item["listing_id"] is not None)
            comparison.append({
                "engine": result.engine_name, "local_uf": result.estimated_price_uf,
                "production_uf": prod["estimated_price_uf"],
                "local_debug": engine_trace(result, uf_to_clp=uf, area_m2=area),
                "production_debug": engine_trace(_restore_engine_result(prod), uf_to_clp=uf, area_m2=area),
                "only_local_ids": sorted(set(local_ids) - set(prod_ids)),
                "only_production_ids": sorted(set(prod_ids) - set(local_ids)),
            })
        ui_ids = {row["listing_id"] for row in case["route_response"]["comparables"]}
        canonical_ids = {row.listing_id for row in local[0].selected_comparables}
        output.append({"payload": payload, "snapshot_pool_n": len(pool), "engines": comparison,
                       "local_orchestrator_selected": consensus.selected_result.engine_name if consensus.selected_result else None,
                       "local_orchestrator_uf": consensus.selected_result.estimated_price_uf if consensus.selected_result else None,
                       "production_orchestrator_uf": case["consensus_selected"]["estimated_price_uf"],
                       "production_route_uf": case["route_response"]["estimated_price_uf"],
                       "ui_only_ids_vs_canonical": sorted(ui_ids - canonical_ids),
                       "canonical_only_ids_vs_ui": sorted(canonical_ids - ui_ids)})
    print(json.dumps({"uf": str(uf), "uf_date": snapshot["uf_date"], "database_access": False, "cases": output}, default=str, indent=2))


def _restore_engine_result(row):
    from dataclasses import fields

    from domain.valuation.engines.contracts import EngineComparable, EngineResult
    values = {item.name: row[item.name] for item in fields(EngineResult) if item.name in row}
    values["selected_comparables"] = tuple(EngineComparable(**item) for item in values["selected_comparables"])
    return EngineResult(**values)


if __name__ == "__main__":
    main()
