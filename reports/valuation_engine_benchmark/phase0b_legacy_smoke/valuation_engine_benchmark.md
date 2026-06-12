# Valuation Engine Benchmark

Generated at: `2026-06-12T08:27:15.563471+00:00`
Engines: `comparables_legacy`
Git commit: `3aa0966d4677970b2cc7f5fb9260c8edd97a8830`
Git status: `M tests/unit/test_valuation_engine_registry.py
?? tests/unit/test_comparables_legacy_engine.py
?? tests/unit/test_evaluate_valuation_engines_cli.py
?? tests/unit/test_valuation_evaluation_framework.py`

## Global

| Metric | Value |
| --- | ---: |
| `total_cases` | 20 |
| `successful` | 19 |
| `failed` | 1 |
| `coverage_pct` | 95.0 |
| `mape_pct` | 21.02 |
| `median_ape_pct` | 17.01 |
| `p90_ape_pct` | 38.51 |
| `mae_clp` | 62322277.16 |
| `signed_bias_pct` | -2.28 |
| `overvaluation_rate_pct` | 36.84 |
| `undervaluation_rate_pct` | 63.16 |
| `error_gt_50_pct` | 10.53 |
| `error_gt_100_pct` | 0.0 |

## Segments

### by_engine

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_legacy` | 21.02 | 17.01 | 95.0 | 20 |

### by_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `apartment` | 18.6 | 18.81 | 100.0 | 4 |
| `house` | 21.66 | 17.01 | 93.75 | 16 |

### by_geocode_precision

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comuna` | 19.44 | 19.51 | 88.89 | 9 |
| `comuna_centroid` | 15.61 | 15.61 | 100.0 | 1 |
| `street` | 22.82 | 16.47 | 100.0 | 10 |

### by_house_land

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `house_without_land` | 21.66 | 17.01 | 93.75 | 16 |

### by_comuna

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |

## Limitations

- Active-listing benchmark; not a full temporal backtest unless cutoff is supplied.
- Legacy comparables still use existing production filters and same-comuna candidate logic.
- UF rate is data-derived from local canonical UF fields when --uf-rate is omitted.
