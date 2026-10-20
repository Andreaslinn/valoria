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

## Autocompletado desde la dirección

Con el mismo flag habilitado, ambas interfaces consultan automáticamente
`POST /api/v1/tasar/address-details` tras 600 ms sin escribir, una vez indicadas
comuna y dirección. Este endpoint requiere autenticación y devuelve 404 con el
flag apagado antes de abrir archivos. Consulta únicamente el índice catastral de
solo lectura; no requiere cargar cierres ni ejecutar una tasación.

Solo una unidad inequívoca permite completar superficie cerrada y tipo de
propiedad; también se muestra el año de construcción disponible. El terreno
de casas se completa desde el archivo complementario `address-details.sqlite`,
con unión por el mismo rol **y** source ID del índice. Varios roles
en el edificio requieren completar el departamento/torre: no se elige la primera
unidad, no se promedian áreas ni se toman atributos de un aviso cercano. La
respuesta conserva candidatos anónimos y no expone roles o direcciones ajenas.

El índice base había omitido el terreno que sí existe en `sii.predio.m2_terreno`.
La exportación complementaria corrige esa omisión sin reescribir el índice ni
el pool de cierres. Baños, dormitorios y estacionamientos no constan en los
datos catastrales disponibles ni tienen un aviso enlazado fiable. Permanecen
desconocidos y editables, nunca se rellenan con cero. Los datos importados desde
una publicación y las correcciones manuales se conservan. Al cambiar dirección
o comuna se retiran las superficies/tipo autocompletados anteriores; las respuestas de
consultas anteriores se descartan. No se consulta sin comuna o dirección.

El campo de construcción muestra su procedencia **SII** y la base de superficie
cerrada. Se envía como superficie
construida y `m2`, dejando `usable_area_m2=null` en lugar de fingir que es útil.
Si se edita manualmente, vuelve a la base de superficie del formulario habitual.
El año se muestra como dato de fuente y no modifica el contrato del canónico.

La ampliación actual pasa 160 pruebas de regresión/API/SII y TypeScript en ambas
interfaces. Se comprobó en Tasar local el llenado desde dirección, conservación
de m² y baños manuales, retirada de m² ante ambigüedad, cambio automático a casa
y tasación completa desde los datos rellenados. El informe agregado de la
ampliación inicial está en `reports/sii/address_autofill_20261019/report.md`.

La revisión de presentación usa una tarjeta de propiedad con tipo y año visibles,
superficies editables con origen por campo y una sección para completar datos
desconocidos. Los campos se apilan en contenedores estrechos para mostrar valores
completos. Se retiraron los párrafos pequeños repetidos bajo la dirección.
La revisión y cobertura están en `reports/sii/address_facts_20261020/report.md`.

Para preparar el archivo complementario únicamente desde el SII local, configurar
`SII_DATABASE_URL` con el destino local documentado y ejecutar:

```powershell
python -m scripts.export_sii_address_facts --index <directorio-privado>/address-index.sqlite --output <directorio-privado>/address-details.sqlite
```

La exportación exige el guard de base local, usa `REPEATABLE READ READ ONLY`,
selecciona las versiones exactas del índice y rechaza sobrescribir una salida
existente. El endpoint no conecta a Postgres. Si falta el archivo opcional o no
coincide la versión, el terreno permanece desconocido. No se hereda terreno
común de un departamento ni se convierte cero o valores inválidos en datos.

## Búsqueda exacta por rol

Ambas interfaces permiten elegir «Por dirección» o «Por rol». El rol se busca
en la comuna seleccionada, como manzana-predio (por ejemplo `1234-56`) o con
prefijo de código SII de comuna. Se admiten ceros iniciales, espacios y separador
guion o barra. Un prefijo de otra comuna se rechaza; nunca se busca una propiedad
vecina ni se interpreta un rol incompleto como una dirección.

`POST /api/v1/tasar/rol-details` requiere autenticación y el mismo flag; devuelve
404 antes de abrir archivos si está apagado. La búsqueda usa la clave exacta del
índice de solo lectura. Comparte el contrato de atributos y el tratamiento de
correcciones manuales con la búsqueda por dirección. Solo en esta consulta
explícita por rol se devuelve `subject_address`: la dirección del inmueble pedido,
sin exponer direcciones de candidatos o comparables.

Al tasar por rol se envía `sii_rol`, que identifica directamente la unidad para
la segunda opinión y su exclusión del pool. Si un cliente envía ambos criterios,
el rol tiene prioridad. El motor canónico conserva sus entradas y cálculo. Con
flag apagado, `sii_rol` se ignora incluso si tiene un tipo inválido; sin dirección
ni rol, la respuesta conserva exactamente los bytes de la release.

La ampliación pasa 181 pruebas y TypeScript en ambas interfaces. El informe
agregado está en `reports/sii/role_lookup_20261020/report.md`.
