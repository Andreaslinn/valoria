# Segunda opinión con cierres SII en Tasar

Continuación del PR #11. `sii_closing_layer` sigue apagado por defecto. No cambia
el motor canónico, sus resultados, K=10, pesos, escalas ni la regla congelada.
La presentación solicitada ahora muestra el kNN fuera de la zona como
**Referencial**; no altera la abstención del protocolo de evaluación anterior.

## Activación exclusivamente local

La API consulta el flag de runtime existente. Para revisar la integración local,
configurar explícitamente `sii_closing_layer=true` y `SII_CLOSING_DATA_DIR` a un
directorio privado que contenga `address-index.sqlite` y `closings.json` generados
por el pipeline del PR. Arrancar API e interfaz con sus comandos habituales.
No se adjuntan esos archivos al repositorio ni se configura ningún despliegue.
No hay consultas a producción, descarga automática ni ingesta desde el endpoint.
El índice se abre en modo SQLite de solo lectura; los cierres se cachean por ruta
y mtime en el proceso. El trabajo SII corre en el threadpool después del canónico.

`GET /api/v1/tasar/capabilities` expone únicamente el booleano del flag. Ambas
interfaces ocultan el nuevo campo hasta recibir `true`. Dirección es un campo
opcional independiente de la referencia personal; solo se envía si está habilitado
y no está vacío. La autenticación y autorización de tasaciones siguen vigentes.

## Contrato aditivo y privacidad

`POST /api/v1/valuations` admite `address`. El campo conserva la tolerancia de la
release a entradas desconocidas mientras la capa está apagada. Con flag apagado,
dirección ausente, nula o vacía, se omite por completo `sii_closing_opinion` en la
respuesta, sin eliminar ni reordenar los campos previos ni sus valores nulos.

Con dirección presente y flag habilitado, el objeto añadido tiene:

- `available`: valor y P25–P75 en UF, número de comparables, las diez fechas, fecha
  mínima/máxima, superficie usada, explicación y `Confianza alta` o `Referencial`.
- `unavailable`: explicación y motivo (cobertura, catastro no encontrado, unidad
  incompleta, menos de diez comparables o archivos SII no disponibles); sin valor.
- `ambiguous`: explicación, cantidad total y hasta veinte candidatos anónimos,
  sin elegir uno. Los identificadores son opciones efímeras, no roles catastrales;
  el usuario debe completar/corregir la dirección, no seleccionar un rol oculto.

La proyección pública no contiene roles, raw IDs, manzanas, unidades, direcciones
ni valores individuales de los comparables. La dirección tampoco se añade al
evento de uso. Un fallo de esta capa conserva la respuesta canónica y añade una
explicación genérica; el log no incluye la excepción ni los datos individuales.

Una unidad identificada aporta superficie cerrada y año del catastro. Si solo
se identifica el edificio, sin elegir arbitrariamente una unidad, se permite
usar la superficie ingresada únicamente cuando las unidades residenciales
comparten un año conocido; la interfaz explica esta base. En caso contrario pide
el departamento. El kNN excluye ventas del propio rol identificado y ventas
en la fecha de consulta o posteriores, como antes.

## Regla congelada

Se llama directamente a `is_trusted` con el mismo JSON versionado del PR previo,
sin recalibración ni nuevas reglas por comuna. La capa comprueba su SHA-256
normalizado a LF: `57ddad8d5276f9b06240904404ef14c7cd75d190e9446888a670822d4debd94d`.
Es el mismo contenido que el archivo local CRLF cuyo hash de auditoría previo es
`62e2647548487f63018a100c2f2b3c6231fd6ae212262f9307fb0cb7574b5f34`.
«Confianza alta» identifica la zona validada en 2025H2; no promete error individual
menor a 10%. No se usa el holdout 2026 para elegir o modificar reglas.

## Reproducción y evidencia

El informe agregado está en `reports/sii/tasar_closing_20261019/report.md`.
El script `python -m scripts.report_sii_signed_bias --records <archivo-local>
--output <resumen-agregado>` calcula las medianas con signo y el recentrado
descriptivo sin exportar filas ni escribir calibraciones de producción.

`tests/unit/test_sii_tasar.py` ejecuta el endpoint fuente de la release
`24b56dc6fe626d19834bcd6707a9b77d1d3d44c7` y el actual sobre el mismo servicio
canónico. Requiere disponer de ese commit en el checkout (`git fetch` si es
superficial). Las fixtures SII son sintéticas y usan kNN y regla reales.
También prueba las ramas alta/referencial/sin datos, candidatos, privacidad,
fallo seguro y SQLite sin escrituras. Las regresiones previas siguen ejecutándose.

Las capturas se obtuvieron del formulario real y routers/servicios reales en
loopback, con el stock de avisos previamente capturado y los archivos SII locales.
El acceso sintético existe solo en el arnés local fuera del repositorio. Los
registros individuales, el arnés y las capturas permanecen exclusivamente locales.
