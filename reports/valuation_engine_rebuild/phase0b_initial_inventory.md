# Phase 0B Initial Inventory

Fecha: 2026-06-12  
Proyecto: `C:\Users\heiko\Downloads\AVM v3\Andy\AVM-v2`  
Estado Git inicial: `.git` ausente  
Accion: reconstruccion controlada, no consolidacion de implementaciones previas

## Resumen

El checkout actual no es un repositorio Git. El proyecto contiene aproximadamente 60.415 archivos y 1,69 GB al contar `.venv`, `.venv-win`, caches, reportes y artefactos temporales. Antes de inicializar Git se identificaron secretos potenciales, bases locales, backups SQL, caches y reportes que deben quedar fuera del baseline salvo los reportes explicitamente solicitados para Fase 0B.

## Archivos De Entorno

- `.env` existe, 1.458 bytes. Debe excluirse de Git.
- `.env.example` existe, 3.899 bytes. Puede versionarse porque es plantilla.
- `.streamlit/secrets.toml` esta cubierto por `.gitignore` y debe seguir excluido.

No se leyeron ni se reportan valores de secretos.

## Bases, Backups Y SQL Local

Detectado:

- `.mypy_cache/3.11/cache.db`
- `.tmp/portal_inmobiliario_audit_20260605_110513/scripts/sql/scraper_reencounter_diagnostics.sql`
- `reports/refresh_yapo_manual_100_revert_uf_artifacts.sql`
- `scripts/sql/scraper_reencounter_diagnostics.sql`
- `backup_avm_before_geocode_precision_backfill.sql`
- `backup_avm_before_property_type_backfill.sql`

Politica: excluir DBs locales, backups SQL y SQL generado por auditorias si no son codigo fuente requerido.

## Caches Y Temporales

Directorios detectados que deben excluirse:

- `.mypy_cache/`
- `.pycache_compile/`
- `.pytest-basetemp*/`
- `.pytest-tmp/`
- `.pytest_cache/`
- `.pytest_tmp*/`
- `.ruff_cache/`
- `.tmp/`
- `.venv/`
- `.venv-win/`
- `__pycache__/`
- `logs/`
- `pytest_tmp*/`
- `releases/`
- `avm.egg-info/`

## Archivos Grandes

Los archivos grandes principales estan dentro de `.venv` y `.venv-win`, incluyendo binarios de `pyarrow`, `ruff`, `cryptography`, `numpy` y mapas JS de paquetes. Deben quedar excluidos.

Tambien existen backups SQL de aproximadamente 2,2 MB en la raiz. Deben excluirse como respaldo local, no como codigo fuente.

## Modulos Criticos De Valoracion

- `services/valuation.py`
- `domain/valuation/comparables.py`
- `domain/valuation/scoring.py`
- `domain/valuation/reliability.py`
- `domain/valuation/comparable_metrics.py`
- `domain/valuation/comparable_quality.py`
- `domain/valuation/price_surface.py`
- `domain/valuation/canonical_price.py`
- `domain/valuation/beta_scope.py`
- `core/entities/opportunity.py`
- `core/entities/listing.py`
- `infrastructure/db/repositories/listing_repo.py`
- `api/v1/valuations.py`

## Hashes SHA256 Criticos

| Archivo | SHA256 |
| --- | --- |
| `services/valuation.py` | `D35BBAF9F78A5E96EE7F3A1E72D942BEF5576C436B2C83A724208C11CCE4019D` |
| `domain/valuation/comparables.py` | `DFF3BF217BECC46977D3E0A91084CE345EB502363568B6703961A7D989882B09` |
| `domain/valuation/scoring.py` | `2246FD369E9240E7721BF52E264D064B716A8041BE19EE267FC332F546647B81` |
| `domain/valuation/reliability.py` | `6D91BDFBC834B0B8D6112C5B13FC3E9D1776D8501D9AD68F134266F565A9335D` |
| `domain/valuation/comparable_metrics.py` | `05182A13E40B2FE6235178E114579265D4AF5B89240472A116455C4251AA26B1` |
| `domain/valuation/comparable_quality.py` | `E83232EECC93D7404FB53EBF4C3E3B423EB3204723D02F997BD018660AC7D9AD` |
| `domain/valuation/price_surface.py` | `5D669100B3684612ED1FF7600A8028BC85D5A6B67E719CAF86EE9150024F71C8` |
| `domain/valuation/canonical_price.py` | `900603C7DA508E6ED2BB51759B04550A4320EA8AC3361A139F94A1C7A189CB79` |
| `domain/valuation/beta_scope.py` | `4A02C1E732D7028A27D96100BBB7267D6F7722DC4FC18DD5F8572448E964B80D` |
| `core/entities/opportunity.py` | `2195CC0CDEEABAFAF60C1950F1CD86E98916056B4ECABB0F8E1E8896407790A9` |

## Tests Actuales Relacionados

- `tests/unit/test_comparable_quality.py`
- `tests/unit/test_comparable_metrics.py`
- `tests/unit/test_evaluation_benchmark.py`
- `tests/unit/test_price_surface.py`
- `tests/unit/test_valuation.py`
- `tests/unit/test_valuation_canonical_mode.py`
- `tests/unit/test_valuation_reliability.py`
- `tests/unit/test_valuation_feedback.py`
- `tests/unit/test_valuation_engine_registry.py`
- `tests/unit/test_valuation_canonical_price.py`
- `tests/unit/test_valuation_service.py`

Nota: `test_valuation_engine_registry.py` pertenece al esqueleto desconectado previo y no prueba todavia la arquitectura oficial de Fase 0B.

## Esqueleto Desconectado

Rutas presentes antes de Fase 0B:

- `domain/valuation/engines/contracts.py`
- `domain/valuation/engines/registry.py`
- `domain/valuation/engines/__init__.py`
- `domain/valuation/engines/valoria_consensus/agreement.py`
- `domain/valuation/engines/valoria_consensus/calibration.py`
- `domain/valuation/engines/valoria_consensus/combination.py`
- `domain/valuation/engines/valoria_consensus/config.py`
- `domain/valuation/engines/valoria_consensus/engine.py`
- `domain/valuation/engines/valoria_consensus/explain.py`
- `domain/valuation/engines/valoria_consensus/__init__.py`
- `tests/unit/test_valoria_consensus.py`
- `tests/unit/test_valuation_engine_registry.py`

Decision inicial: conservar como evidencia en baseline, no usar como fuente de verdad. Despues del baseline se debe aislar o reemplazar con contratos oficiales unicos.

## Reportes De Auditoria Existentes

- `reports/comparables_engine_audit/comparables_engine_audit_latest.md`
- `reports/comparables_engine_audit/comparables_engine_audit_latest.json`
- `reports/valuation_engine_consolidation/phase0_consolidation_latest.md`
- `reports/valuation_engine_consolidation/phase0_consolidation_latest.json`
- `reports/house_error_cause_audit/house_error_cause_audit_latest.md`
- `reports/house_error_cause_audit/house_error_cause_audit_latest.json`
- `reports/house_refresh_impact_audit/house_refresh_impact_audit_latest.md`
- `reports/house_refresh_impact_audit/house_refresh_impact_audit_latest.json`
- `reports/valuation_canonical_price/valuation_canonical_price_latest.md`
- `reports/valuation_canonical_price/valuation_canonical_price_latest.json`

## Exclusiones Git Requeridas

Se debe corregir o mantener `.gitignore` para excluir:

- `.env`, `.env.*`, excepto `.env.example`
- credenciales y secrets locales
- `.venv/`, `.venv-win/`, `venv/`
- `__pycache__/`, `*.pyc`
- `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`
- `.tmp/`, temporales de pytest
- `*.db`, `*.sqlite`, `*.sqlite3`
- logs
- backups SQL
- zips y artefactos binarios pesados
- reportes generados no solicitados

Los reportes explicitamente solicitados en `reports/valuation_engine_rebuild/` deben poder versionarse.
