# AVM — Automated Valuation Model (v2)

Motor de tasación automática de departamentos en Santiago de Chile basado en
comparables del mercado. Reescritura del prototipo original siguiendo una
arquitectura **Ports & Adapters** (hexagonal) para permitir crecimiento sin
acumular deuda técnica.

---

## Deploy beta local

La guia operativa para Windows, Docker, migraciones, admin inicial, backend,
frontend, auditoria y migracion SQLite -> Postgres esta en
`docs/deploy_beta.md`.

Para deploy beta con Docker, FastAPI, Streamlit, PostgreSQL, Redis, HTTPS por
proxy y opciones Railway/Render/VPS, ver `docs/deployment.md`.

## Release ZIP

El empaquetado limpio para beta, demo y production se genera con
`scripts/create_release_zip.py`. Ver comandos, manifest, checksum y reglas de
seguridad en `docs/release_zip.md`.

## Estado de scrapers

Yapo es la fuente principal actual. PortalInmobiliario esta experimental:
el parser tiene tests, pero el scraping real puede quedar bloqueado por login,
account-verification, captcha/anti-bot o 403. En esos casos se marca como
`blocked` y no se intenta evadir controles del sitio.

## Estado del proyecto

Módulo | Estado
---|---
1. Fundación (config, core) | ✅ Prompt 1
2. ORM + Alembic | ✅ Prompt 2
3. Repositorios + mappers + tests | ✅ Prompt 3
4. Dominio: tasación + UFClient | ✅ Prompt 4
5. Dominio: radar de oportunidades | ✅ Prompt 5
6. Pipeline de ingesta | ✅ Prompt 6
7. Scrapers + worker + scheduler | ✅ Prompt 7
8. API FastAPI (auth + JWT + bcrypt) | ✅ Prompt 8
9. UI Streamlit | ⏳
10. Auditoría | ⏳
11. Migración & deploy | ⏳

---

## Arquitectura

```
┌──────────────┐   ┌──────────────┐
│  UI Streamlit│   │  API FastAPI │
└──────┬───────┘   └──────┬───────┘
       │                  │
       ▼                  ▼
┌──────────────────────────────────┐
│         services/ (facade)       │
└────────────────┬─────────────────┘
                 ▼
┌──────────────────────────────────┐
│      domain/ (casos de uso)      │
│ · valuation  · radar  · ingestion│
└────────────────┬─────────────────┘
                 ▼
┌──────────────────────────────────┐
│  core/ (dominio puro, sin I/O)   │
│  entities · value_objects · ports│
└────────────────┬─────────────────┘
                 ▲
                 │ implementa los ports
┌────────────────┴─────────────────┐
│  infrastructure/ (adapters)      │
│  · db/  · scrapers/  · external/ │
└──────────────────────────────────┘
```

### Regla de oro

**`core/` no importa nada externo.** Si el dominio necesita algo del mundo
exterior (DB, HTTP, caché), se define un puerto en `core/ports/` y lo
implementa una clase de `infrastructure/`.

---

## Setup local Windows/PowerShell

Este modo corre API, Streamlit y Alembic desde Windows. Postgres y Redis siguen
en Docker, expuestos en `localhost:5432` y `localhost:6379`.

```powershell
# 1. Crear entorno virtual e instalar dependencias
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# 2. Configurar variables locales
Copy-Item .env.example .env
# En .env, DATABASE_URL y SYNC_DATABASE_URL deben usar @localhost:5432.

# 3. Levantar solo infraestructura local
docker compose up -d postgres redis

# 4. Aplicar migraciones desde Windows
python -m alembic upgrade head

# 5. Correr API y Streamlit desde Windows
python -m uvicorn api.main:app --reload
python -m streamlit run ui/app.py
```

## Setup Docker

Este modo corre API, Streamlit y Alembic dentro de Docker. Compose inyecta
`DATABASE_URL` y `SYNC_DATABASE_URL` con host `postgres`, y Streamlit usa
`http://api:8000` dentro de la red Docker.

```powershell
docker compose up -d
docker compose ps
```

Para ejecutar Alembic manualmente dentro del contenedor:

```powershell
docker compose exec api python -m alembic upgrade head
```

### Flujo de migraciones

```bash
# Crear una migración nueva después de modificar models.py
alembic revision --autogenerate -m "add foo column"

# Aplicar migraciones pendientes
alembic upgrade head

# Rollback una revisión
alembic downgrade -1

# Ver historial
alembic history
```

> ⚠️ **Regla:** revisá siempre el archivo autogenerado antes de commitear.
> Alembic no detecta bien cambios en check constraints ni server defaults.

---

## Estructura actual

```
avm/
├── config/                  # única fuente de verdad para settings/constantes
│   ├── settings.py          # pydantic-settings cargando .env
│   ├── constants.py         # LEGACY_UF_ARTIFACT_RATE, MIN_COMPARABLES, pesos, etc.
│   └── comunas.py           # catálogo canónico de comunas + normalizador
│
├── core/                    # dominio puro
│   ├── entities/            # Listing, Property, Opportunity, ValuationResult
│   ├── value_objects/       # Price, Coordinates, Score
│   ├── ports/               # interfaces (ListingRepository, UFService, ...)
│   └── exceptions.py
│
├── domain/                  # casos de uso (puros, sin I/O)
│   ├── valuation/
│   │   ├── scoring.py       # similarity_score(target, candidate) → Score
│   │   └── comparables.py   # valuate() — algoritmo principal
│   ├── radar/
│   │   ├── detector.py      # detect_opportunities() → RadarResult
│   │   └── filters.py       # apply_quality_filters(), top_n()
│   └── ingestion/
│       ├── data_cleaning.py # clean_listing(raw) → CleanedListing
│       ├── deduplication.py # make_fingerprint(cleaned) → sha1 hash
│       └── pipeline.py      # process_listing() — ÚNICO write path
│
├── infrastructure/          # adapters (DB, HTTP, caché)
│   ├── db/
│   │   ├── base.py          # DeclarativeBase + TimestampMixin + naming convention
│   │   ├── database.py      # engine lazy + get_session_factory + get_db
│   │   ├── models.py        # PropertyORM, ListingORM, PriceHistoryORM, ...
│   │   ├── mappers.py       # entidad dominio ↔ modelo ORM (ambos sentidos)
│   │   └── repositories/
│   │       ├── listing_repo.py    # SqlAlchemyListingRepository
│   │       └── property_repo.py   # SqlAlchemyPropertyRepository
│   └── external/
│       └── uf_client.py     # UFService implementado con httpx + Redis + fallback
│
├── tests/
│   ├── conftest.py          # fixtures async (engine + session in-memory)
│   ├── integration/
│   │   ├── test_listing_repo.py   # 12 tests
│   │   └── test_property_repo.py  # 10 tests
│   └── unit/
│       ├── factories.py              # make_property() / make_listing()
│       ├── test_scoring.py           # 10 tests
│       ├── test_valuation.py         # 19 tests
│       ├── test_uf_client.py         # 11 tests (mocks httpx + Redis)
│       ├── test_radar_detector.py    # 15 tests
│       └── test_radar_filters.py     # 14 tests
│
├── alembic/
│   ├── env.py               # carga URL sync desde settings
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial_schema.py
├── alembic.ini
│
├── pyproject.toml
├── docker-compose.yml
└── .env.example
```

### Schema actual (6 tablas)

Tabla | Propósito | Índices / constraints clave
---|---|---
`properties` | Inmueble físico único | `ix_properties_match(comuna, m2, bed, bath, park)` para match en ingesta
`listings` | Publicaciones de venta | `uq_fingerprint` (dedup), `uq_source_external`, `ix_comuna_status` (radar)
`price_history` | Historial de precios | `ix_listing_observed`
`users` | Auth + roles | `uq_username`, role ∈ {admin, analyst, viewer}
`saved_listings` | Favoritos por usuario | `uq_user_listing`
`usage_logs` | Tracking de eventos | `ix_event_type_created`, reemplaza `usage_log.json`

---

## Principios de diseño

| Principio | Cómo se aplica |
|---|---|
| **Única fuente de verdad** | Constantes en `config/constants.py`, comunas en `config/comunas.py`. Duplicar está prohibido. |
| **Inmutabilidad** | Value objects con `@dataclass(frozen=True)`. |
| **Precisión monetaria** | `Decimal` en lugar de `float` para montos. |
| **Errores tipados** | Jerarquía en `core/exceptions.py` — la UI/API los mapea, no los inventa. |
| **Tests sin I/O** | El dominio se testea sin DB ni red (se mockean los ports). |

---

## Correr los tests

```bash
source .venv/bin/activate
pytest                          # toda la suite
pytest tests/integration -v     # solo integración, verboso
pytest -k "fingerprint" -v      # filtrar por nombre
pytest --cov=infrastructure     # con cobertura
```

Los tests usan **aiosqlite in-memory**: sin docker, sin red, ~0.25s la suite completa.
