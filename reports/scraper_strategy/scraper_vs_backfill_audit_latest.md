# Auditoría Scraper vs Backfill

Generado: `2026-06-15`  
Clasificación: `hybrid`  
Prioridad recomendada: `scraper_first -> targeted_refresh -> residual_backfill`

## Resumen ejecutivo

Sí conviene dejar de tratar el micro-backfill manual como estrategia principal. La evidencia disponible indica que el mayor retorno está en mejorar la captura de origen para listings nuevos y usar el refresh como mecanismo dirigido de enriquecimiento para registros antiguos.

La Fase 5C elevó `land_area_m2` en casas de `74/1293` (`5.72%`) a `99/1293` (`7.66%`) mediante 25 correcciones de alta confianza, pero no produjo una mejora material de MAPE. Esto confirma que el backfill manual es útil para rescatar evidencia ya persistida, pero tiene alcance pequeño y no corrige el problema recurrente de ingestión.

El scraper periódico de Yapo procesa cards de resultados y no visita el detalle antes de persistir. El parser de detalle sí contiene la mayor parte de la lógica necesaria para recuperar áreas, UF, descripción y señales geográficas, pero hoy queda relegado al refresh puntual. El diseño produce dos poblaciones: listings nuevos estructuralmente pobres y listings refrescados potencialmente más ricos, con riesgos de degradación porque el update reemplaza atributos físicos aunque la nueva extracción venga incompleta.

Recomendación: `hybrid`, con el siguiente orden:

1. `scraper_first`: corregir UF nativa/provenance en cards y añadir enriquecimiento de detalle limitado para nuevos listings prioritarios.
2. `targeted_refresh`: seleccionar antiguos por campos faltantes y valor esperado, con actualizaciones no destructivas.
3. `residual_backfill`: conservar backfills manuales únicamente para evidencia local de alta confianza que no requiera red.

## 1. Preflight

| Control | Resultado |
| --- | --- |
| Branch | `codex/phase5c-apply-land-area-backfill` |
| HEAD | `80b7c260e84b27ac4c7684f8493207d9f66ce490` |
| Worktree antes del reporte | limpio |
| Index antes del reporte | limpio |
| Remotos configurados | ninguno |
| DB | no consultada; no disponible durante la auditoría |
| DB modificada | no |
| Scraping ejecutado | no |
| APIs externas | ninguna |
| Migraciones / apply | no |
| Código productivo | no modificado |
| Push | no |

Las métricas cuantitativas provienen de snapshots versionados de Fases 5A, 5B y 5C, generados el 15 de junio de 2026. Las conclusiones sobre flujo y pérdida de información provienen de inspección estática del código actual. No se presentan como mediciones frescas de DB.

## 2. Mapa del scraper actual

### Yapo listado/card

El job periódico construye `YapoScraper`, obtiene páginas de resultados y persiste directamente cada `ScraperResult`; no incorpora una etapa de detalle (`workers/scraper_job.py:250`, `infrastructure/scrapers/yapo.py:177`).

La card captura:

- título, comuna/location, URL y `external_id`;
- precio visible y moneda original;
- un área genérica `m2`;
- dormitorios, baños y estacionamientos por orden posicional;
- seller, rebaja, hallmark, target de búsqueda y algunas señales geográficas.

La card pierde o no materializa:

- `built_area_m2`, `land_area_m2` y `usable_area_m2` diferenciados;
- monto UF nativo en `price_uf`, aunque ya parseó moneda y monto;
- texto completo de card como campo estable;
- descripción, atributos etiquetados y metadata estructurada del detalle;
- provenance del selector/layout y versión específica del parser de card.

Evidencia: `_parse_card` guarda `currency_original`, pero retorna solo `price_clp`; no retorna `price_uf` (`infrastructure/scrapers/yapo.py:323`, `infrastructure/scrapers/yapo.py:358`).

### Yapo detalle

`parse_listing_detail` puede recuperar:

- precio desde texto visible, metas, selectores de precio y JSON-LD;
- UF nativa y CLP convertido cuando existe una tasa real;
- áreas estructuradas construida, útil y total/terreno;
- `land_area_m2` desde texto para casas, incluyendo separadores de miles;
- dormitorios, baños y estacionamientos;
- comuna y señales de calle/metro/intersección;
- descripción desde `meta description` u `og:description`.

Sin embargo, persiste principalmente el resultado final. No conserva HTML, JSON-LD original, lista de candidatos de precio/atributos, selector ganador ni el texto completo de detalle bajo una clave estable. El texto completo sí se usa transitoriamente para parsing y geo-signals (`infrastructure/scrapers/yapo.py:409`, `infrastructure/scrapers/yapo.py:537`, `infrastructure/scrapers/yapo.py:671`).

Brecha adicional: el detalle retorna `price_uf` cuando corresponde, pero no retorna explícitamente `price_currency`/`currency_original`. Para UF, cleaning puede inferir la moneda desde `price_uf`; para CLP, la moneda depende de metadata histórica preservada o puede quedar desconocida.

### Cleaning, persistencia y ORM

El cleaning normaliza property type, áreas y provenance. Puede extraer áreas desde título/descripción y registra `area_parse_version` y fuentes por campo. Los modelos ORM ya soportan todos los campos físicos, UF, moneda, provenance de precio y `raw_metadata` (`domain/ingestion/data_cleaning.py:163`, `infrastructure/db/models.py:70`).

Por tanto, la limitación principal no es de schema: es de captura y política de actualización.

El pipeline actual:

- reemplaza `m2`, áreas, dormitorios, baños y parking en cada update;
- fusiona `raw_metadata` de forma no destructiva;
- protege coordenadas y precisión geográfica contra evidencia más débil;
- no aplica el mismo principio de no degradación a atributos físicos.

Evidencia: asignaciones directas en `domain/ingestion/pipeline.py:130-148`; guardrails geográficos en `domain/ingestion/pipeline.py:330-349`.

### Refresh

El refresh Yapo visita la URL directa y reutiliza `parse_listing_detail`. Resuelve UF real, registra estados HTTP, detecta bajas y protege downgrades de geocode precision (`workers/refresh_scraper.py:283`, `workers/refresh_scraper.py:533`).

La selección actual prioriza watchlist, recencia, nunca refrescados y antigüedad. Puede filtrar `only_missing_coordinates`, comuna y property type, pero no `missing_land_area`, `missing_price_uf`, `missing_description` o bajo provenance (`workers/refresh_scraper.py:672`, `workers/refresh_scraper.py:721`).

Riesgo principal: si el detalle cambia o entrega atributos incompletos, el pipeline puede reemplazar valores válidos por `None` o cero. Solo geocoding tiene bloqueo explícito posterior al update (`workers/refresh_scraper.py:790`).

### Geocoding y microzona

Yapo genera candidatos geográficos desde título, URL, card y detalle. Sin coordenadas, la normalización limita honestamente una supuesta dirección a precisión `street`.

Las microzonas se derivan al leer un ORM mediante `enrich_raw_metadata_with_microzones`. Ese enriquecimiento puede existir en memoria sin haber quedado guardado en la fila (`infrastructure/db/mappers.py:125`, `domain/geocoding/microzones.py:277`). La cobertura “derivada” y la cobertura “persistida” no deben mezclarse.

### Product classification

La clasificación usa property type, título, descripción, `card_text`, `detail_text` y hints cuando existen. Si solo hay título, puede clasificar todos los registros sin que todos tengan evidencia rica. Cobertura de clasificación del 100% significa que se emitió una clase, no que la fuente aportó descripción suficiente (`domain/valuation/product_classification.py:132`, `domain/valuation/product_classification.py:232`).

### Portal Inmobiliario, brecha secundaria

Portal dispone de parser de listado/card, no de un parser de detalle equivalente en el módulo auditado. El refresh de Portal entrega HTML de URL directa a `PortalInmobiliarioScraper.parse_listings` y toma el primer resultado (`workers/refresh_scraper.py:550`). Es una ruta frágil si la página detalle no contiene cards con el layout de búsqueda.

## 3. Campos críticos

Las coberturas son snapshots observados cuando existe una métrica versionada. “No cuantificado” evita inventar cobertura a partir del schema o de tests.

| Campo | Fuente actual | Cobertura snapshot | Confiabilidad actual | Pérdida / causa | Oportunidad |
| --- | --- | ---: | --- | --- | --- |
| `land_area_m2` | Detalle estructurado/texto; parser de cleaning sobre metadata antigua | Casas: `74/1293` antes y `99/1293` después de 5C | Alta cuando hay etiqueta explícita; media/baja en pares slash o unidad implícita | Scraper nuevo persiste cards sin detalle; muchos antiguos no tienen texto suficiente | Máxima: detalle prioritario para casas y refresh por campo faltante |
| `built_area_m2` | Card `m2` como fallback; detalle etiquetado; cleaning | Casas `99.85%`; departamentos `100%` en Fase 5A | Media: cobertura alta, semántica ambigua en cards | Card no distingue construida/útil/total | Persistir etiqueta y source; no sobrescribir valor explícito con fallback genérico |
| `usable_area_m2` | Detalle etiquetado; fallback a construida en departamentos | Departamentos `100%`; casas `0.15%` | Media en deptos por fallback; baja utilidad esperada en casas | Se pierde distinción entre útil y construida | Mantener valor y provenance separados cuando la fuente entrega ambos |
| Dormitorios | Card posicional; detalle etiquetado/texto | `100%` estructural en Fase 5A | Media | Cero también representa ausencia; orden posicional puede cambiar | Selectores/labels y flag `observed` vs `defaulted` |
| Baños | Card posicional; detalle etiquetado/texto | `100%` estructural en Fase 5A | Media | Mismo problema de cero y posición | Provenance por campo y actualización no destructiva |
| Estacionamientos | Card posicional; detalle etiquetado/texto | `100%` estructural en Fase 5A | Media-baja | Ausencia se convierte en cero; card de tres slots puede confundir parking ausente | Distinguir `missing` de `0`; usar labels/íconos/metadata estructurada |
| Precio UF | Card y detalle parsean UF; solo detalle retorna `price_uf` | Deptos `329/1487` UF nativa; precio canónico total `539/1487` | Alta si el monto nativo se conserva | Card convierte a CLP y descarta monto UF; antiguos quedan `legacy_unrecoverable` | Quick win principal: retornar `price_uf`, moneda, tasa y provenance desde card |
| Precio CLP | Card/detalle, nativo o conversión UF | Campo obligatorio; cobertura semántica no separada | Alta si CLP nativo; display-only si derivado de UF | No siempre se distingue CLP original de snapshot convertido | Persistir `price_clp_snapshot`, moneda original y `uf_rate_used` coherentemente |
| Moneda original | Card `currency_original`; detalle no la retorna explícitamente | No cuantificado globalmente | Alta en card | Puede perderse en detalle CLP o quedar solo en metadata histórica | Campo explícito en todo parser y provenance uniforme |
| Dirección/geocoding | Título, URL, location, card/detalle, geocoder separado | Useful geocode: casas `50.27%`; deptos `44.52%` en Fase 5A | Baja-media sin coordenadas; alta solo con geocoding verificado | Heurísticas antiguas pueden llamar “address” a texto; normalización lo limita a street | Conservar candidatos y exact-address estructurada; geocodificar aparte con cache/guardrails |
| Microzona/señales | Título y metadata; derivación en mapper | Casas `18.33%`; deptos `19.23%` en Fase 5A | Media para metro/intersección; baja para avenidas genéricas | Texto de detalle no se conserva completo; derivado en memoria no siempre persistido | Persistir señales aceptadas con versión, source y confidence; mantener soft signals separadas |
| Product classification | Property type + texto disponible | `100%` emitido | Variable; no equivale a evidencia completa | Listings de card dependen a menudo solo de título | Guardar `product_class`, strength, terms y fields_used como provenance auditable |
| Raw title | Card/detalle; columna `title` | Requerido, efectivamente completo en filas válidas | Alta | El título se limpia/trunca y se sobrescribe en refresh | Conservar `raw_title` además del título normalizado si difieren |
| Raw description | Solo detalle meta; metadata histórica variable | No cuantificado | Media-baja: meta puede ser truncada | El scraper periódico no visita detalle; no se guarda body completo | Guardar texto visible normalizado y hash, con límite de tamaño |
| Raw HTML | No persistido | `0%` por diseño observado | N/A | Imposible reparsear tras cambios o baja del aviso | Snapshot selectivo/comprimido fuera de `raw_metadata`, solo para muestra o fallos |
| Raw metadata | JSON ORM; resultados y provenance parciales | Presente, riqueza no cuantificada | Media | No contiene payload estructurado completo ni snapshot temporal | Envelope versionado: parser, selector, campos observados, hashes y warnings |

### Captura deficiente vs fuente ausente

**Captura deficiente demostrada:**

- UF nativa de cards: el monto ya fue parseado, pero no se retorna/persiste.
- Diferenciación de áreas: las cards entregan solo un `m2` genérico; el sistema no visita detalle para nuevos listings.
- Descripción/detail text: se usa transitoriamente, pero no se guarda íntegro bajo una clave estable.
- Provenance: faltan selector ganador, versión de layout y estado observado/defaulted por campo.
- Refresh dirigido: existen filtros generales, no filtros por campos estratégicos faltantes.

**Probablemente no entregado o no demostrable sin muestra de detalle:**

- `land_area_m2` de casas cuyo aviso no menciona cifra ni etiqueta;
- estacionamiento exacto cuando la publicación omite el dato;
- dirección exacta cuando el portal oculta la ubicación;
- superficie útil separada cuando solo se publica “superficie total”.

La Fase 5A identificó 567 casas donde el área de terreno no estaba en el texto local disponible y 565 candidatas a refresh. Esas 565 son oportunidades de consulta, no recuperaciones garantizadas.

## 4. Nuevos listings vs registros antiguos

| Estrategia | Valor esperado | Alcance | Riesgo | Lectura |
| --- | --- | --- | --- | --- |
| Mejorar scraper futuro | Alto y acumulativo | Todo listing nuevo/re-encontrado | Medio | Evita seguir creando deuda; UF desde card es un quick win sin request adicional |
| Refresh dirigido | Alto si el yield supera umbrales | `565` casas sin terreno y `946` deptos sin precio canónico candidatos | Medio-alto | Debe medirse con muestra, límites y updates no destructivos |
| Backfill manual | Bajo-medio y finito | Evidencia ya persistida | Bajo por lote, alto costo humano | 25 correcciones subieron 1.94 pp y no movieron MAPE materialmente |

### `land_area_m2` en casas

- Baseline pre-5C: `74/1293` (`5.72%`).
- Post-5C: `99/1293` (`7.66%`).
- Candidatas a refresh: `565`.
- Techo teórico si todas recuperaran terreno: `52.05%`.
- Ese techo no es forecast. La fuente puede omitir el terreno, haber retirado el aviso o devolver contenido bloqueado.

Conclusión: el parser/refresh tiene mucho más espacio potencial que otro micro-backfill, pero el siguiente paso correcto es medir yield, no aplicar masivamente.

### Precio UF/canónico en departamentos

- Precio canónico usable: `539/1487` (`36.25%`).
- UF nativa real: `329/1487`.
- CLP canónico convertido: `210/1487`.
- Candidatos legacy a refresh: `946` (`63.62%`).
- Recuperaciones necesarias para 60%: `354`.
- Yield mínimo requerido sobre candidatos: `37.42%`.

La card nueva puede mejorar inmediatamente UF sin detalle porque ya conoce moneda y monto. Para históricos, el refresh de detalle es la única recuperación honesta; no se debe reconstruir UF dividiendo CLP antiguo por una tasa fija o actual.

## 5. Recomendación

**Clasificación: `hybrid`.**

No se recomienda `backfill_first`: ya mostró alcance pequeño y efecto marginal sobre MAPE. Tampoco `refresh_first` aislado: seguiría ingresando listings nuevos pobres y tiene riesgos de degradación. `scraper_first` puro tampoco recupera la deuda histórica de UF y terreno.

Orden de inversión:

1. **Scraper futuro:** persistencia correcta de UF/provenance desde card y detalle limitado para segmentos de alto valor.
2. **Refresh controlado:** candidatos por campo faltante, score de valor esperado y merge no destructivo.
3. **Backfill residual:** extracción local de metadata ya existente, alta confianza, manifiesto cerrado y benchmark posterior.

## 6. Plan propuesto

### Quick wins seguros

- En cards UF, retornar `price_uf`, `price_currency=UF`, `price_uf_source=scraped`, confidence alta, método y tasa usada, además de `price_clp` para display.
- En cards CLP, retornar moneda explícita y marcar CLP como nativo.
- Añadir provenance por campo: `observed`, `defaulted`, source, parser version y selector/layout.
- Conservar `raw_title`, descripción/meta y texto normalizado acotado con hash; no guardar HTML completo en JSON.
- Hacer que updates de áreas y habitaciones sean no destructivos: ausencia nueva no borra un valor válido; conflicto queda auditado.
- Añadir métricas de cobertura por corrida: UF nativa, áreas diferenciadas, description, parser source y defaults.

### Cambios medianos

- Cola de detalle limitada para nuevos listings: primero casas y cards UF; deduplicada por URL/external ID y con rate limit independiente.
- Filtros de refresh: `missing_land_area`, `missing_price_uf`, `missing_description`, `weak_area_provenance`, combinables con property type/comuna.
- Priorización por utilidad: casas sin terreno con URL activa; departamentos UF legacy; watchlist; luego antigüedad.
- Capturar metadata estructurada/JSON-LD y atributos etiquetados mediante un envelope estable, conservando candidato y selector ganador.
- Crear corpus de fixtures reales anonimizados para layouts de casa, departamento, UF, CLP, atributos ausentes, inactivo y captcha.
- Separar cobertura microzona persistida de cobertura derivable en memoria.

### Cambios riesgosos

- Visitar detalle sincrónicamente para todas las cards: multiplica requests y duración, aumenta bloqueo y acopla discovery con detalle.
- Refresh masivo de toda la base: puede disparar anti-bot, bajas falsas y degradaciones de atributos.
- Guardar HTML completo dentro de `raw_metadata`: crecimiento, duplicación, posibles datos personales y consultas JSON costosas.
- Selectores amplios como `[class*=price]` sin corpus/telemetría: riesgo de capturar gastos comunes o precio/m².
- Sobrescribir campos existentes ante cualquier nueva extracción: puede degradar calidad silenciosamente.

### Qué testear

- UF de card: monto original, CLP snapshot, moneda, tasa y provenance.
- CLP de card y detalle: moneda explícita sin UF inventada.
- Áreas casa: construida vs terreno, miles/decimales, pares slash, price/m² y conflictos.
- Apartamentos: útil vs total/construida y ausencia de land.
- Dormitorios/baños/parking: dato ausente no equivale automáticamente a cero.
- Merge de refresh: no degradación, conflicto auditado, idempotencia y price history correcta.
- Selección dirigida: filtros por missing field y orden estable.
- HTML inesperado, 403, 404, 429, captcha, redirect e inactivo explícito.
- Portal: fixture real de detalle antes de considerar soportada esa ruta.

### Qué medir

- `detail_fetch_success_pct`, `blocked_pct`, `parse_error_pct` y latencia por URL.
- Yield de `land_area_m2` sobre casas seleccionadas.
- Yield de UF nativa fuerte sobre departamentos legacy.
- Cambios de cobertura, conflictos y downgrades bloqueados por campo.
- Distribución de parser source/confidence y porcentaje defaulted.
- MAPE, cobertura, P90 y errores extremos después de alcanzar una masa material; no tras cada micro-lote.

### Qué no tocar todavía

- Motores de valoración, endpoints, UI y schema ORM.
- Geocoding externo masivo.
- Backfill general basado en inferencias débiles.
- Activación de detalle para todas las cards.
- Eliminación automática de duplicados.
- Almacenamiento indiscriminado de HTML.

## 7. Próxima fase sugerida

### Fase 6A: piloto read-only de yield de detalle

Objetivo: medir cuánto valor real aporta el detalle antes de cambiar producción o ejecutar un backfill.

Diseño propuesto:

- muestra estratificada de 50 casas activas sin `land_area_m2` y 50 departamentos sin precio canónico fuerte;
- selección desde snapshot/export aprobado, sin escribir DB;
- máximo 100 URLs directas de Yapo, una sola visita por URL, intervalo mínimo vigente y sin concurrencia agresiva;
- guardar únicamente reportes/fixtures de auditoría aprobados, no aplicar resultados;
- comparar card/persistido vs detalle para todos los campos críticos;
- medir source availability, parse success, `land_area` yield, UF yield, descripción, señales geo y conflictos;
- stop conditions: primer captcha persistente; cualquier 429; bloqueo 403 repetido; `parse_error_pct > 10%`; moneda inesperada; o evidencia de selector incorrecto;
- gate de avance: UF fuerte con yield al menos `37.42%` en el estrato de departamentos, cero UF fallback, y yield de terreno suficientemente alto para justificar refresh por lotes;
- salida: recomendación `implement_scraper`, `controlled_refresh`, `fixture_work_first` o `stop`.

Prompt sugerido:

> Auditar en modo read-only una muestra estratificada de hasta 100 URLs Yapo ya conocidas: 50 casas activas sin `land_area_m2` y 50 departamentos sin precio canónico fuerte. No escribir DB ni modificar producción. Comparar datos persistidos/card contra detalle, medir yields por campo, conflictos, bloqueos y errores de parser. Detener ante captcha, 429, 403 repetido o parse error superior a 10%. Generar un reporte con decisión explícita sobre scraper futuro y refresh controlado.

## 8. Riesgos de tocar el scraper productivo

| Riesgo | Severidad | Mitigación |
| --- | --- | --- |
| Bloqueo/rate limit por más requests de detalle | Alta | Cola separada, límite diario, rate limit, stop-on-block y circuit breaker |
| Drift de HTML/selectores | Alta | Fixtures, parser version, selector provenance y alertas de cobertura |
| Captura de precio/m² o gastos comunes como precio | Alta | Candidatos tipados, reglas negativas y validación de rangos/contexto |
| Degradación de campos en refresh | Alta | Merge por confianza, no borrar por ausencia y registrar conflictos |
| Conversión UF que genera falsos cambios de precio | Alta | Canonical change en UF y snapshot CLP separado con tasa real |
| Falsas bajas por redirects/captcha | Alta | Estados diferenciados, no marcar removed ante HTML inesperado |
| Cambios de fingerprint/property por atributos inestables | Media-alta | Revisar impacto antes de persistir y mantener identidad source/external ID |
| Crecimiento o sensibilidad de raw snapshots | Media | Texto acotado, hashes, retención y almacenamiento separado si se usa HTML |
| Clasificación/producto sobre texto parcial | Media | Strength y fields_used; no tratar cobertura como confianza |

## 9. Validación

- Suite focal ejecutada durante la auditoría: `235 passed in 7.34s`.
- Alcance de suite: parser Yapo/base, cleaning, refresh CLI/integración, precio canónico, geo-signals, microzonas y product classification.
- Este reporte no añadió herramientas ni tests porque solo genera artefactos manuales.
- JSON validado con `python -m json.tool` al cierre.
- Consistencia MD/JSON comprobada para métricas principales, clasificación y prioridades.

## Fuentes locales principales

- `infrastructure/scrapers/yapo.py`
- `workers/scraper_job.py`
- `workers/refresh_scraper.py`
- `domain/ingestion/data_cleaning.py`
- `domain/ingestion/pipeline.py`
- `infrastructure/db/models.py`
- `infrastructure/db/mappers.py`
- `domain/valuation/canonical_price.py`
- `domain/geocoding/geo_signals.py`
- `domain/geocoding/microzones.py`
- `domain/valuation/product_classification.py`
- `reports/data_quality/phase5a/data_enrichment_audit_latest.md`
- `reports/data_quality/phase5b/data_enrichment_validation_latest.md`
- `reports/data_quality/phase5c/land_area_backfill_latest.md`

