# Deploy beta local AVM-v2

Guia operativa para correr AVM-v2 en Windows con infraestructura local Docker.

## 1. Instalar entorno Python

```powershell
python -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -e ".[dev]"
```

No uses la carpeta `.venv/` antigua si existe en el repo. Puede provenir de otro sistema operativo.

## 2. Variables de entorno

Copia `.env.example` a `.env` y ajusta valores locales:

```dotenv
DATABASE_URL=postgresql+asyncpg://avm:replace-with-a-long-random-password@localhost:5432/avm
DATABASE_URL_SYNC=postgresql+psycopg://avm:replace-with-a-long-random-password@localhost:5432/avm
SYNC_DATABASE_URL=postgresql+psycopg://avm:replace-with-a-long-random-password@localhost:5432/avm
REDIS_URL=redis://localhost:6379/0
AVM_API_BASE_URL=http://127.0.0.1:8000
JWT_SECRET_KEY=replace-with-64-hex-chars
SECRET_KEY=replace-with-64-hex-chars
ACCESS_TOKEN_EXPIRE_MINUTES=60
ENVIRONMENT=local
```

No subas `.env` al repositorio.

## 3. Levantar infraestructura

```powershell
docker compose up -d
```

Esto levanta Postgres, Redis, FastAPI y Streamlit. Para levantar solo
infraestructura durante desarrollo local:

```powershell
docker compose up -d postgres redis
```

## 4. Correr migraciones

```powershell
.\.venv-win\Scripts\python.exe -m alembic upgrade head
```

## 5. Crear admin inicial

```powershell
.\.venv-win\Scripts\python.exe scripts\create_admin.py --email admin@example.com --username admin
```

Si no entregas `--password`, el script la pide por consola con `getpass`.

## 6. Correr backend

```powershell
.\.venv-win\Scripts\python.exe -m uvicorn api.main:app --reload
```

## 7. Correr frontend

```powershell
.\.venv-win\Scripts\python.exe -m streamlit run ui/app.py
```

## 8. Tests y auditoria

```powershell
.\.venv-win\Scripts\python.exe -m pytest
.\.venv-win\Scripts\python.exe scripts\check_health.py
```

Para compilar sin incluir entornos virtuales:

```powershell
.\.venv-win\Scripts\python.exe -m compileall api config core domain infrastructure services tests workers scripts audits ui
```

No uses `compileall .` si hay entornos virtuales dentro del repo.

## 9. Migrar SQLite legado a Postgres

Dry-run:

```powershell
.\.venv-win\Scripts\python.exe scripts\migrate_sqlite_to_postgres.py --sqlite-path C:\ruta\legacy.sqlite --dry-run --limit 100
```

Migracion real:

```powershell
.\.venv-win\Scripts\python.exe scripts\migrate_sqlite_to_postgres.py --sqlite-path C:\ruta\legacy.sqlite
```

Con truncado del destino:

```powershell
.\.venv-win\Scripts\python.exe scripts\migrate_sqlite_to_postgres.py --sqlite-path C:\ruta\legacy.sqlite --truncate-target
```

El script migra `listings`, `price_history` y `users` cuando existen y omite tablas/columnas faltantes con warnings.

## 10. Limpieza segura del workspace

Inspeccionar candidatos:

```powershell
.\.venv-win\Scripts\python.exe scripts\clean_workspace.py
```

Aplicar limpieza de caches:

```powershell
.\.venv-win\Scripts\python.exe scripts\clean_workspace.py --apply
```

Eliminar virtualenvs solo si quieres regenerarlos y el script detecta `pyvenv.cfg`:

```powershell
.\.venv-win\Scripts\python.exe scripts\clean_workspace.py --include-venv --apply
```

## 11. Notas deploy beta

- Usar Postgres externo administrado si el hosting lo permite.
- Usar Redis externo administrado si el hosting lo permite.
- Configurar `DATABASE_URL`, `SYNC_DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, `BETA_PASSWORD` y `AVM_API_BASE_URL`.
- No subir `.env`.
- No usar SQLite en produccion.
- Rotar `JWT_SECRET_KEY` antes de exponer el backend.
- Ver guia completa de deploy en `docs/deployment.md`.

## 12. Estado de fuentes de scraping

- Yapo es la fuente principal actual para ingesta.
- PortalInmobiliario esta marcado como experimental. El parser HTML tiene tests unitarios con fixture, pero el scraping real puede quedar bloqueado por login, account-verification, captcha/anti-bot o respuestas 403.
- Si PortalInmobiliario detecta bloqueo, retorna estado `blocked` con `items: []` y logs explicitos. No se intenta evadir captcha, login ni controles anti-bot.
- No se garantiza ingesta desde PortalInmobiliario hasta resolver el acceso legal/tecnico de forma estable.
