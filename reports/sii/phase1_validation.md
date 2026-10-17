# Valoria · Fase 1 SII · Validación local · 17/10/2026

Base verificada: `29eaa0b3f3543c57e1e596eda2fb64e527d3f65a`, rama `release/canonical-only-reproducible-20261013`. Rama de trabajo: `feature/sii-ingest-20261017`. La evidencia de producción procede de la auditoría local del 17/10 y se contrastó el commit con GitHub; no se inspeccionó producción en vivo.

Fuente: `F2890_01-10-2026.zip`, SHA-256 `eae2fbd4acd72eb9f4840e8f33b4053363a1216bdeb111fad590364960279cb9`. 9,199,555 filas nacionales; 2,366,069 observaciones crudas seleccionadas. Catastro: 22 archivos N/NL del 2S-2026 aportados por el usuario, 1,984,584 roles y 2,513,170 líneas.

Todas las estadísticas de comparables de este informe usan **FI ≥ 01/01/2024**, la ventana de la referencia validada. La ingesta conserva además toda la historia disponible de las comunas solicitadas. Los importes son **precios de transacción declarados**.

## Criterios

| Criterio | Resultado | Evidencia |
|---|---|---|
| 55.156 deptos, ocho comunas, ±1% | No cumplido | 54,344; diferencia -1.472% |
| Ocho medianas UF/m² H dentro de ±2% | Cumplido | Ver tabla de medianas |
| Join F2890 → catastro ≥93% por comuna | No cumplido | Ver porcentajes, sobre observaciones deduplicadas |
| Segunda corrida, cero filas nuevas | Cumplido | {"passed": true, "catastro_rows_new": 0, "catastro_files_unchanged": 22, "f2890_rows_new": 0, "transfer_rows_new": 0, "geo_rows_new": 0, "counts_unchanged": true, "transfer_fingerprint_unchanged": true} |
| Descarga automática desde la página pública SII | Cumplido | F2890_01-10-2026.zip; hash idéntico; cero filas nuevas |
| Downgrade reversible, sin alterar tablas existentes | Cumplido | Pruebas en Postgres desechable 55433, con datos; calendario existente conservado; upgrade posterior correcto |
| Flag apagado, suite existente verde y health idéntico | Cumplido | 2.011 pruebas pasadas (1.999 existentes + primeras 12 SII); 21 pruebas SII finales pasadas, incluidas health, downgrade y validación de integridad ante fallo |
| Operación exclusivamente local | Cumplido | Postgres 127.0.0.1:55432; prueba separada 55433; URLs no locales rechazadas; sin Oracle, SSH, deploy ni CI de producción |
| Geo: tabla/job, tres métodos y reporte | Cumplido con fallback permitido | Métodos probados con datos sintéticos; cobertura real 0%, pendiente extracto OSM local; cero peticiones a Nominatim público |
| Crudos + tablas ≤10 GB | Cumplido | 4.481 GB decimales |

## Medianas del benchmark

Santiago corresponde exclusivamente a SII 13101. Oeste y Sur no entran en el total de 55.156 ni en la meta de 55,1 UF/m².

| Comuna SII | Nombre | Esperada H | Obtenida H | Diferencia | Cumple ±2% |
|---|---|---:|---:|---:|---|
| 13101 | SANTIAGO | 55.1 | 55.88 | 1.408% | Cumplido |
| 14157 | ESTACION CENTRAL | 47.8 | 48.20 | 0.834% | Cumplido |
| 15103 | PROVIDENCIA | 76.9 | 76.97 | 0.096% | Cumplido |
| 15105 | ÑUÑOA | 80.3 | 80.31 | 0.015% | Cumplido |
| 15108 | LAS CONDES | 87.7 | 87.99 | 0.326% | Cumplido |
| 15128 | LA FLORIDA | 73.2 | 73.31 | 0.152% | Cumplido |
| 15160 | VITACURA | 95.9 | 95.89 | -0.010% | Cumplido |
| 16106 | SAN MIGUEL | 51.1 | 51.08 | -0.036% | Cumplido |

## Diferencias concretas de aceptación

El conteo solicitado es 55.156 ±1% (mínimo entero: 54.605). El resultado es 54,344, diferencia -812. Se aplicaron el token literal DP, el rango 15–500 UF/m² y la exclusión de cualquier monto positivo repetido en el grupo que pide el encargo.

El script de referencia `join6.py` también admite DEPTO/DPTO/DEP, limita a 300 UF/m² y excluye repetidos solo cuando **todas** las filas del grupo tienen importe positivo e idéntico. La tabla siguiente mide cada diferencia de repetidos/techo sobre la población actual; no son escenarios acumulativos ni reemplazan los criterios solicitados.

| SII | Comparables actuales | Filas adicionales con repetidos de referencia | Filas actuales sobre 300 UF/m² | Cinco roles afectados por repetidos |
|---|---:|---:|---:|---|
| 13101 | 11,058 | 127 | 4 | 13101-189-152, 13101-189-164, 13101-213-168, 13101-213-169, 13101-213-178 |
| 14157 | 3,066 | 77 | 1 | 14157-505-220, 14157-505-221, 14157-505-222, 14157-505-223, 14157-506-600 |
| 15103 | 4,989 | 13 | 0 | 15103-633-191, 15103-633-244, 15103-1043-657, 15103-1043-660, 15103-1128-685 |
| 15105 | 13,498 | 55 | 1 | 15105-9-714, 15105-9-715, 15105-25-30, 15105-25-31, 15105-28-92 |
| 15108 | 7,137 | 56 | 1 | 15108-238-214, 15108-238-215, 15108-259-90, 15108-259-125, 15108-291-132 |
| 15128 | 9,371 | 74 | 0 | 15128-2-437, 15128-2-449, 15128-7-136, 15128-7-283, 15128-32-100 |
| 15160 | 2,193 | 13 | 0 | 15160-461-125, 15160-461-126, 15160-1201-61, 15160-1201-64, 15160-1853-52 |
| 16106 | 3,032 | 27 | 0 | 16106-360-20, 16106-360-66, 16106-360-147, 16106-360-148, 16106-360-154 |

Reproducción de solo lectura de las reglas de `join6.py` sobre estas mismas fuentes: **55,153** departamentos. Es un diagnóstico separado; el cache conserva las reglas del encargo.

| SII | Referencia reproducida | Actual | Cinco roles que entran solo con la referencia |
|---|---:|---:|---|
| 13101 | 11,387 | 11,058 | 13101-57-185, 13101-57-219, 13101-57-237, 13101-57-264, 13101-57-323 |
| 14157 | 3,142 | 3,066 | 14157-505-220, 14157-505-221, 14157-505-222, 14157-505-223, 14157-506-600 |
| 15103 | 5,015 | 4,989 | 15103-406-30, 15103-512-274, 15103-633-191, 15103-633-244, 15103-854-86 |
| 15105 | 13,573 | 13,498 | 15105-9-714, 15105-9-715, 15105-13-45, 15105-25-30, 15105-25-31 |
| 15108 | 7,272 | 7,137 | 15108-206-160, 15108-206-230, 15108-212-196, 15108-220-670, 15108-224-478 |
| 15128 | 9,491 | 9,371 | 15128-2-437, 15128-2-449, 15128-7-136, 15128-7-283, 15128-32-100 |
| 15160 | 2,210 | 2,193 | 15160-403-513, 15160-415-110, 15160-415-117, 15160-461-125, 15160-461-126 |
| 16106 | 3,063 | 3,032 | 16106-360-20, 16106-360-66, 16106-360-147, 16106-360-148, 16106-360-154 |

Huechuraba (SII 14158): 5.356 de 6.564 observaciones deduplicadas cruzan con el catastro, **81,5966%**, frente a ≥93%. Hay 1.208 sin cruce. Las manzanas 3115 y 3116 concentran 1.053 de esas observaciones. Una lectura directa del archivo N original confirmó que no contiene ningún rol de esas dos manzanas (tampoco de 7080). La causa histórica requiere evidencia adicional. Santiago Oeste (sector adicional 13134) da 87,7028%; se informa por separado y conserva su llave original.

| Manzana Huechuraba | Observaciones sin cruce | Cinco roles |
|---|---:|---|
| 3116 | 813 | 14158-3116-5, 14158-3116-6, 14158-3116-7, 14158-3116-8, 14158-3116-9 |
| 3115 | 240 | 14158-3115-1, 14158-3115-2, 14158-3115-3, 14158-3115-4, 14158-3115-5 |
| 6052 | 87 | 14158-6052-21, 14158-6052-22, 14158-6052-23, 14158-6052-24, 14158-6052-25 |
| 7080 | 60 | 14158-7080-2, 14158-7080-6, 14158-7080-8, 14158-7080-9, 14158-7080-10 |
| 3130 | 3 | 14158-3130-47, 14158-3130-47, 14158-3130-49 |

## Conteos por comuna y sector

Denominador geo: todos los roles del catastro activo de cada sector. El CSV adjunto conserva los valores completos y el campo separado `comuna_ine`.

| SII | Nombre | Deptos | Casas | Med. depto UF/m² cerrado | Med. casa UF/m² cerrado | Join | Geo exacto / interp. / errata |
|---|---|---:|---:|---:|---:|---:|---|
| 13101 | SANTIAGO | 11,058 | 614 | 57.01 | 42.21 | 93.58% | 0.0% / 0.0% / 0.0% |
| 13134 | SANTIAGO OESTE | 2,383 | 522 | 61.67 | 35.52 | 87.70% | 0.0% / 0.0% / 0.0% |
| 13135 | SANTIAGO SUR | 3,518 | 650 | 68.78 | 35.83 | 97.05% | 0.0% / 0.0% / 0.0% |
| 14157 | ESTACION CENTRAL | 3,066 | 771 | 48.20 | 30.07 | 99.99% | 0.0% / 0.0% / 0.0% |
| 14158 | HUECHURABA | 630 | 1,345 | 54.39 | 55.47 | 81.60% | 0.0% / 0.0% / 0.0% |
| 15103 | PROVIDENCIA | 4,989 | 644 | 76.97 | 64.34 | 94.14% | 0.0% / 0.0% / 0.0% |
| 15105 | ÑUÑOA | 13,498 | 1,360 | 80.31 | 51.28 | 98.30% | 0.0% / 0.0% / 0.0% |
| 15108 | LAS CONDES | 7,137 | 2,692 | 87.99 | 89.58 | 98.28% | 0.0% / 0.0% / 0.0% |
| 15128 | LA FLORIDA | 9,371 | 3,890 | 73.31 | 36.94 | 98.36% | 0.0% / 0.0% / 0.0% |
| 15132 | LA REINA | 488 | 1,277 | 80.06 | 72.00 | 99.89% | 0.0% / 0.0% / 0.0% |
| 15160 | VITACURA | 2,193 | 1,200 | 95.91 | 106.16 | 99.27% | 0.0% / 0.0% / 0.0% |
| 15161 | LO BARNECHEA | 1,348 | 1,799 | 89.96 | 91.05 | 96.97% | 0.0% / 0.0% / 0.0% |
| 16106 | SAN MIGUEL | 3,032 | 489 | 51.08 | 34.48 | 99.82% | 0.0% / 0.0% / 0.0% |

**Santiago completo, comuna_ine=13101 (SII 13101 + 13134 + 13135):** 16,959 deptos y 1,786 casas comparables; mediana deptos UF/m² H 59.09, cerrado 60.06; casas cerrado 38.47; join 93.22%. Las llaves siempre conservan el código SII original.

## Disco y operación

Crudos y auxiliares: 563,126,980 bytes (0.563 GB). Tablas e índices SII: 3,917,594,624 bytes (3.918 GB). Total: 4,480,721,604 bytes (4.481 GB). No supera 10 GB. No incluye WAL, temporales de reconstrucción, respaldos ni el tamaño asignado del disco Docker; necesitan margen adicional.

La validación usa el contenedor local `valoria-sii-local-20261017`, puerto 55432. Se conserva con sus datos para revisión. `.env.local` mantiene el flag apagado por defecto; los comandos de validación lo activaron solo en su proceso. El calendario UF se preparó en la base nueva con autorización explícita del usuario, reutilizando la tabla y parser existentes y HTML oficial cacheado; no se agregó otra fuente ni un bootstrap en las migraciones SII.

No se arrancó un servicio semanal persistente: queda implementado el comando local `python -m scripts.sii_ingest schedule` (domingo 03:00 de Chile). Importación de catastro y rebuild siguen siendo manuales.

## Reglas y límites de interpretación

Se conserva toda fila cruda, incluidas fechas inválidas y roles incompletos, con sus campos originales y motivos explícitos. El archivo catastral trae códigos, no nombres de comuna: los nombres del reporte se contrastaron con la tabla oficial. El grupo (SII, manzana, FE, FI) es solo un proxy de escritura; F2890 no trae un identificador de escritura ni naturaleza del acto. Un cierre comparable no acredita por sí solo una compraventa entre partes independientes.

La referencia externa usaba techo 300 UF/m² y aliases DP/DEPTO/DPTO/DEP. Esta implementación aplica el techo solicitado de 500 y el token literal DP. UF positiva prevalece; para CLP se usa el día exacto de FE, o FI si FE falta. No se rellena una UF histórica ausente con otra fecha. La diferencia entre criterios, si es material, queda visible en las métricas.

Geocodificación real pendiente: no se incorporó un extracto OSM local en esta fase. La tabla y el job aceptan un CSV de direcciones OSM, hacen exacto, interpolación dentro de la misma manzana y corrección difflib ≥0,8 al mismo número. Se verificaron los tres métodos en Postgres, sin peticiones a Nominatim público ni SII Mapas.

## Para Fase 2

- Construir la hoja de vida sobre (comuna SII, manzana, predio), fuentes y versiones conservadas, con una política explícita de cambios históricos de dirección/superficie.
- Presentar importe declarado, fecha y UF usada, paquete y todos los motivos de exclusión; distinguir el proxy de escritura de un acto legal acreditado.
- Incorporar un extracto OSM local con límites/sectores bien asignados y revisar las coordenadas y su precisión heurística antes de usarlas en producto.
- Definir contratos y permisos de consulta de la hoja de vida y la futura operación fuera del entorno local; esta fase no implementa endpoints de producto ni modifica el motor de tasación.

## Exclusiones y ejemplos

Las reglas pueden solaparse; sus conteos no se suman como una partición. Se conservan hasta cinco roles por comuna y motivo para diagnóstico.

| SII | Motivo | Filas | Cinco roles de ejemplo |
|---|---|---:|---|
| 13101 | bloque_3_casas_misma_manzana | 517 | 13101-367-5, 13101-367-45, 13101-367-84, 13101-367-105, 13101-367-147 |
| 13101 | duplicado_rol_fecha | 577 | 13101-13-350, 13101-13-694, 13101-13-744, 13101-16-238, 13101-16-268 |
| 13101 | lote_10_deptos | 721 | 13101-140-833, 13101-140-834, 13101-140-835, 13101-140-838, 13101-140-840 |
| 13101 | m2_fuera_20_300 | 205 | 13101-14-253, 13101-122-198, 13101-124-78, 13101-124-78, 13101-124-83 |
| 13101 | monto_repetido_en_grupo | 1,326 | 13101-49-159, 13101-49-251, 13101-111-223, 13101-122-342, 13101-122-343 |
| 13101 | paquete_estac_bodega_sin_monto | 721 | 13101-2-313, 13101-13-350, 13101-13-350, 13101-44-169, 13101-44-176 |
| 13101 | sin_catastro | 1,752 | 13101-201-310, 13101-201-322, 13101-201-323, 13101-201-329, 13101-233-580 |
| 13101 | sin_m2 | 4 | 13101-1-99, 13101-46-28, 13101-478-144, 13101-607-32 |
| 13101 | sin_monto | 1,278 | 13101-2-330, 13101-13-744, 13101-13-878, 13101-33-115, 13101-44-240 |
| 13101 | sin_uf_fecha_exacta | 14 | 13101-2-11, 13101-37-39, 13101-103-260, 13101-124-75, 13101-134-129 |
| 13101 | tipo_no_comparable | 11,393 | 13101-1-22, 13101-1-83, 13101-1-114, 13101-1-123, 13101-2-61 |
| 13101 | uf_m2_fuera_15_500 | 278 | 13101-2-30, 13101-2-204, 13101-2-214, 13101-2-310, 13101-6-5 |
| 13134 | bloque_3_casas_misma_manzana | 642 | 13134-275-76, 13134-275-87, 13134-275-90, 13134-275-103, 13134-275-119 |
| 13134 | duplicado_rol_fecha | 113 | 13134-20-49, 13134-23-122, 13134-23-155, 13134-24-260, 13134-24-272 |
| 13134 | lote_10_deptos | 396 | 13134-234-19, 13134-234-20, 13134-234-21, 13134-234-22, 13134-234-25 |
| 13134 | m2_fuera_20_300 | 67 | 13134-24-21, 13134-234-18, 13134-234-22, 13134-234-26, 13134-234-30 |
| 13134 | monto_repetido_en_grupo | 783 | 13134-22-184, 13134-22-192, 13134-77-130, 13134-77-133, 13134-77-432 |
| 13134 | paquete_estac_bodega_sin_monto | 226 | 13134-20-59, 13134-20-353, 13134-22-148, 13134-23-149, 13134-24-21 |
| 13134 | sin_catastro | 1,008 | 13134-38-556, 13134-52-72, 13134-52-77, 13134-52-81, 13134-52-84 |
| 13134 | sin_monto | 341 | 13134-20-199, 13134-20-429, 13134-22-273, 13134-22-350, 13134-22-351 |
| 13134 | sin_uf_fecha_exacta | 13 | 13134-20-477, 13134-47-324, 13134-47-325, 13134-163-104, 13134-205-65 |
| 13134 | tipo_no_comparable | 2,780 | 13134-20-164, 13134-20-172, 13134-20-184, 13134-20-199, 13134-20-208 |
| 13134 | uf_m2_fuera_15_500 | 276 | 13134-25-6, 13134-26-2, 13134-29-6, 13134-30-31, 13134-34-27 |
| 13135 | bloque_3_casas_misma_manzana | 393 | 13135-2831-50, 13135-2831-60, 13135-2831-65, 13135-2831-100, 13135-2831-150 |
| 13135 | duplicado_rol_fecha | 112 | 13135-2771-464, 13135-2771-634, 13135-2771-745, 13135-2772-71, 13135-2772-486 |
| 13135 | lote_10_deptos | 335 | 13135-3389-568, 13135-3389-569, 13135-3389-571, 13135-3389-572, 13135-3389-573 |
| 13135 | m2_fuera_20_300 | 34 | 13135-2821-77, 13135-2821-141, 13135-2821-154, 13135-2821-180, 13135-2888-32 |
| 13135 | monto_repetido_en_grupo | 518 | 13135-2771-145, 13135-2771-238, 13135-2771-278, 13135-2771-464, 13135-2772-598 |
| 13135 | paquete_estac_bodega_sin_monto | 258 | 13135-2771-448, 13135-2771-464, 13135-2771-464, 13135-2773-101, 13135-2796-253 |
| 13135 | sin_catastro | 276 | 13135-2786-10, 13135-2808-260, 13135-2808-263, 13135-2808-264, 13135-2808-268 |
| 13135 | sin_m2 | 3 | 13135-3079-34, 13135-3079-34, 13135-3186-15 |
| 13135 | sin_monto | 454 | 13135-2771-590, 13135-2771-634, 13135-2771-634, 13135-2771-745, 13135-2771-753 |
| 13135 | sin_uf_fecha_exacta | 6 | 13135-3044-5, 13135-3081-18, 13135-3104-18, 13135-3643-36, 13135-3707-74 |
| 13135 | tipo_no_comparable | 3,602 | 13135-2771-502, 13135-2771-507, 13135-2771-528, 13135-2771-530, 13135-2771-536 |
| 13135 | uf_m2_fuera_15_500 | 255 | 13135-2772-157, 13135-2782-28, 13135-2783-25, 13135-2784-9, 13135-2786-9 |
| 14157 | bloque_3_casas_misma_manzana | 4 | 14157-597-12, 14157-597-13, 14157-597-48, 14157-597-50 |
| 14157 | duplicado_rol_fecha | 10 | 14157-395-205, 14157-506-254, 14157-543-294, 14157-544-815, 14157-605-272 |
| 14157 | lote_10_deptos | 1,186 | 14157-505-208, 14157-505-209, 14157-505-210, 14157-505-211, 14157-505-212 |
| 14157 | m2_fuera_20_300 | 33 | 14157-509-68, 14157-528-99, 14157-528-99, 14157-528-191, 14157-528-224 |
| 14157 | monto_repetido_en_grupo | 1,060 | 14157-505-208, 14157-505-209, 14157-505-210, 14157-505-211, 14157-505-212 |
| 14157 | paquete_estac_bodega_sin_monto | 156 | 14157-497-443, 14157-497-505, 14157-498-464, 14157-504-56, 14157-506-139 |
| 14157 | sin_catastro | 1 | 14157-1025-7 |
| 14157 | sin_m2 | 1 | 14157-645-34 |
| 14157 | sin_monto | 258 | 14157-251-19, 14157-251-149, 14157-251-366, 14157-251-651, 14157-251-689 |
| 14157 | sin_uf_fecha_exacta | 10 | 14157-640-33, 14157-1775-21, 14157-2221-15, 14157-2604-18, 14157-3465-64 |
| 14157 | tipo_no_comparable | 2,639 | 14157-251-16, 14157-251-19, 14157-251-19, 14157-251-20, 14157-251-26 |
| 14157 | uf_m2_fuera_15_500 | 452 | 14157-343-15, 14157-344-12, 14157-344-14, 14157-344-17, 14157-344-31 |
| 14158 | bloque_3_casas_misma_manzana | 305 | 14158-5-4, 14158-5-5, 14158-5-6, 14158-60-129, 14158-60-131 |
| 14158 | duplicado_rol_fecha | 142 | 14158-16-27, 14158-21-11, 14158-23-44, 14158-24-121, 14158-26-24 |
| 14158 | lote_10_deptos | 131 | 14158-4446-1, 14158-4446-2, 14158-4446-4, 14158-4446-5, 14158-4446-6 |
| 14158 | monto_repetido_en_grupo | 244 | 14158-5-4, 14158-5-5, 14158-5-6, 14158-102-201, 14158-112-33 |
| 14158 | paquete_estac_bodega_sin_monto | 49 | 14158-13-39, 14158-13-48, 14158-13-101, 14158-66-121, 14158-77-394 |
| 14158 | sin_catastro | 1,208 | 14158-33-1, 14158-3110-6, 14158-3115-1, 14158-3115-2, 14158-3115-3 |
| 14158 | sin_monto | 259 | 14158-13-158, 14158-13-228, 14158-13-264, 14158-13-296, 14158-13-328 |
| 14158 | sin_uf_fecha_exacta | 7 | 14158-3-12, 14158-4002-1, 14158-4045-3, 14158-4326-8, 14158-4331-16 |
| 14158 | tipo_no_comparable | 2,761 | 14158-13-141, 14158-13-142, 14158-13-143, 14158-13-144, 14158-13-144 |
| 14158 | uf_m2_fuera_15_500 | 222 | 14158-16-27, 14158-23-44, 14158-40-11, 14158-55-125, 14158-55-238 |
| 15103 | bloque_3_casas_misma_manzana | 4 | 15103-4309-417, 15103-4309-418, 15103-4309-419, 15103-4309-466 |
| 15103 | duplicado_rol_fecha | 389 | 15103-19-272, 15103-19-276, 15103-20-603, 15103-22-372, 15103-25-15 |
| 15103 | lote_10_deptos | 620 | 15103-17-960, 15103-17-961, 15103-17-962, 15103-17-963, 15103-17-964 |
| 15103 | m2_fuera_20_300 | 14 | 15103-17-393, 15103-17-449, 15103-130-177, 15103-130-204, 15103-130-204 |
| 15103 | monto_repetido_en_grupo | 506 | 15103-12-200, 15103-12-233, 15103-17-960, 15103-17-961, 15103-17-962 |
| 15103 | paquete_estac_bodega_sin_monto | 758 | 15103-12-94, 15103-12-243, 15103-16-412, 15103-17-393, 15103-19-185 |
| 15103 | sin_catastro | 1,276 | 15103-23-18, 15103-405-1, 15103-405-2, 15103-405-3, 15103-405-4 |
| 15103 | sin_m2 | 3 | 15103-517-73, 15103-864-62, 15103-917-20 |
| 15103 | sin_monto | 1,749 | 15103-12-331, 15103-12-505, 15103-12-637, 15103-12-872, 15103-16-538 |
| 15103 | sin_uf_fecha_exacta | 10 | 15103-406-19, 15103-623-186, 15103-644-197, 15103-854-154, 15103-929-119 |
| 15103 | tipo_no_comparable | 13,554 | 15103-12-82, 15103-12-221, 15103-12-405, 15103-12-406, 15103-12-413 |
| 15103 | uf_m2_fuera_15_500 | 236 | 15103-12-65, 15103-12-65, 15103-12-200, 15103-12-233, 15103-12-357 |
| 15105 | duplicado_rol_fecha | 516 | 15105-4-333, 15105-4-423, 15105-4-552, 15105-4-583, 15105-4-584 |
| 15105 | lote_10_deptos | 2,053 | 15105-59-1, 15105-59-2, 15105-59-3, 15105-59-4, 15105-59-5 |
| 15105 | m2_fuera_20_300 | 1 | 15105-6303-96 |
| 15105 | monto_repetido_en_grupo | 1,811 | 15105-2-508, 15105-2-511, 15105-2-518, 15105-2-521, 15105-9-714 |
| 15105 | paquete_estac_bodega_sin_monto | 1,370 | 15105-4-397, 15105-5-375, 15105-5-383, 15105-9-198, 15105-9-536 |
| 15105 | sin_catastro | 662 | 15105-43-47, 15105-43-47, 15105-1262-407, 15105-3000-2, 15105-3001-619 |
| 15105 | sin_monto | 2,267 | 15105-3-52, 15105-3-96, 15105-3-438, 15105-4-552, 15105-4-583 |
| 15105 | sin_uf_fecha_exacta | 6 | 15105-1219-483, 15105-5708-1, 15105-6132-36, 15105-6132-185, 15105-6406-199 |
| 15105 | tipo_no_comparable | 19,750 | 15105-3-52, 15105-3-76, 15105-3-80, 15105-3-96, 15105-3-111 |
| 15105 | uf_m2_fuera_15_500 | 437 | 15105-13-17, 15105-13-379, 15105-23-155, 15105-27-455, 15105-32-102 |
| 15108 | bloque_3_casas_misma_manzana | 16 | 15108-354-37, 15108-354-38, 15108-354-39, 15108-910-726, 15108-910-727 |
| 15108 | duplicado_rol_fecha | 410 | 15108-199-13, 15108-199-93, 15108-199-95, 15108-199-97, 15108-199-212 |
| 15108 | lote_10_deptos | 186 | 15108-719-435, 15108-719-436, 15108-719-438, 15108-719-439, 15108-719-440 |
| 15108 | m2_fuera_20_300 | 72 | 15108-223-191, 15108-225-4, 15108-225-13, 15108-225-16, 15108-245-98 |
| 15108 | monto_repetido_en_grupo | 264 | 15108-228-165, 15108-238-214, 15108-238-215, 15108-251-316, 15108-251-415 |
| 15108 | paquete_estac_bodega_sin_monto | 1,401 | 15108-200-323, 15108-200-411, 15108-203-481, 15108-203-639, 15108-206-102 |
| 15108 | sin_catastro | 669 | 15108-231-32, 15108-319-341, 15108-319-341, 15108-331-1, 15108-331-10 |
| 15108 | sin_m2 | 1 | 15108-314-5 |
| 15108 | sin_monto | 3,667 | 15108-200-176, 15108-200-240, 15108-200-261, 15108-200-419, 15108-200-487 |
| 15108 | sin_uf_fecha_exacta | 12 | 15108-277-244, 15108-464-86, 15108-502-181, 15108-586-12, 15108-609-4 |
| 15108 | tipo_no_comparable | 26,572 | 15108-139-44, 15108-139-113, 15108-139-132, 15108-139-178, 15108-199-3 |
| 15108 | uf_m2_fuera_15_500 | 312 | 15108-205-100, 15108-205-174, 15108-209-230, 15108-217-242, 15108-220-189 |
| 15128 | bloque_3_casas_misma_manzana | 34 | 15128-479-19, 15128-479-20, 15128-479-21, 15128-479-46, 15128-479-47 |
| 15128 | duplicado_rol_fecha | 40 | 15128-59-506, 15128-111-142, 15128-111-472, 15128-111-543, 15128-131-115 |
| 15128 | lote_10_deptos | 1,839 | 15128-31-1, 15128-31-2, 15128-31-3, 15128-31-4, 15128-31-5 |
| 15128 | m2_fuera_20_300 | 78 | 15128-5-359, 15128-100-441, 15128-100-452, 15128-100-463, 15128-100-476 |
| 15128 | monto_repetido_en_grupo | 1,938 | 15128-2-437, 15128-2-449, 15128-7-11, 15128-7-13, 15128-7-78 |
| 15128 | paquete_estac_bodega_sin_monto | 1,053 | 15128-2-90, 15128-2-353, 15128-2-378, 15128-2-393, 15128-2-395 |
| 15128 | sin_catastro | 464 | 15128-31-496, 15128-31-497, 15128-31-500, 15128-31-501, 15128-31-502 |
| 15128 | sin_m2 | 2 | 15128-1921-76, 15128-2510-8 |
| 15128 | sin_monto | 1,019 | 15128-2-185, 15128-2-528, 15128-2-538, 15128-2-597, 15128-2-608 |
| 15128 | sin_uf_fecha_exacta | 15 | 15128-541-5, 15128-571-6, 15128-776-41, 15128-796-31, 15128-869-5 |
| 15128 | tipo_no_comparable | 10,946 | 15128-2-13, 15128-2-165, 15128-2-185, 15128-2-191, 15128-2-192 |
| 15128 | uf_m2_fuera_15_500 | 850 | 15128-2-378, 15128-5-37, 15128-32-57, 15128-51-528, 15128-59-506 |
| 15132 | duplicado_rol_fecha | 43 | 15132-40-13, 15132-100-603, 15132-100-924, 15132-110-450, 15132-110-491 |
| 15132 | m2_fuera_20_300 | 1 | 15132-100-342 |
| 15132 | monto_repetido_en_grupo | 13 | 15132-1122-4, 15132-1122-10, 15132-3002-119, 15132-3002-119, 15132-3002-124 |
| 15132 | paquete_estac_bodega_sin_monto | 49 | 15132-100-355, 15132-100-483, 15132-100-603, 15132-100-603, 15132-101-97 |
| 15132 | sin_catastro | 4 | 15132-500-126, 15132-600-47, 15132-6550-32, 15132-7055-10 |
| 15132 | sin_monto | 100 | 15132-100-391, 15132-100-762, 15132-100-779, 15132-100-924, 15132-101-246 |
| 15132 | sin_uf_fecha_exacta | 2 | 15132-3003-189, 15132-5055-237 |
| 15132 | tipo_no_comparable | 1,824 | 15132-1-5, 15132-6-7, 15132-64-84, 15132-64-384, 15132-64-388 |
| 15132 | uf_m2_fuera_15_500 | 135 | 15132-20-19, 15132-40-37, 15132-40-37, 15132-64-54, 15132-64-149 |
| 15160 | bloque_3_casas_misma_manzana | 9 | 15160-431-265, 15160-431-266, 15160-431-306, 15160-1853-1, 15160-1853-2 |
| 15160 | duplicado_rol_fecha | 221 | 15160-111-156, 15160-111-278, 15160-115-476, 15160-115-503, 15160-115-604 |
| 15160 | lote_10_deptos | 39 | 15160-475-410, 15160-475-411, 15160-475-412, 15160-475-413, 15160-475-414 |
| 15160 | m2_fuera_20_300 | 40 | 15160-473-451, 15160-531-58, 15160-1185-266, 15160-1285-22, 15160-3005-413 |
| 15160 | monto_repetido_en_grupo | 64 | 15160-461-125, 15160-461-126, 15160-475-410, 15160-475-411, 15160-475-412 |
| 15160 | paquete_estac_bodega_sin_monto | 433 | 15160-115-119, 15160-115-124, 15160-115-148, 15160-401-124, 15160-401-153 |
| 15160 | sin_catastro | 104 | 15160-431-518, 15160-431-519, 15160-497-15, 15160-497-20, 15160-497-22 |
| 15160 | sin_m2 | 2 | 15160-923-10, 15160-1439-16 |
| 15160 | sin_monto | 1,284 | 15160-111-156, 15160-111-278, 15160-115-255, 15160-115-265, 15160-115-267 |
| 15160 | sin_uf_fecha_exacta | 3 | 15160-927-395, 15160-1169-267, 15160-3401-324 |
| 15160 | tipo_no_comparable | 9,892 | 15160-111-120, 15160-111-125, 15160-111-137, 15160-111-278, 15160-111-278 |
| 15160 | uf_m2_fuera_15_500 | 79 | 15160-115-124, 15160-401-529, 15160-403-15, 15160-405-724, 15160-405-744 |
| 15161 | bloque_3_casas_misma_manzana | 26 | 15161-3688-76, 15161-3688-77, 15161-3688-78, 15161-3779-57, 15161-3779-58 |
| 15161 | duplicado_rol_fecha | 131 | 15161-2377-154, 15161-2377-339, 15161-2377-369, 15161-2377-370, 15161-2377-387 |
| 15161 | lote_10_deptos | 39 | 15161-3012-156, 15161-3012-157, 15161-3012-158, 15161-3012-159, 15161-3012-160 |
| 15161 | m2_fuera_20_300 | 42 | 15161-3102-2, 15161-3485-398, 15161-3512-132, 15161-3538-468, 15161-3538-469 |
| 15161 | monto_repetido_en_grupo | 47 | 15161-3012-156, 15161-3012-157, 15161-3012-158, 15161-3012-159, 15161-3012-161 |
| 15161 | paquete_estac_bodega_sin_monto | 229 | 15161-2371-46, 15161-2371-90, 15161-2371-102, 15161-2371-143, 15161-2371-281 |
| 15161 | sin_catastro | 303 | 15161-3001-1, 15161-3001-5, 15161-3001-9, 15161-3001-10, 15161-3001-12 |
| 15161 | sin_m2 | 8 | 15161-2830-17, 15161-3016-206, 15161-3016-207, 15161-3024-62, 15161-3080-5 |
| 15161 | sin_monto | 718 | 15161-2371-322, 15161-2371-376, 15161-2371-442, 15161-2371-443, 15161-2371-472 |
| 15161 | tipo_no_comparable | 6,208 | 15161-2371-309, 15161-2371-310, 15161-2371-322, 15161-2371-325, 15161-2371-333 |
| 15161 | uf_m2_fuera_15_500 | 84 | 15161-2365-20, 15161-2367-3, 15161-2369-26, 15161-2371-81, 15161-2371-82 |
| 16106 | bloque_3_casas_misma_manzana | 8 | 16106-5548-51, 16106-5548-58, 16106-5548-77, 16106-5548-140, 16106-5548-160 |
| 16106 | duplicado_rol_fecha | 10 | 16106-354-318, 16106-652-535, 16106-3853-682, 16106-5354-2, 16106-5554-20 |
| 16106 | lote_10_deptos | 326 | 16106-3443-345, 16106-3443-346, 16106-3443-347, 16106-3443-348, 16106-3443-349 |
| 16106 | m2_fuera_20_300 | 42 | 16106-2940-235, 16106-3861-445, 16106-3861-457, 16106-3861-466, 16106-3861-469 |
| 16106 | monto_repetido_en_grupo | 352 | 16106-360-20, 16106-360-66, 16106-360-147, 16106-360-148, 16106-360-154 |
| 16106 | paquete_estac_bodega_sin_monto | 273 | 16106-354-29, 16106-354-211, 16106-354-354, 16106-354-354, 16106-360-113 |
| 16106 | sin_catastro | 15 | 16106-652-744, 16106-1960-269, 16106-2746-16, 16106-3440-8, 16106-3440-8 |
| 16106 | sin_m2 | 3 | 16106-3440-129, 16106-4751-31, 16106-5339-13 |
| 16106 | sin_monto | 476 | 16106-354-109, 16106-354-167, 16106-354-288, 16106-354-418, 16106-354-418 |
| 16106 | sin_uf_fecha_exacta | 6 | 16106-1960-100, 16106-2956-45, 16106-3552-563, 16106-4840-37, 16106-5837-13 |
| 16106 | tipo_no_comparable | 3,744 | 16106-354-88, 16106-354-109, 16106-354-120, 16106-354-137, 16106-354-148 |
| 16106 | uf_m2_fuera_15_500 | 241 | 16106-640-5, 16106-643-27, 16106-643-28, 16106-645-8, 16106-652-63 |

## Evidencia técnica

- Métricas completas: `sii_metricas.json`.
- Conteos: `sii_conteos_por_comuna.csv`.
- Perfil de fuentes y errores de parseo: `sii_perfil_fuentes.json`.
- Código y operación: `docs/sii_ingest.md` en el PR.
