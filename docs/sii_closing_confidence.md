# Offline confidence validation and matched canonical baseline

Continuation of draft PR #11. No Tasar integration, merge, deploy, flag change
or change to the SII kNN's weights, K, scales or source. See the aggregate
[report](../reports/sii/closing_confidence_20261019/report.md).

## Frozen protocol

The protocol was recorded before measuring 2025H2. All transaction dates are
effective dates (FE, or FI when FE is absent). The input for fitting contains
only rows before 2026; the fit command rejects any 2026 row.

- Validation: 2025-07-01 through 2025-12-31.
- Pool: 2024-01-01 through 2025-06-30; remove every role appearing in validation,
  including that role's earlier sales. Same-role/future comparable guards stay
  active in the original estimator.
- Location: at least 5/10 neighbors in the same base building; otherwise at
  least 5/10 in the same SII block; otherwise commune. Block counts include
  building counts.
- Age at valuation: 0–9, 10–19, 20–39, 40+ years.
- Relative dispersion: `(P75-P25)/median`, bins <=10%, (10%,20%], (20%,35%], >35%.
- Trust a fixed joint cell only when it has at least 30 validation predictions
  and validation MdAPE <=10%. No boundary search or commune-specific tuning.

Ten cells qualify. They are stored in `frozen-rule.json` with a timestamp and
input/protocol/source hashes. Rule application never reads actual transaction
price or holdout errors. `apply_rule` returns the original estimate unchanged
inside the zone; outside it returns `status=abstained` with no point estimate.

The 2026 evaluation uses all closings, removes every 2026 role from the whole
2024–2025 pool, and checks the frozen rule hash before/after evaluation. Source
hashes normalize Git CRLF line endings, but a change to kNN code is rejected.

## Local replay

All individual records and candidate snapshots stay outside the repository.
The output filenames are also ignored by Git. Use the local phase-1 closing
snapshot and first split its rows with `date < '2026-01-01'` into a separate
training-only JSON file. Do not overwrite an existing fit directory.

```powershell
python -m scripts.evaluate_sii_confidence fit --input ../training-through-2025-local.json --output ../confidence-fit-new
python -m scripts.evaluate_sii_confidence evaluate --input ../closings-local.json --rule ../confidence-fit-new/frozen-rule.json --output ../confidence-holdout-new
```

For exact reproduction of the reported holdout, use the published frozen rule,
not a newly fitted rule. Its SHA-256 is
`62e2647548487f63018a100c2f2b3c6231fd6ae212262f9307fb0cb7574b5f34`.

## Canonical comparison

`compare_sii_canonical` uses the exact productive
`ComparablesCanonicalEngine(variant='outliers')`, not the legacy/consensus model.
It samples up to 150 cases per commune with proportional age stratification,
largest remainders and seed 20261019. Error comparisons use only identical cases
where both engines return a value; separate availability totals retain all
sampled cases.

The canonical target receives the same closed area, commune, property type and
construction year in metadata. The current engine ignores construction year;
a regression verifies this. Missing SII bedrooms/bathrooms/parking use the same
zero defaults as current Tasar, without inventing values.

The candidate snapshot was read in a bounded repeatable-read read-only
transaction, with the current repository's filters and query order. No UF
client refresh/persistence, scrapers or jobs run. `export_canonical_baseline_readonly`
requires both `SII_BASELINE_READONLY=true` and `--production-readonly` before it
reads connection settings; run with `python -B` through stdin in the existing
API environment and save stdout locally. It never needs an installed file or
deployment. Its `--as-of 2026-10-19` selects the already persisted official SII
UF for the audit date.

The export omits contact/description/source URL payloads. It preserves native
price provenance, generated geo signals, and product class through generic
text labels: the robust filter uses product class even in the outliers variant.
Four productive source hashes must match the local code. Before any sample
valuation, 64 synthetic monetary checks must exactly match the full server
inputs to the local projection.

```powershell
python -m scripts.compare_sii_canonical --closings ../closings-local.json --knn-holdout ../confidence-holdout-new/holdout-records-local.json --canonical-pool ../canonical-pool-local.json --uf-snapshot ../uf-readonly-local.json --output ../canonical-baseline-new
```

This compares current asking-price stock with past closings, not historical
asking-price stock as of each sale; differences cannot be attributed solely to
algorithms. Also, only the existing 2026H2 structural catastro snapshot is
available. Transaction/role cutoffs are strict, but historical catastro features
were not reconstructed. The report describes these limits explicitly.

## Outcome

The frozen rule gives MdAPE below 10% in all eight communes, with coverage
11.86%–47.32%. No commune meets the combined >=50% coverage / <=10% MdAPE target;
at least six were requested. The rule was not widened after seeing 2026.
Tasar remains unchanged and `sii_closing_layer` remains off.
