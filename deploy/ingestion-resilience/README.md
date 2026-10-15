# Ingestion resilience — review, rollout and rollback

Base: `release/canonical-only-reproducible-20261013`, `3e6782a16d92b6f2284e96b47b429bf8cb6c27c3`.
Production must **not** be updated until explicit approval. The review canary only writes a temporary SQLite database in a restricted container; no live migrations or timer changes are part of review.

## Behavior

* Fetch the SII annual UF calendar (including all published future dates), at most two attempts/year with backoff, twice daily at 04:30/16:30 UTC. December also checks next year's calendar.
* Acquisition first reads the exact Chilean calendar day from its own durable table, then an existing real daily snapshot. Failure never prevents extraction.
* If today's exact value is unavailable, retain the source UF price in PostgreSQL `ingestion_pending_prices`. The most recent known value on/before the observation is a labelled **provisional reference**, not canonical CLP. A future rate is never used early, a prior rate is never relabelled today, and a guessed rate never enters listings/valuation.
* Replay at most 100 pending identities per run, using the original observation date. Do not expire the queue. Existing Redis Yapo originals remain until a canonical write succeeds.
* `/api/v1/health/ingestion` reports the last attempt/success, counters, sanitized errors, pending count and age for both sources. More than 24 hours without success, latest failure, hung execution or pending conversion makes it degraded. Missing/unavailable ledger also degrades. `/health` remains cheap liveness.
* Portal child errors preserve exception class, stage and file/line/function only. Arbitrary exception strings, cookies, environment, response bodies and source lines are never forwarded. A legacy UF error retains its allowlisted reason and frame locations; nonzero process status propagates.

No changes to the valuation engine, `services/uf_rate.py`, or `infrastructure/external/uf_client.py`. No paid resources, proxy, permanent browser or change in CPU/memory/request budgets.

## Mandatory deployment gates

1. Review/merge the PR against the stated base. Rebuild from the **merged commit**, not the feature commit or default branch. Run `scripts/package_canonical_release.py --commit MERGED_SHA --output merged-release.tar.gz`; verify its commit, package hash and pinned runtime image ID before building with `deploy/canonical-release/Dockerfile`.
2. Obtain explicit deployment approval. Review's canary pass is not that approval.
3. Verify production is still the prepared image `sha256:2aa86cd937c507681b65b9dff0453b6ef76ab9e30eadfb9cc2fc75eaa7c2c9fb`, that API remains healthy, free disk >=8 GiB and available RAM >=768 MiB. Re-audit if image/schema/unit state changed.
4. Record private mode-0600 backups: API inspect, compose file paths, current image, image digest, timer states, `run_portal_discovery_service.sh`, existing Portal session runtime wrapper, Yapo wrapper, all units/drop-ins. Never put private inspect/env/session files in Git/PR/report. Take a PostgreSQL backup and verify it can be read before migration.
5. Stop only the two discovery timers (record original enabled/active state); wait for any current jobs to finish. Do not interrupt an active ingestion transaction or alter locks. Leave API/database/proxy and valuation untouched during preparation.
6. Run the **merged candidate** image with existing private env/network and the original limits to execute `alembic upgrade 0023`. This migration adds three isolated tables only. Do not execute migration as part of canary. Confirm Alembic head and table constraints.
7. Switch API image using its existing compose configuration plus a new image-only override, without rebuilding dependencies or changing limits/mounts/secrets. Replace the old host Portal wrapper (which overlays stale source) with an entrypoint to the versioned `scripts/run_portal_session.py`; install that file and `scripts/ingestion_launcher.py` together on the host. Set `VALORIA_INGESTION_IMAGE` to the exact merged image in the Portal unit drop-in.
8. Install `scripts/run_ingestion_uf_refresh.py` on the host and the two UF unit files in this directory. Pin the same merged image in the UF unit drop-in. Install `discovery-uf-ordering.conf` as a drop-in for both discovery services: `Wants`/`After` orders refresh first, while intentionally avoiding `Requires` so provider failure never blocks extraction. Keep Yapo's existing bounded wrapper, executing the merged API code. Do not enable duplicate scraper schedules.
9. Refresh the official calendar once, then query `/api/v1/health/ingestion` and run the merged candidate's `scripts/ingestion_canary.py` with a read-only session and temporary SQLite. Use `--user UID:GID` matching the existing Ubuntu job/session owner, `--memory=384m --memory-swap=384m --cpus=0.25 --pids-limit=96 --cap-drop=ALL --security-opt=no-new-privileges --read-only --tmpfs /tmp:rw,nosuid,nodev,size=32m`. No production DB/env is needed for the canary (dummy SQLite settings suffice). Pass `PORTAL_SESSION_READ_ONLY=1`, `PORTAL_HTTP_ENABLED=true`; mount session read-only. No published ports.
10. After successful checks, run each real source once with its normal budgets/lock, verify its durable ledger and original-price queue, then restore the two discovery timers to their original states and enable UF timer. Do not infer recovery from resetting systemd failed. Confirm no stale code mounts shadow merged code and no unreviewed image is used.

The canary purposely simulates total UF outage rather than only one failed provider. It tests real HTTP extraction and actual persistence into scratch, not just parser fixtures. Partial input-validation rejections stay distinct from unexpected errors; HTTP/blocking errors prevent reporting a successful run.

## Rollback (only after approved rollout)

1. Stop UF/discovery timers and wait for jobs, preserving locks and no concurrent writes.
2. Restore the exact backed-up API image using the same compose file list and `up -d --no-deps --no-build api`; restore Portal/Yapo host wrappers and unit/drop-in files from private backup. Remove only newly introduced UF units/drop-ins. Reload systemd and restore recorded timer states. Verify API digest, health, mount permissions and canonical release guard.
3. **Retain all three additive ingestion tables and queued originals.** Older app versions ignore them. Do not downgrade/drop them or delete pending prices: archive/reconcile later under a separate approved operation. A full database restore would discard legitimate post-release writes and is not the normal rollback.
4. Rollback restores old behavior, including UF fragility; report that source freshness may degrade again. Never substitute a fabricated conversion to make health green.

## Historical evidence limitation

The old wrapper captured stderr and deleted the container with `--rm`; the journal retained only counters/runtime_error. A reproduced UF failure in both retained images identifies the identical `UFServiceError: UF real no disponible` path and rules out a new-image regression **for that tested path**. It cannot recreate the missing original stderr for October 14/15. Do not claim an archived historical traceback exists or that every possible image regression was excluded.
