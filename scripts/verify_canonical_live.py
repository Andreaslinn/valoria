"""Read-only post-deploy gate: actual API route, current DB, source and sample identity."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text

from api.deps import get_valuation_service
from api.v1.valuations import ValuationRequest, valuate
from core.ports.uf_service import UFRateInfo
from infrastructure.db.database import get_session_factory
from infrastructure.db.repositories import SqlAlchemyListingRepository
from services.release_guard import verify_canonical_response, verify_release_tree


def data_hash(rows):
    facts = sorted((row["listing_id"], row["price_uf_used"], row["area_m2_used"]) for row in rows)
    return hashlib.sha256(json.dumps(facts,separators=(",", ":")).encode()).hexdigest()


async def main():
    root = Path(__file__).resolve().parents[1]
    source = verify_release_tree(root)
    reference = json.loads((root/"deploy/canonical-release/reference-cases.json").read_text(encoding="utf-8"))
    output = []
    async with get_session_factory()() as session:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        uf = (await session.execute(text("SELECT value_clp FROM uf_rates WHERE date=CURRENT_DATE"))).scalar_one()
        class ReadOnlyUF:
            async def get_current_rate(self):
                return uf
            async def get_current_rate_info(self):
                return UFRateInfo(rate=uf,source="read_only_daily_db_snapshot",is_fallback=False,rate_date=date.today())
        service = get_valuation_service(SqlAlchemyListingRepository(session), ReadOnlyUF())
        for case in reference["cases"]:
            result = await valuate(current_user=SimpleNamespace(id=None), payload=ValuationRequest(**case["payload"]),
                                   service=service, session=session)
            payload = result.model_dump(mode="json")
            verify_canonical_response(payload)
            debug = payload["valuation_debug"]
            if debug["release_manifest_match"] is not True or debug["engine_commit"] != source["commit"]:
                raise RuntimeError("Running valuation metadata differs from approved commit")
            changed = data_hash(debug["comparable_calculation"]) != data_hash(case["comparable_calculation"])
            difference = abs(payload["estimated_price_uf"] - case["canonical_uf"])
            if difference > .01 and not changed and Decimal(reference["uf"]) == uf:
                raise RuntimeError("Price changed without a source-data or UF explanation")
            old_ids = {row["listing_id"] for row in case["comparable_calculation"]}
            new_ids = set(debug["comparable_ids"])
            output.append({"comuna":case["payload"]["comuna"],"estimated_uf":payload["estimated_price_uf"],
                           "frozen_reference_uf":case["canonical_uf"],"comparable_data_changed":changed,
                           "uf_rate":str(uf),"only_new_ids":sorted(new_ids-old_ids),"only_reference_ids":sorted(old_ids-new_ids),
                           "debug":debug})
        await session.rollback()
    print(json.dumps({"status":"passed","read_only":True,"source":source,"cases":output}))


if __name__ == "__main__":
    asyncio.run(main())
