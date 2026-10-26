"""Phase-2a prerequisite audit. Explicitly enabled, bounded production reads only.

Run via stdin in the existing API container with python -B. This file never
imports application settings/ORM, starts scrapers, or issues SQL mutations.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import unicodedata
from collections import Counter
from datetime import UTC

COMMUNES = {
    "vitacura": 15160,
    "las_condes": 15108,
    "nunoa": 15105,
    "providencia": 15103,
    "la_florida": 15128,
    "santiago": 13101,
    "san_miguel": 16106,
    "estacion_central": 14157,
}
FIELD_KEYS = (
    "version",
    "source",
    "external_id",
    "stage",
    "observed_at",
    "street",
    "address_number",
    "address_type",
    "address_raw",
    "address_description_raw",
    "apartment_number",
    "latitude",
    "longitude",
    "coordinates_origin",
    "coordinates_precision",
    "coordinates_precision_raw",
    "useful_area_m2",
    "provenance",
    "source_is_project",
)
# Select a projection of facts, not complete descriptions, contacts or originals.
SQL = """SELECT id,source,external_id,url,comuna,property_type,status,lat,lon,geocode_precision,
 usable_area_m2,last_seen_at,scraped_at,
 (SELECT jsonb_object_agg(key,value) FROM jsonb_each(CASE WHEN jsonb_typeof(raw_metadata::jsonb->'published_fields')='object' THEN raw_metadata::jsonb->'published_fields' ELSE '{}'::jsonb END) WHERE key=ANY(%s)) AS published_fields,
 (SELECT jsonb_object_agg(key,value) FROM jsonb_each(CASE WHEN jsonb_typeof(raw_metadata::jsonb->'published_detail_fields')='object' THEN raw_metadata::jsonb->'published_detail_fields' ELSE '{}'::jsonb END) WHERE key=ANY(%s)) AS published_detail_fields
 FROM listings WHERE status='active' AND property_type IN ('apartment','departamento','depto')
"""


def normalized(value):
    value = "".join(
        c
        for c in unicodedata.normalize("NFKD", str(value or "").lower())
        if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def source_name(value):
    return "portal" if value in ("portal", "portalinmobiliario") else str(value or "")


def positive(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def bound(fields, row):
    def digits(value):
        return re.sub(r"\D", "", str(value or ""))

    return (
        isinstance(fields, dict)
        and fields.get("version") == 1
        and bool(digits(row.get("external_id")))
        and digits(fields.get("external_id")) == digits(row.get("external_id"))
        and source_name(fields.get("source")) == source_name(row.get("source"))
    )


def exact_address(fields):
    street = str(fields.get("street") or "").strip()
    number = str(fields.get("address_number") or "").strip()
    placeholders = {
        "dp",
        "dpto",
        "depto",
        "departamento",
        "dep",
        "n",
        "no",
        "nro",
        "numero",
        "calle",
        "av",
        "avenida",
        "pasaje",
        "camino",
    }
    tokens = set(normalized(street).split("_")) - {""}
    if not tokens or tokens.issubset(placeholders) or not re.search(r"[a-z]", normalized(street)):
        return False, "calle_ausente_o_unidad"
    if fields.get("address_type") != "exact" or not re.fullmatch(r"[1-9]\d*[A-Za-z]?", number):
        return False, "direccion_sin_numero_civico_exacto"
    if not (fields.get("provenance") or {}).get("address"):
        return False, "direccion_sin_procedencia"
    raw = str(fields.get("address_raw") or "")
    unit = r"\b(?:dp|dpto|depto|dpto|dep|departamento)\.?\s*(?:n(?:[°ºo.]|ro\.?)?\s*|[#°º]\s*)?(\d+[a-zA-Z]?)\b"
    units = re.findall(unit, raw, re.I)
    if number.casefold() in {u.casefold() for u in units}:
        remainder = re.sub(unit, "", raw, flags=re.I)
        if not re.search(r"(?<!\d)" + re.escape(number) + r"(?!\d)", remainder, re.I):
            return False, "numero_departamento_usado_como_calle"
    return True, None


def coordinate_pair(lat, lon):
    try:
        return (
            math.isfinite(float(lat))
            and math.isfinite(float(lon))
            and -56 <= float(lat) <= -17
            and -76 <= float(lon) <= -66
        )
    except (TypeError, ValueError):
        return False


def published_coordinates(fields):
    if not coordinate_pair(fields.get("latitude"), fields.get("longitude")):
        return False
    origin = str(fields.get("coordinates_origin") or "").lower()
    precision = str(fields.get("coordinates_precision") or "unknown").lower()
    raw = fields.get("coordinates_precision_raw") or {}
    raw = raw if isinstance(raw, dict) else {}
    return (
        origin.startswith(("portal:", "portal.", "yapo:", "yapo."))
        and not any(
            word in origin + " " + precision
            for word in ("centroid", "centroide", "geocod", "imput", "office", "oficina")
        )
        and precision not in ("comuna", "city", "municipality")
        and not raw.get("is_centroid")
        and not raw.get("isCentroid")
    )


def facts(row):
    snapshots = [
        f
        for f in (row.get("published_fields"), row.get("published_detail_fields"))
        if bound(f, row)
    ]
    addresses = [exact_address(f) for f in snapshots]
    address = any(x[0] for x in addresses)
    coords = [f for f in snapshots if published_coordinates(f)]
    useful = any(
        positive(f.get("useful_area_m2"))
        and (f.get("provenance") or {}).get("useful_area_m2")
        and not any(
            w in str(f["provenance"]["useful_area_m2"]).lower()
            for w in ("generic", "fallback", "imput")
        )
        for f in snapshots
    )
    canonical_coords = coordinate_pair(row.get("lat"), row.get("lon"))
    reasons = []
    if not snapshots:
        reasons.append("sin_snapshot_PR5_vinculado")
    if not address:
        reasons.append(
            next(
                (x[1] for x in addresses if x[1] == "numero_departamento_usado_como_calle"),
                addresses[0][1] if addresses else "sin_direccion_publicada",
            )
        )
    if not coords:
        reasons.append("sin_coordenadas_publicadas_verificables")
    if not useful:
        reasons.append("sin_m2_util_explicito")
    return {
        "direccion": address,
        "coordenadas_publicadas": bool(coords),
        "m2_util_explicito": bool(useful),
        "direccion_o_coordenadas": address or bool(coords),
        "localizado_y_m2_util": bool((address or coords) and useful),
        "los_tres_campos": bool(address and coords and useful),
        "snapshot_PR5": bool(snapshots),
        "detalle_PR5": any(f.get("stage") == "detail" for f in snapshots),
        "coordenadas_canonicas": canonical_coords,
        "direccion_o_coordenadas_canonicas": address or canonical_coords,
        "coordenadas_precision_desconocida": any(
            str(f.get("coordinates_precision") or "unknown").lower() == "unknown" for f in coords
        ),
        "proyecto_publicado": any(f.get("source_is_project") is True for f in snapshots),
        "motivos": reasons,
        "direccion_raw": next(
            (f.get("address_raw") for f in snapshots if f.get("address_raw")), None
        ),
        "calle": next((f.get("street") for f in snapshots if f.get("street")), None),
        "numero": next(
            (f.get("address_number") for f in snapshots if f.get("address_number")), None
        ),
    }


def summarize(rows):
    keys = (
        "direccion",
        "coordenadas_publicadas",
        "m2_util_explicito",
        "direccion_o_coordenadas",
        "localizado_y_m2_util",
        "los_tres_campos",
        "snapshot_PR5",
        "detalle_PR5",
        "coordenadas_canonicas",
        "direccion_o_coordenadas_canonicas",
        "coordenadas_precision_desconocida",
        "proyecto_publicado",
    )
    counts = {key: sum(bool(r["facts"][key]) for r in rows) for key in keys}
    n = len(rows)
    return {
        "activos": n,
        "conteos": counts,
        "porcentajes": {k: round(100 * v / n, 4) if n else None for k, v in counts.items()},
        "bajo_40": bool(n and counts["direccion_o_coordenadas"] * 100 < 40 * n),
        "motivos_falta": dict(Counter(reason for r in rows for reason in r["facts"]["motivos"])),
    }


def analyze(rows, as_of):
    cohort = []
    for row in rows:
        comuna = normalized(row["comuna"])
        comuna = "santiago" if comuna == "santiago_centro" else comuna
        if comuna not in COMMUNES:
            continue
        row = {**row, "comuna": comuna, "portal": source_name(row["source"])}
        row["facts"] = facts(row)
        cohort.append(row)
    portals = sorted({"portal", "yapo"} | {r["portal"] for r in cohort})
    commune_rows = [
        {
            "comuna": name,
            "comuna_sii": code,
            **summarize([r for r in cohort if r["comuna"] == name]),
        }
        for name, code in COMMUNES.items()
    ]
    below = [r["comuna"] for r in commune_rows if r["bajo_40"]]
    examples = {
        name: [
            {
                k: r.get(k)
                for k in (
                    "id",
                    "source",
                    "external_id",
                    "url",
                    "comuna",
                    "last_seen_at",
                    "geocode_precision",
                )
            }
            | r["facts"]
            for r in sorted(cohort, key=lambda r: (r["portal"], r["id"]))
            if r["comuna"] == name and not r["facts"]["direccion_o_coordenadas"]
        ][:5]
        for name in COMMUNES
    }
    return {
        "as_of_utc": as_of,
        "transaction_read_only": True,
        "gate": {
            "threshold_pct": 40,
            "majority_required": 5,
            "communes_below_40": below,
            "stop": len(below) >= 5,
            "definition": "direccion exacta OR coordenadas publicadas vinculadas al mismo aviso; campos PR5",
        },
        "total": summarize(cohort),
        "por_comuna": commune_rows,
        "por_portal": [
            {"portal": p, **summarize([r for r in cohort if r["portal"] == p])} for p in portals
        ],
        "por_comuna_y_portal": [
            {
                "comuna": name,
                "comuna_sii": code,
                "portal": p,
                **summarize([r for r in cohort if r["comuna"] == name and r["portal"] == p]),
            }
            for name, code in COMMUNES.items()
            for p in portals
        ],
        "cinco_ejemplos_sin_ubicacion": examples,
    }


def main():
    if os.environ.get("SII_LINKAGE_ENABLED", "false").lower() != "true":
        print(json.dumps({"enabled": False, "status": "disabled"}))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-readonly", action="store_true", required=True)
    parser.parse_args()
    import psycopg
    from psycopg.rows import dict_row

    dsn = re.sub(
        r"^postgres(?:ql)?\+(?:asyncpg|psycopg)://", "postgresql://", os.environ["DATABASE_URL"]
    )
    with psycopg.connect(
        dsn,
        row_factory=dict_row,
        connect_timeout=10,
        options="-c default_transaction_read_only=on -c statement_timeout=20000 -c lock_timeout=1000 -c timezone=UTC",
        application_name="sii_phase2a_step0_readonly",
    ) as c:
        c.read_only = True
        c.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with c.cursor() as cur:
            cur.execute(
                "SELECT current_setting('transaction_read_only') AS ro,transaction_timestamp() AS as_of"
            )
            control = cur.fetchone()
            assert control["ro"] == "on"
            cur.execute(SQL, (list(FIELD_KEYS), list(FIELD_KEYS)))
            rows = cur.fetchall()
        result = analyze(rows, control["as_of"].astimezone(UTC).isoformat())
        c.rollback()
    print(json.dumps(result, default=str, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
