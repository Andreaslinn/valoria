# Phase 4A Canonical Outliers Report

## Preflight

- Source branch: `codex/phase3-ml-house-consensus-strategy`
- Source HEAD: `54e56795056959266516a17eaf25b36cf92c9524`
- Working branch: `codex/phase4a-technical-base-canonical-outliers`
- Registered baseline engines found before changes: `comparables_legacy`, `comparables_canonical`, `comparables_canonical_outliers`, `comparables_canonical_price_only`, `comparables_canonical_product`
- Dataset signature: `62520141dcc9d7f72390253df4b8f031d91c09cb0e70b1e04bce1254694827ab`
- Remote configured: `false`

## Design Decision

Selected Option B: keep one `ComparablesCanonicalEngine` class and freeze `comparables_canonical_outliers` as a named registered variant. This preserves Phase 1 `canonical_plus_outliers`, avoids duplicate logic, and keeps benchmark separation by `engine_name`.

- Engine: `comparables_canonical_outliers`
- Version: `phase4a_canonical_outliers_v1`
- Variant: `outliers`
- Relation to canonical full: same class, but `canonical` keeps product filtering on; `canonical_outliers` disables product hard filtering and keeps robust outlier filtering.
- Production wiring changed: `false`

## Frozen Configuration

| Setting | Value |
| --- | ---: |
| `canonical_price_enabled` | `True` |
| `product_filter_enabled` | `False` |
| `product_hard_filtering_mode` | `disabled` |
| `robust_filter_enabled` | `True` |
| `min_comparables` | `5` |
| `top_n` | `20` |
| `selection_behavior` | `canonical price strictness plus robust local price/m2 outlier filtering; no product hard filter` |
| `robust_filter.min_iqr_samples` | `8` |
| `robust_filter.min_percentile_samples` | `5` |
| `robust_filter.iqr_multiplier` | `2.0` |
| `robust_filter.fallback_iqr_multiplier` | `2.75` |
| `robust_filter.max_deviation_ratio` | `2.25` |
| `robust_filter.min_deviation_ratio` | `0.35` |
| `robust_filter.house_high_tail_ratio` | `1.85` |
| `robust_filter.enable_house_high_tail` | `True` |

## Tests

| Scope | Command | Result |
| --- | --- | --- |
| `focused` | `python -m pytest tests/unit/test_comparables_canonical_engine.py tests/unit/test_valuation_engine_registry.py` | `16 passed` |
| `valuation_related` | `python -m pytest tests/unit/test_valuation_evaluation_framework.py tests/unit/test_product_classification.py tests/unit/test_robust_price_m2.py tests/unit/test_evaluate_valuation_engines_cli.py tests/unit/test_comparables_legacy_engine.py tests/unit/test_comparables_canonical_engine.py tests/unit/test_valuation_engine_registry.py` | `35 passed` |
| `full_unit` | `python -m pytest tests/unit` | `985 passed, 2 failed, 7 errors` |

Known unrelated full-suite failures: 2 Nominatim address-normalization assertions and 7 `tmp_path` permission errors in `test_create_release_zip.py`. No new focused or valuation-related failures.

## Benchmark

Command:

```powershell
python scripts/evaluate_valuation_engines.py --engines comparables_legacy,comparables_canonical,comparables_canonical_outliers --output-dir reports/valuation_engine_benchmark/phase4a_canonical_outliers
```

Dataset cases: `2778`
Dataset signature: `62520141dcc9d7f72390253df4b8f031d91c09cb0e70b1e04bce1254694827ab`
Git hash captured by benchmark: `54e56795056959266516a17eaf25b36cf92c9524`
UF rate: `40644.549956` from `local_listing_price_uf_median`

### global

| Engine | Coverage | MAPE | Median APE | P90 APE | >50 | >100 | Bias | OK/Cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `legacy` | 96.18 | 24.82 | 17.08 | 53.48 | 11.64 | 2.69 | 9.76 | 2672/2778 |
| `canonical` | 84.63 | 22.79 | 17.11 | 47.38 | 8.51 | 1.66 | 2.51 | 2351/2778 |
| `canonical_outliers` | 92.84 | 23.65 | 17.65 | 49.50 | 9.69 | 1.78 | 2.90 | 2579/2778 |

### apartments

| Engine | Coverage | MAPE | Median APE | P90 APE | >50 | >100 | Bias | OK/Cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `legacy` | 97.24 | 17.35 | 12.94 | 36.57 | 4.15 | 0.48 | 4.90 | 1446/1487 |
| `canonical` | 89.37 | 17.34 | 13.90 | 35.82 | 3.31 | 0.38 | -1.10 | 1329/1487 |
| `canonical_outliers` | 92.54 | 17.40 | 13.94 | 36.02 | 3.42 | 0.36 | -1.04 | 1376/1487 |

### houses

| Engine | Coverage | MAPE | Median APE | P90 APE | >50 | >100 | Bias | OK/Cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `legacy` | 94.97 | 33.62 | 24.22 | 73.22 | 20.47 | 5.30 | 15.49 | 1226/1291 |
| `canonical` | 79.16 | 29.87 | 22.61 | 60.28 | 15.26 | 3.33 | 7.19 | 1022/1291 |
| `canonical_outliers` | 93.18 | 30.81 | 23.45 | 64.03 | 16.87 | 3.41 | 7.41 | 1203/1291 |

### houses_with_land

| Engine | Coverage | MAPE | Median APE | P90 APE | >50 | >100 | Bias | OK/Cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `legacy` | 98.61 | 23.89 | 18.24 | 48.79 | 9.86 | 0.00 | 4.63 | 71/72 |
| `canonical` | 54.17 | 22.50 | 16.51 | 43.77 | 7.69 | 2.56 | 3.06 | 39/72 |
| `canonical_outliers` | 94.44 | 22.67 | 17.21 | 45.33 | 5.88 | 1.47 | 1.34 | 68/72 |

### houses_without_land

| Engine | Coverage | MAPE | Median APE | P90 APE | >50 | >100 | Bias | OK/Cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `legacy` | 94.75 | 34.22 | 24.60 | 74.57 | 21.13 | 5.63 | 16.15 | 1155/1219 |
| `canonical` | 80.64 | 30.16 | 22.66 | 61.04 | 15.56 | 3.36 | 7.36 | 983/1219 |
| `canonical_outliers` | 93.11 | 31.29 | 23.80 | 64.90 | 17.53 | 3.52 | 7.77 | 1135/1219 |

### useful_geocode

| Engine | Coverage | MAPE | Median APE | P90 APE | >50 | >100 | Bias | OK/Cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `legacy` | 96.75 | 26.79 | 18.09 | 58.41 | 13.90 | 3.43 | 12.34 | 1252/1294 |
| `canonical` | 84.85 | 24.22 | 17.98 | 51.23 | 10.66 | 2.09 | 3.99 | 1098/1294 |
| `canonical_outliers` | 93.51 | 25.20 | 18.34 | 52.87 | 11.40 | 2.15 | 4.55 | 1210/1294 |

### low_precision_geocode

| Engine | Coverage | MAPE | Median APE | P90 APE | >50 | >100 | Bias | OK/Cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `legacy` | 95.69 | 23.08 | 16.58 | 48.24 | 9.65 | 2.04 | 7.48 | 1420/1484 |
| `canonical` | 84.43 | 21.54 | 16.06 | 43.57 | 6.62 | 1.28 | 1.21 | 1253/1484 |
| `canonical_outliers` | 92.25 | 22.29 | 17.12 | 46.10 | 8.18 | 1.46 | 1.44 | 1369/1484 |

### all_three_engines_ok_intersection

| Engine | Coverage | MAPE | Median APE | P90 APE | >50 | >100 | Bias | OK/Cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `legacy` | 100.00 | 23.69 | 16.48 | 51.12 | 10.59 | 2.38 | 8.93 | 2351/2351 |
| `canonical` | 100.00 | 22.79 | 17.11 | 47.38 | 8.51 | 1.66 | 2.51 | 2351/2351 |
| `canonical_outliers` | 100.00 | 22.74 | 17.23 | 47.52 | 8.72 | 1.66 | 2.49 | 2351/2351 |

Errors by engine:

| Engine | Error counts |
| --- | --- |
| `legacy` | `{'insufficient_data': 106}` |
| `canonical` | `{'insufficient_data': 427}` |
| `canonical_outliers` | `{'insufficient_data': 199}` |

Current benchmark rows do not expose `microzona_available` or target-level `canonical_price_usable` as segment columns; this is documented as observability debt rather than inferred ad hoc.

## Comparison Against Phase 1

The Phase 1 and Phase 4A runs use the same active-listing benchmark methodology but different dataset signatures, so deltas include data drift.

| Metric | Phase 1 canonical_plus_outliers houses | Phase 4A canonical_outliers houses | Delta pp |
| --- | ---: | ---: | ---: |
| `coverage_pct` | 93.22 | 93.18 | -0.04 |
| `mape_pct` | 30.81 | 30.81 | 0.00 |
| `median_ape_pct` | 23.12 | 23.45 | 0.33 |
| `p90_ape_pct` | 64.32 | 64.03 | -0.29 |
| `error_gt_50_pct` | 16.75 | 16.87 | 0.12 |
| `error_gt_100_pct` | 3.38 | 3.41 | 0.03 |

## Diagnostics

Flat diagnostics added: `variant`, `config_version`, `candidates_loaded`, `structurally_eligible`, `canonical_price_usable`, `robust_filter_input`, `robust_filter_output`, `high_outliers_excluded`, `low_outliers_excluded`, `fallback_applied`, `selected_comparables`, `local_reference_level`, `local_median_price_m2`, `lower_threshold`, `upper_threshold`, `threshold_method`, `confidence_penalties`, `comparables_used`, `price_basis_by_comparable`, `estimate_before_outlier_filter`, `estimate_after_outlier_filter`. Existing nested diagnostics remain.

## Recommendation

Classification: `stable_challenger`. It reproduces Phase 1 `canonical_plus_outliers` closely, keeps high coverage, improves houses versus legacy, preserves apartment performance, exposes diagnostics, and leaves production/legacy untouched.

## Guardrails

- `db_modified`: `false`
- `migrations_created_or_executed`: `false`
- `production_changed`: `false`
- `comparables_legacy_modified`: `false`
- `legacy_filters_weights_or_formulas_modified`: `false`
- `valuation_service_changed`: `false`
- `hedonic_ml_house_land_building_or_consensus_implemented`: `false`
- `remote_configured`: `false`
- `push_performed`: `false`
