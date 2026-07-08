# Cloud beta runtime profile

Valoria supports two runtime profiles:

- `local`: complete local stack with PostgreSQL, Redis, scheduler, workers, scrapers, Streamlit, and on-demand refresh.
- `cloud_beta`: API-only container for a free/small cloud beta with external PostgreSQL, optional Redis disabled, no scheduler, no workers, no user-triggered refresh, and no runtime migrations.

## API runtime command

The API container starts FastAPI only:

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1} --proxy-headers --forwarded-allow-ips='${FORWARDED_ALLOW_IPS:-*}'
```

## Migrations

Run migrations as a separate, single-instance operational step before starting or promoting the API:

```bash
python -m alembic upgrade head
```

Do not run Alembic from multiple API instances at startup.

## Cloud beta minimum variables

Use `.env.cloud-beta.example` as a non-secret template. Store real secrets in the provider secret manager.

Recommended cloud-beta values:

- `VALORIA_RUNTIME_PROFILE=cloud_beta`
- `REDIS_ENABLED=false`
- `SCHEDULER_ENABLED=false`
- `WORKERS_ENABLED=false`
- `LISTING_ON_DEMAND_REFRESH_ENABLED=false`
- `PORTFOLIO_SNAPSHOT_WRITE_ENABLED=false`
- `VALUATION_FEEDBACK_ENABLED=false`
- `DATABASE_POOL_SIZE=2`
- `DATABASE_MAX_OVERFLOW=3`
- strict `BACKEND_CORS_ORIGINS` for the frontend domain

## Oracle ARM64 notes

`python:3.13-slim`, PostgreSQL, Redis, FastAPI, Uvicorn, SQLAlchemy, asyncpg, psycopg, and pure Python app code are expected to be multi-architecture compatible. Before moving to Oracle A1, verify with:

```bash
docker buildx build --platform linux/arm64 -f Dockerfile.api .
```

No Render, Neon, or Netlify-specific SDKs or proprietary runtime assumptions are required.
