# Phase 3 Model Strategy Audit

## Preflight

- Branch: `codex/phase3-ml-house-consensus-strategy`
- HEAD: `0f2317d07a77fd74dc5f1d0ced5ee9bd5b990a47`
- Dataset signature: `f2305597971dd93d6bc88ee0ab6656170ae69f820c38546f97c7b9aa972503da`
- Git status: `clean`
- Real engines: `comparables_canonical, comparables_canonical_outliers, comparables_canonical_price_only, comparables_canonical_product, comparables_legacy`
- Future engines not registered: `hedonic, ml, house_land_building, valoria_consensus`
- Consensus skeleton: `contract_connected_but_not_operationally_ready`

## Consolidated Evidence

- Main practical challenger: `comparables_canonical_outliers`
- Phase 1 dataset signature: `56460740a7619d1fc3d9eb5add54e118a5978ecaa19a817a8846577fdea02fc8`
- Phase 2 dataset signature: `f2305597971dd93d6bc88ee0ab6656170ae69f820c38546f97c7b9aa972503da`

## ML Eligibility

| Level | Global obs | Global coverage | House obs | Apartment obs | Can split |
| --- | ---: | ---: | ---: | ---: | --- |
| `ML0_basic` | 1533 | 55.14% | 994 | 539 | True |
| `ML1_physical` | 1533 | 55.14% | 994 | 539 | True |
| `ML2_geo` | 819 | 29.46% | 536 | 283 | True |
| `ML3_house_enriched` | 994 | 35.76% | 994 | 0 | True |
| `ML4_full` | 42 | 1.51% | 42 | 0 | False |

## ML Improvement Ceiling

| Reference | Level | Eligible share | Current eligible MAPE | Base 20pp gain | Upper bound gain |
| --- | --- | ---: | ---: | ---: | ---: |
| `comparables_legacy` | `ML0_basic` | 54.83% | 29.82 | 3.27 | 16.35 |
| `comparables_legacy` | `ML1_physical` | 54.83% | 29.82 | 3.27 | 16.35 |
| `comparables_legacy` | `ML2_geo` | 29.45% | 31.57 | 1.86 | 9.3 |
| `comparables_legacy` | `ML3_house_enriched` | 35.29% | 35.27 | 2.49 | 12.45 |
| `comparables_legacy` | `ML4_full` | 1.57% | 26.55 | 0.09 | 0.42 |
| `comparables_canonical_outliers` | `ML0_basic` | 55.22% | 27.17 | 3.0 | 15.0 |
| `comparables_canonical_outliers` | `ML1_physical` | 55.22% | 27.17 | 3.0 | 15.0 |
| `comparables_canonical_outliers` | `ML2_geo` | 29.55% | 28.4 | 1.67 | 8.38 |
| `comparables_canonical_outliers` | `ML3_house_enriched` | 35.87% | 31.9 | 2.29 | 11.44 |
| `comparables_canonical_outliers` | `ML4_full` | 1.59% | 25.65 | 0.08 | 0.41 |

## House Land Building

- Houses with land: `74` (5.72%).
- Communes with >=10 land observations: `2`.
- Decision: `defer`.

## Consensus

- Imports real EngineResult: `True`
- Imports real EngineContext: `True`
- Registered: `False`
- Status: `contract_connected_but_not_operationally_ready`
- Decision: `defer`

## Decisions

- ML: `limited_pilot`
- house_land_building: `defer`
- valoria_consensus: `defer`

## Roadmap

1. `B` Stabilize canonical_plus_outliers as a practical challenger variant - impact `high`, risk `low`.
2. `C` Improve data before heavier new engines: land_area, microzone, geocode, apartment canonical target - impact `high`, risk `medium`.
3. `A` Implement hedonic_house_minimal as a limited offline pilot before full ML - impact `medium`, risk `medium`.
4. `D` Run ML as laboratory only after a clean validation plan - impact `medium`, risk `high`.
5. `E` Defer house_land_building - impact `low now`, risk `high`.
6. `F` Rewrite valoria_consensus after 2-3 real engines exist - impact `future high`, risk `medium`.

## Tests

| Command | Passed | Failed | Errors | Skipped |
| --- | ---: | ---: | ---: | ---: |
| `pytest tests/unit/test_model_strategy_audit.py tests/unit/test_hedonic_coverage_audit.py tests/unit/test_valuation_evaluation_framework.py tests/unit/test_evaluate_valuation_engines_cli.py` | 16 | 0 | 0 | 0 |
| `pytest tests/unit/test_valuation_engine_registry.py tests/unit/test_comparables_canonical_engine.py tests/unit/test_comparables_legacy_engine.py` | 17 | 0 | 0 | 0 |
| `pytest tests/unit/test_valuation.py tests/unit/test_valuation_service.py tests/unit/test_valuation_reliability.py tests/unit/test_comparable_quality.py tests/unit/test_comparable_metrics.py tests/unit/test_price_surface.py tests/unit/test_valuation_canonical_mode.py tests/unit/test_valuation_canonical_price.py` | 89 | 0 | 0 | 0 |
| `pytest tests/unit` | 980 | 2 | 7 | 0 |

## Guardrails

- `db_modified`: `False`
- `migrations_created_or_executed`: `False`
- `models_trained`: `False`
- `model_artifacts_created`: `False`
- `ml_registered`: `False`
- `house_land_building_registered`: `False`
- `valoria_consensus_registered`: `False`
- `base_engines_modified`: `False`
- `production_changed`: `False`
- `remote_configured`: `False`
- `push_performed`: `False`
