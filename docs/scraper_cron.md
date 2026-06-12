# AVM Scraper Cron en Linux con Docker

Esta guía deja el scraper de Yapo corriendo una vez al día en un servidor Linux, aunque tu computador personal esté apagado.

El cron ejecuta:

```bash
python -m workers.scraper_job
```

dentro del contenedor Docker del servicio `api`, para que use las variables correctas del `docker-compose.yml`:

- `DATABASE_URL=...@postgres:5432/...`
- `SYNC_DATABASE_URL=...@postgres:5432/...`
- `REDIS_URL=redis://redis:6379/0`

## 1. Preparar el servidor

Instala Docker Engine con el plugin `docker compose` y copia el proyecto al servidor, por ejemplo:

```bash
cd /opt
git clone <repo-url> AVM-v2
cd /opt/AVM-v2
```

Crea `.env` desde `.env.example` y define al menos:

```bash
POSTGRES_PASSWORD=...
JWT_SECRET_KEY=...
BETA_PASSWORD=...
```

Luego construye la imagen de la API una vez:

```bash
docker compose build api
docker compose up -d postgres redis
docker compose run --rm --no-deps api python -m alembic upgrade head
chmod +x scripts/run_scraper_cron.sh
```

## 2. Probar manualmente

Desde la raíz del proyecto:

```bash
bash scripts/run_scraper_cron.sh
```

Si quieres probar el comando Docker exacto sin el wrapper:

```bash
mkdir -p logs
docker compose up -d postgres redis
docker compose run --rm --no-deps api python -m workers.scraper_job
```

El script:

- crea `logs/` si no existe,
- escribe en `logs/scraper_cron.log`,
- evita ejecuciones simultáneas con `flock`,
- levanta `postgres` y `redis` si no están corriendo,
- ejecuta `python -m workers.scraper_job` dentro del servicio `api`.

## 3. Instalar cron diario

Edita el crontab del usuario que administrará Docker:

```bash
crontab -e
```

Agrega una línea como esta, ajustando la ruta absoluta:

```cron
15 7 * * * cd /opt/AVM-v2 && /usr/bin/env bash scripts/run_scraper_cron.sh
```

Ese ejemplo corre todos los días a las 07:15 hora local del servidor.

Si quieres fijar timezone explícito para ese crontab:

```cron
CRON_TZ=America/Santiago
15 7 * * * cd /opt/AVM-v2 && /usr/bin/env bash scripts/run_scraper_cron.sh
```

## 4. Ver logs

```bash
tail -f /opt/AVM-v2/logs/scraper_cron.log
```

También puedes revisar contenedores:

```bash
docker compose ps
docker compose logs --tail=100 postgres redis
```

## 5. Verificar que corrió

Busca en el log líneas como:

```text
AVM scraper cron starting
AVM scraper cron finished
```

Y revisa el resumen del job:

```bash
grep -E "raw=|inserted=|updated=|health|AVM scraper cron" logs/scraper_cron.log
```

También puedes verificar en Postgres:

```sql
SELECT property_type, status, COUNT(*) AS total
FROM listings
GROUP BY property_type, status
ORDER BY property_type, status;
```

## 6. Operación después de actualizar código

Después de hacer `git pull` o cambiar dependencias:

```bash
docker compose build api
docker compose run --rm --no-deps api python -m alembic upgrade head
bash scripts/run_scraper_cron.sh
```

## Notas

- No uses `@localhost` dentro del contenedor. El compose inyecta `@postgres` y `redis://redis:6379/0`.
- El lock está en `logs/scraper_cron.lock`. Si un scraper anterior sigue activo, el siguiente run se salta sin fallar.
- Si el servidor reinicia, `postgres` y `redis` tienen `restart: unless-stopped`; el cron además los levanta antes de correr el scraper.
