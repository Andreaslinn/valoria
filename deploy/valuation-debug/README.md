# Diagnostic metadata overlay for the currently deployed image

The release branch and active image have different valuation/orchestrator sources. The normal source changes in this PR add provenance to the release branch without changing its engine selection. `production-overlay.patch` is the corresponding metadata-only patch against the exact production files, preserving the active multi-family consensus and its existing report renderer.

This overlay is review material. It has not been deployed. Do not replace production's entire `services/valuation.py` or `api/v1/valuations.py` with their release-branch counterparts to install diagnostics: that would change the existing behavior.

Before any separately authorized rollout:

1. Verify the image ID and every original source hash in `production-overlay-manifest.json`.
2. Add the new `services/valuation_debug.py` from this PR to the candidate image.
3. Apply this patch only to that verified source tree; `git apply --check --unidiff-zero production-overlay.patch` must pass first.
4. Test the candidate in isolation. The two frozen-snapshot tests already performed assert that every existing response field remains unchanged and that the downloadable HTML contains `#valoria-valuation-debug`.

The overlay modifies only services/valuation.py, api/v1/valuations.py and services/reports.py. It does not patch engines, weights, flags, source data, microzones or price surfaces. In a multi-engine consensus, final weighted-listing count/hash and surface fields are null because no single such sample exists; individual engine traces and the previous pipeline are recorded separately. Missing engine listing IDs are reported as unknown, never invented.

A release commit is exposed only if explicitly supplied via `VALORIA_RELEASE_COMMIT`; otherwise it stays null. Actual source hashes are always attempted, with unreadable/missing sources reported as null. No image label is substituted for source verification.
