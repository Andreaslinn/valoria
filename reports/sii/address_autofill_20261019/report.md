# Autocompletado de Tasar por dirección · 19/10/2026

Continuación del PR #11 en borrador. Sin merge ni deploy; el flag existente
`sii_closing_layer` sigue apagado por defecto. K, pesos, escalas, regla congelada,
servicio canónico y endpoint de tasación permanecen intactos.

En ambas interfaces, tras indicar comuna y dirección, se consultan las
características de la unidad identificada en el índice catastral. Se completan
solo los m² cerrados y el tipo disponibles y se muestra el año de construcción.
Baños, dormitorios, estacionamientos y terreno no constan en el índice y no
existe enlace fiable de los avisos a la unidad: se dejan sin completar.

No se sobrescriben superficies ni tipos corregidos/importados manualmente.
Al cambiar dirección o comuna se retiran los datos autocompletados anteriores.
Las consultas tienen espera de 600 ms y descartan respuestas de otra dirección.
El usuario ve el origen SII y la distinción entre superficie cerrada y útil;
la superficie cerrada no se envía como `usable_area_m2`.

Un edificio con varias unidades, dirección ambigua o departamento inexistente
no rellena campos. Se pide completar la dirección y se conservan candidatos
anónimos en el contrato; no se filtran roles ni direcciones de terceros.
El endpoint exige autenticación, no abre archivos con flag apagado y puede
consultar el índice sin disponer del archivo de cierres. No realiza escrituras.

## Verificación

**153 pruebas pasadas**: las 145 anteriores más ocho pruebas del nuevo endpoint.
Cubren atributos reales del índice, privacidad, ausencia de archivo de cierres,
ambigüedad, unidad no encontrada, edificio con varias unidades, autenticación,
flag apagado y rechazo de unidades no residenciales. Se siguen comprobando
las respuestas byte a byte contra la release y los caminos canónicos anteriores.
Ruff, `git diff --check` y `tsc --noEmit` correctos en ambas interfaces.

Prueba en el formulario real de Tasar con API, motores y archivos locales:

- Unidad identificada: área rellenada automáticamente, año visible, baños y
  dormitorios vacíos. Tasación completa sin escribir la superficie manualmente.
- Correcciones manuales: se conservan área y baños al consultar otra dirección.
- Cambio rápido de dirección a una ambigua: área automática anterior retirada,
  sin tomar atributos de una respuesta anterior.
- Casa identificada: selección automática de tipo casa y superficie cerrada;
  terreno permanece desconocido para completar manualmente.

Las capturas y los datos de estos casos permanecen solo en la entrega local.
No se añadieron registros individuales ni capturas al repositorio.
