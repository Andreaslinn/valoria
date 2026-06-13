# Phase 1 Canonical Comparables Report

## Preflight and Baseline

Base Fase 0B verificada en `9135fe34f218ac4a2adead5b8da98932d4ffa3ef`.
Se creo rama `codex/phase1-comparables-canonical-quick-win`.

Piezas encontradas:

- `.git`
- `domain/valuation/engines/contracts.py`
- `domain/valuation/engines/registry.py`
- `domain/valuation/engines/legacy_comparables.py`
- `domain/valuation/evaluation/`
- `scripts/evaluate_valuation_engines.py`
- tests de paridad legacy
- benchmark Fase 0B

Baseline reproducida:

```powershell
python scripts/evaluate_valuation_engines.py --engines comparables_legacy --output-dir reports/valuation_engine_benchmark/phase1_baseline
```

Firma estable del dataset: `56460740a7619d1fc3d9eb5add54e118a5978ecaa19a817a8846577fdea02fc8`

Baseline legacy: 2740 casos, 2636 exitosos, cobertura 96.20%, MAPE 24.72%, mediana 17.00%, P90 54.13%. En casas: MAPE 33.45%, mediana 23.70%, P90 72.17%.

## Design

Motor nuevo offline:

- name: `comparables_canonical`
- version: `phase1_canonical_v1`
- archivo: `domain/valuation/engines/canonical_comparables.py`
- registrado en registry offline
- no conectado a `ValuationService`

Componentes:

- `domain/valuation/product_classification.py`
- `domain/valuation/robust_price_m2.py`

El motor reutiliza scoring, reliability, comparable quality, beta scope y price surface sin modificar el legacy. La diferencia esta antes del promedio: precio canonico estricto, exclusion por producto y filtro robusto de price/m2.

## Product Classification

Clases:

- `standard_residential`
- `land_or_site`
- `demolition_candidate`
- `needs_remodeling`
- `commercial_use`
- `investment_or_income`
- `multi_unit`
- `unknown`

La clasificacion normaliza minusculas y acentos, conserva evidencias y evita convertir una casa en sitio por menciones ambiguas como "amplio terreno". Si el target no tiene texto, queda como `unknown`; en ese caso se excluyen candidatos con evidencia fuerte de producto especial.

## Robust Price/M2 Filter

Configuracion v1:

- IQR con minimo 8 muestras
- percentiles conservadores con minimo 5 muestras
- `iqr_multiplier = 2.0`
- fallback relajado `2.75`
- cola alta casas: `median * 1.85`
- sin filtro duro si la muestra es demasiado pequena

El filtro usa solo la distribucion de candidatos elegibles. No usa precio real del target, signo del error ni informacion del holdout.

## Ablation Study

Comando:

```powershell
python scripts/evaluate_valuation_engines.py --engines comparables_canonical_price_only,comparables_canonical_product,comparables_canonical_outliers,comparables_canonical --output-dir reports/valuation_engine_benchmark/phase1_canonical_ablation
```

| Variante | Cobertura casas | MAPE casas | Mediana | P90 | Error >50 | Error >100 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Canonical price only | 93.61% | 32.86% | 23.98% | 71.49% | 19.12% | 4.97% |
| Canonical + producto | 79.73% | 32.09% | 23.63% | 68.61% | 17.71% | 4.55% |
| Canonical + outliers | 93.22% | 30.81% | 23.12% | 64.32% | 16.75% | 3.38% |
| Canonical full | 78.94% | 29.88% | 22.56% | 60.15% | 14.79% | 3.30% |

Lectura: el filtro robusto explica la mayor parte del quick win con perdida menor de cobertura. El filtro de producto mejora la cola, pero hoy es el principal causante de perdida de cobertura.

## Tests

Pasaron:

```powershell
pytest tests/unit/test_valuation_evaluation_framework.py tests/unit/test_product_classification.py tests/unit/test_robust_price_m2.py tests/unit/test_comparables_canonical_engine.py tests/unit/test_valuation_engine_registry.py
```

Resultado: 23 passed.

```powershell
pytest tests/unit/test_product_classification.py tests/unit/test_robust_price_m2.py tests/unit/test_comparables_canonical_engine.py tests/unit/test_valuation_engine_registry.py tests/unit/test_valuation_evaluation_framework.py tests/unit/test_evaluate_valuation_engines_cli.py
```

Resultado: 23 passed.

```powershell
pytest tests/unit/test_valuation.py tests/unit/test_valuation_service.py tests/unit/test_valuation_reliability.py tests/unit/test_comparable_quality.py tests/unit/test_comparable_metrics.py tests/unit/test_price_surface.py tests/unit/test_valuation_canonical_mode.py tests/unit/test_valuation_canonical_price.py tests/unit/test_comparables_legacy_engine.py
```

Resultado: 95 passed.

Suite completa:

```powershell
pytest tests/unit
```

Resultado: 968 passed, 2 failed, 7 errors. Los 2 fallos de Nominatim y los 7 errores de permisos `tmp_path` son preexistentes y no relacionados con esta fase.

## Benchmark Legacy vs Canonical

Comando:

```powershell
python scripts/evaluate_valuation_engines.py --engines comparables_legacy,comparables_canonical --output-dir reports/valuation_engine_benchmark/phase1_canonical
```

Firma del dataset: `56460740a7619d1fc3d9eb5add54e118a5978ecaa19a817a8846577fdea02fc8`

| Segmento | Motor | Cobertura | MAPE | Mediana | P90 |
| --- | --- | ---: | ---: | ---: | ---: |
| Global | legacy | 96.20% | 24.72% | 17.00% | 54.13% |
| Global | canonical | 85.26% | 22.71% | 16.99% | 47.38% |
| Departamentos | legacy | 97.28% | 17.38% | 12.88% | 36.73% |
| Departamentos | canonical | 90.69% | 17.33% | 13.79% | 36.00% |
| Casas | legacy | 94.95% | 33.45% | 23.70% | 72.17% |
| Casas | canonical | 78.94% | 29.88% | 22.56% | 60.15% |
| Casas con terreno | legacy | 97.75% | 25.70% | 17.35% | 50.39% |
| Casas con terreno | canonical | 57.30% | 24.05% | 14.46% | 48.03% |
| Casas sin terreno | legacy | 94.74% | 34.05% | 24.28% | 74.58% |
| Casas sin terreno | canonical | 80.58% | 30.19% | 22.73% | 60.51% |

Interseccion donde ambos motores valoran: 2336 casos. En esa interseccion, legacy MAPE 23.59% y canonical MAPE 22.71%; P90 baja de 51.39% a 47.38%.

## Quick Win

Casas:

- mejora MAPE: 33.45% - 29.88% = 3.57 pp
- captura de hipotesis 2 pp: 178.5%
- cambio cobertura: -16.01 pp
- cambio P90: -12.02 pp
- cambio sobrevaloracion: -5.96 pp
- cambio error >50%: -5.64 pp
- cambio error >100%: -1.85 pp

## Large Error Diagnosis

En casas, canonical full:

- corrigio 60 casos que legacy tenia con error >50% y canonical dejo <=50%
- empeoro 18 casos que legacy tenia <=50% y canonical llevo >50%
- mejoro 182 casas por al menos 10 pp de APE
- empeoro 119 casas por al menos 10 pp de APE
- excluyo 1200 comparables de cola alta price/m2 en ejecuciones de casas
- cuando hubo outlier alto, la estimacion bajo 7.56% promedio

Principales exclusiones acumuladas en casas:

- `legacy_unrecoverable`: 9234
- `product_incompatible`: 4586
- `price_m2_high_outlier`: 1200
- `price_m2_low_outlier`: 175
- `land_outside_tolerance`: 97

Todos los errores canonical de casas fueron `insufficient_data`: 267 casos.

## Git

Commits de Fase 1:

- `32feb18 feat: add deterministic property product classification`
- `0728176 feat: add canonical comparable selection and robust filtering`
- `34ecfb6 test: cover canonical comparable engine`
- `cb4308e fix: preserve uf artifact guardrail in canonical engine`
- `c854faf fix: stabilize valuation evaluation dataset order`

## Recommendation

`mixed`

Canonical full mejora claramente MAPE, P90, sesgo y errores extremos en casas, y captura mas que los 2 pp esperados. Pero la perdida de cobertura es material: casas bajan de 94.95% a 78.94%, y casas con terreno de 97.75% a 57.30%. No debe activarse en produccion.

La opcion mas prometedora para una Fase 1B es partir desde `canonical_plus_outliers`: logra MAPE casas 30.81% con cobertura 93.22%, capturando gran parte del beneficio sin el costo fuerte del filtro de producto.

## Guardrails

- No se modifico la DB.
- No se crearon ni ejecutaron migraciones.
- No se cambio produccion.
- No se modifico `comparables_legacy`.
- No se conecto canonical al servicio productivo.
- No se uso el precio real del target en seleccion.
- No se implementaron otros motores.
- No se configuro remoto.
- No se hizo push.
