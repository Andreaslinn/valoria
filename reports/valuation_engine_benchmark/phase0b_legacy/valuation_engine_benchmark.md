# Valuation Engine Benchmark

Generated at: `2026-06-12T08:29:27.097476+00:00`
Engines: `comparables_legacy`
Git commit: `3aa0966d4677970b2cc7f5fb9260c8edd97a8830`
Git status: `M tests/unit/test_valuation_engine_registry.py
?? reports/valuation_engine_benchmark/
?? tests/unit/test_comparables_legacy_engine.py
?? tests/unit/test_evaluate_valuation_engines_cli.py
?? tests/unit/test_valuation_evaluation_framework.py`

## Global

| Metric | Value |
| --- | ---: |
| `total_cases` | 2740 |
| `successful` | 2636 |
| `failed` | 104 |
| `coverage_pct` | 96.2 |
| `mape_pct` | 24.71 |
| `median_ape_pct` | 17.01 |
| `p90_ape_pct` | 54.07 |
| `mae_clp` | 76928040.29 |
| `signed_bias_pct` | 9.75 |
| `overvaluation_rate_pct` | 55.8 |
| `undervaluation_rate_pct` | 44.2 |
| `error_gt_50_pct` | 11.68 |
| `error_gt_100_pct` | 2.62 |

## Segments

### by_engine

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_legacy` | 24.71 | 17.01 | 96.2 | 2740 |

### by_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `apartment` | 17.36 | 12.95 | 97.28 | 1472 |
| `house` | 33.45 | 23.7 | 94.95 | 1268 |

### by_geocode_precision

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `address` | 17.13 | 9.95 | 91.3 | 23 |
| `comuna` | 23.6 | 17.06 | 95.91 | 1296 |
| `comuna_centroid` | 17.59 | 13.6 | 97.59 | 83 |
| `street` | 26.82 | 18.12 | 96.82 | 1289 |
| `unknown` | 12.49 | 9.8 | 87.76 | 49 |

### by_house_land

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `house_with_land` | 25.53 | 17.35 | 97.75 | 89 |
| `house_without_land` | 34.07 | 24.28 | 94.74 | 1179 |

### by_comuna

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `estacion_central` | 22.36 | 13.69 | 96.45 | 197 |
| `independencia` | 21.03 | 16.56 | 97.97 | 197 |
| `la_florida` | 28.9 | 20.07 | 95.0 | 220 |
| `la_reina` | 20.13 | 13.71 | 94.07 | 135 |
| `las_condes` | 22.98 | 15.89 | 96.5 | 257 |
| `macul` | 28.19 | 16.37 | 98.61 | 144 |
| `maipu` | 30.58 | 23.09 | 98.0 | 250 |
| `nunoa` | 20.19 | 13.02 | 98.41 | 252 |
| `penalolen` | 81.21 | 39.34 | 53.12 | 32 |
| `providencia` | 24.58 | 17.36 | 97.1 | 207 |
| `recoleta` | 27.37 | 21.32 | 97.04 | 169 |
| `san_joaquin` | None | None | 0.0 | 6 |
| `san_miguel` | 27.58 | 16.07 | 97.59 | 166 |
| `santiago` | 21.54 | 15.61 | 97.32 | 299 |
| `vitacura` | 22.51 | 16.77 | 99.0 | 201 |

## Limitations

- Active-listing benchmark; not a full temporal backtest unless cutoff is supplied.
- Legacy comparables still use existing production filters and same-comuna candidate logic.
- UF rate is data-derived from local canonical UF fields when --uf-rate is omitted.
