# Valuation Engine Benchmark

Generated at: `2026-06-12T09:03:33.070917+00:00`
Engines: `comparables_legacy, comparables_canonical`
Git commit: `9135fe34f218ac4a2adead5b8da98932d4ffa3ef`
Git status: `M domain/valuation/engines/__init__.py
 M domain/valuation/engines/registry.py
 M domain/valuation/evaluation/dataset.py
 M domain/valuation/evaluation/metrics.py
 M scripts/evaluate_valuation_engines.py
 M tests/unit/test_valuation_engine_registry.py
?? domain/valuation/engines/canonical_comparables.py
?? domain/valuation/product_classification.py
?? domain/valuation/robust_price_m2.py
?? reports/valuation_engine_benchmark/phase1_baseline/
?? tests/unit/test_comparables_canonical_engine.py
?? tests/unit/test_product_classification.py
?? tests/unit/test_robust_price_m2.py`

## Global

| Metric | Value |
| --- | ---: |
| `total_cases` | 50 |
| `successful` | 38 |
| `failed` | 12 |
| `coverage_pct` | 76.0 |
| `mape_pct` | 39.09 |
| `median_ape_pct` | 23.44 |
| `p90_ape_pct` | 94.73 |
| `mae_clp` | 89008481.58 |
| `signed_bias_pct` | 15.63 |
| `overvaluation_rate_pct` | 39.47 |
| `undervaluation_rate_pct` | 60.53 |
| `error_gt_50_pct` | 26.32 |
| `error_gt_100_pct` | 10.53 |

## Segments

### by_engine

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical` | 39.12 | 21.84 | 72.0 | 25 |
| `comparables_legacy` | 39.07 | 26.58 | 80.0 | 25 |

### by_engine_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical:apartment` | 38.45 | 14.76 | 62.5 | 8 |
| `comparables_canonical:house` | 39.37 | 23.41 | 76.47 | 17 |
| `comparables_legacy:apartment` | 38.64 | 16.92 | 75.0 | 8 |
| `comparables_legacy:house` | 39.25 | 36.14 | 82.35 | 17 |

### by_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `apartment` | 38.56 | 14.76 | 68.75 | 16 |
| `house` | 39.31 | 33.02 | 79.41 | 34 |

### by_geocode_precision

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comuna` | 48.65 | 18.78 | 75.0 | 24 |
| `street` | 30.48 | 29.27 | 76.92 | 26 |

### by_house_land

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `house_without_land` | 39.31 | 33.02 | 79.41 | 34 |

### by_comuna

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `independencia` | 22.68 | 22.31 | 66.67 | 6 |
| `la_florida` | 28.27 | 23.15 | 66.67 | 6 |
| `maipu` | 48.56 | 32.97 | 100.0 | 10 |
| `santiago` | 67.45 | 29.7 | 70.0 | 10 |

### engine_intersections

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical__comparables_legacy` | None | None | None | None |

## Limitations

- Active-listing benchmark; not a full temporal backtest unless cutoff is supplied.
- Legacy comparables still use existing production filters and same-comuna candidate logic.
- UF rate is data-derived from local canonical UF fields when --uf-rate is omitted.
