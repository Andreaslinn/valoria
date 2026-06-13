# Phase 5A Data Enrichment Audit

## Phase 4A Closure

Commits: `0154ff3 feat: stabilize canonical outliers valuation engine, bb1aa48 test: cover canonical outliers variant, 98e3b05 docs: add phase4a canonical outliers benchmark report`
Tests: `16 passed, 35 passed`
Clean before Phase 5A: `True`

## Phase 5A Preflight

Branch: `codex/phase5a-data-quality-enrichment-audit`
HEAD: `249e6d0a857cb06be69ad1597e89fc082f195893`
Database mode: `select_only_session_with_explicit_rollback`
External requests: `0`

Dataset signature: `c65a72673d729bc4c27da8be53a8891bd3c41496b8b79042e7aab0935ef24c20`
Total listings: `3218`
Active listings: `2780`
Benchmark cases: `2778`

## Coverage

| Segment | Total | Built | Land | Canonical price | Useful geocode | Microzone |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `house` | 1293 | 99.85 | 5.72 | 76.95 | 50.27 | 18.33 |
| `apartment` | 1487 | 100.0 | 0.0 | 36.25 | 44.52 | 19.23 |

## Land Area

| Category | Count |
| --- | ---: |
| `inconsistent_area_fields` | 6 |
| `land_mentioned_without_value` | 47 |
| `not_in_available_publication_text` | 567 |
| `present` | 74 |
| `refresh_candidate` | 565 |
| `text_recoverable` | 28 |
| `text_recoverable_thousands_normalized` | 6 |

Recoverable or candidate: `599` (46.33%).

Recovery tiers:

- `current_count`: `74`
- `current_pct`: `5.72`
- `direct_high_confidence_count`: `34`
- `direct_high_confidence_potential_pct`: `8.35`
- `refresh_candidate_count`: `565`
- `refresh_theoretical_ceiling_pct`: `52.05`
- `warning`: `refresh candidates are not guaranteed recoveries; sample yield must be measured before any apply`

## Geocoding

| Category | Count |
| --- | ---: |
| `already_reliable` | 1312 |
| `commune_only` | 1370 |
| `coordinates_low_precision` | 70 |
| `recoverable_geo_signal` | 18 |
| `recoverable_title_street` | 10 |

Recoverable or candidate: `28` (1.01%).

## Microzone

| Category | Count |
| --- | ---: |
| `current` | 480 |
| `no_current_signal` | 2245 |
| `potential_from_description` | 5 |
| `potential_from_metadata` | 26 |
| `potential_from_title` | 24 |

Recoverable or candidate: `55` (1.98%).

## Canonical Price Apartments

| Category | Count |
| --- | ---: |
| `estimated_low_confidence` | 2 |
| `legacy_unrecoverable_refresh_candidate` | 946 |
| `usable_clp_converted` | 210 |
| `usable_native_uf` | 329 |

Recoverable or candidate: `946` (63.62%).

Recovery tiers:

- `current_count`: `539`
- `current_pct`: `36.25`
- `refresh_candidate_count`: `946`
- `refresh_theoretical_ceiling_pct`: `99.87`
- `recoveries_needed_for_60_pct`: `354`
- `required_refresh_yield_pct`: `37.42`
- `warning`: `legacy UF recovery requires fresh source evidence; old CLP snapshots must not be reverse-engineered with UF 37000`

## Source Audit

- `yapo_card_parser`: card data is structurally sparse; detail parser is the main source for land area, description and native UF
- `yapo_detail_parser`: supports structured built/usable/total area labels, land text patterns and thousands separators
- `portal_parser`: card parser exposes basic attributes but no equivalent detail enrichment path in the audited module
- `refresh_scraper`: --dry-run selects and reports candidates without fetching URLs; non-dry-run performs external requests and writes, so it was not executed
- `geocoding`: existing CLI supports --dry-run --no-external; title-inferred apply requires an explicit opt-in
- `microzones`: mappers enrich microzone signals in memory on read; persisted metadata and operational derived coverage must be distinguished
- `canonical_price`: native strong UF and CLP converted with a real inferred UF are usable; weak, fallback and legacy-unrecoverable UF are excluded
- `deduplication`: fingerprint is source-agnostic for complete listings and excludes price; ORM also enforces unique fingerprint and source/external_id
- `dates`: scraped_at and last_seen_at exist, but original publication date is absent in current metadata

## Product Classification

| Class | Count |
| --- | ---: |
| `commercial_use` | 65 |
| `investment_or_income` | 41 |
| `land_or_site` | 85 |
| `multi_unit` | 20 |
| `needs_remodeling` | 29 |
| `standard_residential` | 2540 |

Unknown: `0`. Strong special: `107`.
Potential false-positive risks: `{'apartment_bodega_storage_ambiguity': 22, 'weak_investment_language': 35, 'weak_land_context': 81}`.

## Duplicates And Leakage

Affected listings: `79` (2.84%).
Near duplicate groups: `35`.
Benchmark leakage risk: `medium`.

## Quick Wins

| Field | Current % | Potential % | Risk | Difficulty |
| --- | ---: | ---: | --- | --- |
| `land_area_m2` | 5.72 | 8.35 | low | medium |
| `geocode_precision` | 47.19 | 48.2 | medium | medium |
| `microzone` | 18.81 | 20.79 | medium | low |
| `canonical_price_apartment` | 36.25 | 60.05 | high | medium |
| `duplicate_diagnostics` | 0.0 | 0.0 | low | low |

## Enrichment Phases

- `D1_report_only`: land parser opportunity report, canonical price provenance report, duplicate candidate report; apply=`False`
- `D2_cache_only`: geocoding cache-only validation, microzone extraction corpus validation, refresh candidate sampling; apply=`False`
- `D3_limited_backfill_candidate`: review high-confidence land and canonical price candidates, define rollback and acceptance thresholds; apply=`False`
- `D4_future_controlled_apply`: separate approved implementation after benchmark gate; apply=`not_in_phase5a`

## Future Dry-run Commands

- `python scripts/audit_data_enrichment_opportunities.py --output-dir reports/data_quality/phase5a --no-external-requests --examples 50`
- `python scripts/geocode_listings.py --dry-run --no-external --limit 100 --examples 25`
- `python scripts/refresh_scraper.py --dry-run --limit 100`
- `python scripts/preview_property_type_backfill.py --changed-only --summary-only`

## Expected Engine Impact

- `comparables_legacy`: better candidate geography and house land completeness; no guaranteed MAPE change
- `comparables_canonical`: higher canonical/product/geographic coverage and fewer insufficient-data outcomes
- `comparables_canonical_outliers`: same robust logic with denser, cleaner candidate pools
- `hedonic_house_minimal`: larger usable sample and missingness reduction
- `ml_lab`: better feature coverage and lower duplicate leakage risk
- `house_land_building_future`: land_area and local geography are hard prerequisites
- `consensus_future`: more comparable coverage and better segment calibration inputs

## Date Coverage

- `scraped_at`: `{'valid_count': 2780, 'total': 2780, 'valid_pct': 100.0}`
- `last_seen_at`: `{'valid_count': 2780, 'total': 2780, 'valid_pct': 100.0}`
- `publication_date_metadata`: `{'valid_count': 0, 'total': 2780, 'valid_pct': 0.0}`
- `temporal_evaluation_note`: `scraped_at is an observation timestamp, not necessarily the original publication date`

## Tests

| Scope | Result | Command |
| --- | --- | --- |
| `new` | `9 passed` | `python -m pytest tests/unit/test_data_enrichment_audit.py` |
| `parser_refresh` | `91 passed` | `python -m pytest tests/unit/test_yapo_parser.py tests/unit/test_portal_parser.py tests/unit/test_refresh_scraper_cli.py tests/unit/test_scraper_base.py` |
| `geocoding_microzones` | `40 passed` | `python -m pytest tests/unit/test_geocoding_readiness_audit.py tests/unit/test_geographic_microzones.py tests/unit/test_microzones.py tests/unit/test_geocoding_quality.py tests/unit/test_geocode_precision_normalization.py tests/unit/test_diagnose_geocoding_quality.py` |
| `canonical_price` | `16 passed` | `python -m pytest tests/unit/test_valuation_canonical_price.py tests/unit/test_product_classification.py tests/unit/test_robust_price_m2.py` |
| `engines_evaluation_legacy` | `62 passed` | `python -m pytest tests/unit/test_valuation_evaluation_framework.py tests/unit/test_evaluate_valuation_engines_cli.py tests/unit/test_comparables_legacy_engine.py tests/unit/test_comparables_canonical_engine.py tests/unit/test_valuation_engine_registry.py tests/unit/test_valuation.py tests/unit/test_valuation_service.py` |

Failed: `0`. Skipped: `0`.

## Guardrails

- `read_only`: `True`
- `database_writes`: `0`
- `external_requests`: `0`
- `apply_mode`: `False`
- `uf_37000_operational`: `False`
