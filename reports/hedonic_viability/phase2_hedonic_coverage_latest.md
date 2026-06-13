# Phase 2 Hedonic Viability Audit

Dataset signature: `f2305597971dd93d6bc88ee0ab6656170ae69f820c38546f97c7b9aa972503da`
Recommendation apartments: `defer`
Recommendation houses: `limited_pilot`
Recommendation geography: `defer`
Recommendation land: `defer`

## Universe

| Metric | Value |
| --- | ---: |
| `active_listings` | 2780 |
| `benchmark_cases` | 2778 |
| `potential_training_rows_minimal` | 1533 |
| `canonical_price_usable` | 1534 |
| `apartment_rows` | 1487 |
| `house_rows` | 1293 |
| `house_with_land_rows` | 74 |
| `house_without_land_rows` | 1219 |

## Feature Coverage

### apartment

| Feature | Valid % | Valid | Total |
| --- | ---: | ---: | ---: |
| `canonical_price_clp` | 36.25 | 539 | 1487 |
| `price_uf_real` | 18.7 | 278 | 1487 |
| `property_type` | 100.0 | 1487 | 1487 |
| `comuna` | 100.0 | 1487 | 1487 |
| `built_area_m2` | 100.0 | 1487 | 1487 |
| `usable_area_m2` | 100.0 | 1487 | 1487 |
| `land_area_m2` | 0.0 | 0 | 1487 |
| `effective_area` | 100.0 | 1487 | 1487 |
| `land_building_ratio` | 0.0 | 0 | 1487 |
| `bedrooms` | 100.0 | 1487 | 1487 |
| `bathrooms` | 100.0 | 1487 | 1487 |
| `parking` | 100.0 | 1487 | 1487 |
| `scraped_at` | 100.0 | 1487 | 1487 |
| `lat_lon` | 8.07 | 120 | 1487 |
| `geocode_address` | 1.55 | 23 | 1487 |
| `geocode_street` | 41.83 | 622 | 1487 |
| `useful_geocode` | 49.23 | 732 | 1487 |
| `microzone` | 19.3 | 287 | 1487 |
| `product_classification` | 100.0 | 1487 | 1487 |

### house

| Feature | Valid % | Valid | Total |
| --- | ---: | ---: | ---: |
| `canonical_price_clp` | 76.95 | 995 | 1293 |
| `price_uf_real` | 15.55 | 201 | 1293 |
| `property_type` | 100.0 | 1293 | 1293 |
| `comuna` | 100.0 | 1293 | 1293 |
| `built_area_m2` | 99.85 | 1291 | 1293 |
| `usable_area_m2` | 0.15 | 2 | 1293 |
| `land_area_m2` | 5.72 | 74 | 1293 |
| `effective_area` | 99.85 | 1291 | 1293 |
| `land_building_ratio` | 5.57 | 72 | 1293 |
| `bedrooms` | 100.0 | 1293 | 1293 |
| `bathrooms` | 100.0 | 1293 | 1293 |
| `parking` | 100.0 | 1293 | 1293 |
| `scraped_at` | 100.0 | 1293 | 1293 |
| `lat_lon` | 0.62 | 8 | 1293 |
| `geocode_address` | 0.0 | 0 | 1293 |
| `geocode_street` | 50.27 | 650 | 1293 |
| `useful_geocode` | 50.27 | 650 | 1293 |
| `microzone` | 18.64 | 241 | 1293 |
| `product_classification` | 100.0 | 1293 | 1293 |

## Joint Eligibility

| Spec | Eligible | Coverage | Communes | Can split |
| --- | ---: | ---: | ---: | --- |
| `apartment_H0_min_structural` | 539 | 36.25 | 17 | True |
| `apartment_H1_basic` | 539 | 36.25 | 17 | True |
| `apartment_H2_expanded` | 277 | 18.63 | 17 | True |
| `apartment_H3_fine_geo` | 254 | 17.08 | 15 | True |
| `house_H0_min_structural` | 994 | 76.88 | 18 | True |
| `house_H1_basic` | 994 | 76.88 | 18 | True |
| `house_H2_land` | 68 | 5.26 | 13 | False |
| `house_H3_land_geo` | 59 | 4.56 | 13 | False |
| `house_H4_product` | 59 | 4.56 | 13 | False |

## Improvement Ceiling

### comparables_canonical

| Spec | Eligible % | Current/elegible MAPE | Base 20 pp gain | Unrealistic upper gain |
| --- | ---: | ---: | ---: | ---: |
| `apartment_H0_min_structural` | 20.46 | 22.79 / 18.26 | 0.75 | 3.74 |
| `apartment_H1_basic` | 20.46 | 22.79 / 18.26 | 0.75 | 3.74 |
| `apartment_H2_expanded` | 10.46 | 22.79 / 19.35 | 0.41 | 2.03 |
| `apartment_H3_fine_geo` | 9.61 | 22.79 / 19.27 | 0.37 | 1.85 |
| `house_H0_min_structural` | 32.33 | 22.79 / 30.91 | 2.0 | 9.99 |
| `house_H1_basic` | 32.33 | 22.79 / 30.91 | 2.0 | 9.99 |
| `house_H2_land` | 1.57 | 22.79 / 22.63 | 0.07 | 0.36 |
| `house_H3_land_geo` | 1.4 | 22.79 / 22.15 | 0.06 | 0.31 |
| `house_H4_product` | 1.4 | 22.79 / 22.15 | 0.06 | 0.31 |

### comparables_canonical_outliers

| Spec | Eligible % | Current/elegible MAPE | Base 20 pp gain | Unrealistic upper gain |
| --- | ---: | ---: | ---: | ---: |
| `apartment_H0_min_structural` | 19.35 | 23.65 / 18.41 | 0.71 | 3.56 |
| `apartment_H1_basic` | 19.35 | 23.65 / 18.41 | 0.71 | 3.56 |
| `apartment_H2_expanded` | 9.89 | 23.65 / 19.55 | 0.38 | 1.93 |
| `apartment_H3_fine_geo` | 9.11 | 23.65 / 19.49 | 0.35 | 1.77 |
| `house_H0_min_structural` | 35.87 | 23.65 / 31.9 | 2.28 | 11.44 |
| `house_H1_basic` | 35.87 | 23.65 / 31.9 | 2.28 | 11.44 |
| `house_H2_land` | 2.52 | 23.65 / 23.23 | 0.11 | 0.58 |
| `house_H3_land_geo` | 2.17 | 23.65 / 23.28 | 0.1 | 0.5 |
| `house_H4_product` | 2.17 | 23.65 / 23.28 | 0.1 | 0.5 |

### comparables_legacy

| Spec | Eligible % | Current/elegible MAPE | Base 20 pp gain | Unrealistic upper gain |
| --- | ---: | ---: | ---: | ---: |
| `apartment_H0_min_structural` | 19.54 | 24.82 / 19.97 | 0.78 | 3.9 |
| `apartment_H1_basic` | 19.54 | 24.82 / 19.97 | 0.78 | 3.9 |
| `apartment_H2_expanded` | 9.99 | 24.82 / 21.21 | 0.43 | 2.12 |
| `apartment_H3_fine_geo` | 9.28 | 24.82 / 21.12 | 0.39 | 1.96 |
| `house_H0_min_structural` | 35.29 | 24.82 / 35.27 | 2.49 | 12.45 |
| `house_H1_basic` | 35.29 | 24.82 / 35.27 | 2.49 | 12.45 |
| `house_H2_land` | 2.51 | 24.82 / 24.06 | 0.12 | 0.61 |
| `house_H3_land_geo` | 2.17 | 24.82 / 23.87 | 0.11 | 0.52 |
| `house_H4_product` | 2.17 | 24.82 / 23.87 | 0.11 | 0.52 |

## Roadmap

| Item | Current | Target | Priority |
| --- | ---: | ---: | --- |
| house_land_area_m2 | 5.72 | 70.0 | high |
| house_microzone | 18.64 | 50.0 | high |
| useful_geocode | 50.27 | 60.0 | medium |
| product_classification | 100.0 | 90.0 | low |