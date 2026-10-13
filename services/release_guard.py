"""Fail closed on source drift or inconsistent canonical valuation evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def verify_release_tree(root: Path) -> dict:
    manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
    failures = []
    for name, expected in manifest["files"].items():
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            failures.append(name)
    expected_python = {name for name in manifest["files"] if name.endswith(".py")}
    actual_python = {str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*.py")}
    failures.extend(sorted(actual_python - expected_python))
    if failures:
        raise RuntimeError("Release source drift: " + ", ".join(sorted(set(failures))))
    return {"commit": manifest["commit"], "files_checked": len(manifest["files"]), "source_tree_match": True}


def verify_canonical_response(response: dict) -> None:
    debug = response.get("valuation_debug") or {}
    if debug.get("release_manifest_commit") and (
        debug.get("release_manifest_match") is not True
        or debug.get("engine_commit") != debug["release_manifest_commit"]
    ):
        raise RuntimeError("Canonical release source or commit does not match its manifest")
    if (debug.get("final_price_policy") != "canonical_only"
        or debug.get("engine_selected") != "comparables_canonical_outliers"
        or response.get("selected_engine_names") != ["comparables_canonical_outliers"]
        or response.get("consensus_used") or response.get("fallback_engine_used")):
        raise RuntimeError("Canonical-only release mixed or substituted engines")
    rows = response.get("comparables") or []
    ids = sorted(row["listing_id"] for row in rows if row.get("listing_id") is not None)
    digest = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()
    if digest != debug.get("comparable_ids_sha256") or len(rows) != debug.get("n_comparables_weighted"):
        raise RuntimeError("Final price and comparable identity differ")
    calculations = debug.get("comparable_calculation") or []
    if len(calculations) != len(rows):
        raise RuntimeError("Canonical comparable calculation is incomplete")
    weighted_ppm2 = 0.0
    weight_total = 0.0
    for row, shown in zip(calculations, rows, strict=True):
        if row["listing_id"] != shown["listing_id"]:
            raise RuntimeError("Canonical comparable order or identity differs")
        shown_area = shown.get("usable_area_m2") or shown.get("built_area_m2") or shown["m2"]
        if shown_area != row["area_m2_used"] or abs(shown["price_uf"] - row["price_uf_used"]) > 0.011:
            raise RuntimeError("Visible comparable uses a different price or area basis")
        weight = row["normalized_weight"]
        weighted_ppm2 += weight * row["price_uf_used"] / row["area_m2_used"]
        weight_total += weight
    if abs(weight_total - 1) > 0.0001 or abs(weighted_ppm2 - debug["ppm2_base"]) > 0.005:
        raise RuntimeError("Weighted comparable price is inconsistent with canonical base")
    final_ppm2 = response["estimated_price_uf"] / debug["area_m2_used"]
    if abs(final_ppm2 - debug["ppm2_base"] * debug["price_surface_factor"]) > 0.005:
        raise RuntimeError("Final price was replaced after canonical valuation")
