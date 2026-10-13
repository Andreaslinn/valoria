# Canonical comparable price basis: diagnosis and guarded calculation

Base: `release/radar-tasar-engine-20261013`, revision `c889f4d65ce1fc7a145b72491a470bda728465c9`. No UI change, deployment, database mutation, weight change, outlier-policy change, microzone change or price-surface change is included.

## Read-only diagnosis, performed before the engine edit

Active listings only, `source IN ('yapo','portalinmobiliario')`. Ratio = `price_clp / (price_uf * current_uf_rate)`. The denominator n includes only rows with positive, non-null prices in both units; exclusions are disclosed separately. Percentiles use linear interpolation at `(n-1)*p`. Interval boundaries 0.97 and 1.03 are inclusive.

Snapshot: 2026-10-13 15:38:44 UTC. UF: **41,152.13 CLP**, dated 2026-10-13, taken from the existing current-day `uf_rates` snapshot with a SELECT in a read-only transaction. The public mindicador endpoint was unreachable from the diagnostic process, so it did not fetch or persist an alternative rate. No cache, listing, user, valuation, or other production record was written.

| Source | Active total | n with both positive prices | Excluded missing/nonpositive | p5 | Median | p95 | Outside 0.97–1.03 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Yapo | 4,695 | 1,802 | 2,893 | 0.990138 | 0.999485 | 1.000000 | 0 / 1,802 = 0.00% |
| Portalinmobiliario | 1,184 | 1,078 | 106 | 0.992532 | 0.995904 | 1.000000 | 0 / 1,078 = 0.00% |

Reproduce on the configured backend (no credentials in arguments):

```powershell
python -m scripts.diagnose_canonical_price_basis --uf-rate 41152.13 --uf-date 2026-10-13
python -m scripts.diagnose_canonical_price_cases
```

The second command requires today's existing UF record and never creates one. The first also supports fetching the real published UF when no explicit dated rate is supplied. Both scripts explicitly start read-only database transactions. `source_price_ratios.json` contains the original diagnostic output.

## What this establishes, and what it does not

`_weighted_mean_ppm2` previously read `listing.price.clp` directly. However, `_canonical_price_pool` already replaced each eligible comparable's CLP snapshot with `valuation_price_basis(...).amount_uf * uf_to_clp` before weighting. That upstream normalization explains why the complete original engine already ignored stale/duplicated CLP snapshots for native-UF listings. The source ratios also provide no evidence of a large stored-CLP inflation in this snapshot.

The change makes that invariant explicit at the weighted calculation itself: use `valuation_price_basis`, preserve the score weights, take native UF/m², and convert to CLP/m² with the run's UF for existing downstream processing. This prevents the helper from depending on its caller's prior normalization. It is a guard against inconsistent snapshots, **not a demonstrated resolution of the reported 5,877 UF overestimate**.

The original deployed canonical source SHA256, after normalizing line endings, matches this PR's base revision: `1c15fabefcf807420bb0cb6cc724bd6371be885e0c67c8d514031347a47543b1`.

## Before/after with the supplied exact inputs

Same current active-data context, UF 41,152.13, no address/coordinates, other fields unknown. Candidate comparison runs used a separate process and read-only transactions. The candidate source was loaded only into that diagnostic process; the running API was not patched. Both snapshots have identical selected IDs, weights, and exclusions. Output is the **canonical outliers engine**, not a different engine's consensus or UI total.

| Case | User-reported UI total | Reproduced canonical before (UF) | Canonical after (UF) | Base UF/m² before → after | After-surface UF/m² | Surface factor |
|---|---:|---:|---:|---:|---:|---:|
| Santiago, 70 m², 2D/2B/0E, published 2,552 UF | 5,877 UF | 3,300.65 | 3,300.65 | 47.152179 → 47.152179 | 47.152179 | 1.000000 |
| La Florida, 82 m², 3D/2B/1E, published 4,000 UF | 4,428 UF | 3,909.15 | 3,909.15 | 47.672531 → 47.672531 | 47.672531 | 1.000000 |

These are controlled reproductions on the current active catalog, not claims that the historical UI values were reproduced or corrected. The current Santiago selected pool totals differ from the user-reported pool (57,601.15 UF / 1,213 m² versus reported 61,840 UF / 1,191 m²). Without the original selected IDs or report, the reason for that difference is unresolved. The final service response also depends on valuation strategy; this table deliberately isolates the named canonical engine.

## Supplied La Florida regression fixture

All 20 supplied `(area_m2, published_uf)` pairs are preserved verbatim in `tests/unit/test_canonical_engine_price_basis.py`. The target is 82 m², 3D/2B/1E, no coordinates. Unchanged outlier filtering selects 19 comparables from this fixture; the 7,500-UF / 74-m² listing is excluded by the existing policy. Real score/rank code runs in the regression; no fabricated bedroom/parking differences are inferred from the supplied rounded UI similarity percentages.

| Fixture / synthetic check | Before | After |
|---|---:|---:|
| Fixture canonical base UF/m², before surface | 47.321327 | 47.321327 |
| Fixture estimate UF | 3,880.35 | 3,880.35 |
| Fixture surface factor | 1.000000 | 1.000000 |
| Weighted helper: 4,185 UF / 80 m², consistent CLP | 52.3125 UF/m² | 52.3125 UF/m² |
| Same helper input, CLP snapshot duplicated | 104.625 UF/m² | 52.3125 UF/m² |

The complete fixture's base is in the required 44–52 UF/m² interval. The helper test covers both an old UF conversion (35,000 CLP/UF) and duplicated CLP. A full-engine regression verifies the estimate, selected weights and exclusions remain identical when stored CLP is doubled. Native-CLP listings continue to use the canonical CLP-to-UF basis rather than an unrelated stored `price_uf` field.

## Debug metadata

`EngineResult.diagnostics["result"]` now includes:

- `ppm2_base`: UF/m² of the rounded CLP base used by the existing surface code.
- `ppm2_after_surface`: UF/m² of the actual final CLP estimate.
- `price_surface_factor`: final CLP / base CLP, i.e. the actual multiplicative change, distinct from the existing blend `surface_adjustment.weight`.
- `ppm2_unit`: `UF/m2`.

The existing surface diagnostics remain intact. A controlled surface regression verifies a factor of 1.1 and the equality `ppm2_after_surface = ppm2_base * price_surface_factor`; it does not change the production surface implementation.

## Validation and existing repository limitation

Focused checks on this PR checkout: **66 passed**, covering the new regressions, diagnostic statistics, canonical engine/mode/price basis, consensus orchestration and price surfaces.

A full suite attempt on the release Git checkout cannot collect the API tests because this pre-existing branch imports `api.rate_limit` but does not track that module. This PR does not add unrelated runtime packaging files to conceal that baseline issue. Additional full-suite validation is recorded separately against the existing runtime-complete isolated checkout, with the exact modified engine and tests overlaid; it is not claimed to be a clean full-suite pass on the partial Git release checkout.

Additional full-suite result: **1,979 passed**, nine deprecation warnings, 193.37 seconds, in the runtime-complete isolated checkout with this exact engine overlay and the eight added regression cases. This is separate from the 66 focused passing tests in the PR checkout. Ruff passed on all five changed Python files; `git diff --check` passed.
