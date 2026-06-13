# Phase 5B Data Enrichment Dry-run Validation

## Preflight

- Branch: `codex/phase5b-data-enrichment-dry-run-validation`
- HEAD: `6e3cf04f813e5262dac4ad8c07ef346084f89d1d`
- Git status before generation: `clean`
- Phase 5A signature matches: `True`
- Database mode: `select_only_session_with_explicit_rollback`
- External requests: `0`

## Land Area Validation

- Recalculated: `34`
- Accepted: `25`
- Review: `9`
- Rejected: `0`
- Current coverage: `5.72%`
- Potential accepted coverage: `7.66%`
- Potential coverage including review cases: `8.35%`

## Land Mentions Without Numeric Value

- Cases: `47`
- Classifications: `{'opportunity_or_site_without_surface': 4, 'possible_special_product_classification': 7, 'real_land_attribute_without_surface': 27, 'requires_detail_refresh': 9}`
- No surface was inferred from a non-numeric mention.

## Surface Inconsistencies

- Cases: `6`
- Recommendations: `{'future_parser_correction': 6}`

## Microzone Validation

- Candidates: `55`
- Accepted: `25`
- Review: `1`
- Soft signal only: `29`
- Rejected: `0`
- Persistence recommendation: `persist_only_accepted_after_corpus_review; keep avenues and landmarks as soft signals`
- No microzone was persisted.

## Duplicates And Leakage

- Groups: `35`
- Affected listings: `79`
- Validated duplicate groups: `29`
- Validated affected listings: `67`
- Classifications: `{'near_duplicate_high_confidence': 5, 'not_duplicate': 6, 'possible_duplicate': 22, 'weak_duplicate': 2}`
- Proposal: `{'default_behavior': 'unchanged', 'future_flag': '--dedupe-diagnostics', 'target_rule': 'report whether target belongs to a validated duplicate group', 'candidate_rule': 'diagnose and optionally exclude copies of target in experimental runs', 'metrics': 'report benchmark metrics with and without validated high-confidence groups'}`

## Department Canonical Price Refresh Sample

- Requested sample: `50`
- Selected: `50`
- Comunas represented: `16`
- Price bands: `{'high': 11, 'low': 18, 'mid': 21}`
- Surface bands: `{'large_gt_90': 7, 'medium_50_90': 18, 'small_lt_50': 25}`
- UF metadata signals: `{'structured_currency_only': 50}`
- Limitation: `all eligible legacy candidates retain structured UF currency, but none in the selected sample retains local textual UF evidence`
- URLs were not visited.

## Phase 5C Plan

### land_area

- `{'apply_candidates': 25, 'review_candidates': 9, 'rejected_candidates': 0, 'expected_coverage_pct': 7.66, 'minimum_tests': 'candidate fixture corpus, parser provenance, idempotency, row-count and before/after snapshot', 'rollback': 'export listing_id and previous land_area_m2; one transaction; rollback on count/value mismatch', 'future_command': 'python scripts/backfill_house_area_corrections.py --manifest <approved.json> --limit <N> --dry-run', 'safety_limits': 'approved IDs only, one transaction, max rows equal manifest, no parser-wide apply'}`

### microzone

- `{'persist_candidates': 25, 'soft_or_review_candidates': 30, 'recommendation': 'prefer soft signals until a comuna-aware false-positive corpus passes', 'minimum_tests': 'known metro/intersection positives and avenue/marketing false positives', 'rollback': 'snapshot raw_metadata keys and restore only touched IDs in one transaction'}`

### duplicates

- `{'diagnostic_groups': 35, 'recommendation': 'add opt-in evaluator diagnostics before any exclusion behavior', 'measurement': 'same split and seed; compare metrics, coverage and extreme errors with/without high-confidence dedupe'}`

### department_price_refresh

- `{'pilot_recommended': True, 'pilot_size': 50, 'mode_order': 'cache-only/no-external first, then separately approved limited network pilot', 'stop_conditions': 'captcha/block, >10% parse errors, unexpected currency, missing real UF, or DB delta outside approved IDs', 'rollback': 'snapshot canonical price/provenance fields and price history; transactional apply in a separate phase', 'success_metric': 'valid strong canonical UF recovery rate >=37.42% with zero fallback UF and audited provenance'}`

## Tests

- `new`: `15 passed` - `python -m pytest tests/unit/test_data_enrichment_validation.py`
- `phase5a`: `9 passed` - `python -m pytest tests/unit/test_data_enrichment_audit.py`
- `parser_refresh`: `91 passed` - `python -m pytest tests/unit/test_yapo_parser.py tests/unit/test_portal_parser.py tests/unit/test_refresh_scraper_cli.py tests/unit/test_scraper_base.py`
- `geocoding_microzone`: `40 passed` - `python -m pytest tests/unit/test_geocoding_readiness_audit.py tests/unit/test_geographic_microzones.py tests/unit/test_microzones.py tests/unit/test_geocoding_quality.py tests/unit/test_geocode_precision_normalization.py tests/unit/test_diagnose_geocoding_quality.py`
- `canonical_price`: `16 passed` - `python -m pytest tests/unit/test_valuation_canonical_price.py tests/unit/test_product_classification.py tests/unit/test_robust_price_m2.py`
- `evaluation_engines`: `62 passed` - `python -m pytest tests/unit/test_valuation_evaluation_framework.py tests/unit/test_evaluate_valuation_engines_cli.py tests/unit/test_comparables_legacy_engine.py tests/unit/test_comparables_canonical_engine.py tests/unit/test_valuation_engine_registry.py tests/unit/test_valuation.py tests/unit/test_valuation_service.py`

## Git

- Branch: `codex/phase5b-data-enrichment-dry-run-validation`
- HEAD at report generation: `6e3cf04f813e5262dac4ad8c07ef346084f89d1d`
- Working tree before report generation: `clean`
- Recent commits: `['6e3cf04 fix: normalize phase5b csv text output', '95a3ba9 docs: add phase5b enrichment validation reports', 'd32d6dd fix: complete phase5b validation diagnostics', 'b4b9a7c test: cover phase5b enrichment validation', '8f708f9 feat: add phase5b enrichment candidate validation']`
- Configured remotes: `0`

## Guardrails

- `read_only`: `True`
- `database_writes`: `0`
- `external_requests`: `0`
- `apply_mode`: `False`
- `microzones_persisted`: `0`
- `land_area_updated`: `0`
- `duplicates_deleted`: `0`
- `uf_37000_operational`: `False`
- `benchmark_default_changed`: `False`
