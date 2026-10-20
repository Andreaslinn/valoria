# SII — contraste canónico y confianza congelada en 2025H2

**Meta no alcanzada: ninguna comuna llega a 50% de cobertura. MdAPE dentro de la zona marcada ≤10% en las ocho.**

Continuación del PR #11 en borrador, sin merge ni deploy, flag apagado. No se integra en Tasar. Pesos, K, escalas y código del kNN originales permanecen idénticos.

## 1. Línea base: mismos casos

Muestra de **1200 cierres**: 150 por comuna, estratificación proporcional por edad (0–9, 10–19, 20–39, 40+, desconocida si existe), asignación por restos mayores y semilla 20261019. No se seleccionó por error ni por confianza. Las métricas siguientes usan exactamente la intersección de **1142 casos** donde ambos motores devolvieron valor.

| Comuna | Pares / 150 | Canónico MdAPE % | Canónico P95 % | kNN SII MdAPE % | kNN SII P95 % |
|---|---:|---:|---:|---:|---:|
| SANTIAGO | 139 | 32.24 | 102.02 | 10.41 | 43.99 |
| ESTACION CENTRAL | 141 | 30.64 | 123.53 | 14.16 | 66.33 |
| PROVIDENCIA | 139 | 40.33 | 168.73 | 13.42 | 97.81 |
| ÑUÑOA | 146 | 16.82 | 126.27 | 9.62 | 69.84 |
| LAS CONDES | 143 | 19.66 | 221.90 | 11.87 | 134.35 |
| LA FLORIDA | 140 | 21.58 | 124.75 | 11.63 | 75.62 |
| VITACURA | 148 | 24.19 | 131.31 | 13.44 | 111.77 |
| SAN MIGUEL | 146 | 21.43 | 112.59 | 15.33 | 54.39 |

Disponibilidad sobre los 1.200 intentos: canónico 1166; kNN 1176. No se comparan grupos diferentes ni se esconden las abstenciones.

| Comuna | Canónico con valor | kNN con valor | Asignación de muestra por edad |
|---|---:|---:|---|
| SANTIAGO | 144/150 | 145/150 | 0-9: 42, 10-19: 63, 20-39: 26, 40+: 19 |
| ESTACION CENTRAL | 146/150 | 145/150 | 0-9: 86, 10-19: 24, 20-39: 9, 40+: 31 |
| PROVIDENCIA | 139/150 | 150/150 | 0-9: 29, 10-19: 22, 20-39: 44, 40+: 55 |
| ÑUÑOA | 149/150 | 147/150 | 0-9: 84, 10-19: 23, 20-39: 15, 40+: 28 |
| LAS CONDES | 146/150 | 147/150 | 0-9: 25, 10-19: 25, 20-39: 58, 40+: 42 |
| LA FLORIDA | 146/150 | 144/150 | 0-9: 86, 10-19: 10, 20-39: 28, 40+: 26 |
| VITACURA | 150/150 | 148/150 | 0-9: 34, 10-19: 28, 20-39: 35, 40+: 53 |
| SAN MIGUEL | 146/150 | 150/150 | 0-9: 69, 10-19: 37, 20-39: 23, 40+: 21 |

### Qué significa esta comparación

- Motor real `comparables_canonical_outliers`, versión `phase4a_canonical_outliers_v1`, invocado directamente como lo hace el servicio canónico. Coinciden los hashes del servicio, motor, scoring y filtro robusto con el código leído en producción.
- Stock activo actual: 3895 avisos, corte UTC `2026-10-19 16:48:11.030183+00:00`. Lectura `REPEATABLE READ READ ONLY`, SELECTs acotados y rollback. Se conservan los filtros, orden de consulta del repositorio, precios, señales geográficas y clase de producto; no se exportan contactos ni descripciones.
- La clase de producto influye en el filtro robusto aun con el filtro directo de producto desactivado. Se conserva mediante etiquetas genéricas. **64 controles monetarios sintéticos coinciden exactamente** entre entradas completas del servidor y la proyección local.
- UF auténtica persistida en el calendario SII para 2026-10-19: 41183.94 CLP/UF. No se llama al cliente que refresca/persiste la UF, no se usa tasa inventada o fallback.
- Ambos modelos reciben los mismos m² cerrados, comuna, tipo y año de cada cierre. El canónico actual **ignora el año**, aunque se conserva en la metadata del objetivo. No se añadió una sensibilidad de edad que el motor no tiene. Al no haber dormitorios/baños/estacionamientos del objetivo en SII, se usa 0 como hace Tasar cuando faltan; no se inventan atributos.
- **Comparación retrospectiva con ofertas actuales, no backtest histórico del stock canónico.** Las fechas de los cierres preceden al stock de octubre; además, se comparan ofertas con precios declarados de cierre. La mejora observada no aísla el efecto del algoritmo y no justifica por sí sola un reemplazo.

## 2. Regla definida solo en validación 2025H2

Protocolo registrado UTC `2026-10-19T16:40:08.984277+00:00`; regla congelada UTC `2026-10-19T16:40:19.551924+00:00`. SHA-256 de la regla: `62e2647548487f63018a100c2f2b3c6231fd6ae212262f9307fb0cb7574b5f34`. El archivo de entrenamiento excluye todas las filas 2026; `fit` las rechaza si se intentan introducir. La evaluación 2026 exige el archivo congelado y verifica que no cambie su hash ni el código del kNN.

Validación: **13544 cierres 2025H2**. Pool: 36247 cierres desde 2024 hasta el 30/06/2025, antes de excluir los roles de validación. Se eliminan todas las ventas previas de cualquier rol de validación; no se usan comparables posteriores. No se cambió el estimador para crear confianza.

### Segmentación fijada antes de medir

1. Ubicación de los diez vecinos: `building5` si ≥5 son del mismo edificio; si no, `block5` si ≥5 son de la misma manzana; si no, `commune`. El conteo de manzana incluye los del edificio.
2. Edad en la fecha de valoración: 0–9, 10–19, 20–39 o ≥40 años. Desconocida o futura: abstención.
3. Dispersión relativa `D = (P75 − P25) / mediana`: D≤10%; 10%<D≤20%; 20%<D≤35%; D>35%.

**Regla simple:** un resultado se marca «confiable» si pertenece a una celda fija con **n≥30 y MdAPE 2025H2≤10%**. Fuera de esas celdas se devuelve `status=abstained`, sin valor puntual. Dentro se conserva exactamente el valor/rango/comparables del kNN, sin recalibración. No se buscaron nuevas fronteras, reglas por comuna ni umbrales para mejorar 2026.

### Las diez celdas admitidas

| Ubicación / edad / dispersión % | n validación | MdAPE validación % | P95 validación % |
|---|---:|---:|---:|
| block5/0-9/0-10 | 73 | 7.09 | 52.66 |
| block5/0-9/10-20 | 75 | 9.52 | 51.94 |
| block5/0-9/20-35 | 97 | 7.89 | 49.62 |
| block5/10-19/0-10 | 31 | 6.65 | 157.40 |
| block5/10-19/10-20 | 68 | 7.34 | 66.87 |
| building5/0-9/0-10 | 2349 | 4.55 | 23.10 |
| building5/0-9/10-20 | 1791 | 6.80 | 24.86 |
| building5/10-19/0-10 | 66 | 9.44 | 52.85 |
| building5/20-39/10-20 | 41 | 8.85 | 118.54 |
| commune/10-19/0-10 | 47 | 9.99 | 134.20 |

El mínimo de 30 se fijó antes de evaluar; evita declarar una zona por unos pocos cierres. El umbral es empírico y no garantiza un error individual ≤10%. Los P95 siguen siendo altos en varias zonas.

## 3. Regla congelada aplicada al holdout 2026

Se evalúan los **13135 cierres**, no solo la muestra de comparación. Pool 2024–2025, excluyendo por completo todos los roles presentes en 2026. Cobertura = casos admitidos / todos los cierres de la comuna, incluidas las abstenciones por datos faltantes. MdAPE y P95 usan solo los admitidos.

| Comuna | Admitidos / total | Cobertura % | MdAPE zona % | P95 zona % | ≥50% y ≤10% |
|---|---:|---:|---:|---:|---|
| SANTIAGO | 588/2202 | 26.70 | 6.42 | 36.00 | No |
| ESTACION CENTRAL | 241/837 | 28.79 | 5.59 | 38.52 | No |
| PROVIDENCIA | 150/1265 | 11.86 | 5.82 | 73.76 | No |
| ÑUÑOA | 1214/2699 | 44.98 | 5.41 | 20.66 | No |
| LAS CONDES | 339/2033 | 16.67 | 7.96 | 47.49 | No |
| LA FLORIDA | 1253/2648 | 47.32 | 5.36 | 20.43 | No |
| VITACURA | 144/776 | 18.56 | 8.24 | 72.48 | No |
| SAN MIGUEL | 156/675 | 23.11 | 8.00 | 56.81 | No |

Resultado: **0/8 comunas** cumplen simultáneamente; se pedían al menos seis. Las ocho cumplen MdAPE dentro de la zona, pero todas quedan por debajo de 50% de cobertura. La mejor cobertura es La Florida (47,32%), seguida de Ñuñoa (44,98%). No se amplió la regla después de observar estos números.

La cobertura limitada viene de celdas de validación sin apoyo suficiente o con MdAPE>10%: ningún tramo ≥40 años fue admitido, y la mayoría de combinaciones de ubicación débil o dispersión alta tampoco. La regla abstiene para esos casos; no se traslada a otra celda ni sustituye por una estimación del canónico.

## Validación por segmento: conteos exactos y márgenes

Descriptivos de 2025H2 únicamente; no se usan como nuevas reglas. Los conteos de ubicación incluyen de 0 a 10 vecinos.

### Vecinos del mismo edificio

| Segmento | n | MdAPE % | P95 % |
|---|---:|---:|---:|
| 0 | 4209 | 18.84 | 110.38 |
| 1 | 1113 | 13.75 | 114.63 |
| 2 | 900 | 12.64 | 95.38 |
| 3 | 667 | 13.47 | 89.67 |
| 4 | 577 | 12.46 | 75.64 |
| 5 | 425 | 10.00 | 69.75 |
| 6 | 350 | 11.42 | 92.32 |
| 7 | 257 | 9.87 | 55.47 |
| 8 | 174 | 9.36 | 70.33 |
| 9 | 196 | 10.34 | 67.15 |
| 10 | 4442 | 6.10 | 31.19 |

### Vecinos de la misma manzana

| Segmento | n | MdAPE % | P95 % |
|---|---:|---:|---:|
| 0 | 2585 | 20.68 | 109.70 |
| 1 | 1263 | 16.35 | 114.32 |
| 2 | 1062 | 13.96 | 110.81 |
| 3 | 834 | 13.61 | 94.24 |
| 4 | 758 | 14.36 | 96.92 |
| 5 | 604 | 10.84 | 76.51 |
| 6 | 446 | 12.13 | 101.55 |
| 7 | 394 | 10.57 | 64.77 |
| 8 | 262 | 11.42 | 70.18 |
| 9 | 273 | 10.07 | 64.61 |
| 10 | 4829 | 6.33 | 32.46 |

### Tramo de edad

| Segmento | n | MdAPE % | P95 % |
|---|---:|---:|---:|
| 0-9 | 6912 | 7.54 | 37.99 |
| 10-19 | 2113 | 13.06 | 85.01 |
| 20-39 | 2090 | 15.55 | 120.33 |
| 40+ | 2195 | 21.30 | 126.46 |

### Dispersión relativa %

| Segmento | n | MdAPE % | P95 % |
|---|---:|---:|---:|
| 0-10 | 2879 | 5.30 | 31.67 |
| 10-20 | 3863 | 9.10 | 57.22 |
| 20-35 | 3242 | 14.13 | 84.51 |
| 35+ | 3326 | 20.08 | 110.65 |

## Anexo: todas las celdas conjuntas de validación

| Ubicación / edad / dispersión % | n | MdAPE % | P95 % | Admitida |
|---|---:|---:|---:|---|
| block5/0-9/0-10 | 73 | 7.09 | 52.66 | Sí |
| block5/0-9/10-20 | 75 | 9.52 | 51.94 | Sí |
| block5/0-9/20-35 | 97 | 7.89 | 49.62 | Sí |
| block5/0-9/35+ | 44 | 15.26 | 99.42 | No |
| block5/10-19/0-10 | 31 | 6.65 | 157.40 | Sí |
| block5/10-19/10-20 | 68 | 7.34 | 66.87 | Sí |
| block5/10-19/20-35 | 91 | 17.26 | 58.76 | No |
| block5/10-19/35+ | 86 | 14.37 | 102.15 | No |
| block5/20-39/0-10 | 17 | 12.07 | 27.71 | No |
| block5/20-39/10-20 | 58 | 10.85 | 88.17 | No |
| block5/20-39/20-35 | 83 | 12.27 | 88.73 | No |
| block5/20-39/35+ | 75 | 17.11 | 106.35 | No |
| block5/40+/0-10 | 11 | 7.79 | 17.68 | No |
| block5/40+/10-20 | 54 | 10.19 | 52.91 | No |
| block5/40+/20-35 | 50 | 12.53 | 152.19 | No |
| block5/40+/35+ | 51 | 17.47 | 183.11 | No |
| building5/0-9/0-10 | 2349 | 4.55 | 23.10 | Sí |
| building5/0-9/10-20 | 1791 | 6.80 | 24.86 | Sí |
| building5/0-9/20-35 | 510 | 10.28 | 43.54 | No |
| building5/0-9/35+ | 250 | 19.10 | 62.78 | No |
| building5/10-19/0-10 | 66 | 9.44 | 52.85 | Sí |
| building5/10-19/10-20 | 201 | 11.16 | 52.82 | No |
| building5/10-19/20-35 | 295 | 14.15 | 64.20 | No |
| building5/10-19/35+ | 178 | 16.30 | 89.31 | No |
| building5/20-39/0-10 | 16 | 12.42 | 99.02 | No |
| building5/20-39/10-20 | 41 | 8.85 | 118.54 | Sí |
| building5/20-39/20-35 | 54 | 12.63 | 162.65 | No |
| building5/20-39/35+ | 54 | 12.40 | 59.26 | No |
| building5/40+/0-10 | 2 | 3.44 | 5.88 | No |
| building5/40+/10-20 | 10 | 10.90 | 98.00 | No |
| building5/40+/20-35 | 13 | 28.03 | 94.35 | No |
| building5/40+/35+ | 14 | 21.84 | 84.25 | No |
| commune/0-9/0-10 | 209 | 11.88 | 45.98 | No |
| commune/0-9/10-20 | 686 | 15.85 | 42.15 | No |
| commune/0-9/20-35 | 553 | 14.98 | 48.58 | No |
| commune/0-9/35+ | 275 | 17.47 | 74.44 | No |
| commune/10-19/0-10 | 47 | 9.99 | 134.20 | Sí |
| commune/10-19/10-20 | 346 | 10.66 | 126.01 | No |
| commune/10-19/20-35 | 440 | 13.34 | 80.87 | No |
| commune/10-19/35+ | 264 | 15.98 | 76.01 | No |
| commune/20-39/0-10 | 45 | 15.39 | 160.09 | No |
| commune/20-39/10-20 | 345 | 11.57 | 137.78 | No |
| commune/20-39/20-35 | 534 | 14.87 | 114.74 | No |
| commune/20-39/35+ | 768 | 21.78 | 121.43 | No |
| commune/40+/0-10 | 13 | 22.06 | 155.76 | No |
| commune/40+/10-20 | 188 | 19.28 | 154.84 | No |
| commune/40+/20-35 | 522 | 20.72 | 122.59 | No |
| commune/40+/35+ | 1267 | 23.91 | 126.93 | No |

## Pruebas, reproducibilidad y límites

- **126 passed in 8.85s**, Ruff y diff check correctos. Se probaron rechazo de 2026 al entrenar, límites de edad/IQR, mínimo de soporte, independencia del precio real al aplicar la regla, abstención sin valor, muestreo y regresiones canónicas/SII.
- 64 controles sintéticos de la proyección canónica y verificación de igualdad de hashes con producción. El stock se leyó sin escrituras; todos los registros resultantes quedan locales.
- Se comprobó que añadir la salida explícita de abstención no cambia ninguna selección, predicción ni métrica del holdout. La regla mantiene el mismo SHA y el kNN conserva exactamente su código original.
- Catastro estructural disponible: snapshot 2026H2 de la primera evaluación. No se reconstruyó un catastro histórico 2025; el corte temporal se aplica a cierres, roles y labels. Esa limitación de covariables impide presentar esto como un backtest histórico completo.
- Ningún endpoint, servicio de valoración o vista de Tasar fue modificado. Flag apagado; sin integración, merge ni deploy.
- El PR contiene solo código, protocolo, regla y métricas agregadas. Los cierres, roles, entradas canónicas, muestras y comparables individuales se entregan en el ZIP local. Los nombres de salidas individuales están ignorados por Git.
- La suite completa del proyecto no se ejecutó; se corrieron las pruebas relevantes anteriores.
