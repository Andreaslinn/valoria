# Corrección de altas deduplicadas y redespliegue

El respaldo anterior conserva la fila 6612, ID Yapo 32982982: Departamento en
Avenida Pocuro, Providencia, 84 m², 2 dormitorios y 2 baños; coordenadas
-33.435883,-70.60571. No tenía published_fields ni published_detail_fields.
La publicación 32747182 reutilizó esa fila y su fingerprint. Estos coinciden
en los datos de tarjeta, pero el fingerprint no prueba por sí solo que sean
el mismo departamento. Al no existir una ficha canónica completa, la omisión
no puede contarse como éxito, cualquiera sea la identidad física.

Yapo decide si el ID de publicación existe **antes** del upsert. Una identidad
nueva recibe detalle incluso si el upsert la clasifica como actualización de
una fila canónica. Los aliases incompletos de una identidad ya conocida se
recuperan usando como máximo los cinco cupos de mantenimiento existentes,
cuando el historial acredita otro ID en esa fila. Esos GET descuentan del
mantenimiento posterior; no aumenta ese presupuesto ni toca el refresher.
La captura está ligada al ID solicitado, sin copiar hechos de un duplicado
solo por compartir fingerprint. Las pruebas cubren ambos estados de 32747182.

Se registran en ledger y lanzador http_requests, http_302, http_403 y http_429,
además de los contadores de detalle. Se observan las respuestas del cliente
existente; no se crean solicitudes para instrumentar ni se registran URLs.

**La alarma de disco de 10 GB queda explícitamente fuera de este cambio.**
No se implementa ni activa limpieza de caché, retención o un timer nuevo.
Se miden bytes libres antes y después del despliegue.

Procedimiento autorizado: respaldo nuevo restaurado en aislamiento, ensayo
candidato/80bd8a9 sobre esa misma DB y UF, merge sobre la rama release,
reconstrucción exclusivamente desde ese commit y guardia de archivos. El
lanzador del host se instala desde el blob comprometido de la imagen y se
restaura su copia anterior al revertir. Ningún archivo de timer cambia.

El ledger Portal de la prueba anterior quedó interrumpido por el rollback.
Si su única degradación inicial es esa corrida sin finalizar, se documenta
como condición de partida y se recupera con el primer ciclo normal; no se
edita manualmente la DB para ocultarla. Cualquier otra degradación bloquea.

Aceptación: hasta tres ciclos normales por fuente o al menos quince altas
nuevas; 90% de fichas completas, cero respuestas 302/403/429 observadas,
ledger concordante y salud final OK. Una ficha canónica de duplicado solo se
cuenta con evidencia de duplicidad y observación completa; una tarjeta nunca
cuenta como ficha. Ante fallo, rollback de código a 80bd8a9, conservando datos.

Si no queda desplegado, release vuelve **al commit exacto 80bd8a9** con lease
del tip remoto, conservando los commits en las ramas de PR, y los PRs mergeados
no desplegados se marcan deployment-rolled-back. No se deja una rama release
que afirme correr un artefacto diferente de producción.
