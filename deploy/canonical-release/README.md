# Canonical-only release — deployment requires explicit approval

This release repairs both the selection boundary and the provenance of the application image. It does not modify valuation engines, score weights, outlier rules, microzones, price surfaces or frontend code.

## What changes

The API dependency constructs ValuationService with `final_price_policy="canonical_only"`. The Tasar route also explicitly requests that policy. The canonical path runs only `comparables_canonical_outliers`; no previous valuation, quality challenger, mixed consensus or numeric fallback runs. Canonical failure produces insufficient-data instead of another final price. The response and comparable list are assembled from the same EngineResult.

Comparable display serialization uses the native canonical price and the exact area used by the engine. When a source's useful area differs from the area used, the valuation table falls back to the actual used built area; original source useful/built areas remain in `valuation_debug.comparable_calculation`. Existing engine weights are exposed for reconstruction, not changed.

The application files missing from Git were recovered verbatim from the active API image. Operational API, ingestion, thumbnails, schema definitions and report rendering are preserved rather than silently inherited from an older image. Existing database revision remains 0022; this rollout does not run migrations. Previous deployment-era tests were reconciled only for the adopted operational code and the new selection policy. The original 66 diagnostic tests remain in place.

## Source guard and obsolete paths

`scripts/package_canonical_release.py` reads immutable **Git blobs**, not the working directory. It excludes private configuration and creates a SHA256 manifest of every packaged application file. The Dockerfile reuses the existing verified image only for installed dependencies, deletes its entire `/app` inside the candidate build, then installs the committed source tree. No inherited application source survives.

The dependency tag must resolve to `sha256:22081087e836574f11091c45a164f6dbe6891f095cf55e6c6945c38c49f90f69` before build. Build with `--pull=false --network=none`. The Git commit is passed as RELEASE_COMMIT and appears in both the image label and response metadata. Source checks run at build, application startup, preflight and postflight. Startup rejects modified files and unexpected Python files. Metadata exposes `release_manifest_commit` and `release_manifest_match`; canonical response verification rejects a mismatch or false commit.

The old `deploy/radar-tasar-engine/Dockerfile` used three COPY statements over v6; that path caused the drift and is now explicitly disabled. Do not use filesystem overlays, uncommitted ZIPs or an image label alone as a production source assertion. The preflight accepts only the reviewed candidate image ID and a matching committed-source manifest. The older developer Dockerfile/ZIP path is not an approved production release path.

## Prepared rollback

Current API image: `sha256:22081087e836574f11091c45a164f6dbe6891f095cf55e6c6945c38c49f90f69`.

Protected backup on Oracle: `/home/ubuntu/backups/canonical-only-ready-20261013`. It contains the previous API inspection, exact Compose file copies, private preservation state and a catalog-verified database dump. No private material belongs in Git. Before an approved rollout, re-audit if the live image/configuration changed or if a newer backup is needed after a prolonged pause.

The rollout changes **only api.image**; it compares resolved Compose configurations before starting anything. It uses `up -d --no-deps --no-build api`, never changes database/Redis/Caddy/thumbnail containers, and keeps the verified Portal session mounted read-only. No database restore is required for code rollback. A failed health or canonical gate automatically restores the previous API via the original Compose files.

## Commands after reviewing the candidate

Package locally from the reviewed commit:

```powershell
python -m scripts.package_canonical_release --commit COMMIT --output canonical-release.tar.gz
```

Build/test the candidate in isolation on Oracle. The prepared build record names the exact image/tag/commit; the frozen snapshot stays private. Run `python -m scripts.verify_canonical_candidate --snapshot /diagnostic/snapshot.json` in a disposable candidate container with `--network=none` and only the snapshot mounted read-only.

Host-side plan (no deployment):

```bash
python3 rollout.py --release candidate-image.json --backup /home/ubuntu/backups/canonical-only-ready-20261013
```

**Only after the user's explicit OK**, the same command with `--approved` replaces the API and runs `scripts.verify_canonical_live`. That read-only gate verifies all application hashes, the actual API route, policy, single selected engine, final price, selected IDs/hash, visible price/area basis and reconstructed weighted UF/m2. It checks the two reference cases and reports any current-data/UF changes; a price change with unchanged data/UF fails.

Manual code rollback after approval, if needed:

```bash
python3 rollout.py --release candidate-image.json --backup /home/ubuntu/backups/canonical-only-ready-20261013 --rollback --approved
```

No command with `--approved` has been executed during preparation. Production conditions 1–3 cannot be claimed complete until the approved rollout and live gate pass.
