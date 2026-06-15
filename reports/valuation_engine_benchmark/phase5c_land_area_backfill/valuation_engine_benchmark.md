# Valuation Engine Benchmark

Generated at: `2026-06-15T12:30:14.425280+00:00`
Engines: `comparables_legacy, comparables_canonical, comparables_canonical_outliers`
Git commit: `57922f375eab5373c8441c10bef9e942debe1227`
Git status: `clean`

## Global

| Metric | Value |
| --- | ---: |
| `total_cases` | 8334 |
| `successful` | 7600 |
| `failed` | 734 |
| `coverage_pct` | 91.19 |
| `mape_pct` | 23.79 |
| `median_ape_pct` | 17.32 |
| `p90_ape_pct` | 50.01 |
| `mae_clp` | 76013685.63 |
| `signed_bias_pct` | 5.19 |
| `overvaluation_rate_pct` | 49.58 |
| `undervaluation_rate_pct` | 50.42 |
| `error_gt_50_pct` | 10.01 |
| `error_gt_100_pct` | 2.08 |

## Segments

### by_engine

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical` | 22.78 | 17.11 | 84.56 | 2778 |
| `comparables_canonical_outliers` | 23.66 | 17.67 | 92.84 | 2778 |
| `comparables_legacy` | 24.82 | 17.08 | 96.18 | 2778 |

### by_engine_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical:apartment` | 17.34 | 13.9 | 89.37 | 1487 |
| `comparables_canonical:house` | 29.86 | 22.61 | 79.01 | 1291 |
| `comparables_canonical_outliers:apartment` | 17.4 | 13.94 | 92.54 | 1487 |
| `comparables_canonical_outliers:house` | 30.81 | 23.45 | 93.18 | 1291 |
| `comparables_legacy:apartment` | 17.35 | 12.94 | 97.24 | 1487 |
| `comparables_legacy:house` | 33.62 | 24.31 | 94.97 | 1291 |

### by_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `apartment` | 17.37 | 13.66 | 93.05 | 4461 |
| `house` | 31.53 | 23.43 | 89.05 | 3873 |

### by_geocode_precision

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `address` | 17.72 | 11.74 | 85.51 | 69 |
| `comuna` | 23.02 | 17.17 | 90.78 | 4056 |
| `comuna_centroid` | 16.71 | 13.66 | 95.18 | 249 |
| `street` | 25.59 | 18.26 | 91.79 | 3813 |
| `unknown` | 12.49 | 9.46 | 82.99 | 147 |

### by_house_land

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `house_with_land` | 24.32 | 18.69 | 77.66 | 291 |
| `house_without_land` | 32.04 | 23.62 | 89.98 | 3582 |

### by_comuna

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `conchali` | None | None | 0.0 | 6 |
| `el_bosque` | None | None | 0.0 | 6 |
| `estacion_central` | 20.49 | 16.14 | 94.67 | 600 |
| `independencia` | 20.84 | 17.06 | 95.77 | 591 |
| `la_cisterna` | None | None | 0.0 | 6 |
| `la_florida` | 27.19 | 20.85 | 92.38 | 669 |
| `la_reina` | 20.31 | 13.76 | 83.46 | 405 |
| `las_condes` | 23.43 | 15.09 | 88.85 | 798 |
| `macul` | 26.51 | 17.32 | 90.48 | 441 |
| `maipu` | 28.84 | 22.85 | 95.33 | 750 |
| `nunoa` | 20.55 | 13.19 | 95.74 | 774 |
| `penalolen` | 68.82 | 31.78 | 49.49 | 99 |
| `providencia` | 23.68 | 18.21 | 90.82 | 621 |
| `recoleta` | 25.47 | 20.88 | 89.52 | 525 |
| `san_joaquin` | None | None | 0.0 | 18 |
| `san_miguel` | 26.0 | 17.25 | 92.7 | 507 |
| `santiago` | 20.68 | 15.9 | 94.17 | 909 |
| `vitacura` | 22.47 | 15.93 | 89.05 | 603 |

### engine_intersections

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical__comparables_canonical_outliers` | None | None | None | None |
| `comparables_canonical__comparables_legacy` | None | None | None | None |
| `comparables_canonical_outliers__comparables_legacy` | None | None | None | None |

## Limitations

- Active-listing benchmark; not a full temporal backtest unless cutoff is supplied.
- Legacy comparables still use existing production filters and same-comuna candidate logic.
- UF rate is data-derived from local canonical UF fields when --uf-rate is omitted.
