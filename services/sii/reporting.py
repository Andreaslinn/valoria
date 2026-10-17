"""Local job health and reproducible benchmark; no valuation endpoints."""

from __future__ import annotations

from psycopg.rows import dict_row

from services.sii.jobs import JOB_NAMES, connect
from services.sii.parsing import COMUNAS, EXPECTED_MEDIANS
from services.sii.settings import Settings, enabled

STATS_SQL = """
SELECT comuna,count(*) AS observaciones,
 count(*) FILTER (WHERE NOT ('duplicado_rol_fecha'=ANY(motivos_exclusion))) AS deduplicadas,
 100.0*count(*) FILTER (WHERE predio_source_file_id IS NOT NULL
 AND NOT ('duplicado_rol_fecha'=ANY(motivos_exclusion)))/nullif(count(*) FILTER
 (WHERE NOT ('duplicado_rol_fecha'=ANY(motivos_exclusion))),0) AS join_pct,
 count(*) FILTER (WHERE cierre_comparable AND tipo='depto') AS deptos,
 count(*) FILTER (WHERE cierre_comparable AND tipo='casa') AS casas,
 percentile_cont(.5) WITHIN GROUP (ORDER BY uf_m2_h) FILTER
 (WHERE cierre_comparable AND tipo='depto') AS mediana_depto_uf_m2_h,
 percentile_cont(.5) WITHIN GROUP (ORDER BY uf_m2_cerrado) FILTER
 (WHERE cierre_comparable AND tipo='depto') AS mediana_depto_uf_m2_cerrado,
 percentile_cont(.5) WITHIN GROUP (ORDER BY uf_m2_cerrado) FILTER
 (WHERE cierre_comparable AND tipo='casa') AS mediana_casa_uf_m2_cerrado
FROM sii.transferencia WHERE fi >= DATE '2024-01-01' GROUP BY comuna ORDER BY comuna
"""


def health():
    if not enabled():
        return {"enabled": False}
    settings = Settings.load()
    with connect(settings) as conn:
        conn.row_factory = dict_row
        # A bounded read-only snapshot cannot race a rebuild into inconsistent counts.
        with conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            conn.execute("SET LOCAL statement_timeout='30s'")
            runs = conn.execute(
                "SELECT DISTINCT ON(job) job,started_at,finished_at,successful,counters,error FROM sii.job_run ORDER BY job,started_at DESC,id DESC"
            ).fetchall()
            jobs = {name: next((r for r in runs if r["job"] == name), None) for name in JOB_NAMES}
            version = conn.execute(
                "SELECT nombre,fecha,hash,filas,filas_seleccionadas,cargado_en FROM sii.source_file WHERE tipo='F2890' ORDER BY fecha DESC,cargado_en DESC,id DESC LIMIT 1"
            ).fetchone()
            catastro = conn.execute("""SELECT DISTINCT ON(s.comuna) s.comuna,s.semestre,s.hash,s.filas,
                s.nombre,l.nombre AS lineas_nombre,l.hash AS lineas_hash,s.id AS role_source
                FROM sii.source_file s JOIN LATERAL (SELECT nombre,hash FROM sii.source_file n
                 WHERE n.tipo='NL' AND n.comuna=s.comuna AND n.semestre=s.semestre
                 ORDER BY n.cargado_en DESC,n.id DESC LIMIT 1) l ON true WHERE s.tipo='N'
                ORDER BY s.comuna,s.semestre DESC,s.cargado_en DESC,s.id DESC""").fetchall()
            stats = conn.execute(STATS_SQL).fetchall()
            total_santiago_sql = STATS_SQL.replace("SELECT comuna,", "SELECT comuna_ine,").replace(
                "GROUP BY comuna ORDER BY comuna",
                "AND comuna_ine=13101 GROUP BY comuna_ine ORDER BY comuna_ine",
            )
            santiago = conn.execute(total_santiago_sql).fetchone()
            counts = {
                table: conn.execute(f"SELECT count(*) AS n FROM sii.{table}").fetchone()["n"]
                for table in (
                    "source_file",
                    "predio",
                    "linea_construccion",
                    "transferencia_raw",
                    "transferencia",
                    "geo_predio",
                )
            }
            disk = int(
                conn.execute("""SELECT coalesce(sum(pg_total_relation_size(c.oid)),0) AS bytes
                FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid
                WHERE n.nspname='sii' AND c.relkind='r'""").fetchone()["bytes"]
            )
            active_sources = [r["role_source"] for r in catastro]
            geo = conn.execute(
                """SELECT p.comuna,count(*) AS predios,
                count(g.comuna) AS geocodificados,
                count(*) FILTER (WHERE g.metodo='osm_exacto') AS osm_exacto,
                count(*) FILTER (WHERE g.metodo='interpolado') AS interpolado,
                count(*) FILTER (WHERE g.metodo='errata_corregida') AS errata_corregida
                FROM sii.predio p LEFT JOIN sii.geo_predio g
                ON (p.comuna,p.manzana,p.predio,p.source_file_id)=
                (g.comuna,g.manzana,g.predio,g.predio_source_file_id)
                WHERE p.source_file_id=ANY(%s) GROUP BY p.comuna""",
                (active_sources,),
            ).fetchall()
            exclusions = conn.execute("""SELECT comuna,motivo,count(*) AS n,
                (array_agg(rol ORDER BY raw_id))[1:5] AS ejemplos
                FROM sii.transferencia CROSS JOIN LATERAL unnest(motivos_exclusion) motivo
                WHERE fi>=DATE '2024-01-01' GROUP BY comuna,motivo ORDER BY comuna,motivo""").fetchall()
    raw_bytes = sum(p.stat().st_size for p in settings.data.rglob("*") if p.is_file())
    for row in stats:
        row["nombre_tabla_oficial"] = COMUNAS.get(
            row["comuna"], {13134: "SANTIAGO OESTE", 13135: "SANTIAGO SUR"}.get(row["comuna"])
        )
        expected = EXPECTED_MEDIANS.get(row["comuna"])
        obtained = row["mediana_depto_uf_m2_h"]
        if expected:
            row["mediana_esperada"] = expected
            row["desviacion_pct"] = (obtained / expected - 1) * 100 if obtained else None
            row["mediana_cumple"] = obtained is not None and abs(obtained / expected - 1) <= 0.02
        georow = next((g for g in geo if g["comuna"] == row["comuna"]), {})
        row["geo"] = georow
        for method in ("osm_exacto", "interpolado", "errata_corregida"):
            georow[method + "_pct"] = (
                100 * georow.get(method, 0) / georow["predios"] if georow.get("predios") else 0
            )
    benchmark_total = sum(r["deptos"] for r in stats if r["comuna"] in EXPECTED_MEDIANS)
    return {
        "enabled": True,
        "status": "ok" if all(r and r["successful"] for r in jobs.values()) else "degraded",
        "jobs": jobs,
        "f2890": version,
        "catastro": catastro,
        "counts": counts,
        "benchmark": {
            "desde_fi": "2024-01-01",
            "santiago_sii": 13101,
            "deptos_8_comunas": benchmark_total,
            "esperado": 55156,
            "conteo_cumple": abs(benchmark_total / 55156 - 1) <= 0.01,
            "medianas_cumplen": len([r for r in stats if r.get("mediana_cumple")]) == 8,
            "join_cumple": set(COMUNAS).issubset({r["comuna"] for r in stats})
            and all((r["join_pct"] or 0) >= 93 for r in stats if r["comuna"] in COMUNAS),
        },
        "por_comuna": stats,
        "santiago_completo_por_comuna_ine": santiago,
        "exclusiones": exclusions,
        "disk": {
            "raw_and_auxiliary_bytes": raw_bytes,
            "table_and_index_bytes": disk,
            "total_bytes": raw_bytes + disk,
            "over_10_gb": raw_bytes + disk > 10_000_000_000,
        },
        "price_label": "precio de transacción declarado",
    }
