# AVM v2 Beta Deployment

This guide prepares a serious but simple beta deployment for:

- FastAPI API
- Streamlit UI
- PostgreSQL
- Redis
- HTTPS termination by the hosting platform or reverse proxy

Do not commit `.env`, Streamlit secrets, database dumps, or generated reports.

## Required Environment Variables

Use `.env.example` as the template. Required for beta:

| Variable | Used by | Notes |
|---|---|---|
| `ENVIRONMENT` | API/UI | Use `beta` or `production`. |
| `DATABASE_URL` | API/jobs/scripts | Async SQLAlchemy URL, usually `postgresql+asyncpg://...`. |
| `SYNC_DATABASE_URL` | Alembic | Sync URL, usually `postgresql+psycopg://...`. |
| `REDIS_URL` | API/geocoding/cache | Use managed Redis in hosted beta. |
| `JWT_SECRET_KEY` | API | Generate with `openssl rand -hex 32`. |
| `SECRET_KEY` | API compatibility | Set equal to `JWT_SECRET_KEY`. |
| `BETA_PASSWORD` | Streamlit | Required outside local/dev. |
| `ADMIN_PASSWORD` | Streamlit | Optional. |
| `AVM_API_BASE_URL` | Streamlit | Public or private API URL reachable from Streamlit. |
| `NOMINATIM_USER_AGENT` | Geocoding | Use a real app/contact identifier. |

Never use example passwords in beta.

## Docker Compose Beta

Local beta-like run:

```bash
cp .env.example .env
# edit .env and replace every secret
docker compose up --build -d
docker compose exec api alembic upgrade head
```

Open:

- API health: `http://localhost:8000/health`
- Streamlit: `http://localhost:8501`

Logs:

```bash
docker compose logs -f api
docker compose logs -f streamlit
docker compose logs -f postgres
```

Stop:

```bash
docker compose down
```

Keep volumes for beta data. Use `docker compose down -v` only when intentionally deleting local DB/Redis data.

## HTTPS Ready

The app containers listen on plain HTTP inside the private network. HTTPS should terminate at:

- Railway public service domain
- Render public service domain
- Caddy/Nginx/Traefik on a VPS

The API container starts Uvicorn with proxy headers enabled:

```bash
--proxy-headers --forwarded-allow-ips='*'
```

For a VPS reverse proxy, forward:

- `/` on the UI domain to Streamlit `8501`
- `/` on the API domain to FastAPI `8000`

Use separate domains when possible:

- `https://avm-beta.example.com` for Streamlit
- `https://api-avm-beta.example.com` for FastAPI

Then set:

```dotenv
AVM_API_BASE_URL=https://api-avm-beta.example.com
```

## Railway Suggested Setup

Use separate services:

1. PostgreSQL managed database.
2. Redis managed database.
3. API service from `Dockerfile.api`.
4. Streamlit service from `Dockerfile.streamlit`.

Set the API service variables:

```dotenv
ENVIRONMENT=beta
DATABASE_URL=<railway-postgres-asyncpg-url>
SYNC_DATABASE_URL=<railway-postgres-psycopg-url>
REDIS_URL=<railway-redis-url>
JWT_SECRET_KEY=<random>
SECRET_KEY=<same-random>
LOG_LEVEL=INFO
```

Set the Streamlit service variables:

```dotenv
ENVIRONMENT=beta
AVM_API_BASE_URL=<public-api-service-url>
BETA_PASSWORD=<random>
ADMIN_PASSWORD=<optional-random>
LOG_LEVEL=INFO
```

After first deploy, run:

```bash
alembic upgrade head
```

Use the provider shell/job runner if available. Otherwise run migrations from a trusted local machine pointed at the managed DB.

## Render Suggested Setup

Use:

1. Render PostgreSQL.
2. Render Redis.
3. Web Service for API using `Dockerfile.api`.
4. Web Service for Streamlit using `Dockerfile.streamlit`.

Both services can use Docker deploys. Configure health checks:

- API: `/health`
- Streamlit: `/_stcore/health`

Set the same environment variables as Railway. Ensure `AVM_API_BASE_URL` in Streamlit points to the public API service URL.

## Simple VPS Suggested Setup

Install Docker and Docker Compose plugin, then:

```bash
git clone <repo-url> avm-v2
cd avm-v2
cp .env.example .env
# edit .env secrets
docker compose up --build -d
docker compose exec api alembic upgrade head
```

Put Caddy, Nginx, or Traefik in front for HTTPS. Minimal Caddy shape:

```caddyfile
avm-beta.example.com {
    reverse_proxy 127.0.0.1:8501
}

api-avm-beta.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

For a VPS beta, restrict firewall ports to:

- `80/443` public
- `22` from trusted IPs
- do not expose `5432` or `6379` publicly

If Postgres/Redis must remain local-only, remove their public port mappings in `docker-compose.yml` or bind them to `127.0.0.1`.

## Operational Checklist

Before sharing the beta URL:

- Replace every value containing `replace-with`.
- Set `ENVIRONMENT=beta` or `production`.
- Confirm Streamlit blocks access without `BETA_PASSWORD`.
- Confirm `/health` returns `{"status":"ok"}`.
- Run `alembic upgrade head`.
- Create admin user if API auth is needed.
- Run `python scripts/avm_quality_dashboard.py --output-dir reports/avm_quality`.
- Confirm logs do not print secrets.

## What This Does Not Do Yet

- No autoscaling policy.
- No blue/green deploy.
- No object storage for exports.
- No centralized log aggregation.
- No background worker container split.

Those can wait until beta usage proves the need.
