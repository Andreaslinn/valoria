# Validación de campos publicados — 16 octubre 2026

Se consultaron desde Oracle 200 fichas frescas por fuente con el cliente HTTP del scraper y separación mínima de 3,1 segundos. Se persistieron las 400 observaciones con el ORM y el actualizador candidatos en SQLite aislada en memoria de Oracle: cero escrituras en PostgreSQL de producción. No hubo despliegue ni cambios de timers.

El contraste independiente aleatorio de 30 fichas por fuente capturó el 100% de los campos publicados en los siete grupos evaluados; los denominadores y ausencias están en metrics.json y reviewed-reference-60.json. Los seis casos exigidos coinciden con la auditoría. Se rechazan 0,0 y la dirección de oficina, se conservan conflictos de año y no se imputa superficie útil desde valores genéricos.

Con la misma transacción de solo lectura, base y UF 41.162,73, Santiago 70 m² conserva 3.247,66 UF y La Florida 82 m² conserva 3.854,09 UF; los comparables también son idénticos. La sesión inválida real recibió el 302 a account-verification y activó PORTAL_SESSION_EXPIRED sin alterar la sesión válida.

before-after.csv conserva las columnas históricas y agrega los campos publicados y su procedencia; existed_in_prod distingue avisos nuevos del estado anterior. Las pruebas completas y su resultado se adjuntan en tests.txt.

La muestra es una corrida real de adquisición y persistencia aislada, no una ingesta de producción. El flujo normal mantiene el presupuesto de cinco detalles por ciclo y completa los campos gradualmente; este PR no promete completar todos los avisos en una sola corrida. No cambia el motor de tasación. El plan de despliegue y rollback está en ../README.md y requiere un nuevo OK.
