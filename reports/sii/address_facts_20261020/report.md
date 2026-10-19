# Ficha de propiedad: terreno SII y presentación legible

Continuación del PR #11 en borrador. El flag sigue apagado por defecto en el
código. Solo la demostración local lo habilita. Sin merge ni deploy; motores,
pesos, K, escalas y regla de confianza permanecen iguales.

## Datos recuperados

El terreno sí estaba en la base SII local (`sii.predio.m2_terreno`), pero había
quedado fuera del índice de direcciones exportado. Se corrige mediante un
archivo complementario de solo lectura, sin modificar el índice original ni
el pool de cierres. Se exportaron **194.518 casas**, de las **ocho versiones de
fuente** usadas por el índice, en una transacción local de solo lectura.

La consulta añade terreno positivo únicamente a una casa identificada de forma
inequívoca y con rol/source ID idénticos. No mezcla semestres, no reparte terreno
común entre departamentos y no inventa superficies ausentes. Baños, dormitorios
y estacionamientos siguen desconocidos cuando no existe un dato enlazado fiable.
Los registros y archivos SQLite permanecen solo locales.

## Presentación

- Tarjeta «Propiedad encontrada», origen catastral, tipo y año destacados.
- Construcción y terreno se muestran directamente en campos editables, con
  indicación SII en los campos rellenados. No se repiten superficies en párrafos.
- Sección «Completa tu ficha» para los datos desconocidos, sin convertirlos en cero.
- Se conservan las correcciones manuales. Cambiar dirección/comuna retira los
  valores automáticos anteriores y descarta respuestas de consultas anteriores.
- La tarjeta y los campos se apilan en paneles estrechos, con tipografía legible
  y valores completos. Se eliminaron los antiguos textos pequeños repetidos.

## Verificación

**160 pruebas en verde**, Ruff y TypeScript correctos en ambas interfaces.
Las pruebas nuevas cubren terreno de la misma casa y versión, versión distinta,
valores nulos/negativos/no finitos, ausencia de terreno común en departamentos
y lectura sin escrituras. Se mantienen las regresiones de respuesta exacta de
la release con flag apagado o sin dirección y los casos SII anteriores.

La ficha se comprobó en el Tasar real local para una casa de Vitacura: construcción,
terreno, año y tipo disponibles. La prueba se realizó también en el panel estrecho
del navegador y se corrigió el solapamiento de las superficies. Las capturas y
los datos de los casos se conservan exclusivamente en la entrega local.
