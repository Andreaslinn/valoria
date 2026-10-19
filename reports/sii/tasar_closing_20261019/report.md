# Tasar: segunda opinión SII y diagnóstico de sesgo · 19/10/2026

PR #11, en borrador, sobre `release/canonical-only-reproducible-20261013`.
Integración aditiva en ambas interfaces; `sii_closing_layer` apagado por defecto.
Sin merge ni deploy. No se cambia K, pesos, escalas, motor canónico ni regla congelada.

## Sesgo en los mismos 1.142 casos emparejados

Error con signo = `100 × (valor estimado / cierre real − 1)`; positivo significa
sobreestimación. MdAPE es la mediana del error porcentual absoluto.

| Comuna | n | Mediana con signo canónico % | Mediana con signo kNN % | Razón proxy aviso/cierre | MdAPE canónico % | MdAPE canónico / razón % |
|---|---:|---:|---:|---:|---:|---:|
| Santiago | 139 | +28.89 | +0.34 | 1.2889 | 32.24 | 32.33 |
| Estación Central | 141 | +5.16 | +0.00 | 1.0516 | 30.64 | 32.05 |
| Providencia | 139 | +39.58 | -2.52 | 1.3958 | 40.33 | 19.20 |
| Ñuñoa | 146 | +14.41 | -3.18 | 1.1441 | 16.82 | 14.69 |
| Las Condes | 143 | +5.37 | -3.42 | 1.0537 | 19.66 | 19.23 |
| La Florida | 140 | -8.02 | -2.02 | 0.9198 | 21.58 | 19.54 |
| Vitacura | 148 | +19.93 | -1.21 | 1.1993 | 24.19 | 18.51 |
| San Miguel | 146 | +10.48 | -3.71 | 1.1048 | 21.43 | 22.10 |


**Límite de la razón aviso/cierre:** no hay parejas de aviso observado y venta
del mismo inmueble. La razón disponible es el **proxy** `mediana(valor canónico
del stock de avisos / cierre real)` por comuna, en estos mismos casos. El stock
es vigente al 19/10/2026 frente a cierres anteriores. No representa una tasa de
negociación observada ni permite separar causalmente el algoritmo del origen de
precios. El MdAPE ajustado divide el valor canónico por ese proxy, calculado ex
post sobre el mismo holdout; es un diagnóstico descriptivo, **no una validación
de calibración aprendida fuera de muestra**. No entra en Tasar, kNN ni confianza.
El ajuste mejora cinco comunas y empeora Santiago, Estación Central y San Miguel.
Las cifras completas, incluido P95 ajustado, están en `bias-summary.json`.

## Comportamiento integrado

- La estimación actual y sus comparables permanecen iguales. La capa adicional
  se muestra junto a ella, con valor en UF, rango P25–P75, diez cierres y fechas.
- **Confianza alta** utiliza exactamente la zona congelada de validación 2025H2.
  Fuera de ella se muestra **Referencial**, según la nueva política de presentación
  solicitada. No se modifica `apply_rule`, su abstención de auditoría ni sus celdas.
- Catastro sin coincidencia, campos insuficientes, menos de diez comparables o
  datos locales ausentes: no hay valor SII y se explica el motivo.
- Dirección ambigua: no hay valor SII ni selección automática; se devuelven
  candidatos anónimos y se pide completar la dirección. Sin roles ni direcciones
  de terceros, tampoco en los caminos de error o ambigüedad.
- Sin flag o sin dirección, no se carga el índice/pool SII ni se añade la clave
  opcional a la respuesta. La segunda opinión tampoco altera el evento de uso.

Para unidad identificada se usan m² cerrados y año del catastro. Si solo se resuelve
el edificio con año común conocido, se explica el uso del área ingresada y que no
se identificó la unidad; nunca se elige arbitrariamente un departamento.

## Validación

**145 pruebas pasadas**, incluidas las regresiones canónicas y SII anteriores,
API de la release real frente al actual, privacidad, cuatro ramas, fallo seguro,
default apagado y SQLite de solo lectura. Ruff y `git diff --check` correctos.
TypeScript `tsc --noEmit` correcto en `frontend` y `frontend-v2`.
No se ejecutó la suite completa ni se realizó un despliegue.

Además, el endpoint fuente del commit de release
`24b56dc6fe626d19834bcd6707a9b77d1d3d44c7` y el actual se ejecutaron con el mismo
servicio canónico y stock local verificado en los 1.142 casos reales:

| Escenario | HTTP 200 con cuerpo idéntico byte a byte |
|---|---:|
| Flag apagado, dirección presente | 1.142 / 1.142 |
| Flag encendido, dirección ausente | 1.142 / 1.142 |

También se probaron direcciones nulas, vacías y entradas de dirección malformadas
ignoradas con flag apagado. Con flag encendido, los campos canónicos completos
coinciden con la release en las cuatro ramas de la capa adicional.

Se observaron y capturaron las tres ramas en el Tasar real local, y adicionalmente
la ambigüedad, usando routers y motores reales, stock capturado y catastro local.
Las capturas, el arnés de autenticación exclusivamente local y los registros
individuales se entregan **solo localmente**, no se suben al PR. El repositorio
contiene únicamente código, fixtures sintéticas y agregados.

Regla normalizada a LF SHA-256 `57ddad8d5276f9b06240904404ef14c7cd75d190e9446888a670822d4debd94d`;
kNN normalizado a LF SHA-256 `0e29cf44711c2cab8da612ca42ade263ca4f6aa10c4914c57a8ccd75423bd54f`. Ambos archivos siguen
idénticos al padre `9f0cc7f`. El hash CRLF previo de la regla es
`62e2647548487f63018a100c2f2b3c6231fd6ae212262f9307fb0cb7574b5f34`;
su contenido y bytes normalizados son iguales.

La evaluación anterior conserva su resultado: MdAPE ≤10% dentro de la zona en
las ocho comunas, pero **ninguna** alcanza cobertura ≥50%. Esta integración no
amplía ni reentrena la regla para corregir esa limitación. «Confianza alta» no
garantiza que un caso individual tenga error ≤10%.

Reproducción y contrato: `docs/sii_tasar_closing_layer.md`.
