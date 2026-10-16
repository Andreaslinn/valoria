# Cruce aviso → catastro (16-oct-2026)
Inputs: 400 fichas auditadas PR #5 (/workspace/work/pr5/ba.csv; 322 en 8 comunas), catastro BRTMPCATAS 2S-2026, OSM addresses (Overpass, 95k en 8 comunas) + comuna boundaries, cierres_deptos_ufm2.parquet, export 15-oct (precios).
Geolocalización catastro: dirección SII (calle+número) → OSM exacto o interpolado por calle → 42–81% de deptos geolocalizados por comuna (manzanas 57–90%).
Resultados:
- Dirección exacta: 46/59 al edificio SII; año coincide ±3 en 32/41.
- Coords Portal: mediana 21 m al edificio de su dirección; mismo edificio 22/27, misma manzana 24/27.
- Asignados a edificio: 193/322 (Portal 129/200, Yapo 64/122).
- m² útil Portal ≈ m² SII construido CERRADO (m2_H − m2_H_abierta): mediana 1,00; 95/127 dentro de ±5% (sesgo de vecino más cercano). Total publicado vs SII total: 0,96.
- Gap pedido vs cierres similares (±12% m², mismo edificio, ≥2 cierres 2024–26): mediana +13% (p25 −1%, p75 +41%), n=57. Preliminar.
Next: recompute SII UF/m² on m² cerrado; more fichas from PR #6; offline benchmark Valoria.
