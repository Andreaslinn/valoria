# Búsqueda por rol en Tasar — 2026-10-20

Se incorpora búsqueda exacta por rol y comuna en ambas interfaces, además de la
búsqueda por dirección. Completa los atributos disponibles de la misma unidad y
permite obtener su segunda opinión sin volver a resolver la dirección.

- Formatos corto y completo con código SII; ceros iniciales y separadores admitidos.
- Avisos para formato inválido, comuna incompatible y rol ausente.
- Endpoint autenticado y detrás de `sii_closing_layer`, apagado por defecto.
- Dirección mostrada únicamente del inmueble solicitado expresamente por rol.
- Datos automáticos retirados al cambiar consulta; correcciones manuales conservadas.
- Rol exacto usado para excluir las ventas del propio inmueble de los comparables.
- Sin cambios en motor canónico, K, pesos, escalas o regla congelada.

## Verificación

181 pruebas en verde: lookup, atributos, API, opinión SII, confianza, catastro,
ingesta y regresiones del motor. Incluyen igualdad byte a byte contra la release
con flag apagado y diferentes tipos de rol, y equivalencia de la tasación al
identificar la misma unidad por dirección o por rol. TypeScript correcto en ambas
interfaces y Ruff correcto en Python.

En Tasar local se verificaron el selector, rol corto y completo, ficha y superficies
autocompletadas, retirada de datos automáticos ante consulta inválida, aviso de
formato y tasación desde rol. Los registros y capturas individuales permanecen
exclusivamente locales. Solo se publican código, fixtures sintéticas y este informe.

El PR sigue en borrador, sin merge ni despliegue. La demostración local activa el
flag expresamente para probarlo; el valor por defecto de la aplicación sigue apagado.
