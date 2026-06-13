# Valuation Engine Benchmark

Generated at: `2026-06-13T09:11:01.398074+00:00`
Engines: `comparables_legacy, comparables_canonical, comparables_canonical_outliers`
Git commit: `54e56795056959266516a17eaf25b36cf92c9524`
Git status: `M domain/valuation/engines/canonical_comparables.py
 M tests/unit/test_comparables_canonical_engine.py
 M tests/unit/test_valuation_engine_registry.py
?? reports/valuation_engine_benchmark/phase4a_canonical_outliers/`

## Global

| Metric | Value |
| --- | ---: |
| `total_cases` | 8334 |
| `successful` | 7602 |
| `failed` | 732 |
| `coverage_pct` | 91.22 |
| `mape_pct` | 23.8 |
| `median_ape_pct` | 17.3 |
| `p90_ape_pct` | 50.0 |
| `mae_clp` | 76117126.57 |
| `signed_bias_pct` | 5.19 |
| `overvaluation_rate_pct` | 49.59 |
| `undervaluation_rate_pct` | 50.41 |
| `error_gt_50_pct` | 10.01 |
| `error_gt_100_pct` | 2.07 |

## Segments

### by_engine

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical` | 22.79 | 17.11 | 84.63 | 2778 |
| `comparables_canonical_outliers` | 23.65 | 17.65 | 92.84 | 2778 |
| `comparables_legacy` | 24.82 | 17.08 | 96.18 | 2778 |

### by_engine_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical:apartment` | 17.34 | 13.9 | 89.37 | 1487 |
| `comparables_canonical:house` | 29.87 | 22.61 | 79.16 | 1291 |
| `comparables_canonical_outliers:apartment` | 17.4 | 13.94 | 92.54 | 1487 |
| `comparables_canonical_outliers:house` | 30.81 | 23.45 | 93.18 | 1291 |
| `comparables_legacy:apartment` | 17.35 | 12.94 | 97.24 | 1487 |
| `comparables_legacy:house` | 33.62 | 24.22 | 94.97 | 1291 |

### by_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `apartment` | 17.37 | 13.66 | 93.05 | 4461 |
| `house` | 31.53 | 23.41 | 89.1 | 3873 |

### by_geocode_precision

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `address` | 17.72 | 11.74 | 85.51 | 69 |
| `comuna` | 23.02 | 17.16 | 90.8 | 4056 |
| `comuna_centroid` | 16.71 | 13.66 | 95.18 | 249 |
| `street` | 25.59 | 18.24 | 91.82 | 3813 |
| `unknown` | 12.49 | 9.46 | 82.99 | 147 |

### by_house_land

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `house_with_land` | 23.12 | 17.61 | 82.41 | 216 |
| `house_without_land` | 31.99 | 23.61 | 89.5 | 3657 |

### by_comuna

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `conchali` | None | None | 0.0 | 6 |
| `el_bosque` | None | None | 0.0 | 6 |
| `estacion_central` | 20.49 | 16.14 | 94.67 | 600 |
| `independencia` | 20.84 | 17.06 | 95.77 | 591 |
| `la_cisterna` | None | None | 0.0 | 6 |
| `la_florida` | 27.19 | 20.85 | 92.38 | 669 |
| `la_reina` | 20.33 | 13.71 | 83.46 | 405 |
| `las_condes` | 23.41 | 15.09 | 88.85 | 798 |
| `macul` | 26.51 | 17.32 | 90.48 | 441 |
| `maipu` | 28.84 | 22.85 | 95.33 | 750 |
| `nunoa` | 20.61 | 13.19 | 95.99 | 774 |
| `penalolen` | 68.82 | 31.78 | 49.49 | 99 |
| `providencia` | 23.7 | 18.21 | 90.82 | 621 |
| `recoleta` | 25.45 | 20.88 | 89.52 | 525 |
| `san_joaquin` | None | None | 0.0 | 18 |
| `san_miguel` | 25.95 | 16.96 | 92.7 | 507 |
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
