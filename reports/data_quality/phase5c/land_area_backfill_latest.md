# Phase 5C Controlled Land Area Backfill

## Preflight

- Branch: `codex/phase5c-apply-land-area-backfill`
- HEAD before apply: `57922f375eab5373c8441c10bef9e942debe1227`
- Database: `postgresql+asyncpg://localhost:5432/avm`
- Manifest: `reports\data_quality\phase5b\land_area_backfill_candidates.json`

## Manifest And Dry-run

- Manifest summary: `{'total_candidates': 34, 'accept_high_confidence': 25, 'review_required': 9, 'rejected': 0, 'other_or_not_applicable': 0, 'status_counts': {'accept_high_confidence': 25, 'review_required': 9}}`
- Apply ready: `25`
- Skipped: `9`
- Expected coverage: `7.66%`

## Apply

- Transaction: `committed`
- Rows affected: `25`
- Duration seconds: `20.582`
- Verified: `True`

## Coverage

- Before: `74/1293` (5.72%)
- After: `99/1293` (7.66%)

## Benchmark Comparison

| Engine | Segment | F4A MAPE | F5C MAPE | F4A Median | F5C Median | F4A P90 | F5C P90 | F4A >50 | F5C >50 | F4A >100 | F5C >100 | F4A Coverage | F5C Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `comparables_canonical` | `global` | 22.79 | 22.78 | 17.11 | 17.11 | 47.38 | 47.29 | 8.51 | 8.47 | 1.66 | 1.66 | 84.63 | 84.56 |
| `comparables_canonical` | `apartment` | 17.34 | 17.34 | 13.9 | 13.9 | 35.82 | 35.82 | 3.31 | 3.31 | 0.38 | 0.38 | 89.37 | 89.37 |
| `comparables_canonical` | `house` | 29.87 | 29.86 | 22.61 | 22.61 | 60.28 | 60.3 | 15.26 | 15.2 | 3.33 | 3.33 | 79.16 | 79.01 |
| `comparables_canonical` | `house_with_land` | 22.5 | 22.42 | 16.51 | 17.68 | 43.77 | 40.89 | 7.69 | 4.76 | 2.56 | 2.38 | 54.17 | 43.3 |
| `comparables_canonical` | `house_without_land` | 30.16 | 30.18 | 22.66 | 22.66 | 61.04 | 61.11 | 15.56 | 15.64 | 3.36 | 3.37 | 80.64 | 81.91 |
| `comparables_canonical_outliers` | `global` | 23.65 | 23.66 | 17.65 | 17.67 | 49.5 | 49.6 | 9.69 | 9.69 | 1.78 | 1.82 | 92.84 | 92.84 |
| `comparables_canonical_outliers` | `apartment` | 17.4 | 17.4 | 13.94 | 13.94 | 36.02 | 36.02 | 3.42 | 3.42 | 0.36 | 0.36 | 92.54 | 92.54 |
| `comparables_canonical_outliers` | `house` | 30.81 | 30.81 | 23.45 | 23.45 | 64.03 | 64.35 | 16.87 | 16.87 | 3.41 | 3.49 | 93.18 | 93.18 |
| `comparables_canonical_outliers` | `house_with_land` | 22.67 | 24.39 | 17.21 | 19.06 | 45.33 | 47.33 | 5.88 | 6.67 | 1.47 | 2.22 | 94.44 | 92.78 |
| `comparables_canonical_outliers` | `house_without_land` | 31.29 | 31.33 | 23.8 | 23.76 | 64.9 | 65.35 | 17.53 | 17.7 | 3.52 | 3.59 | 93.11 | 93.22 |
| `comparables_legacy` | `global` | 24.82 | 24.82 | 17.08 | 17.08 | 53.48 | 53.31 | 11.64 | 11.68 | 2.69 | 2.69 | 96.18 | 96.18 |
| `comparables_legacy` | `apartment` | 17.35 | 17.35 | 12.94 | 12.94 | 36.57 | 36.57 | 4.15 | 4.15 | 0.48 | 0.48 | 97.24 | 97.24 |
| `comparables_legacy` | `house` | 33.62 | 33.62 | 24.22 | 24.31 | 73.22 | 73.22 | 20.47 | 20.55 | 5.3 | 5.3 | 94.97 | 94.97 |
| `comparables_legacy` | `house_with_land` | 23.89 | 25.09 | 18.24 | 18.53 | 48.79 | 49.85 | 9.86 | 10.64 | 0.0 | 2.13 | 98.61 | 96.91 |
| `comparables_legacy` | `house_without_land` | 34.22 | 34.33 | 24.6 | 24.7 | 74.57 | 74.6 | 21.13 | 21.38 | 5.63 | 5.57 | 94.75 | 94.81 |

## Rollback

- `{'manifest_path': 'reports/data_quality/phase5c/land_area_rollback_manifest.json', 'rows': 25, 'executed': False, 'instructions': 'Rollback proposal only. Review current values and execute transactionally; this file is not an automatic script.'}`

## Tests

- `new`: `14 passed` - `python -m pytest tests/unit/test_land_area_backfill.py`
- `data_quality`: `25 passed` - `python -m pytest tests/unit/test_data_enrichment_audit.py tests/unit/test_data_enrichment_validation.py`
- `evaluation_engines`: `33 passed` - `phase5c valuation/evaluation smoke suite`
- `parser`: `42 passed` - `python -m pytest tests/unit/test_house_area_corrections.py tests/unit/test_yapo_parser.py`

## Git

- `{'branch': 'codex/phase5c-apply-land-area-backfill', 'head': 'ab544bd46acb6af6eaca5bebe67a6ad3eb195a2f', 'status': '?? reports/valuation_engine_benchmark/phase5c_land_area_backfill/', 'recent_commits': ['ab544bd docs: complete phase5c report metadata', '57922f3 test: cover controlled land area backfill', '12288e5 feat: add controlled land area backfill', '054e9ca docs: add phase5b data enrichment validation report', 'e53892e fix: sanitize multiline phase5b csv fields', 'b24e2d3 docs: refresh phase5b reports after csv normalization'], 'remotes': 'clean'}`

## Guardrails

- `only_land_area_updated`: `True`
- `microzones_updated`: `0`
- `geocoding_updated`: `0`
- `prices_updated`: `0`
- `duplicates_deleted`: `0`
- `external_requests`: `0`
- `migrations_created_or_run`: `0`
- `production_changed`: `False`
