# SII closing layer: offline exit gates, product integration stopped

This draft starts at release `24b56dc` (PR #9 included). It implements a
disposable catastro address index, the requested weighted kNN, and an offline
auditor. The exit gates failed, so there is **no Tasar integration**. Setting
`sii_closing_layer=true` currently has no effect on product responses. Its default
is false. No deploy, merge, production database changes or new background job.

## Reproduce locally

Use the existing local SII database populated through the phase-1 importer.
The auditor validates loopback, an explicit non-5432 port, the database name
`valoria_sii_local`, and the psycopg driver before opening a connection. It never
consults application settings, `.env` or `DATABASE_URL`.

```powershell
python -m scripts.validate_sii_closing --local-url $env:SII_DATABASE_URL --output ../closing-validation-new
```

The output directory must be new: the index is never overwritten. The initial
export uses a repeatable-read read-only transaction and bounded statements. It
does not create database tables. It records source hashes and exports the
latest complete N/NL snapshot for each of the eight benchmark communes. The
derived SQLite index reparses `direccion_raw`; it does not trust the previously
derived street/number fields, which sometimes contain the unit number.

To replay an already exported snapshot without any database connection:

```powershell
python -m scripts.validate_sii_closing --local-url $env:SII_DATABASE_URL --output ../closing-validation-new --reuse-snapshot
```

The supplied URL is ignored during replay. The 300-role sample is stratified
with a fixed seed. Query rewrites are automatic and the source parser supplies
the expected street/number, so this measures catastro consistency and is **not
independent human certification of physical building identity**. No role is
removed from the sample for missing/complex address data.

The address resolver returns all candidates when a base address spans multiple
SII blocks or a unit is not unique. Floor alone does not identify an individual
unit; no floor is inferred from apartment digits. The OSM hook is called only
after a textual miss and can return alternative street names within the same
commune and civic number. There was no local OSM extract for this run; an actual
OSM provider and its recovery accuracy remain unvalidated. No public geocoder
or nearest-coordinate assignment is used.

## Frozen estimator

Only `cierre_comparable` houses/apartments, with matching property type and
commune, participate. Closed H surface is `m2_h - m2_h_abierta`. Surface ratios
outside [0.5, 1.5] are ineligible. Similarity is the sum of:

- 0.30 × `max(0, 1 - abs(log(area_ratio))/log(1.5))`;
- 0.30 × location: base building 1, same SII block 0.7, same commune 0.2;
- 0.30 × `max(0, 1 - abs(construction_year_delta)/20)`;
- 0.10 × `max(0, 1 - elapsed_days/730.5)`.

K=10, deterministic raw-ID tie breaking, no price-based neighbor selection.
Weighted empirical UF/closed-m² quantiles × target closed m² give the value,
P25 and P75. The returned ten comparables include role, source raw ID, date,
closed m², UF/m² and similarity. A missing year, missing base address or fewer
than ten eligible closings produces an explicit abstention. No imputation or
fallback to the current asking-price model.

2026 effective transaction dates (FE, FI only if FE absent) form the holdout.
Every holdout role is removed from the entire 2024–2025 pool, including prior
sales of that role. The estimator independently rejects same-role and future
comparables. MdAPE and P95 use predicted cases; coverage and abstentions are
always reported. These descriptive quantiles are not calibrated uncertainty
intervals. No weights, thresholds or calibration were fitted to the holdout.

## Evidence and stopping point

See `reports/sii/closing_layer_20261019/report.md` for aggregate metrics only.
Full prediction/comparable evidence, the 300-query address CSV, failed examples,
source hashes and unchanged product-source hashes were delivered locally to the
requester. Row-level addresses, roles and transactions are excluded from GitHub
publication. The local `holdout-validation.json` contains every prediction and
its ten comparables. Replaying the auditor produces the same local artifacts.

The global building consistency rate is 93.67%, but Estación Central and Ñuñoa
are below 90%. Six communes exceed 10% MdAPE. Product integration (step 4) is
therefore stopped. No current endpoint, valuation service, form or result view
was changed, so flag-off and no-address behavior follow the identical path.

Validation: 105 selected unit/regression tests passed, Ruff and diff checks
passed. The full project suite was not run. Focused tests include real canonical
service paths and endpoint contracts as well as the new offline estimator.

The follow-up canonical comparison and confidence rule, fitted only on 2025H2,
are documented in [sii_closing_confidence.md](sii_closing_confidence.md). Their
aggregate report is `reports/sii/closing_confidence_20261019/report.md`.
