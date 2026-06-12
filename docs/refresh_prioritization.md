# Refresh prioritization

El refresh scraper selecciona listings conocidos con un batch limitado y orden
estable. El objetivo es actualizar primero lo que mas importa y evitar golpear
Yapo con reintentos demasiado frecuentes.

Orden de prioridad:

1. Listings guardados por usuarios en watchlist activa.
2. Listings activos vistos en los ultimos 30 dias.
3. Listings activos no vistos hace 30 a 45 dias.
4. Ultima revision: listings activos no vistos hace mas de 45 dias, y listings
   inactivos que ya superaron el corte de stale configurado.

Reglas operativas:

- El limite total se controla con `limit` en el job manual o
  `SCHEDULER_REFRESH_LIMIT` en scheduler.
- El cooldown evita refrescar filas con `last_refresh_attempted_at` reciente.
  Por defecto son 24 horas, configurable con `--cooldown-hours` o
  `SCHEDULER_REFRESH_COOLDOWN_HOURS`.
- El orden es auditable: prioridad, listings nunca refrescados primero,
  `last_refresh_attempted_at`, `last_seen_at` e `id`.
- Listings `removed` no entran al batch.
- El rate limiting existente sigue aplicando entre requests.
