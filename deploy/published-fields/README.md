# Captura de datos publicados — despliegue sujeto a nuevo OK

## Contrato y alcance

`listings.raw_metadata.published_fields` conserva una observación de ficha con
superficie útil, total y construida independientes; antigüedad y año; piso;
coordenadas y precisión declarada; dirección original y sus partes. Cada valor
tiene procedencia y original. Ausentes quedan `null`. No hay geocodificación,
conversión de años a antigüedad, copia de `square` a útil ni coordenadas imputadas.
`built_area_m2` y `usable_area_m2` reciben solamente valores explícitos de esta
observación. El `m2` genérico permanece disponible por compatibilidad y
`valuation_m2_kind` identifica la superficie que efectivamente elige el motor.
No cambia código del motor ni se introduce dirección/microzonas en el cálculo.

Se guardan los años y superficies diferentes del JSON y la descripción, con
conflicto explícito. Se rechazan (0,0), oficinas del corredor y datos de otra
publicación. Una precisión desconocida sigue siendo desconocida: dirección,
zoom y privacidad del marcador no certifican exactitud. Piso, pisos del edificio
y departamentos por piso no se convierten en número de departamento.

Una tarjeta no borra la observación de ficha anterior; se conserva por separado
con su fecha. Una ficha completa posterior sí reemplaza el snapshot: un dato
que dejó de publicarse no reaparece por un merge de valores antiguos.

## Presupuesto de adquisición

Portal mantiene hasta ocho búsquedas de una página, cinco detalles y el
presupuesto geográfico existente de hasta cinco solicitudes (incluido mapa y
redirecciones). Ahora también rota detalles de tarjetas completas, primero
las nunca intentadas y luego el intento más antiguo, incluyendo los fallidos. Yapo conserva sus límites de
paginación y añade dentro del mismo proceso hasta cinco detalles de departamento
por ciclo, priorizando observaciones pendientes. No agrega timers, navegador,
proxy, servicio externo ni gasto. Cada GET de enriquecimiento espera al limitador;
el nuevo paso Yapo no sigue redirecciones. Se detiene ante bloqueo, 403 o 429.
Estos lotes completan la captura gradualmente; no se promete detallar todos los
avisos nuevos en un solo ciclo de cinco solicitudes.

La auditoría de aceptación es una adquisición separada y explícitamente
autorizada de al menos 200 fichas por fuente, desde Oracle con sus clientes HTTP,
sin ingesta manual de producción. La persistencia se verifica en SQLite aislada,
en lotes de cinco y usando el modelo ORM y la función de actualización reales.
`scripts/audit_published_fields.py` nunca crea un motor contra PostgreSQL.

## Alarma

`PortalSessionExpired` registra `PORTAL_SESSION_EXPIRED` en stderr y en el
ledger de la fuente. `/health` incluye `sources.portalinmobiliario.alarms` y
degrada la fuente si falla la corrida. El cliente comprueba el 302 a
`/gz/account-verification` antes de seguirlo y no guarda cookies de una sesión
rechazada. La renovación sigue siendo la verificación oficial; no se automatiza
un bypass ni se imprime el destino con parámetros privados.

## Procedimiento tras el OK

1. Verificar que el PR definitivo incluye la dependencia de ubicación del PR #4;
   integrar sobre `release/canonical-only-reproducible-20261013`, nunca sobre la
   rama predeterminada. Reconstruir únicamente desde el commit mergeado.
2. Capturar estado de imagen, commit, timers, `/health`, ledger y manifiesto de
   hashes. Mantener disponibles el código e imagen de rollback `c55f4b6`.
3. Crear un respaldo PostgreSQL y verificarlo restaurándolo en una base aislada;
   acreditar referencias sobre una única base y UF congeladas. No restaurar
   sobre producción durante la preparación.
4. Conservar límites CPU/memoria/PIDs, raíces de solo lectura, reservas Always
   Free, frecuencias y timer UF. No existe una migración nueva para este contrato:
   usa JSON existente y columnas físicas existentes; 0023 permanece aplicada.
5. Sustituir el artefacto con el commit mergeado, verificar sincronización y
   repetir ambas referencias antes de cualquier ingesta. Si difieren, rollback.
6. Dejar actuar el siguiente ciclo normal. Consultar en lectura los campos,
   conteos, conflictos, `/health` y alarmas. No lanzar 200 fichas extra contra
   producción ni modificar comparables para hacer pasar la prueba.

## Rollback

Reactivar exactamente el artefacto y código verificados de `c55f4b6`, comprobar
manifiesto, `/health` y referencias. No bajar 0023 ni desactivar el timer UF.
No se necesita downgrade de esquema y no se borran observaciones JSON. El código
anterior ignora los nuevos campos y retoma su captura histórica. Conservar los
errores de la corrida fallida. Una restauración de datos necesita autorización
separada y solo se contempla si existe daño acreditado; un rollback de código
no justifica borrar la ingesta válida.
