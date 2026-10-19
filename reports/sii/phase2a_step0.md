# SII Fase 2a · Control previo de producción · 19/10/2026

**Resultado: PARADA EN PASO 0.** Siete de ocho comunas están bajo el 40% de dirección exacta o coordenadas publicadas en los campos del PR #5. Se aplica la condición de parada del encargo; los pasos de geocodificación, enlace y muestra de 100 no se ejecutan.

Corte de datos: **19/10/2026 17:49:06 Europe/Berlin**, `2026-10-19T15:49:06.745452+00:00`. Una transacción PostgreSQL `REPEATABLE READ, READ ONLY`, comprobada mediante `transaction_read_only=on`, con statement timeout de 20 s, lock timeout de 1 s y rollback. El script se ejecuta por stdin con `python -B` en el contenedor API existente. No se instala código ni se despliega una imagen.

## Base y merge autorizado

El PR #9 se marcó listo y se mergeó a `release/canonical-only-reproducible-20261013`, commit `24b56dc6fe626d19834bcd6707a9b77d1d3d44c7`, sin deploy. Se verificó que el release no contiene workflows de GitHub Actions. La nueva rama `feature/sii-linkage-phase2a-20261019` parte de ese merge.

## Definiciones del control

- Denominador: avisos con estado canónico `active` y tipo departamento en las ocho comunas. No equivale a vigencia comercial comprobada ni a inmuebles únicos.
- Dirección: calle y número cívico exactos, con procedencia y observación vinculada a la misma identidad de publicación; se excluyen rangos, cruces, marcadores de unidad y el caso de tomar el departamento como número de calle.
- Coordenadas publicadas: pareja válida para Chile en los campos del PR #5, vinculada a la misma publicación y con origen del portal. Se excluyen centroides/inferencias/oficinas identificados. Se incluyen las de precisión `unknown` como dato disponible; no certifican edificio ni exactitud.
- m² útil explícito: valor positivo con procedencia explícita, en un snapshot vinculado. No se sustituye por m² genérico, construido ni total. Se consideran `published_fields` y `published_detail_fields` válidos.
- Umbral: unión **dirección O coordenadas publicadas**, no suma y no intersección. Menos del 40% en al menos cinco de ocho comunas activa la parada; exactamente 40% pasa. No se usa redondeo para decidir.
- Se muestran aparte las coordenadas canónicas y su unión con dirección. Pueden tener procedencia/precisión distinta; no reemplazan los campos publicados del PR #5 en este control.

## Resultado global

De **2.107 avisos activos**, 287 tienen calle/número (13,62%), 309 coordenadas publicadas (14,67%) y 143 m² útil explícito (6,79%). La unión de dirección o coordenadas es **536/2107 = 25,44%**. Solo 126 tienen ubicación y m² útil explícito (5,98%); 15 reúnen los tres campos (0,71%).

## Por comuna

| Comuna | Activos | Calle+número | Coord. publicadas | m² útil explícito | Dirección O coord. | Cobertura | Paso 0 |
|---|---:|---:|---:|---:|---:|---:|---|
| Vitacura | 322 | 31 | 91 | 39 | 117 | 36,34% | No pasa |
| Las Condes | 163 | 2 | 24 | 2 | 26 | 15,95% | No pasa |
| Ñuñoa | 248 | 54 | 20 | 3 | 69 | 27,82% | No pasa |
| Providencia | 185 | 42 | 65 | 13 | 74 | 40,00% | Pasa |
| La Florida | 228 | 45 | 22 | 9 | 65 | 28,51% | No pasa |
| Santiago | 356 | 68 | 20 | 7 | 84 | 23,60% | No pasa |
| San Miguel | 196 | 26 | 47 | 39 | 62 | 31,63% | No pasa |
| Estación Central | 409 | 19 | 20 | 31 | 39 | 9,54% | No pasa |

## Por portal

| Portal | Activos | Calle+número | Coord. publicadas | m² útil explícito | Dirección O coord. | Cobertura |
|---|---:|---:|---:|---:|---:|---:|
| portal | 601 | 257 | 113 | 117 | 325 | 54,08% |
| yapo | 1506 | 30 | 196 | 26 | 211 | 14,01% |

## Por comuna y portal

| Comuna | Portal | Activos | Calle+número | Coord. publicadas | m² útil explícito | Dirección O coord. | Cobertura |
|---|---|---:|---:|---:|---:|---:|---:|
| Vitacura | portal | 57 | 29 | 31 | 32 | 57 | 100,00% |
| Vitacura | yapo | 265 | 2 | 60 | 7 | 60 | 22,64% |
| Las Condes | portal | 0 | 0 | 0 | 0 | 0 | — |
| Las Condes | yapo | 163 | 2 | 24 | 2 | 26 | 15,95% |
| Ñuñoa | portal | 64 | 46 | 0 | 0 | 46 | 71,88% |
| Ñuñoa | yapo | 184 | 8 | 20 | 3 | 23 | 12,50% |
| Providencia | portal | 50 | 41 | 42 | 10 | 50 | 100,00% |
| Providencia | yapo | 135 | 1 | 23 | 3 | 24 | 17,78% |
| La Florida | portal | 43 | 43 | 0 | 2 | 43 | 100,00% |
| La Florida | yapo | 185 | 2 | 22 | 7 | 22 | 11,89% |
| Santiago | portal | 108 | 63 | 1 | 5 | 63 | 58,33% |
| Santiago | yapo | 248 | 5 | 19 | 2 | 21 | 8,47% |
| San Miguel | portal | 47 | 19 | 35 | 38 | 46 | 97,87% |
| San Miguel | yapo | 149 | 7 | 12 | 1 | 16 | 10,74% |
| Estación Central | portal | 232 | 16 | 4 | 30 | 20 | 8,62% |
| Estación Central | yapo | 177 | 3 | 16 | 1 | 19 | 10,73% |

## Causa observada y límites

**La brecha está en los datos publicados almacenados:** 1537 de 2107 avisos no tienen un snapshot PR #5 vinculado a la misma publicación. Solo 126 tienen una observación de detalle vinculada. Yapo concentra 1.506 de los 2.107 avisos y su cobertura de ubicación publicada es 14,01%; Portal alcanza 54,08%, con denominadores muy desiguales por comuna. Las Condes no tiene departamentos activos de Portal en este corte. Estación Central tiene 232 avisos Portal, pero solo 20 tienen dirección o coordenadas publicadas.

Esto no demuestra que el portal jamás publique esos campos ni identifica por sí solo una avería del scraper. Demuestra que la mayoría del inventario activo aún no los tiene almacenados con esa procedencia. Resolver el déficit requiere investigar/recuperar observaciones de avisos, antes de buscar roles en el catastro; esa recuperación no se ejecuta porque el encargo exige parar en este punto.

Todas las **309 coordenadas publicadas** tienen precisión declarada `unknown`, incluso las contadas en el numerador. Tampoco se ha verificado que cada anuncio corresponda a una unidad: hay 237 marcados como proyecto en los snapshots publicados.

Si se admitiera cualquier pareja canónica de lat/lon, aparecen 697 avisos con coordenadas (33,08%) y la unión con dirección sube a 857 (40,67%). Es una medición distinta: no acredita procedencia publicada ni exactitud de edificio. El CSV conserva ambas métricas para evitar confundirlas.

## Cinco avisos que fallan el control por comuna

Son avisos sin dirección exacta ni coordenadas publicadas verificables. No son enlaces intentados; no se genera un rol supuesto para completar una muestra. El CSV de ejemplos conserva los indicadores y la URL.

| Comuna | ID | Portal | Aviso | Motivos |
|---|---:|---|---|---|
| Vitacura | 557 | yapo | [32178639](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-venta-de-4-dorm-en-vitacura/32178639) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Vitacura | 558 | yapo | [32257922](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-venta-3d-2b-1e-en-vitacura/32257922) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Vitacura | 559 | yapo | [32203308](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-venta-de-3-dorm-en-vitacura/32203308) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Vitacura | 560 | yapo | [32202995](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-venta-de-3-dorm-en-vitacura/32202995) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Vitacura | 561 | yapo | [31229915](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/deptos-nuevos-sin-comision-4d-cocina-semicerrada/31229915) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Las Condes | 48 | yapo | [31091338](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-venta-club-de-golf/31091338) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Las Condes | 336 | yapo | [32340355](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-general-carol-urzua/32340355) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Las Condes | 343 | yapo | [32289123](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/para-vivir-invertir-presidente-riesco-el-golf/32289123) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Las Condes | 345 | yapo | [32162512](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-venta-de-3-dorm-en-las-condes/32162512) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Las Condes | 347 | yapo | [28227253](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-la-gloria-las-condes/28227253) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Ñuñoa | 4037 | portalinmobiliario | [MLC-4173014996](https://portalinmobiliario.com/MLC-4173014996-edificio-own-_JM) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Ñuñoa | 4044 | portalinmobiliario | [MLC-4414820762](https://portalinmobiliario.com/MLC-4414820762-edificio-quartz-_JM) | direccion_sin_numero_civico_exacto, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Ñuñoa | 4054 | portalinmobiliario | [MLC-1572707373](https://portalinmobiliario.com/MLC-1572707373-irarrazaval-aldunate-_JM) | direccion_sin_numero_civico_exacto, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Ñuñoa | 4056 | portalinmobiliario | [MLC-1720033917](https://portalinmobiliario.com/MLC-1720033917-edificio-los-leones-nunoa-_JM) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Ñuñoa | 4060 | portalinmobiliario | [MLC-2181866219](https://portalinmobiliario.com/MLC-2181866219-edificio-lux-_JM) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Providencia | 74 | yapo | [32334105](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-3-dormitorios-3-banos/32334105) | direccion_sin_numero_civico_exacto, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Providencia | 276 | yapo | [31752014](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-avenida-luis-thayer-ojeda/31752014) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Providencia | 278 | yapo | [32396839](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/venta-departamento-providencia-3d-3b/32396839) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Providencia | 288 | yapo | [32303287](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/en-marchant-pereira-depto-de-3-dormitorios-2-banos/32303287) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Providencia | 289 | yapo | [32229877](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-venta-de-3d2b-en-providencia-4526uf/32229877) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| La Florida | 519 | yapo | [29478553](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-avenida-vicuna-mackenna-oriente/29478553) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| La Florida | 520 | yapo | [31600263](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-barcelona/31600263) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| La Florida | 521 | yapo | [32640219](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-santa-amalia/32640219) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| La Florida | 522 | yapo | [28701149](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-avenida-vicuna-mackenna-poniente/28701149) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| La Florida | 523 | yapo | [31759527](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/departamento-en-avenida-vicuna-mackenna/31759527) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Santiago | 3917 | portalinmobiliario | [MLC-3621878454](https://portalinmobiliario.com/MLC-3621878454-edificio-centenario-ingevec-_JM) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Santiago | 3990 | portalinmobiliario | [MLC-3621803402](https://portalinmobiliario.com/MLC-3621803402-edificio-tocornal-ingevec-_JM) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Santiago | 3991 | portalinmobiliario | [MLC-1736990499](https://portalinmobiliario.com/MLC-1736990499-sinergia-vicuna-edificio-c-sinergia-_JM) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Santiago | 3993 | portalinmobiliario | [MLC-3625472880](https://portalinmobiliario.com/MLC-3625472880-don-ignacio-ingevec-_JM) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Santiago | 3996 | portalinmobiliario | [MLC-4064369078](https://portalinmobiliario.com/MLC-4064369078-distrito-grajales-sinergia-_JM) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| San Miguel | 7538 | portalinmobiliario | [MLC-4560599764](https://portalinmobiliario.com/MLC-4560599764-departamento-2d-estacionamiento-y-bodega-_JM) | direccion_sin_numero_civico_exacto, sin_coordenadas_publicadas_verificables |
| San Miguel | 10 | yapo | [32261743](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/se-vende-dpto-townhouse-un-estacionamiento-bodega-7807-uf/32261743) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| San Miguel | 43 | yapo | [32300252](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/dpto-n-903-1d-1b-est-calle-berlin-metro-san-mi/32300252) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| San Miguel | 107 | yapo | [31417284](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/venta-depto-san-miguel-2d-1b/31417284) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| San Miguel | 129 | yapo | [32269146](https://www.yapo.cl/bienes-raices-venta-de-propiedades-apartamentos/venta-dpto-2d-1b-1-estac-oportunidad-metro-san-miguel/32269146) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Estación Central | 3904 | portalinmobiliario | [MLC-3705880440](https://portalinmobiliario.com/MLC-3705880440-coronel-godoy-ingevec-_JM) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Estación Central | 3911 | portalinmobiliario | [MLC-3225344318](https://portalinmobiliario.com/MLC-3225344318-edificio-ecuador-norte-verde-_JM) | direccion_sin_numero_civico_exacto, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Estación Central | 4217 | portalinmobiliario | [MLC-920281620](https://portalinmobiliario.com/MLC-920281620-edificio-toro-mazote-_JM) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Estación Central | 4220 | portalinmobiliario | [MLC-4118647000](https://portalinmobiliario.com/MLC-4118647000-depto-1d1b-inversion-o-1era-vivienda-estacion-central-_JM) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |
| Estación Central | 4222 | portalinmobiliario | [MLC-4045559882](https://portalinmobiliario.com/MLC-4045559882-moderno-departamento-en-estacion-central-_JM) | sin_snapshot_PR5_vinculado, sin_direccion_publicada, sin_coordenadas_publicadas_verificables, sin_m2_util_explicito |

## Estado de los criterios de fase 2a

| Criterio | Estado |
|---|---|
| ≥40% con enlace a edificio en las ocho comunas | No evaluado: parada obligatoria en el control previo |
| Precisión ≥90% en muestra revisada de 100 | No evaluada: no se generaron enlaces ni muestra |
| Segunda ejecución sin filas nuevas de enlaces | No aplica: no se crearon tablas ni filas de enlaces |
| Pruebas del control y regresiones canónicas | 46 pasadas; Ruff correcto |
| Tasaciones actuales | Código y rutas de valoración sin cambios; regresiones canónicas en verde; sin deploy |

El único código nuevo es el auditor aislado de Paso 0, detrás de `SII_LINKAGE_ENABLED=false` por defecto. La activación en producción se limitó al proceso de lectura ejecutado por stdin; no cambia la configuración persistente de la API. No se incorporan consultas SII a Tasar, Radar ni al motor canónico.

## Entregables y siguiente decisión

- `SII_FASE2A_COBERTURA.csv`: conteos y porcentajes por comuna, portal y cruce de ambos.
- `SII_FASE2A_EJEMPLOS.csv`: cinco casos fallidos por comuna y sus motivos.
- `SII_FASE2A_CONTROL.json`: evidencia agregada y ejemplos de la transacción de producción.
- Nuevo PR en borrador: auditor y reporte del bloqueo. Los pasos 1–3 requieren que se resuelva el control o una nueva instrucción explícita sobre el alcance.
