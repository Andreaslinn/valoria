# Tasar: separación entre el repo y producción — 13-10-2026

## Causa raíz comprobada

La divergencia está en **la orquestación Python desplegada**, no en la media canónica, el formulario, una conversión fija de UF ni una base de comparables distinta.

Con la misma instantánea de anuncios, mismos campos y UF de 41.152,13 CLP:

- El repo base `release/radar-tasar-engine-20261013` selecciona el favorito `comparables_canonical_outliers` mediante `favorite_first_with_legacy_fallback_v1`.
- Oracle ejecuta `valoria_consensus_v1_min_two_families`, que combina canónico, microzona, hedónico y, cuando está disponible, tendencia. La ruta de producción llama explícitamente al servicio con `valuation_strategy="consensus_v1"` y `VALORIA_USE_CONSENSUS=true`.
- Todos los motores individuales reproducidos localmente coinciden con sus equivalentes de producción. Sus conjuntos de IDs también coinciden. Es el paso de selección/combinación final el que cambia el resultado.

La ruta real de Oracle, ejecutada en un proceso diagnóstico separado con una instantánea y sin escrituras, reprodujo **5.877,21 UF / 83,9601 UF/m² / rango 1.224,65–9.139,36 / confianza medium 0,401505** para Santiago y **4.428,14 UF / 54,0017 UF/m² / rango 2.953,45–5.889,79 / confianza high 0,601745** para La Florida. Son los resultados reportados, con precisión sin redondear la presentación.

## Versiones y por qué la etiqueta Git engañaba

| Capa | Revisión comprobada |
|---|---|
| Next.js y proxy Netlify | `c889f4d65ce1fc7a145b72491a470bda728465c9`, deploy `6acde09716880ca8084866fa`, publicado 13-10-2026 07:42:21 UTC |
| Oracle: etiqueta OCI | Declara el mismo `c889f4d…` |
| Oracle: imagen real | `sha256:22081087e836574f11091c45a164f6dbe6891f095cf55e6c6945c38c49f90f69`, `valoria-remediation:radar-tasar-20261013`, API iniciada 13-10-2026 07:34:25 UTC |
| Motor canónico | `phase4a_canonical_outliers_v1`; archivo idéntico al repo tras normalizar saltos de línea |
| Orquestador del repo | `favorite_first_with_legacy_fallback_v1` |
| Orquestador de Oracle | `valoria_consensus_v1_min_two_families` |
| Huella pública de capacidades | `41a546ec7725669d2419998e9325438598c5093491a63780a703b5b68de8db88`, igual por Netlify y Oracle |

La imagen **no representa el árbol Git completo de c889f4d**. El Dockerfile de esa entrega parte de `valoria-remediation:candidate-20261012-v6` y copia solo `services/radar.py`, `api/deps.py` y `api/v1/radar.py`. Conserva por tanto las versiones previas de la imagen base para Tasar y su orquestación, aunque su etiqueta OCI lleve el nuevo SHA.

La comparación de archivos encontró diferencias en `services/valuation.py`, `api/v1/valuations.py` y `domain/valuation/engines/consensus_orchestrator.py`, entre otros archivos de informes/contratos. Canónico, legacy, price_surface, registro de motores, hedónico, microzona, tendencias y banderas comparados coinciden. Véase `production-trace-module-differences.json` para hashes completos. No es correcto describir esto simplemente como «un commit anterior»: es una imagen con capas de código que no corresponden a un único árbol del repo.

La huella antigua de capacidades no incluye los archivos del motor canónico ni del orquestador. Sirve para los contratos que cubre, pero no garantiza igualdad de todo el cálculo. La nueva trazabilidad incluye hashes de esos módulos y de los demás motores.

## Request: formulario → Netlify → Oracle → orquestador

Se ejecutó el **JavaScript publicado en /tasar** en un navegador desechable con el transporte backend interceptado. Esto captura la petición que construye el componente real, sin leer una sesión del usuario ni enviar credenciales reales. Separadamente se verificó el proxy HTTP real y se ejecutó la función real de la ruta Oracle. No se presenta esta combinación de pruebas como una nueva sesión HTTP autenticada del usuario.

1. `PropertyForm` → `useValuation.submit` → `createValuation` → `apiClient.post`: `POST /backend/api/v1/valuations`, JSON y `cache: "no-store"`.
2. El rewrite fijo de Next.js elimina `/backend` y dirige a `https://161-153-201-245.sslip.io/api/v1/valuations`. No hay route handler de tasación en Next.js que modifique el JSON o calcule un valor.
3. `ValuationRequest` de Oracle valida el cuerpo y construye `ValuationInput`, conservando las superficies y los valores numéricos. El `target_listing_id` ausente queda en `None`.
4. La ruta desplegada añade la **estrategia interna** `consensus_v1`; esta estrategia no viene del navegador. El servicio crea `Property` con `built_area_m2 or usable_area_m2 or m2` y, al normalizar los campos de dormitorios/baños/estacionamientos, convierte `None` en `0` mediante `or 0`.
5. Tras el recorrido legacy/quality inicial, `_with_product_consensus` llama al orquestador de varias familias. Su resultado sustituye precio, rango y confidence_score finales.

Payloads capturados:

```json
{"comuna":"santiago","property_type":"apartment","m2":70,"built_area_m2":70,"usable_area_m2":70,"land_area_m2":null,"dormitorios":2,"banos":2,"estacionamientos":0,"precio_publicado_uf":2552,"precio_publicado_clp":null}
{"comuna":"la_florida","property_type":"apartment","m2":82,"built_area_m2":82,"usable_area_m2":82,"land_area_m2":null,"dormitorios":3,"banos":2,"estacionamientos":1,"precio_publicado_uf":4000,"precio_publicado_clp":null}
```

La UI solicita superficie útil para departamentos y la copia en `m2`, `built_area_m2` y `usable_area_m2`; no solicita una superficie total independiente. Ambas reproducciones usaron exactamente esta convención. La comuna se envía como slug (`santiago`, `la_florida`), el tipo como `apartment` y el precio publicado como UF. Una prueba adicional dejó vacíos los tres campos de habitaciones: el navegador envió `null`, no `0` ni `""`; la conversión posterior a `0` ocurre en Python. Una referencia personal no se envía al cálculo. Un ID de publicación solo se envía si hubo prefill; en estos dos formularios nuevos no existe.

## Motores, fallbacks, cachés y mocks

El frontend muestra `result.estimated_price_uf` y el resto de la respuesta. No contiene otro AVM ni un fallback numérico; los fallos producen un mensaje. El estado React puede conservar la tasación anterior hasta volver a enviarla y marca la ficha modificada; eso no explica este caso, que se reprodujo en Python.

Netlify utiliza el rewrite de Next.js, sin motor ni mock de tasación. Las respuestas anónimas reales de Netlify y Oracle fueron 401 y compartieron la misma huella de backend. Netlify informó `cache-control: no-cache`, Durable bypass y Edge miss para esa comprobación. El cliente envía POST con `no-store`; no se identificó una caché de resultados de tasación en Netlify. La prueba del navegador utilizó interceptación **solo como instrumentación de diagnóstico**, no como descripción del runtime publicado.

Python sí tiene caché de UF y de índices de `price_surface`, además de fallback de calidad/consenso. Las dos cifras se reprodujeron con una tasa diaria fija, un proceso separado y el snapshot: no requieren una caché HTTP o React vieja. El canónico tuvo factor de surface 1 en ambos casos. El legacy de Santiago tuvo factor 0,992877, que reduce ligeramente el valor y no puede explicar un aumento a 5.877 UF.

## Matriz local vs producción, sobre una única instantánea

Instantánea de solo anuncios de ambas comunas: Santiago 344; La Florida 170. Se exportó mediante una transacción `REPEATABLE READ, READ ONLY`. La repetición local no accede a la base. Se mantuvieron los mismos datos y la misma UF para todos los motores.

| Motor/etapa | Santiago local | Santiago producción | La Florida local | La Florida producción |
|---|---:|---:|---:|---:|
| Canónico, base UF/m² | 47,152179 | 47,152179 | 47,672531 | 47,672531 |
| Canónico, después de surface UF/m² | 47,152179 | 47,152179 | 47,672531 | 47,672531 |
| Canónico, total UF | 3.300,65 | 3.300,65 | 3.909,15 | 3.909,15 |
| Legacy, base UF/m² | 51,631348 | 51,631348 | 50,010550 | 50,010550 |
| Legacy, después de surface UF/m² | 51,263596 | 51,263596 | 50,010550 | 50,010550 |
| Legacy, factor de surface | 0,992877 | 0,992877 | 1 | 1 |
| Legacy, total UF | 3.588,45 | 3.588,45 | 4.100,87 | 4.100,87 |
| Microzona, total UF | 6.015,5718 | 6.015,5718 | 4.879,00 | 4.879,00 |
| Hedónico, total UF | 5.877,2136 | 5.877,2136 | 4.789,2264 | 4.789,2264 |
| Tendencia, total UF | 6.015,5718 | 6.015,5718 | Se abstiene | Se abstiene |
| Orquestador final | Favorito canónico | Consenso multi-familia | Favorito canónico | Consenso multi-familia |
| Resultado de selección/consenso UF | **3.300,65** | **5.877,21** | **3.909,15** | **4.428,14** |

El recorrido previo de quality-v2 da 3.350,53 UF en Santiago y 3.979,26 UF en La Florida. Producción conserva su metadata/comparables de soporte, pero sustituye su estimación con el consenso.

### Cómo se forman las dos diferencias

**Santiago:** canónico 3.300,65; microzona 6.015,57; hedónico 5.877,21; tendencia 6.015,57. El consenso detecta desacuerdo extremo y usa `weighted_median_extreme_disagreement`. Sus pesos finales registrados son aproximadamente 0,223544 / 0,217074 / 0,417449 / 0,141933, respectivamente. Al ordenar valores, la masa acumulada cruza 0,5 en el hedónico: por eso el resultado coincide con **5.877,21**, y no con la media de los 20 comparables visibles.

**La Florida:** consenso `calibrated:global`, con canónico 3.909,15 (peso 0,430178), microzona 4.879 (0,194939) y hedónico 4.789,2264 (0,374883). Su combinación da aproximadamente **4.428,14 UF**. La diferencia relativa es distinta porque cambian los motores disponibles, su desacuerdo y la estrategia de combinación; no hay un multiplicador fijo.

Estos son cálculos observados, no una recomendación de cambiar pesos o motores.

## Comparables: diferencia de base descartada y muestra visible distinta

Por cada motor individual, local y producción tienen **IDs idénticos** en la instantánea: `only_local_ids=[]`, `only_production_ids=[]`. En particular, el canónico de Santiago pondera los mismos 20 IDs y produce el hash `dd4c799e33ca32d763979738cda87e80f0de4f8b1ca43e3f1a8ca9aa3fc73d59` en ambos lados. No se requiere una base local diferente para explicar el problema.

Hay otra diferencia real: los 20 anuncios visibles provienen del recorrido previo y no son la muestra canónica completa. Para Santiago:

- Solo en la lista visible respecto del canónico: **184, 191, 192, 846, 2582, 3351, 3531, 3795**.
- Solo en el canónico respecto de la lista visible: **2520, 3343, 3797, 3964, 5836, 6427, 6756, 7035**.

La Florida: solo visibles **2630, 5426**; solo canónico **950, 5436**. Los JSON incluyen los conjuntos completos y los hashes. Estas listas son diferencias entre etapas de una misma base, no diferencias de base local vs Oracle.

La suma de la lista visible actual de Santiago es 64.100,12 UF / 1.231 m², distinta de los 61.840 / 1.191 reportados. No se puede reconstruir esa lista histórica sin IDs/informe. Esta limitación no impide la atribución de la cifra final: precio, rango y confianza reportados se reprodujeron exactamente.

## Metadata añadida y compatibilidad de la imagen activa

El PR añade `valuation_debug` a la respuesta y un bloque JSON no visible `script[type=application/json]#valoria-valuation-debug` al HTML descargable. Incluye engine_selected, engine_version, engine_commit cuando el entorno lo declara explícitamente, hashes de fuentes reales, ppm2_base, ppm2_after_surface, ppm2_final, factor de surface, n ponderado e IDs/hash cuando el motor expone esa muestra.

El commit de imagen no se inventa: si no existe un SHA explícito en `VALORIA_RELEASE_COMMIT`, `engine_commit` es null y los hashes reales siguen disponibles. Los hashes de IDs usan JSON compacto de IDs numéricos ordenados, conservando duplicados y señalando IDs ausentes.

Un consenso no tiene una sola muestra ponderada de anuncios ni una sola etapa de surface. Esos campos son null en el nivel final; la instrumentación de producción registra `engines[]` y `previous_pipeline` para no atribuirle los 20 comparables legacy como si fueran su muestra final. Motores que no exponen IDs ponderados señalan esa ausencia; no se inventa un hash de una muestra vacía.

Debido a la divergencia de código, se incluye un **overlay opcional exclusivamente de diagnóstico**, contra los hashes exactos de los tres archivos desplegados: `deploy/valuation-debug/production-overlay.patch` y su manifiesto. Conserva la orquestación actual. No sustituir directamente esos archivos de Oracle por las versiones completas de la rama: eso alteraría su comportamiento. El overlay no se ha desplegado ni aplicado al proceso de API activo.

## Pruebas y preservación

- **66 pruebas enfocadas aprobadas**: servicio de tasación, orquestador, canónico, legacy, informes, trazabilidad de IDs, ausencia de commit, muestras múltiples y escape seguro del JSON descargable.
- **Dos casos de la ruta real de producción probados con el overlay** en un proceso separado y sin acceso a DB, sobre la instantánea: todos los campos anteriores de cada respuesta permanecen exactamente iguales; metadata y bloque del informe presentes.
- Captura del formulario Next.js publicado: dos fichas exactas y un caso de campos vacíos. Todos los transportes backend interceptados en contexto desechable; sin credenciales reales.
- `git apply --check` del overlay contra los tres archivos originales descargados: aprobado. Ruff y `git diff --check`: aprobados.
- Ningún archivo de `domain/valuation` ni frontend cambia en el PR. Ningún peso, microzona, surface, motor, dato, usuario, alerta o guardado fue modificado. No hubo despliegue, migración ni cambio de banderas.

La limitación previa de la rama para recoger toda la suite de API por `api.rate_limit` faltante sigue fuera de alcance, como en PR #1. La validación de la respuesta serializada de la API y del informe de la imagen activa se hizo con el overlay aislado descrito, sin ocultar esa limitación.

## Reproducción y evidencia

`python -m scripts.diagnose_valuation_path --snapshot /ruta/privada/production-trace-snapshot.json` compara todos los motores sobre un snapshot serializado de Listing; no abre conexiones de base. El snapshot completo permanece en el workspace, fuera de Git, y no contiene tablas de usuarios ni sesiones. Los JSON de este directorio conservan payloads, resultados, conjuntos de IDs, hashes, versiones y pruebas; no incluyen credenciales ni cabeceras de autorización.

La causa de la discrepancia queda identificada. Sigue abierta una cuestión distinta: si las señales de microzona/hedónico/tendencia y el consenso son apropiadas para estos segmentos. Este PR las observa y conserva; no las modifica.
