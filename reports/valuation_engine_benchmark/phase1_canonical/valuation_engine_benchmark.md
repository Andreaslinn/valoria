# Valuation Engine Benchmark

Generated at: `2026-06-12T09:26:07.390435+00:00`
Engines: `comparables_legacy, comparables_canonical`
Git commit: `c854faf1a550798d0706fb139732e6e0ea143178`
Git status: `?? reports/valuation_engine_benchmark/phase1_baseline/
?? reports/valuation_engine_benchmark/phase1_canonical/
?? reports/valuation_engine_benchmark/phase1_canonical_ablation/
?? reports/valuation_engine_benchmark/phase1_canonical_smoke/`

## Global

| Metric | Value |
| --- | ---: |
| `total_cases` | 5480 |
| `successful` | 4972 |
| `failed` | 508 |
| `coverage_pct` | 90.73 |
| `mape_pct` | 23.77 |
| `median_ape_pct` | 17.0 |
| `p90_ape_pct` | 50.22 |
| `mae_clp` | 74502965.6 |
| `signed_bias_pct` | 6.63 |
| `overvaluation_rate_pct` | 51.97 |
| `undervaluation_rate_pct` | 48.03 |
| `error_gt_50_pct` | 10.08 |
| `error_gt_100_pct` | 2.15 |

## Segments

### by_engine

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical` | 22.71 | 16.99 | 85.26 | 2740 |
| `comparables_legacy` | 24.72 | 17.0 | 96.2 | 2740 |

### by_engine_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical:apartment` | 17.33 | 13.79 | 90.69 | 1472 |
| `comparables_canonical:house` | 29.88 | 22.56 | 78.94 | 1268 |
| `comparables_legacy:apartment` | 17.38 | 12.88 | 97.28 | 1472 |
| `comparables_legacy:house` | 33.45 | 23.7 | 94.95 | 1268 |

### by_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `apartment` | 17.36 | 13.48 | 93.99 | 2944 |
| `house` | 31.83 | 23.07 | 86.95 | 2536 |

### by_geocode_precision

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `address` | 17.29 | 10.57 | 86.96 | 46 |
| `comuna` | 22.89 | 17.0 | 90.39 | 2592 |
| `comuna_centroid` | 16.91 | 13.36 | 95.18 | 166 |
| `street` | 25.63 | 17.95 | 91.08 | 2578 |
| `unknown` | 12.4 | 9.29 | 84.69 | 98 |

### by_house_land

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `house_with_land` | 25.09 | 17.25 | 77.53 | 178 |
| `house_without_land` | 32.28 | 23.5 | 87.66 | 2358 |

### by_comuna

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `estacion_central` | 20.85 | 14.77 | 93.91 | 394 |
| `independencia` | 20.72 | 16.8 | 95.18 | 394 |
| `la_florida` | 27.34 | 20.3 | 91.36 | 440 |
| `la_reina` | 20.08 | 13.88 | 87.41 | 270 |
| `las_condes` | 22.82 | 14.89 | 88.52 | 514 |
| `macul` | 26.79 | 16.64 | 88.89 | 288 |
| `maipu` | 29.11 | 22.76 | 94.4 | 500 |
| `nunoa` | 20.09 | 12.7 | 95.63 | 504 |
| `penalolen` | 72.49 | 34.85 | 48.44 | 64 |
| `providencia` | 23.98 | 17.93 | 89.37 | 414 |
| `recoleta` | 25.76 | 20.32 | 87.57 | 338 |
| `san_joaquin` | None | None | 0.0 | 12 |
| `san_miguel` | 26.02 | 16.57 | 92.77 | 332 |
| `santiago` | 20.53 | 15.38 | 92.64 | 598 |
| `vitacura` | 22.45 | 15.99 | 90.8 | 402 |

### engine_intersections

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical__comparables_legacy` | None | None | None | None |

## Limitations

- Active-listing benchmark; not a full temporal backtest unless cutoff is supplied.
- Legacy comparables still use existing production filters and same-comuna candidate logic.
- UF rate is data-derived from local canonical UF fields when --uf-rate is omitted.
