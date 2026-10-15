# Validación de campos publicados — 16 octubre 2026

Se consultaron desde Oracle 200 fichas frescas por fuente con el cliente HTTP del scraper y separación mínima de 3,1 segundos. Se persistieron las 400 observaciones con el ORM y el actualizador candidatos en SQLite aislada en memoria de Oracle: cero escrituras en PostgreSQL de producción. No hubo despliegue ni cambios de timers.

El contraste independiente aleatorio de 30 fichas por fuente capturó el 100% de los campos publicados en los siete grupos evaluados; los denominadores y ausencias están en metrics.json y reviewed-reference-60.json. Los seis casos exigidos coinciden con la auditoría. Se rechazan 0,0 y la dirección de oficina, se conservan conflictos de año y no se imputa superficie útil desde valores genéricos.

Con la misma transacción de solo lectura, base y UF 41.162,73, Santiago 70 m² conserva 3.247,66 UF y La Florida 82 m² conserva 3.854,09 UF; los comparables también son idénticos. La sesión inválida real recibió el 302 a account-verification y activó PORTAL_SESSION_EXPIRED sin alterar la sesión válida.

before-after.csv conserva las columnas históricas y agrega los campos publicados y su procedencia; existed_in_prod distingue avisos nuevos del estado anterior. Las pruebas completas y su resultado se adjuntan en tests.txt.

La muestra es una corrida real de adquisición y persistencia aislada, no una ingesta de producción. El flujo normal mantiene el presupuesto de cinco detalles por ciclo y completa los campos gradualmente; este PR no promete completar todos los avisos en una sola corrida. No cambia el motor de tasación. El plan de despliegue y rollback está en ../README.md y requiere un nuevo OK.

## Corrección de direcciones: replay local sin red

Las mismas 400 fichas guardadas se reprocesaron y persistieron en SQLite local en memoria, sin consultar portales ni Oracle. Se corrigieron ocho direcciones. `addresses-affected-before-after.csv` compara el resultado de 9ab8b56 con el nuevo parser; el CSV completo también está actualizado. Direcciones crudas y campos ajenos a dirección permanecen idénticos.

Casos: Yapo 32286254 → CALLE ZENTENO, número de calle NULL, depto 1815; Yapo 32266506 → Santa Isabel (intersección Santa Isabel/Av. Matta publicada en descripción), número de calle NULL, depto 1401; Portal 4061330986 → Calle Ecuador 5079, depto 2307; Portal 4563754608 → Av. Ecuador 4707, depto NULL. Hay cuatro números de departamento explícitos: tres Yapo y uno Portal. Piso y departamentos por piso nunca se usan como unidad.

No quedan cadenas de calle vacías ni calles compuestas solo por DPTO/DP/N° y similares. La exigencia literal de tener calle en las 400 fichas no se puede cumplir sin imputar: quedan 164 calles NULL y en 92 casos no hay dirección original publicada. `addresses-proof.json` contiene el inventario. No se rellenan NULL con comunas, referencias o números de departamento.

El motor real sobre una copia local congelada de 2.699 avisos del snapshot guardado y UF 41.162,73 conserva Santiago 70 m² = 3.247,66 UF y La Florida 82 m² = 3.854,09 UF, incluidos comparables idénticos. Evidencia: `addresses-reference-proof.json`. Esta nueva prueba no accedió a producción; `persistence-proof.json` y `reference-same-snapshot.json` conservan la validación histórica de 9ab8b56 en Oracle. Las pruebas nuevas figuran en `tests.txt`.
