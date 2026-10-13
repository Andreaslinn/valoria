"""Additive valuation provenance. Never runs engines or changes their outputs."""
from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from domain.valuation.engines.contracts import EngineResult

_ROOT = Path(__file__).resolve().parents[1]
_FILES = (
    "services/valuation.py", "api/v1/valuations.py",
    "domain/valuation/engines/canonical_comparables.py",
    "domain/valuation/engines/legacy_comparables.py",
    "domain/valuation/engines/consensus_orchestrator.py",
    "domain/valuation/engines/valoria_consensus/engine.py", "domain/valuation/price_surface.py",
    "domain/valuation/engines/registry.py", "domain/valuation/engines/hedonic_baseline/engine.py",
    "domain/valuation/engines/microzone_geo/engine.py", "domain/valuation/engines/market_trends/engine.py",
    "domain/valuation/engines/valoria_consensus/config.py", "domain/valuation/engines/valoria_consensus/combination.py",
    "config/valuation_flags.py",
)


def runtime_provenance() -> dict[str, Any]:
    hashes = {}
    for name in _FILES:
        try:
            hashes[name] = hashlib.sha256((_ROOT / name).read_bytes()).hexdigest()
        except OSError:
            hashes[name] = None
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    # An image label is not proof of the file contents. Keep an unknown revision
    # explicit and always expose the hashes of the actual runtime source.
    revision = os.getenv("VALORIA_RELEASE_COMMIT", "")
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision.lower()):
        revision = None
    return {"engine_commit": revision, "runtime_source_sha256": digest, "runtime_files_sha256": hashes}


def comparable_identity(ids: list[int | None]) -> dict[str, Any]:
    known = sorted(value for value in ids if value is not None)
    return {
        "n_comparables_weighted": len(ids), "comparable_ids": known,
        "comparable_ids_missing_n": len(ids) - len(known),
        "comparable_ids_sha256": hashlib.sha256(json.dumps(known, separators=(",", ":")).encode()).hexdigest(),
        "comparable_ids_hash_format": "sha256(sorted numeric IDs as compact JSON; duplicates retained)",
    }


def value_trace(
    *, engine_selected: str, engine_version: str | None,
    uf_to_clp: Decimal, area_m2: float, base_clp: int | float | Decimal | None,
    after_surface_clp: int | float | Decimal | None, final_clp: int | float | Decimal | None,
    comparable_ids: list[int | None],
) -> dict[str, Any]:
    divisor = uf_to_clp * Decimal(str(area_m2))
    def ppm2(value):
        return float(Decimal(str(value)) / divisor) if value is not None else None
    return {
        "schema_version": "valuation_debug_v1", "engine_selected": engine_selected,
        "engine_version": engine_version, "uf_rate_clp": float(uf_to_clp),
        "area_m2_used": area_m2, "ppm2_unit": "UF/m2",
        "ppm2_base": ppm2(base_clp), "ppm2_after_surface": ppm2(after_surface_clp),
        "ppm2_final": ppm2(final_clp),
        "price_surface_factor": float(Decimal(str(after_surface_clp)) / Decimal(str(base_clp)))
        if base_clp and after_surface_clp is not None else None,
        **comparable_identity(comparable_ids), **runtime_provenance(),
    }


def engine_trace(result: EngineResult, *, uf_to_clp: Decimal, area_m2: float) -> dict[str, Any]:
    debug = result.diagnostics.get("result", result.diagnostics)
    has_surface = "surface_adjustment" in debug
    trace = value_trace(
        engine_selected=result.engine_name, engine_version=result.engine_version,
        uf_to_clp=uf_to_clp, area_m2=area_m2,
        base_clp=debug.get("base_estimated_price_clp") if has_surface else None,
        after_surface_clp=result.estimated_price_clp if has_surface else None,
        final_clp=result.estimated_price_clp,
        comparable_ids=[item.listing_id for item in result.selected_comparables],
    )
    if result.engine_name == "valoria_consensus_v1":
        # A consensus combines engines, not one weighted listing set. Do not
        # mislabel the legacy UI comparables as the final estimator's sample.
        trace.update(n_comparables_weighted=None, comparable_ids=None, comparable_ids_sha256=None,
                     comparable_ids_missing_n=None, comparables_scope="multiple_engine_samples")
    else:
        trace["comparables_scope"] = "selected_engine_weighted_sample"
        if not result.selected_comparables and result.comparables_used:
            trace.update(n_comparables_weighted=None, comparable_ids=None, comparable_ids_sha256=None,
                         comparables_scope="engine_did_not_expose_weighted_ids",
                         n_comparables_reported=result.comparables_used)
    return trace


def embed_valuation_debug(html: str, debug: Any) -> str:
    """Include machine-readable provenance in the downloaded HTML only."""
    if not isinstance(debug, dict) or not debug:
        return html
    encoded = json.dumps(debug, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    block = f'<script type="application/json" id="valoria-valuation-debug">{encoded}</script>'
    return html.replace("</body>", block + "</body>")
