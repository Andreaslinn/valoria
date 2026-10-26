-- Read-only reproduction of the external join6.py comparator, not production rules.
WITH base AS MATERIALIZED (
 SELECT t.raw_id,t.comuna,t.manzana,t.predio,t.rol,t.fi,t.fe,t.cierre_comparable,t.tipo AS runtime_tipo,
  r.campos->>'FECHA_ESCRITURA' AS fe_raw,r.campos->>'FECHA_INSCRIPCION' AS fi_raw,
  CASE WHEN p.destino='H' AND p.direccion_raw ~* '(^|[^A-Z0-9])(DP|DEPTO|DPTO|DEP)([^A-Z0-9]|$)' THEN 'depto'
   WHEN p.destino='H' THEN 'casa' WHEN p.destino='Z' THEN 'estac' WHEN p.destino='L' THEN 'bodega' ELSE 'otro' END AS tipo,
  p.m2_h,coalesce(CASE WHEN r.uf>0 THEN r.uf WHEN r.clp>0 THEN r.clp/u.value END,0) AS uf
 FROM sii.transferencia t JOIN sii.transferencia_raw r ON r.id=t.raw_id
 LEFT JOIN sii.predio p ON (p.source_file_id,p.comuna,p.manzana,p.predio)=
  (t.predio_source_file_id,t.comuna,t.manzana,t.predio)
 LEFT JOIN public.ingestion_uf_calendar u ON u.date=CASE WHEN r.fe>=DATE '2024-01-01' AND r.fe<=r.fi THEN r.fe ELSE r.fi END
 WHERE t.fi>=DATE '2024-01-01' AND t.comuna IN(13101,14157,15103,15105,15108,15128,15160,16106)
  AND t.manzana IS NOT NULL AND t.predio IS NOT NULL
), ranked AS MATERIALIZED (
 SELECT *,row_number() OVER(PARTITION BY comuna,manzana,predio,fe_raw,fi_raw ORDER BY uf DESC,raw_id) AS rank
 FROM base
), winners AS MATERIALIZED (SELECT * FROM ranked WHERE rank=1), groups AS MATERIALIZED (
 SELECT comuna,manzana,fe_raw,fi_raw,count(*) AS n,count(*) FILTER(WHERE uf>0) AS priced,
  count(DISTINCT uf) AS amounts,count(*) FILTER(WHERE tipo='depto') AS deptos,
  count(*) FILTER(WHERE tipo IN('estac','bodega') AND uf<=0) AS unpriced_aux
 FROM winners GROUP BY comuna,manzana,fe_raw,fi_raw
), decisions AS MATERIALIZED (
 SELECT w.*,coalesce(w.tipo='depto' AND w.uf>0 AND w.m2_h BETWEEN 20 AND 300
  AND NOT(g.n>1 AND g.n=g.priced AND g.amounts=1) AND g.unpriced_aux=0 AND g.deptos<10
  AND w.uf/nullif(w.m2_h,0) BETWEEN 15 AND 300,false) AS reference_comparable
 FROM winners w JOIN groups g USING(comuna,manzana,fe_raw,fi_raw)
)
SELECT comuna,count(*) FILTER(WHERE reference_comparable) AS reference_count,
 count(*) FILTER(WHERE cierre_comparable AND runtime_tipo='depto') AS runtime_count,
 (array_agg(rol ORDER BY raw_id) FILTER(WHERE reference_comparable AND NOT(cierre_comparable AND runtime_tipo='depto')))[1:5] AS reference_only_examples,
 (array_agg(rol ORDER BY raw_id) FILTER(WHERE cierre_comparable AND runtime_tipo='depto' AND NOT reference_comparable))[1:5] AS runtime_only_examples
FROM decisions GROUP BY comuna ORDER BY comuna;
