# Valuation Engine Benchmark

Generated at: `2026-06-12T09:27:46.587231+00:00`
Engines: `comparables_canonical_price_only, comparables_canonical_product, comparables_canonical_outliers, comparables_canonical`
Git commit: `c854faf1a550798d0706fb139732e6e0ea143178`
Git status: `?? reports/valuation_engine_benchmark/phase1_baseline/
?? reports/valuation_engine_benchmark/phase1_canonical/
?? reports/valuation_engine_benchmark/phase1_canonical_ablation/
?? reports/valuation_engine_benchmark/phase1_canonical_smoke/`

## Global

| Metric | Value |
| --- | ---: |
| `total_cases` | 10960 |
| `successful` | 9817 |
| `failed` | 1143 |
| `coverage_pct` | 89.57 |
| `mape_pct` | 23.7 |
| `median_ape_pct` | 17.21 |
| `p90_ape_pct` | 49.49 |
| `mae_clp` | 75290890.99 |
| `signed_bias_pct` | 4.91 |
| `overvaluation_rate_pct` | 49.3 |
| `undervaluation_rate_pct` | 50.7 |
| `error_gt_50_pct` | 9.66 |
| `error_gt_100_pct` | 2.02 |

## Segments

### by_engine

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical` | 22.71 | 16.99 | 85.26 | 2740 |
| `comparables_canonical_outliers` | 23.55 | 17.52 | 93.61 | 2740 |
| `comparables_canonical_price_only` | 24.64 | 17.62 | 93.8 | 2740 |
| `comparables_canonical_product` | 23.81 | 17.03 | 85.62 | 2740 |

### by_engine_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical:apartment` | 17.33 | 13.79 | 90.69 | 1472 |
| `comparables_canonical:house` | 29.88 | 22.56 | 78.94 | 1268 |
| `comparables_canonical_outliers:apartment` | 17.35 | 13.88 | 93.95 | 1472 |
| `comparables_canonical_outliers:house` | 30.81 | 23.12 | 93.22 | 1268 |
| `comparables_canonical_price_only:apartment` | 17.58 | 13.77 | 93.95 | 1472 |
| `comparables_canonical_price_only:house` | 32.86 | 23.98 | 93.61 | 1268 |
| `comparables_canonical_product:apartment` | 17.55 | 13.71 | 90.69 | 1472 |
| `comparables_canonical_product:house` | 32.09 | 23.63 | 79.73 | 1268 |

### by_property_type

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `apartment` | 17.45 | 13.78 | 92.32 | 5888 |
| `house` | 31.45 | 23.41 | 86.38 | 5072 |

### by_geocode_precision

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `address` | 17.48 | 13.91 | 86.96 | 92 |
| `comuna` | 22.95 | 17.17 | 89.22 | 5184 |
| `comuna_centroid` | 16.38 | 11.9 | 93.98 | 332 |
| `street` | 25.42 | 18.18 | 89.95 | 5156 |
| `unknown` | 12.79 | 9.2 | 82.65 | 196 |

### by_house_land

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `house_with_land` | 25.17 | 17.16 | 76.69 | 356 |
| `house_without_land` | 31.87 | 23.78 | 87.11 | 4716 |

### by_comuna

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `conchali` | None | None | 0.0 | 8 |
| `el_bosque` | None | None | 0.0 | 8 |
| `estacion_central` | 20.16 | 16.39 | 93.65 | 788 |
| `independencia` | 21.15 | 16.89 | 94.67 | 788 |
| `la_cisterna` | None | None | 0.0 | 8 |
| `la_florida` | 27.01 | 20.43 | 90.91 | 880 |
| `la_reina` | 19.74 | 13.84 | 85.19 | 540 |
| `las_condes` | 24.26 | 14.66 | 84.44 | 1028 |
| `macul` | 26.53 | 17.68 | 86.63 | 576 |
| `maipu` | 28.33 | 23.09 | 94.0 | 1000 |
| `nunoa` | 20.14 | 12.55 | 95.14 | 1008 |
| `penalolen` | 70.0 | 38.69 | 48.44 | 128 |
| `providencia` | 23.57 | 18.36 | 88.65 | 828 |
| `recoleta` | 25.6 | 20.86 | 85.21 | 676 |
| `san_joaquin` | None | None | 0.0 | 24 |
| `san_miguel` | 26.01 | 17.4 | 91.87 | 664 |
| `santiago` | 20.24 | 15.57 | 93.06 | 1196 |
| `vitacura` | 22.88 | 16.39 | 88.56 | 804 |

### engine_intersections

| Segment | MAPE | Median APE | Coverage | Cases |
| --- | ---: | ---: | ---: | ---: |
| `comparables_canonical__comparables_canonical_outliers` | None | None | None | None |
| `comparables_canonical__comparables_canonical_price_only` | None | None | None | None |
| `comparables_canonical__comparables_canonical_product` | None | None | None | None |
| `comparables_canonical_outliers__comparables_canonical_price_only` | None | None | None | None |
| `comparables_canonical_outliers__comparables_canonical_product` | None | None | None | None |
| `comparables_canonical_price_only__comparables_canonical_product` | None | None | None | None |

## Limitations

- Active-listing benchmark; not a full temporal backtest unless cutoff is supplied.
- Legacy comparables still use existing production filters and same-comuna candidate logic.
- UF rate is data-derived from local canonical UF fields when --uf-rate is omitted.
