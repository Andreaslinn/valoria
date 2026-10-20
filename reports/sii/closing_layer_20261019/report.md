# Segunda capa SII — resultado agregado, integración detenida

**No cumple MdAPE ≤10% en las ocho comunas. PR en borrador, sin merge ni deploy.**

Base: `24b56dc` sobre `release/canonical-only-reproducible-20261013`, con PR #9 incluido. Se construyeron índice y estimador offline. El paso 4 se detuvo al fallar el holdout: no se cambió ningún endpoint, servicio de tasación, formulario ni vista de resultados. El flag `sii_closing_layer` está apagado por defecto y encenderlo todavía no muestra una segunda opinión.

## Métricas

| Comuna | Muestra dirección | Resolución % | Holdout | Predichos | MdAPE % | P95 error % |
|---|---:|---:|---:|---:|---:|---:|
| SANTIAGO | 38 | 92.11 | 2202 | 2130 | 12.39 | 61.83 |
| ESTACION CENTRAL | 38 | 81.58 | 837 | 817 | 16.23 | 100.14 |
| PROVIDENCIA | 38 | 97.37 | 1265 | 1259 | 13.02 | 122.46 |
| ÑUÑOA | 38 | 89.47 | 2699 | 2640 | 8.33 | 72.01 |
| LAS CONDES | 37 | 97.30 | 2033 | 2014 | 11.59 | 121.29 |
| LA FLORIDA | 37 | 100.00 | 2648 | 2584 | 9.45 | 77.77 |
| VITACURA | 37 | 94.59 | 776 | 765 | 11.92 | 95.39 |
| SAN MIGUEL | 37 | 97.30 | 675 | 672 | 15.77 | 79.37 |

**Dirección: 281/300 = 93,67% global.** Cumple la meta numérica global; Estación Central y Ñuñoa presentan menores tasas en el desglose. Las reescrituras son automáticas de estilo humano y la identidad esperada usa el catastro: no es certificación independiente de edificio físico. OSM no tenía extracto local y no se evaluó recuperación.

**Holdout: 13.135 cierres, 12.881 predicciones y 254 abstenciones.** Seis comunas superan MdAPE 10%. Ñuñoa y La Florida sí cumplen ese umbral. MdAPE y P95 se calculan sobre predichos; los totales conservan las abstenciones.

## Error por tramo de edad

| Comuna | Edad en 2026 | n | Predichos | MdAPE % | P95 % |
|---|---|---:|---:|---:|---:|
| SANTIAGO | 0-9 | 618 | 613 | 6.42 | 47.77 |
| SANTIAGO | 10-19 | 928 | 880 | 14.88 | 56.99 |
| SANTIAGO | 20-39 | 383 | 367 | 14.49 | 65.02 |
| SANTIAGO | 40+ | 273 | 270 | 19.38 | 88.36 |
| SANTIAGO | unknown | 0 | 0 | — | — |
| ESTACION CENTRAL | 0-9 | 481 | 481 | 13.08 | 118.52 |
| ESTACION CENTRAL | 10-19 | 131 | 130 | 16.54 | 74.60 |
| ESTACION CENTRAL | 20-39 | 50 | 50 | 20.56 | 69.70 |
| ESTACION CENTRAL | 40+ | 175 | 156 | 22.19 | 97.16 |
| ESTACION CENTRAL | unknown | 0 | 0 | — | — |
| PROVIDENCIA | 0-9 | 247 | 247 | 8.06 | 62.98 |
| PROVIDENCIA | 10-19 | 182 | 181 | 10.39 | 104.96 |
| PROVIDENCIA | 20-39 | 369 | 368 | 13.63 | 146.18 |
| PROVIDENCIA | 40+ | 467 | 463 | 18.47 | 149.92 |
| PROVIDENCIA | unknown | 0 | 0 | — | — |
| ÑUÑOA | 0-9 | 1505 | 1505 | 5.85 | 26.30 |
| ÑUÑOA | 10-19 | 412 | 411 | 8.88 | 70.75 |
| ÑUÑOA | 20-39 | 276 | 269 | 14.86 | 166.39 |
| ÑUÑOA | 40+ | 506 | 455 | 20.71 | 144.42 |
| ÑUÑOA | unknown | 0 | 0 | — | — |
| LAS CONDES | 0-9 | 342 | 341 | 9.40 | 35.41 |
| LAS CONDES | 10-19 | 344 | 343 | 8.57 | 87.16 |
| LAS CONDES | 20-39 | 784 | 772 | 11.02 | 121.60 |
| LAS CONDES | 40+ | 563 | 558 | 18.89 | 157.70 |
| LAS CONDES | unknown | 0 | 0 | — | — |
| LA FLORIDA | 0-9 | 1520 | 1513 | 5.88 | 24.28 |
| LA FLORIDA | 10-19 | 179 | 157 | 13.29 | 68.47 |
| LA FLORIDA | 20-39 | 497 | 469 | 22.35 | 121.38 |
| LA FLORIDA | 40+ | 452 | 445 | 26.61 | 107.32 |
| LA FLORIDA | unknown | 0 | 0 | — | — |
| VITACURA | 0-9 | 175 | 167 | 9.51 | 48.48 |
| VITACURA | 10-19 | 143 | 142 | 9.16 | 55.55 |
| VITACURA | 20-39 | 182 | 182 | 10.90 | 78.73 |
| VITACURA | 40+ | 276 | 274 | 16.05 | 149.36 |
| VITACURA | unknown | 0 | 0 | — | — |
| SAN MIGUEL | 0-9 | 313 | 313 | 11.35 | 45.76 |
| SAN MIGUEL | 10-19 | 165 | 165 | 16.64 | 59.30 |
| SAN MIGUEL | 20-39 | 102 | 102 | 19.05 | 84.21 |
| SAN MIGUEL | 40+ | 95 | 92 | 36.97 | 108.82 |
| SAN MIGUEL | unknown | 0 | 0 | — | — |

## Método y diagnóstico

- Índice de 1.673.327 roles desde la dirección original del último par N/NL completo. Normaliza tildes, abreviaturas y prefijos, separa edificio y unidad, y devuelve candidatos ante ambigüedad. No infiere unidad a partir del piso.
- kNN K=10, pesos área/ubicación/edad/fecha 0,30/0,30/0,30/0,10, escalas y ecuaciones en `docs/sii_closing_layer.md`. UF/m² sobre superficie H cerrada. Mediana y P25–P75 ponderados, sin calibración sobre el holdout.
- Todos los roles con cierres efectivos en 2026 se excluyen del pool 2024–2025, incluidas sus ventas previas. Se rechazan además comparables del mismo rol o con fecha posterior.
- Los residuos mayores muestran precios por m² muy diferentes a sus vecinos, incluso con coincidencias de edificio. El modelo no explica esas diferencias; su causa económica o registral no fue verificada.
- Las direcciones fallan principalmente por ambigüedad entre manzanas, formatos de bloque/torre no interpretados o ausencia de dirección. No se elige un candidato arbitrariamente.
- La evidencia individual, cinco fallos de valoración por comuna y sus motivos, muestra de 300 direcciones, rangos y diez comparables por predicción se entregan en archivos locales al solicitante. **No se publican direcciones, roles ni registros de transacciones en este PR.**

## Validación y límites

- 105 pruebas unitarias/regresión pasadas: índice, kNN, ingesta SII, servicio canónico real, guardia release, endpoint y ruta compartida Radar. No se ejecutó la suite completa.
- Ruff y diff check correctos; todos los comparables se verificaron contra exclusión de roles del holdout y fechas estrictamente anteriores. P25 ≤ valor ≤ P75 en todas las predicciones.
- Endpoints, servicio y ambas interfaces idénticos byte a byte a la release (normalizando CRLF). Sin integración experimental, flag apagado y ausencia de dirección conservan exactamente el mismo camino.
- Solo lectura del SII local, SQLite desechable; sin escrituras en producción, nuevas migraciones, jobs, merge ni deploy.
- Pendientes: anotación independiente de edificios, respaldo OSM con datos locales, resolución segura de formatos y candidatos, investigación de errores de precio, y paso 4 tras superar los controles.
