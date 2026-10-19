CREATE SCHEMA IF NOT EXISTS sii;
CREATE TABLE sii.source_file (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 tipo text NOT NULL CHECK (tipo IN ('F2890', 'N', 'NL', 'OSM')),
 nombre text NOT NULL, semestre text, fecha date, comuna integer,
 hash char(64) NOT NULL, filas bigint NOT NULL DEFAULT 0,
 filas_seleccionadas bigint NOT NULL DEFAULT 0,
 ruta text NOT NULL, cargado_en timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tipo,nombre,hash)
);
CREATE TABLE sii.predio (
 source_file_id bigint NOT NULL REFERENCES sii.source_file(id),
 comuna integer NOT NULL, manzana integer NOT NULL, predio integer NOT NULL,
 comuna_ine integer GENERATED ALWAYS AS (CASE comuna WHEN 13101 THEN 13101 WHEN 13134 THEN 13101 WHEN 13135 THEN 13101 WHEN 14157 THEN 13106 WHEN 14158 THEN 13107 WHEN 15103 THEN 13123 WHEN 15105 THEN 13120 WHEN 15108 THEN 13114 WHEN 15128 THEN 13110 WHEN 15132 THEN 13113 WHEN 15160 THEN 13132 WHEN 15161 THEN 13115 WHEN 16106 THEN 13130 END) STORED,
 rol text GENERATED ALWAYS AS (comuna::text || '-' || manzana::text || '-' || predio::text) STORED,
 direccion_raw text NOT NULL, calle text NOT NULL, numero text, unidad text,
 destino text NOT NULL, tipo text NOT NULL CHECK (tipo IN ('casa','depto','estac','bodega','otro')),
 m2_terreno numeric NOT NULL, avaluo numeric NOT NULL, contribucion numeric NOT NULL,
 anio_min integer, m2_h numeric, m2_h_abierta numeric,
 m2_cerrado numeric GENERATED ALWAYS AS (m2_h-m2_h_abierta) STORED,
 semestre text NOT NULL, line_source_file_id bigint REFERENCES sii.source_file(id),
 raw_line text NOT NULL,
 PRIMARY KEY(source_file_id,comuna,manzana,predio)
);
CREATE INDEX predio_rol_idx ON sii.predio(comuna,manzana,predio);
CREATE TABLE sii.linea_construccion (
 source_file_id bigint NOT NULL REFERENCES sii.source_file(id),
 comuna integer NOT NULL, manzana integer NOT NULL, predio integer NOT NULL,
 n_linea integer NOT NULL, destino text NOT NULL, material text NOT NULL,
 calidad text NOT NULL, anio integer, m2 numeric NOT NULL,
 abierta boolean NOT NULL, condicion text NOT NULL, pisos integer NOT NULL,
 raw_line text NOT NULL,
 PRIMARY KEY(source_file_id,comuna,manzana,predio,n_linea)
);
CREATE INDEX linea_rol_idx ON sii.linea_construccion(comuna,manzana,predio);
CREATE TABLE sii.transferencia_raw (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 source_file_id bigint NOT NULL REFERENCES sii.source_file(id), fila bigint NOT NULL,
 comuna integer NOT NULL, manzana integer, predio integer,
 fi date, fe date, clp numeric, uf numeric,
 raw_line text NOT NULL, campos jsonb NOT NULL,
 UNIQUE(source_file_id,fila)
);
CREATE INDEX transferencia_raw_rol_idx ON sii.transferencia_raw(comuna,manzana,predio);
CREATE FUNCTION sii.raw_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'sii.transferencia_raw is append-only'; END $$;
CREATE TRIGGER raw_no_mutation BEFORE UPDATE OR DELETE OR TRUNCATE ON sii.transferencia_raw
FOR EACH STATEMENT EXECUTE FUNCTION sii.raw_append_only();
CREATE TABLE sii.transferencia (
 raw_id bigint PRIMARY KEY REFERENCES sii.transferencia_raw(id),
 source_file_id bigint NOT NULL REFERENCES sii.source_file(id),
 predio_source_file_id bigint REFERENCES sii.source_file(id),
 comuna integer NOT NULL, manzana integer, predio integer,
 comuna_ine integer GENERATED ALWAYS AS (CASE comuna WHEN 13101 THEN 13101 WHEN 13134 THEN 13101 WHEN 13135 THEN 13101 WHEN 14157 THEN 13106 WHEN 14158 THEN 13107 WHEN 15103 THEN 13123 WHEN 15105 THEN 13120 WHEN 15108 THEN 13114 WHEN 15128 THEN 13110 WHEN 15132 THEN 13113 WHEN 15160 THEN 13132 WHEN 15161 THEN 13115 WHEN 16106 THEN 13130 END) STORED,
 rol text GENERATED ALWAYS AS (comuna::text || '-' || manzana::text || '-' || predio::text) STORED,
 fi date, fe date, fecha date, tipo text, semestre text,
 monto_uf numeric, monto_clp numeric, uf_usada numeric, uf_fecha date,
 m2_h numeric, m2_cerrado numeric, uf_m2_h numeric, uf_m2_cerrado numeric,
 paquete boolean NOT NULL DEFAULT false,
 cierre_comparable boolean NOT NULL, motivo_exclusion text,
 motivos_exclusion text[] NOT NULL,
 reglas_version text NOT NULL DEFAULT 'sii-phase1-v1'
);
CREATE INDEX transferencia_comuna_idx ON sii.transferencia(comuna,tipo,cierre_comparable);
CREATE TABLE sii.geo_predio (
 comuna integer NOT NULL, manzana integer NOT NULL, predio integer NOT NULL,
 predio_source_file_id bigint NOT NULL REFERENCES sii.source_file(id),
 lat double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
 lon double precision NOT NULL CHECK (lon BETWEEN -180 AND 180),
 metodo text NOT NULL CHECK (metodo IN ('osm_exacto','interpolado','errata_corregida')),
 precision_m double precision NOT NULL CHECK (precision_m > 0),
 osm_source_file_id bigint NOT NULL REFERENCES sii.source_file(id),
 evidencia jsonb NOT NULL,
 PRIMARY KEY(comuna,manzana,predio)
);
CREATE TABLE sii.job_run (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 job text NOT NULL, started_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz, successful boolean, counters jsonb NOT NULL DEFAULT '{}', error text
);
CREATE INDEX job_run_latest_idx ON sii.job_run(job,started_at DESC);
