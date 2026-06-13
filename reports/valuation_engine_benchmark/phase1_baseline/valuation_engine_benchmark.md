# Valuation Engine Benchmark

Generated at: `2026-06-12T09:24:28.934084+00:00`
Engines: `comparables_legacy`
Git commit: `c854faf1a550798d0706fb139732e6e0ea143178`
Git status: `?? reports/valuation_engine_benchmark/phase1_baseline/
?? reports/valuation_engine_benchmark/phase1_canonical/
?? reports/valuation_engine_benchmark/phase1_canonical_ablation/
?? reports/valuation_engine_benchmark/phase1_canonical_smoke/`

## Global

| Metric | Value |
| --- | ---: |
| `total_cases` | 2740 |
| `successful` | 2636 |
| `failed` | 104 |
| `coverage_pct` | 96.2 |
| `mape_pct` | 24.72 |
| `median_ape_pct` | 17.0 |
| `p90_ape_pct` | 54.13 |
| `mae_clp` | 76914990.07 |
| `signed_bias_pct` | 9.79 |
| `overvaluation_rate_pct` | 55.84 |
| `undervaluation_rate_pct` | 44.16 |
| `error_gt_50_pct` | 11.65 |
| `error_gt_100_pct` | 2.62 |

## Segments

### by_engine

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_legacy` | 24.72 | 17.0 | 96.2 | 2740 |

### by_engine_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_legacy:apartment` | 17.38 | 12.88 | 97.28 | 1472 |
| `comparables_legacy:house` | 33.45 | 23.7 | 94.95 | 1268 |

### by_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `apartment` | 17.38 | 12.88 | 97.28 | 1472 |
| `house` | 33.45 | 23.7 | 94.95 | 1268 |

### by_geocode_precision

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `address` | 17.41 | 10.9 | 91.3 | 23 |
| `comuna` | 23.6 | 17.06 | 95.91 | 1296 |
| `comuna_centroid` | 17.74 | 13.87 | 97.59 | 83 |
| `street` | 26.83 | 18.08 | 96.82 | 1289 |
| `unknown` | 12.53 | 10.5 | 87.76 | 49 |

### by_house_land

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `house_with_land` | 25.7 | 17.35 | 97.75 | 89 |
| `house_without_land` | 34.05 | 24.28 | 94.74 | 1179 |

### by_comuna

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `estacion_central` | 22.37 | 13.69 | 96.45 | 197 |
| `independencia` | 21.03 | 16.69 | 97.97 | 197 |
| `la_florida` | 28.98 | 20.07 | 95.0 | 220 |
| `la_reina` | 20.15 | 13.71 | 94.07 | 135 |
| `las_condes` | 22.95 | 15.89 | 96.5 | 257 |
| `macul` | 28.05 | 16.49 | 98.61 | 144 |
| `maipu` | 30.74 | 22.99 | 98.0 | 250 |
| `nunoa` | 20.22 | 13.02 | 98.41 | 252 |
| `penalolen` | 81.21 | 39.34 | 53.12 | 32 |
| `providencia` | 24.56 | 17.25 | 97.1 | 207 |
| `recoleta` | 27.31 | 21.32 | 97.04 | 169 |
| `san_joaquin` | None | None | 0.0 | 6 |
| `san_miguel` | 27.56 | 15.97 | 97.59 | 166 |
| `santiago` | 21.56 | 15.87 | 97.32 | 299 |
| `vitacura` | 22.51 | 16.77 | 99.0 | 201 |

### engine_intersections

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |

## Limitations

- Active-listing benchmark; not a full temporal backtest unless cutoff is supplied.
- Legacy comparables still use existing production filters and same-comuna candidate logic.
- UF rate is data-derived from local canonical UF fields when --uf-rate is omitted.
