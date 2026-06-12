# Phase 0B Rebuild Report

Fecha: 2026-06-12  
Proyecto: `C:\Users\heiko\Downloads\AVM v3\Andy\AVM-v2`  
Rama de trabajo: `codex/rebuild-valuation-engines-phase0b`  
Estado: reconstruccion minima completada con bloqueos residuales documentados

## 1. Estado Inicial Y Respaldo

- `.git` estaba ausente al inicio.
- Tamano aproximado del checkout: 60.415 archivos, 1,69 GB contando venvs, caches, reportes y temporales.
- `.env` existe y quedo ignorado; no se leyeron valores de secretos.
- `.env.example` quedo versionado.
- DBs locales, SQL backups, venvs, caches, logs, releases, zips y reportes historicos quedaron ignorados.
- Inventario inicial:
  - `reports/valuation_engine_rebuild/phase0b_initial_inventory.md`
  - `reports/valuation_engine_rebuild/phase0b_initial_inventory.json`
- Respaldo no destructivo:
  - `reports/valuation_engine_rebuild/backups/phase0b_source_snapshot_20260612.zip`
  - SHA256: `FFF472453B0925C0A1CAE190DAA3014E19535AB1E7085AA44F3FD13A5EE3FD2A`
  - El backup esta ignorado por Git.

## 2. Inicializacion De Git

- Repositorio local Git inicializado en `main`.
- No se configuro remoto.
- Commit baseline:
  - `6a4e8e3 chore: establish recovered AVM-v2 baseline`
- Rama de trabajo creada:
  - `codex/rebuild-valuation-engines-phase0b`

Commits de trabajo:

- `f2fc541 feat: add minimal valuation engine registry and legacy wrapper`
- `3aa0966 feat: add offline valuation engine evaluation CLI`
- `14bf144 test: cover phase0b legacy engine evaluation`

## 3. Arquitectura Multimotor Creada

Contratos oficiales:

- `domain/valuation/engines/contracts.py`
  - `EngineRequest`
  - `EngineContext`
  - `EngineComparable`
  - `EngineResult`
  - `EngineStatus`
  - `ValuationEngine`

Registry:

- `domain/valuation/engines/registry.py`
  - `EngineRegistry.register`
  - `EngineRegistry.get`
  - `EngineRegistry.list`
  - `DuplicateValuationEngineError`
  - `UnknownValuationEngineError`
  - `default_engine_registry`

Motor registrado:

- `comparables_legacy`
- Version: `phase0b_legacy_v1`
- Implementacion: `domain/valuation/engines/legacy_comparables.py`

El servicio productivo no fue migrado al registry. La integracion queda offline para evaluacion.

## 4. Esqueleto Desconectado

Se conservaron los archivos previos de `valoria_consensus`, pero no se usaron como fuente de verdad ni se registraron.

Decision:

- conservar sin activar;
- documentar como experimental/deprecated;
- no importar desde `default_engine_registry`;
- mantener una sola definicion oficial de `EngineResult`, `EngineContext`, `ValuationEngine` y registry.

Documento agregado:

- `domain/valuation/engines/valoria_consensus/README.md`

## 5. Paridad De `comparables_legacy`

El wrapper delega en:

- `domain.valuation.comparables.valuate_with_comparables`
- `domain.valuation.price_surface.lookup_price_surface`
- `domain.valuation.price_surface.maybe_apply_surface_adjustment`
- `core.assessment.confidence.build_confidence_contract`
- `core.assessment.beta_status.beta_scope_warning_codes`

No se reescribieron filtros, scoring, pesos, tolerancias, canonical price, reliability, comparable quality, beta scope ni price surface.

Tests de paridad:

- departamento homogeneo;
- casa con terreno;
- casa sin terreno;
- insuficiencia de comparables;
- passthrough de canonical mode;
- confirmacion de que `ValuationService` sigue levantando `InsufficientDataError`.

Campos comparados:

- precio CLP;
- rango CLP;
- confidence score;
- cantidad de comparables;
- orden de comparables;
- warnings;
- comparable quality;
- beta scope;
- price surface.

Resultado dirigido: `15 passed`.

## 6. Framework De Evaluacion

Framework creado:

- `domain/valuation/evaluation/dataset.py`
- `domain/valuation/evaluation/evaluator.py`
- `domain/valuation/evaluation/metrics.py`
- `domain/valuation/evaluation/reports.py`

CLI creada:

- `scripts/evaluate_valuation_engines.py`

CLI minima:

```powershell
python scripts/evaluate_valuation_engines.py --engines comparables_legacy --output-dir reports/valuation_engine_benchmark/phase0b_legacy
```

Reglas:

- usa listings activos;
- excluye target;
- excluye duplicados evidentes por fingerprint, source/external_id y URL;
- filtra precio CLP positivo;
- filtra superficie positiva;
- permite `--limit`, `--property-type`, `--seed`, `--cutoff`, `--dry-run`;
- infiere UF desde `price_uf` local o acepta `--uf-rate`;
- valida que UF no sea fallback ni tasa artefacto 37.000.

Limitacion: benchmark activo, no backtest temporal completo salvo que se use `--cutoff`.

## 7. Tests Ejecutados

Dirigidos:

```powershell
pytest tests/unit/test_valuation_engine_registry.py tests/unit/test_comparables_legacy_engine.py tests/unit/test_valuation_evaluation_framework.py tests/unit/test_evaluate_valuation_engines_cli.py
```

Resultado: `15 passed`.

Suite legacy de valoracion:

```powershell
pytest tests/unit/test_valuation.py tests/unit/test_valuation_service.py tests/unit/test_valuation_reliability.py tests/unit/test_comparable_quality.py tests/unit/test_comparable_metrics.py tests/unit/test_price_surface.py tests/unit/test_valuation_canonical_mode.py tests/unit/test_valuation_canonical_price.py
```

Resultado: `89 passed`.

Suite unitaria amplia:

```powershell
pytest tests/unit
```

Resultado:

- `954 passed`
- `2 failed`
- `7 errors`

Fallos residuales no relacionados con Fase 0B:

- `tests/unit/test_nominatim_client.py::test_address_metadata_wins`
- `tests/unit/test_nominatim_client.py::test_address_fallback_selection`
- diferencia esperada por expansion `Av Grecia 100` -> `Avenida Grecia 100`.

Errores residuales de entorno:

- `tests/unit/test_create_release_zip.py` falla en setup de `tmp_path`;
- error: `PermissionError: [WinError 5] Acceso denegado: C:\Users\heiko\AppData\Local\Temp\pytest-of-heiko`.

## 8. Benchmark Real

Smoke:

```powershell
python scripts/evaluate_valuation_engines.py --engines comparables_legacy --output-dir reports/valuation_engine_benchmark/phase0b_legacy_smoke --limit 20
```

Resultado: reportes generados correctamente.

Completo:

```powershell
python scripts/evaluate_valuation_engines.py --engines comparables_legacy --output-dir reports/valuation_engine_benchmark/phase0b_legacy
```

Dataset:

- active listings: 2.742
- casos evaluables construidos: 2.740
- UF inferida desde datos locales: 40.644,55 CLP/UF

Metricas globales:

- total cases: 2.740
- successful: 2.636
- failed: 104
- coverage: 96,20%
- MAPE: 24,71%
- mediana APE: 17,01%
- P90 APE: 54,07%
- MAE CLP: 76.928.040,29
- signed bias: 9,75%
- error >50%: 11,68%
- error >100%: 2,62%

Departamentos:

- total: 1.472
- successful: 1.432
- coverage: 97,28%
- MAPE: 17,36%
- mediana APE: 12,95%
- P90 APE: 36,63%

Casas:

- total: 1.268
- successful: 1.204
- coverage: 94,95%
- MAPE: 33,45%
- mediana APE: 23,70%
- P90 APE: 71,83%

Casas con terreno:

- total: 89
- successful: 87
- MAPE: 25,53%
- mediana APE: 17,35%
- P90 APE: 50,39%

Casas sin terreno:

- total: 1.179
- successful: 1.117
- MAPE: 34,07%
- mediana APE: 24,28%
- P90 APE: 74,58%

Reportes generados:

- `reports/valuation_engine_benchmark/phase0b_legacy/valuation_engine_benchmark.json`
- `reports/valuation_engine_benchmark/phase0b_legacy/valuation_engine_benchmark.md`
- `reports/valuation_engine_benchmark/phase0b_legacy/valuation_engine_benchmark_rows.csv`

## 9. Archivos Creados Y Modificados

Creados:

- `domain/valuation/engines/legacy_comparables.py`
- `domain/valuation/engines/valoria_consensus/README.md`
- `domain/valuation/evaluation/__init__.py`
- `domain/valuation/evaluation/dataset.py`
- `domain/valuation/evaluation/evaluator.py`
- `domain/valuation/evaluation/metrics.py`
- `domain/valuation/evaluation/reports.py`
- `scripts/evaluate_valuation_engines.py`
- `tests/unit/test_comparables_legacy_engine.py`
- `tests/unit/test_evaluate_valuation_engines_cli.py`
- `tests/unit/test_valuation_evaluation_framework.py`
- `reports/valuation_engine_rebuild/phase0b_initial_inventory.md`
- `reports/valuation_engine_rebuild/phase0b_initial_inventory.json`
- benchmark reports bajo `reports/valuation_engine_benchmark/phase0b_legacy*`

Modificados:

- `.gitignore`
- `domain/valuation/engines/__init__.py`
- `domain/valuation/engines/contracts.py`
- `domain/valuation/engines/registry.py`
- `tests/unit/test_valuation_engine_registry.py`

## 10. Git Final

Estado antes de escribir este reporte:

- branch: `codex/rebuild-valuation-engines-phase0b`
- HEAD: `14bf144b2a0816070277279ce129de140cab0efe`
- remoto: ninguno

`git status --short --branch` solo reportaba la rama; Git emitio warnings de acceso denegado en directorios temporales ignorados.

## 11. Bloqueos Y Pendientes

Pendientes antes de activar en produccion:

1. Decidir si el servicio productivo debe usar registry o seguir directo.
2. Agregar `comparables_canonical` en Fase 1, no en esta fase.
3. Convertir benchmark activo en backtest temporal si hay fechas suficientes.
4. Resolver fallos no relacionados de `test_nominatim_client.py`.
5. Resolver permisos del temp global de pytest para `test_create_release_zip.py`.
6. Considerar no versionar filas completas de benchmark si el repo creciera demasiado.

Confirmaciones:

- no se modifico la DB;
- no se crearon ni ejecutaron migraciones;
- no se modificaron filtros, pesos ni formulas legacy;
- no se activo ningun motor nuevo en produccion;
- no se implemento `comparables_canonical`;
- no se uso el consenso desconectado como contrato;
- no se configuro remoto;
- no se hizo push.
