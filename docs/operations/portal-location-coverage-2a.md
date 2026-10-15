# Portal: cobertura de ubicación, Codex 2a

## Diagnóstico comprobado el 15 de octubre de 2026

La base del cambio es `c55f4b65da8c03cb3a3fd6634f35ccd09f8f427a`, en
`release/canonical-only-reproducible-20261013`, actualmente desplegada.

El recorrido de venta no incluía departamentos de Providencia y San Miguel:
sus targets eran de arriendo y el runner los excluye. Vitacura solo tenía casas.
La Florida no tenía target. Consultas HTTP de solo lectura desde Oracle
devolvieron 48 tarjetas por comuna (46 parseadas en San Miguel, 48 en las demás).
Por tanto, la ausencia no corresponde a búsquedas vacías ni a un bloqueo 403.
Algunas búsquedas incluyen tarjetas declaradas en Santiago: no se fuerza la
comuna del target sobre la ubicación publicada.

El componente `location_and_points.map_info` del aviso `MLC-1938092725`
entrega dirección `Av. Los Leones 1500, Providencia` y coordenadas originales
`-33.4331049`, `-70.601649`. El parser conservaba el punto pero perdía la dirección.
No entrega precisión, radio ni garantía de ubicación exacta; zoom 16 no es una
declaración de precisión. Las respuestas de detalle 301 tampoco se seguían.

La vista de mapa de Estación Central devolvió 100 puntos con IDs de publicación.
Sus tarjetas no son equivalentes a las de listado: hay proyectos, rangos de
superficie y precios «desde». Se usan exclusivamente para recuperar puntos de
avisos ya existentes, identificados por el mismo MLC; nunca para crear avisos
ni modificar precios.

## Corrección y límites

- Se agregan los cuatro targets de venta de departamentos. Las seis comunas
  solicitadas se consultan diariamente. Dos slots rotan las otras seis rutas de
  venta: siguen cubiertas en tres días, con ocho búsquedas por corrida.
- Un GET de mapa rota entre las seis comunas y consume uno de los cinco GETs
  geográficos existentes. Detalles y redirecciones comparten los restantes.
  No se agregan timers, navegadores, proxies ni proveedores de geocodificación.
- Se conservan dirección original, componente fuente, MLC, fecha, coordenadas
  originales y atributos de precisión entregados. La precisión no certificada
  sigue siendo `unknown`, excluida del numerador utilizable.
- Se admite una redirección canónica hacia el mismo MLC, en HTTPS y hosts
  permitidos, dentro del presupuesto. Login, otro MLC y hosts externos se rechazan.
- La clave `building_candidate` usa calle, número y comuna. Rechaza rangos,
  intersecciones, unidades y direcciones sin número. Es candidata, no identidad
  física certificada. No se incorpora al motor de tasación.
- `python -m scripts.audit_location_coverage` usa una transacción PostgreSQL
  `REPEATABLE READ, READ ONLY` y reporta cobertura por comuna y fuente, así como
  candidatos con dos o más publicaciones. No hace solicitudes externas ni escribe.

## Producción: antes y después de preparar el cambio

El cambio **no está desplegado**. Ambas mediciones de solo lectura coinciden.
«Utilizable» exige par válido y precisión almacenada `address` o `street`;
excluye `unknown`, centroides, pares incompletos y coordenadas inválidas.
Esto audita la precisión registrada, no certifica independientemente al geocodificador.

| Comuna | Fuente | Activos | Pares | Utilizables antes | Utilizables después observado |
|---|---|---:|---:|---:|---:|
| Providencia | Portal | 0 | 0 | — | — |
| Providencia | Yapo | 131 | 35 | 34 (25,95%) | 34 (25,95%) |
| Vitacura | Portal | 0 | 0 | — | — |
| Vitacura | Yapo | 224 | 86 | 86 (38,39%) | 86 (38,39%) |
| La Florida | Portal | 0 | 0 | — | — |
| La Florida | Yapo | 176 | 68 | 68 (38,64%) | 68 (38,64%) |
| Estación Central | Portal | 230 | 2 | 0 (0%) | 0 (0%) |
| Estación Central | Yapo | 175 | 50 | 50 (28,57%) | 50 (28,57%) |
| San Miguel | Portal | 0 | 0 | — | — |
| San Miguel | Yapo | 149 | 23 | 20 (13,42%) | 20 (13,42%) |
| Santiago | Portal | 98 | 1 | 0 (0%) | 0 (0%) |
| Santiago | Yapo | 247 | 69 | 39 (15,79%) | 39 (15,79%) |

| Comuna | Utilizables / activos, ambas fuentes | Cobertura | Faltantes para >40%, denominador fijo | Candidatos de edificio con ≥2 avisos |
|---|---:|---:|---:|---:|
| Providencia | 34 / 131 | 25,95% | 19 | 0 |
| Vitacura | 86 / 224 | 38,39% | 4 | 0 |
| La Florida | 68 / 176 | 38,64% | 3 | 0 |
| Estación Central | 50 / 405 | 12,35% | 113 | 0 |
| San Miguel | 20 / 149 | 13,42% | 40 | 0 |
| Santiago | 39 / 345 | 11,30% | 100 | 0 |

Total utilizable: 297 / 1.430 (20,77%). El denominador cambió respecto al
síntoma inicial tras la ingesta normal anterior. Los ceros de edificios significan
ausencia de claves verificables con calle y número en los datos almacenados,
no ausencia de edificios repetidos. Las etiquetas Yapo disponibles contienen
también calles sin número, referencias de metro y títulos comerciales.

La condición de >40% **no está cumplida**. Recuperar puntos desconocidos no la
cumple. No se ha demostrado una imposibilidad definitiva por comuna: falta
medir ingesta con el cambio autorizado y disponer de precisión utilizable cuando
la fuente no la declara. No se propone cambiar el criterio para declarar éxito.

## Referencias y ejecución programada

Con una única transacción de solo lectura, base y UF congeladas en 41.162,73,
se evaluó antes y después de cargar los módulos candidatos solo en memoria:
Santiago 70 m² = **3.247,66 UF**, La Florida 82 m² = **3.854,09 UF**, idénticos
incluidos los hashes de comparables. No fue un despliegue ni una ingesta.

Las corridas manuales exitosas del 15 a las 12:33/12:35 UTC no satisfacen Parte A.
La primera UF programada se espera el 15 después de 16:30 UTC; Yapo el 16
después de 06:00 UTC y Portal después de 07:00 UTC. Se dejó verificación
desatendida en este chat el 16 a las 10:30 Europe/Berlin. Debe correlacionar
timer, journal, ledger y salud, y leer stderr privado si falla. La verificación
programada sigue pendiente; no se marca exitosa anticipadamente.

## Despliegue y rollback: requieren OK nuevo

1. Completar Parte A sobre la imagen actual. Si falla, conservar y reportar
   stderr completo antes de continuar. No lanzar una corrida manual para sustituirla.
2. Tras revisión y OK explícito, mergear este PR en la rama indicada. Reconstruir
   exclusivamente el commit mergeado y generar su manifiesto. Obtener respaldo
   verificable y guardar imagen, pins de lanzadores y estado de timers actuales.
3. Comprobar guardia de archivos, UF, salud y referencias antes/después sobre
   la misma base y UF **antes** de ingesta. Ante diferencias, rollback de imagen.
4. Canary acotado de ingesta normal: una búsqueda, un detalle y un GET geográfico,
   con memoria 384 MiB, CPU 0,25, swap 384 MiB, pids 96 y pausa mínima tres segundos.
   La corrida completa conserva ocho búsquedas, hasta cinco detalles incompletos
   y cinco GETs geográficos totales. Si falla, guardar stderr y restaurar imagen/pins.
5. Auditoría de producción de solo lectura después de ingesta. Publicar antes/
   después, precisión desconocida por separado, edificios candidatos y referencias.
   No declarar cierre hasta >40% en las seis comunas o evidencia de barrera real.
6. Rollback de este PR: restaurar imagen y pins `c55f4b65da8c03cb3a3fd6634f35ccd09f8f427a`,
   verificar manifiesto y salud. Este cambio no agrega migraciones: **no** bajar
   0023 ni desactivar UF. Los metadatos aditivos pueden permanecer auditables;
   no borrar avisos ni restaurar producción por fuera de la autorización de ingesta.
