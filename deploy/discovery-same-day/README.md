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

## Conservación de espacio y alarma: plan pendiente de aprobación

Estas acciones NO se han ejecutado. Requieren el OK específico de este PR,
incluida la autorización de limpieza: en esta auditoría no se borra nada en Oracle.

1. Antes de desplegar, inventariar espacio del sistema de archivos que aloja
   Docker y PostgreSQL, imágenes, caché de construcción, logs y respaldos.
   Verificar la restauración del respaldo PostgreSQL en aislamiento y conservar
   la imagen del commit actual y la de rollback `80bd8a9`.
2. Tras aprobación, limpiar exclusivamente caché de construcción Docker sin
   uso y con más de siete días, con objetivo de caché retenida de 2 GB.
   No limpiar volúmenes, datos, imágenes necesarias para rollback ni respaldos
   mediante una limpieza global. La medición de lectura encontró 13,25 GB de
   caché, de los cuales Docker declaró recuperables 11,34 GB; el resultado real
   de una limpieza se verificará después, sin garantizar esa recuperación.
3. Conservar stdout/stderr completos por corrida: 30 días sin compresión y
   hasta 90 días comprimidos, con acceso restringido. Los incidentes abiertos
   quedan retenidos hasta resolución; no truncar stderr al lanzar scrapers.
   Limitar también los logs de contenedores y journal mediante rotación. Antes
   de aprobar expiraciones, medir su tamaño y documentar qué se eliminaría.
4. Retener siete respaldos diarios, cuatro semanales y el respaldo verificado
   del despliegue vigente; preservar el anterior hasta cerrar su rollback.
   Son archivos de PostgreSQL y no respaldos de volumen OCI. Verificar el
   presupuesto conjunto antes de copiar fuera del servidor: no crear recursos
   OCI de almacenamiento o respaldos adicionales sin confirmar el cupo gratis
   de toda la tenencia. Ninguna retención se aplica en esta auditoría.
5. Configurar, como parte del despliegue aprobado y usando la supervisión
   existente, una alarma persistente `DISK_LOW` si el sistema de archivos real
   de datos tiene menos de 10 GB libres (10.000.000.000 bytes). Exponer bytes
   libres y estado degradado en salud y notificar por el canal ya existente;
   comprobar el umbral con una lectura simulada, sin llenar el disco. No crear
   timers ni borrar automáticamente. Revisar antes de la ingesta el mismo
   umbral y conservar la alarma hasta recuperar al menos 12 GB.

La VM observada es A1 de 1 OCPU y 6 GB; esto no acredita que toda la cuenta
esté dentro de Always Free. La aprobación de despliegue debe incluir evidencia
de tipo de tenencia, recursos de todos los compartimentos/regiones, tamaños de
volúmenes, número de respaldos y consumo/cargos. SSH e IMDS no permiten esa
confirmación y no sustituyen una consulta autorizada de la consola OCI.

Auditoría de consola autorizada del 16-oct: la tenencia es **Pay As You Go**
(no Free-only), tiene una sola región suscrita y el explorador con alcance
All muestra 34 recursos en dos páginas. Se observa una sola VM y un volumen
boot de 47 GB marcado Always Free, sin block volumes, buckets ni respaldos
adicionales en el inventario. La pestaña de backups del volumen está vacía
tanto en root como en valoria-always-free. Cost Analysis sin filtros reporta
CLP 0 para 1–16 octubre, con advertencia de retraso aproximado de 24 h.
Esto confirma el estado observado, no impide futuros cargos en PAYG.
La evidencia depurada está en `validation/oci-account-readonly.json`.

## Revalidación de Yapo

El ciclo inicial repetido sobre f2ba0b8 terminó con 43 respuestas 200 y ledger
coherente, pero solo 6/15 altas aisladas con detalle (40%). El diagnóstico de
una respuesta ya obtenida identificó registros Flight `T<bytes>,texto`: el
texto admite saltos de línea y termina sin separador antes del siguiente JSON.
El parser anterior dividía por líneas y perdía el payload propio de la ficha.
El decoder ahora respeta la longitud UTF-8, incluso entre scripts; no evalúa
JavaScript ni extrae atributos desde recomendaciones. Las pruebas cubren
texto multilínea, acentos, símbolos y texto vacío. La extracción de campos
propios tampoco depende de aceptar una moneda/precio del payload; no modifica
el precio guardado del aviso ni el motor.


Resultado final del ciclo real aislado del 16-oct 10:42–10:47 UTC: **14/15
altas individuales con detalle (93,33%)**, 43 respuestas 200 y cero
302/403/429. El ledger exitoso coincide con los contadores del job: 15
insertados, 389 actualizados, 149 omitidos y 10 rechazados por validación.
Se realizaron 29 búsquedas y 14 fichas; frente a 29 búsquedas + hasta cinco
fichas anteriores, son **9 solicitudes extra** en este ciclo. Las 14 fichas
pedidas se capturaron; la aceptación usa el denominador conservador de las
15 nuevas identidades de departamentos en las ocho comunas persistidas en
aislamiento, sin excluir la que no tiene observación de detalle.

Suite completa final: **1995 passed**, nueve advertencias de deprecación
existentes. Con la misma base y UF 41.168,03: Santiago 70 m² = 3.247,47 UF,
La Florida 82 m² = 3.878,19 UF, idénticos antes/después y mismos comparables.
Los hashes de los ocho archivos candidatos se adjuntan con la evidencia.
No hubo merge, despliegue, borrados ni escrituras de producción; se conservaron
los contenedores de auditoría detenidos y sus logs, respetando la prohibición
de borrar recursos de Oracle. El PR permanece en borrador y requiere OK nuevo.
