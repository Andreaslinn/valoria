# Nuevas altas con campos publicados dentro de discovery

Base: producción `80bd8a9` / release/canonical-only-reproducible-20261013.
Este PR requiere un OK propio de Andy. No está desplegado y no modifica el
refresher, timers, límites del contenedor ni el motor de tasación.

## Medición anterior al cambio

Se midieron desde Oracle 30 tarjetas de Estación Central y sus mismos 30 IDs
en el mapa, sin abrir fichas. Se usó el cliente y la sesión del scraper en modo
solo lectura, con pausa mínima de 3,1 s. La muestra final usa dos solicitudes
del presupuesto normal: una búsqueda y el mapa. Un intento inicial identificó
un 301 de normalización del mapa; se corrigió la URL canónica.

| Campo publicado | Tarjetas/mapa | Porcentaje |
| --- | ---: | ---: |
| Útil: valor o rango etiquetado | 29/30 | 96,67% |
| Útil: valor escalar de una unidad | 21/30 | 70% |
| Útil: rango de proyecto | 8/30 | 26,67% |
| Total etiquetado | 1/30 | 3,33% |
| Coordenadas del mismo ID en mapa | 30/30 | 100% |

Los rangos se guardan como rangos: jamás como el m² de un departamento.
Un m² genérico permanece genérico. El mapa declara precisión desconocida;
no se etiqueta como exacta. La muestra es de una comuna y no demuestra esos
porcentajes en cada comuna: se extraen hechos explícitos donde estén presentes.
No se agregan siete mapas para simular cobertura de las ocho comunas.

Separando proyectos, se revisaron también 30 tarjetas de departamentos
individuales de las mismas 48 tarjetas ya descargadas, sin otra solicitud:
29/30 publican útil escalar (96,67%), 1/30 total (3,33%) y sus 30/30 IDs tienen
coordenadas en el mapa. `individual-card-measurement.json` es la medición
pertinente para las altas individuales y confirma el umbral del 95% de útil.

## Flujo y presupuesto

Las tarjetas guardan útil/total explícitos, dirección original y procedencia.
El mapa rotativo existente se obtiene una vez al inicio y se reutiliza en
geografía. Sus marcadores se vinculan por ID de publicación, sin usar sus precios.

Cada alta nueva de departamento de las ocho comunas se detalla en discovery,
con el mismo cliente, limitador y sesión. Portal intercala las altas en el
recorrido de búsquedas, sin ordenar URLs por ID; usa la búsqueda como Referer.
Una redirección canónica al mismo ID puede consumir un segundo GET. Yapo usa
un GET por ficha y no sigue redirecciones. Los proyectos se distinguen de
departamentos individuales para no confundir precios/superficies "desde".

Los GET de altas consumen primero los cinco cupos anteriores de detalle.
Cuando hay altas Portal reutiliza sus respuestas para geografía y el mapa;
no añade después el recorrido consecutivo de URLs antiguas. El refresher no
se modifica. Sin altas se conserva el mantenimiento acotado anterior.

El límite de espera sigue siendo al menos tres segundos por solicitud. La
fase de altas tiene una ventana de 600 s y conserva la tarjeta si vence;
`same_day_deferred_deadline` expone la deuda. No se promete cobertura diaria
ilimitada ante ráfagas ni se aumenta el timeout del lanzador de 900 s.
Yapo reserva hasta 300 s para las búsquedas completas, frente al corte interno
anterior de 180 s; la fase de altas descuenta el tiempo ya transcurrido y no
puede extenderse más allá del segundo 840 del job. Se conservan 60 s para
cierre/mantenimiento dentro del límite global existente, sin acelerar peticiones.
302 a verificación/login, 403 y 429 interrumpen el flujo y degradan la fuente
con la alarma correspondiente; no se reintentan ni se soluciona un muro.

Contabilidad: si P es el número de GET de altas de Portal, el ciclo con altas
usa 8 búsquedas + 1 mapa + P + max(0,5-P) de mantenimiento, sin GET geográficos
adicionales. Frente al máximo previo de 18 GET, la diferencia es max(5,P)-9.
Para Yapo, si Y es el número de GET de altas, el cambio es max(0,Y-5) GET;
el número de búsquedas no cambia. Las redirecciones cuentan como solicitudes.

## Validación y aprobación

La prueba real se ejecuta desde Oracle en un contenedor temporal con 384 MiB,
0,25 CPU, 96 PIDs, raíz de solo lectura y sesión montada de solo lectura.
PostgreSQL se consulta en una transacción de solo lectura; las escrituras del
ciclo van exclusivamente a SQLite en memoria. Para reproducir altas se omite
de la copia aislada uno de cada diez IDs activos elegibles, además de las altas
que las búsquedas realmente añadan. Por tanto son altas de la base aislada,
no una afirmación sobre el número de altas de producción de hoy.

La aceptación cuenta filas nuevas individuales con observación de detalle;
un objeto vacío `published_fields` de tarjeta no se contabiliza como éxito.
Las evidencias, solicitudes reales, estados HTTP y referencias con idéntica
base y UF se adjuntan en `validation/`. Una muestra sin bloqueos no garantiza
ausencia de bloqueos futuros. No hubo ingesta manual de producción.

El primer ensayo capturó 61/61 altas individuales de Portal, pero el recorrido
antiguo de geografía añadió tres 302 canónicos; por eso sus cupos se dedican
a las altas y a reutilizar respuestas. Un ensayo posterior mostró la necesidad
de acotar la caché HTML: se conservan solo cuatro respuestas y un conjunto de
IDs visitados, no las páginas de todas las altas. No se aumentan los 384 MiB.
El primer ensayo completo Yapo recibió 29 respuestas 200 antes de vencer el
corte interno de búsqueda de 180 s; se documenta en la evidencia y se repite
con la redistribución del tiempo global descrita arriba.

Tras un OK nuevo: reconstruir exactamente el commit mergeado en release,
respaldar y restaurar en aislamiento, comparar referencias antes de ingesta,
mantener recursos/timers y observar el siguiente ciclo normal. Rollback de
código a `80bd8a9`; sin downgrade de 0023, sin desactivar UF ni borrar datos.
