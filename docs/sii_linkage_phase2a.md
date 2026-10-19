# SII linkage phase 2a: prerequisite control

The branch starts at release merge `24b56dc6fe626d19834bcd6707a9b77d1d3d44c7`,
which includes PR #9. The merge was expressly authorized; deployment was not performed.

## Current outcome

The 2026-10-19 production control stops phase 2a before geocoding or linking:
seven of eight benchmark communes have fewer than 40% of active apartment ads
with a verified exact address or publication-bound coordinates from PR #5.
Coverage is 536/2,107 (25.44%). Providencia alone reaches exactly 40%.

The branch adds the isolated audit and evidence, not a linking pipeline.
It does not change valuation code, ingestion, public tables or SII migrations.
There are no generated links and no 100-link review sample; precision and
link-level coverage remain unevaluated.

## Reproduce the control safely

`scripts/audit_sii_linkage_readiness.py` defaults to disabled unless the process
environment contains `SII_LINKAGE_ENABLED=true`. Even when enabled, it requires
the explicit `--production-readonly` argument before reading `DATABASE_URL`.
This production-only audit is separate from the phase-1 SII local jobs, which
still accept only the guarded local SII database.

An authorized operator may pipe the saved script into the existing API container:

```sh
docker exec -i -e SII_LINKAGE_ENABLED=true <existing-api-container> \
  python -B - --production-readonly < scripts/audit_sii_linkage_readiness.py
```

The script reads the API container's existing connection in memory. It neither
prints the DSN nor loads application settings. It starts a repeatable-read,
read-only transaction, asserts `transaction_read_only=on`, issues only SELECTs,
uses 20-second statement and one-second lock timeouts, and rolls back. It exports
aggregates and up to five failed examples per commune, omitting descriptions,
contacts and full raw metadata. Running from stdin with `-B` avoids installing
the script or creating Python bytecode on the production host.

The temporary environment variable applies to the audit process only; it is not
a persistent API configuration change. No scraper, migration or valuation job
is run. The audit itself does not call a geocoder or portal.

## Metric definitions

- Active means canonical `listings.status='active'`, not independently verified
  commercial availability. Apartment property types are selected explicitly.
- Source facts require version 1 and matching source/external identity; facts
  from `published_fields` and `published_detail_fields` can complement one another.
- Address requires a meaningful street, a positive civic number, exact address
  type and provenance. Ranges, intersections, placeholders and a labeled unit
  number incorrectly used as civic number are excluded.
- Published coordinates require a Chile-valid pair and portal provenance.
  Identified centroids, office or inferred points are excluded. Unknown precision
  is counted as observed availability and reported separately, never certified
  as building accuracy.
- Explicit usable area requires a positive `useful_area_m2` and explicit
  provenance. Canonical/generic/constructed/total surface is not a substitute.
- The stop gate uses the union of exact address OR published coordinates. A
  strict majority is at least five of the eight requested communes. Exactly
  40% passes, and decisions use integer counts before display rounding.
- Canonical coordinates and their union with address are supplementary metrics;
  they do not replace source-bound PR #5 facts in this control.

## Evidence and tests

`reports/sii/phase2a_step0.md` contains the cut, counts by commune and portal,
failure causes and examples. Machine-readable evidence is in the adjacent JSON
and CSV files. Five examples per commune are failures of the input-data control,
not attempted or rejected SII links.

Tests exercise the disabled guard, publication binding, apartment-versus-street
number confusion, centroid rejection, unknown precision, explicit useful-area
provenance, complementary detail facts, strict-majority stopping and the 40%
boundary. The control and canonical valuation regression tests pass together.

The observed deficit is stored source data: 1,537 of 2,107 active ads have no
matching PR #5 snapshot, and only 126 have a bound detail observation. This is
not proof that a portal never publishes those fields, or of a particular scraper
failure. Resolving source-field acquisition/refresh is the next investigation;
phase 2a linking remains stopped under the user's gate.
