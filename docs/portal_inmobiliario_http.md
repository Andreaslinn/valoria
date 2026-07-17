# Portal Inmobiliario HTTP Manual

Ejecutar el canary manual recomendado desde el repositorio:

```powershell
python scripts/portal_canary.py --apply --max-pages-per-target 1 --max-details 40
```

El comando usa solo HTTP y PostgreSQL local. Inserta exclusivamente ventas de
casas y departamentos de la Region Metropolitana; los arriendos quedan fuera
del contrato de ingesta.

`PORTAL_HTTP_ENABLED` permanece en `false`: el comando no registra ni activa
ningun scheduler. `--apply` es siempre explicito. El limite se puede ampliar
manualmente hasta 50 detalles con `--max-details 50`.

El runner se detiene ante HTTP 403, HTTP 429, CAPTCHA, verificacion visible o
contenido inesperado. Cada publicacion usa una transaccion independiente.
