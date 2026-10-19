-- Latest complete role/line pair by semester. Incomplete new imports do not replace
-- the previous complete snapshot. SII sector codes remain part of every join.
UPDATE sii.predio SET tipo='depto' WHERE destino='H' AND tipo<>'depto'
 AND direccion_raw ~* '(^|[^A-Z0-9])(DP|DEPTO|DPTO|DEP)([^A-Z0-9]|$)';
CREATE TEMP TABLE active_catastro ON COMMIT DROP AS
SELECT DISTINCT ON (s.comuna) s.comuna,s.id AS role_source,nl.id AS line_source,s.semestre
FROM sii.source_file s
JOIN LATERAL (SELECT id FROM sii.source_file l
 WHERE l.tipo='NL' AND l.comuna=s.comuna AND l.semestre=s.semestre
 ORDER BY l.cargado_en DESC,l.id DESC LIMIT 1) nl ON true
WHERE s.tipo='N'
ORDER BY s.comuna,s.semestre DESC,s.cargado_en DESC,s.id DESC;
ANALYZE active_catastro;

CREATE TEMP TABLE line_totals ON COMMIT DROP AS
SELECT l.comuna,l.manzana,l.predio,l.source_file_id,
 min(l.anio) AS anio_min,
 coalesce(sum(l.m2) FILTER (WHERE l.destino='H'),0) AS m2_h,
 coalesce(sum(l.m2) FILTER (WHERE l.destino='H' AND l.abierta),0) AS m2_h_abierta
FROM sii.linea_construccion l JOIN active_catastro a ON l.source_file_id=a.line_source
GROUP BY l.comuna,l.manzana,l.predio,l.source_file_id;
CREATE UNIQUE INDEX ON line_totals(comuna,manzana,predio);
ANALYZE line_totals;

UPDATE sii.predio p SET anio_min=l.anio_min,m2_h=l.m2_h,m2_h_abierta=l.m2_h_abierta,
 semestre=a.semestre
FROM active_catastro a,line_totals l
WHERE p.source_file_id=a.role_source AND l.source_file_id=a.line_source
 AND (p.comuna,p.manzana,p.predio)=(l.comuna,l.manzana,l.predio)
 AND (p.anio_min,p.m2_h,p.m2_h_abierta)
 IS DISTINCT FROM (l.anio_min,l.m2_h,l.m2_h_abierta);
UPDATE sii.predio p SET anio_min=NULL,m2_h=0,m2_h_abierta=0
FROM active_catastro a
WHERE p.source_file_id=a.role_source AND NOT EXISTS
 (SELECT 1 FROM line_totals l WHERE (p.comuna,p.manzana,p.predio)=(l.comuna,l.manzana,l.predio))
 AND (p.m2_h,p.m2_h_abierta) IS DISTINCT FROM (0::numeric,0::numeric);
UPDATE sii.source_file s SET line_source_file_id=a.line_source FROM active_catastro a
WHERE s.id=a.role_source AND s.line_source_file_id IS DISTINCT FROM a.line_source;

CREATE TEMP TABLE current_predio ON COMMIT DROP AS
SELECT p.source_file_id,p.comuna,p.manzana,p.predio,p.tipo,p.semestre,p.m2_h,p.m2_cerrado,p.calle,p.numero
FROM sii.predio p JOIN active_catastro a ON p.source_file_id=a.role_source;
CREATE UNIQUE INDEX ON current_predio(comuna,manzana,predio);
ANALYZE current_predio;

-- Exact dated calendar only: FE is preferred, FI only when FE is absent.
-- Missing FE calendar values remain excluded, never silently substituted.
CREATE TEMP TABLE converted ON COMMIT DROP AS
SELECT r.id,r.source_file_id,r.comuna,r.manzana,r.predio,r.fi,r.fe,r.clp,r.uf,r.errores_parseo,
 p.source_file_id AS predio_source_file_id,p.tipo,p.semestre,p.m2_h,p.m2_cerrado,
 coalesce(r.fe,r.fi) AS fecha,
 CASE WHEN r.uf>0 THEN r.uf WHEN r.clp>0 AND u.value>0 THEN r.clp/u.value END AS monto_uf,
 CASE WHEN NOT coalesce(r.uf>0,false) AND r.clp>0 AND u.value>0 THEN u.value END AS uf_usada,
 CASE WHEN NOT coalesce(r.uf>0,false) AND r.clp>0 AND u.value>0 THEN u.date END AS uf_fecha
FROM sii.transferencia_raw r
LEFT JOIN current_predio p USING (comuna,manzana,predio)
LEFT JOIN public.ingestion_uf_calendar u ON u.date=CASE
 WHEN 'fe_invalida'=ANY(r.errores_parseo) THEN NULL ELSE coalesce(r.fe,r.fi) END
WHERE r.source_file_id=(SELECT id FROM sii.source_file WHERE tipo='F2890' ORDER BY fecha DESC,cargado_en DESC,id DESC LIMIT 1);

-- All observations survive in raw and derived; ranking chooses the largest
-- amount per (SII rol, FE, FI) before group-level statistics.
CREATE TEMP TABLE ranked ON COMMIT DROP AS
SELECT *,row_number() OVER (PARTITION BY comuna,manzana,predio,fe,fi
 ORDER BY monto_uf DESC NULLS LAST,id) AS duplicate_rank
FROM converted;
ANALYZE ranked;
CREATE TEMP TABLE winners ON COMMIT DROP AS SELECT * FROM ranked WHERE duplicate_rank=1;
ANALYZE winners;
CREATE TEMP TABLE operation_stats ON COMMIT DROP AS
SELECT comuna,manzana,fe,fi,
 count(*) FILTER (WHERE tipo='depto') AS deptos,
 count(*) FILTER (WHERE tipo IN ('estac','bodega')
  AND coalesce(uf,0)<=0 AND coalesce(clp,0)<=0) AS aux_sin_monto
FROM winners GROUP BY comuna,manzana,fe,fi;
ANALYZE operation_stats;
CREATE TEMP TABLE repeated ON COMMIT DROP AS
SELECT comuna,manzana,fe,fi,max(monto_uf) AS monto_uf,count(*) AS cantidad
FROM winners GROUP BY comuna,manzana,fe,fi
HAVING count(*)>1 AND count(*) FILTER (WHERE monto_uf>0)=count(*)
 AND count(DISTINCT monto_uf)=1;
ANALYZE repeated;
CREATE TEMP TABLE house_blocks ON COMMIT DROP AS
SELECT comuna,manzana,fecha,count(DISTINCT predio) AS casas
FROM winners WHERE tipo='casa' GROUP BY comuna,manzana,fecha;
ANALYZE house_blocks;

CREATE TEMP TABLE decisions ON COMMIT DROP AS
SELECT r.*,
 r.monto_uf/nullif(r.m2_h,0) AS uf_m2_h,
 r.monto_uf/nullif(r.m2_cerrado,0) AS uf_m2_cerrado,
 (r.tipo='depto' AND s.aux_sin_monto>0) AS paquete,
 array_remove(ARRAY[
  CASE WHEN r.duplicate_rank>1 THEN 'duplicado_rol_fecha' END,
  CASE WHEN r.predio_source_file_id IS NULL THEN 'sin_catastro' END,
  CASE WHEN r.tipo NOT IN ('depto','casa') THEN 'tipo_no_comparable' END,
  CASE WHEN coalesce(r.uf,0)<=0 AND coalesce(r.clp,0)<=0 THEN 'sin_monto' END,
  CASE WHEN coalesce(r.uf,0)<=0 AND r.clp>0 AND r.uf_usada IS NULL THEN 'sin_uf_fecha_exacta' END,
  CASE WHEN r.fecha IS NULL THEN 'sin_fecha' END,
  CASE WHEN r.tipo='depto' AND (r.m2_h IS NULL OR r.m2_h<20 OR r.m2_h>300) THEN 'm2_fuera_20_300' END,
  CASE WHEN r.tipo='casa' AND coalesce(r.m2_h,0)<=0 THEN 'sin_m2' END,
  CASE WHEN r.monto_uf/nullif(r.m2_h,0)<15 OR r.monto_uf/nullif(r.m2_h,0)>500 THEN 'uf_m2_fuera_15_500' END,
  CASE WHEN r.tipo IN ('depto','casa') AND rep.cantidad>1 THEN 'monto_repetido_en_grupo' END,
  CASE WHEN r.tipo='depto' AND s.aux_sin_monto>0 THEN 'paquete_estac_bodega_sin_monto' END,
  CASE WHEN r.tipo='depto' AND s.deptos>=10 THEN 'lote_10_deptos' END,
  CASE WHEN r.tipo='casa' AND h.casas>=3 THEN 'bloque_3_casas_misma_manzana' END
 ]::text[],NULL) || r.errores_parseo AS motivos
FROM ranked r
LEFT JOIN operation_stats s ON (r.comuna,r.manzana)=(s.comuna,s.manzana)
 AND coalesce(r.fe,'-infinity'::date)=coalesce(s.fe,'-infinity'::date)
 AND coalesce(r.fi,'-infinity'::date)=coalesce(s.fi,'-infinity'::date)
LEFT JOIN repeated rep ON (r.comuna,r.manzana,r.monto_uf)=(rep.comuna,rep.manzana,rep.monto_uf)
 AND coalesce(r.fe,'-infinity'::date)=coalesce(rep.fe,'-infinity'::date)
 AND coalesce(r.fi,'-infinity'::date)=coalesce(rep.fi,'-infinity'::date)
LEFT JOIN house_blocks h ON (r.comuna,r.manzana)=(h.comuna,h.manzana)
 AND coalesce(r.fecha,'-infinity'::date)=coalesce(h.fecha,'-infinity'::date);

CREATE TEMP TABLE rebuild_counters ON COMMIT DROP AS
SELECT count(*) AS rows_new FROM decisions d WHERE NOT EXISTS
 (SELECT 1 FROM sii.transferencia t WHERE t.raw_id=d.id);

-- Build without row-by-row FK probes, then validate every FK in bulk before
-- the atomic cache swap. Raw's append-only trigger remains enabled throughout.
CREATE TABLE sii.transferencia_build
 (LIKE sii.transferencia INCLUDING DEFAULTS INCLUDING GENERATED INCLUDING CONSTRAINTS);
INSERT INTO sii.transferencia_build(raw_id,source_file_id,predio_source_file_id,comuna,manzana,predio,
 fi,fe,fecha,tipo,semestre,monto_uf,monto_clp,uf_usada,uf_fecha,m2_h,m2_cerrado,
 uf_m2_h,uf_m2_cerrado,paquete,cierre_comparable,motivo_exclusion,motivos_exclusion,reglas_version)
SELECT id,source_file_id,predio_source_file_id,comuna,manzana,predio,fi,fe,fecha,tipo,semestre,
 monto_uf,clp,uf_usada,uf_fecha,m2_h,m2_cerrado,uf_m2_h,uf_m2_cerrado,coalesce(paquete,false),
 cardinality(motivos)=0,motivos[1],motivos,'sii-phase1-v2' FROM decisions;
ALTER TABLE sii.transferencia_build ADD PRIMARY KEY(raw_id);
ALTER TABLE sii.transferencia_build ADD CONSTRAINT bulk_raw_fk
 FOREIGN KEY(raw_id) REFERENCES sii.transferencia_raw(id) NOT VALID;
ALTER TABLE sii.transferencia_build ADD CONSTRAINT bulk_file_fk
 FOREIGN KEY(source_file_id) REFERENCES sii.source_file(id) NOT VALID;
ALTER TABLE sii.transferencia_build ADD CONSTRAINT bulk_predio_file_fk
 FOREIGN KEY(predio_source_file_id) REFERENCES sii.source_file(id) NOT VALID;
ALTER TABLE sii.transferencia_build VALIDATE CONSTRAINT bulk_raw_fk;
ALTER TABLE sii.transferencia_build VALIDATE CONSTRAINT bulk_file_fk;
ALTER TABLE sii.transferencia_build VALIDATE CONSTRAINT bulk_predio_file_fk;
CREATE INDEX ON sii.transferencia_build(comuna,tipo,cierre_comparable);
DROP TABLE sii.transferencia;
ALTER TABLE sii.transferencia_build RENAME TO transferencia;
