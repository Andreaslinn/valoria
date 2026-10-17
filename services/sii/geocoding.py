"""Offline OSM extract adapter. Never calls public Nominatim or SII maps.

Optional data/sii/osm/addresses.csv: comuna,calle,numero,lat,lon,osm_id.
The commune must be the original SII sector code, assigned by a local spatial join.
© OpenStreetMap contributors, ODbL: https://www.openstreetmap.org/copyright
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from difflib import SequenceMatcher

from psycopg.types.json import Jsonb

from services.sii.jobs import file_hash, source
from services.sii.parsing import RAW_CODES, normalize


def distance(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    return (
        6371000
        * 2
        * math.asin(
            min(
                1,
                math.sqrt(
                    math.sin((lat2 - lat1) / 2) ** 2
                    + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
                ),
            )
        )
    )


def interpolate(number, anchors):
    candidates = [(n, point) for n, point in anchors.items() if n % 2 == number % 2]
    lower = [(n, p) for n, p in candidates if n < number]
    upper = [(n, p) for n, p in candidates if n > number]
    if not lower or not upper:
        return None
    lo, a = max(lower)
    hi, b = min(upper)
    meters = distance(a, b)
    if hi - lo > 200 or meters > 300:
        return None
    t = (number - lo) / (hi - lo)
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), max(30, meters / 2), lo, hi)


def geocode(conn, settings):
    path = settings.data / "osm" / "addresses.csv"
    # Drop stale derived locations when a catastro version changes, even without OSM.
    conn.execute("""DELETE FROM sii.geo_predio g WHERE NOT EXISTS
        (SELECT 1 FROM current_predio p WHERE (p.comuna,p.manzana,p.predio,p.source_file_id)=
         (g.comuna,g.manzana,g.predio,g.predio_source_file_id))""")
    if not path.exists():
        return {
            "status": "pending_local_osm_extract",
            "rows_new": 0,
            "public_nominatim_requests": 0,
        }
    digest = file_hash(path)
    saved = source(conn, path, "OSM", digest)
    source_id = (
        saved[0]
        if saved
        else conn.execute(
            "SELECT id FROM sii.source_file WHERE tipo='OSM' AND nombre=%s AND hash=%s",
            (path.name, digest),
        ).fetchone()[0]
    )
    points = defaultdict(set)
    evidence = defaultdict(list)
    count = 0
    with path.open(encoding="utf8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["comuna", "calle", "numero", "lat", "lon", "osm_id"]:
            raise ValueError("osm_extract_header_mismatch")
        for row in reader:
            count += 1
            code, number = int(row["comuna"]), int(row["numero"])
            point = float(row["lat"]), float(row["lon"])
            if code not in RAW_CODES or not (-56 <= point[0] <= -17 and -76 <= point[1] <= -66):
                raise ValueError("osm_extract_invalid_code_or_chile_coordinate")
            key = code, normalize(row["calle"]), number
            points[key].add(point)
            evidence[key].append(row["osm_id"])
    # Ambiguous same-number locations are left unresolved, never averaged.
    exact = {key: next(iter(values)) for key, values in points.items() if len(values) == 1}
    by_number = defaultdict(list)
    for key in exact:
        by_number[key[0], key[2]].append(key)
    rows = conn.execute("""SELECT comuna,manzana,predio,source_file_id,calle,numero
        FROM current_predio WHERE numero ~ '^[0-9]+$'""").fetchall()
    anchors = defaultdict(dict)
    for code, block, _, _, street, number in rows:
        point = exact.get((code, street, int(number)))
        if point:
            anchors[code, block, street][int(number)] = point
    matched = []
    for code, block, parcel, role_source, street, number in rows:
        number = int(number)
        key = code, street, number
        point = exact.get(key)
        method, precision, detail = "osm_exacto", 15, {}
        if point:
            detail = {"osm_ids": evidence[key]}
        else:
            result = interpolate(number, anchors[code, block, street])
            if result:
                point, precision = result[:2], result[2]
                method = "interpolado"
                detail = {"numeros_ancla": result[3:], "misma_manzana": block}
            else:
                candidates = sorted(
                    [
                        (SequenceMatcher(None, street, k[1]).ratio(), k)
                        for k in by_number[code, number]
                    ],
                    reverse=True,
                )
                if (
                    candidates
                    and candidates[0][0] >= 0.8
                    and (len(candidates) == 1 or candidates[0][0] > candidates[1][0])
                ):
                    score, target = candidates[0]
                    point = exact[target]
                    method, precision = "errata_corregida", 30
                    detail = {
                        "calle_osm": target[1],
                        "similitud": score,
                        "osm_ids": evidence[target],
                    }
        if point:
            matched.append(
                (
                    code,
                    block,
                    parcel,
                    role_source,
                    *point,
                    method,
                    precision,
                    source_id,
                    Jsonb(detail),
                )
            )
    conn.execute(
        "CREATE TEMP TABLE geo_next (LIKE sii.geo_predio INCLUDING DEFAULTS) ON COMMIT DROP"
    )
    with conn.cursor().copy("COPY geo_next FROM STDIN") as copy:
        for row in matched:
            copy.write_row(row)
    new = conn.execute("""SELECT count(*) FROM geo_next n WHERE NOT EXISTS
        (SELECT 1 FROM sii.geo_predio g WHERE (g.comuna,g.manzana,g.predio)=(n.comuna,n.manzana,n.predio))""").fetchone()[
        0
    ]
    # Exact replacement makes removed or newly ambiguous OSM addresses disappear.
    conn.execute("""DELETE FROM sii.geo_predio g WHERE NOT EXISTS (SELECT 1 FROM geo_next n
        WHERE (g.comuna,g.manzana,g.predio)=(n.comuna,n.manzana,n.predio))""")
    conn.execute("""INSERT INTO sii.geo_predio SELECT * FROM geo_next ON CONFLICT(comuna,manzana,predio)
        DO UPDATE SET predio_source_file_id=EXCLUDED.predio_source_file_id,lat=EXCLUDED.lat,lon=EXCLUDED.lon,
        metodo=EXCLUDED.metodo,precision_m=EXCLUDED.precision_m,osm_source_file_id=EXCLUDED.osm_source_file_id,
        evidencia=EXCLUDED.evidencia WHERE (geo_predio.predio_source_file_id,geo_predio.lat,geo_predio.lon,
        geo_predio.metodo,geo_predio.precision_m,geo_predio.osm_source_file_id,geo_predio.evidencia)
        IS DISTINCT FROM (EXCLUDED.predio_source_file_id,EXCLUDED.lat,EXCLUDED.lon,EXCLUDED.metodo,
        EXCLUDED.precision_m,EXCLUDED.osm_source_file_id,EXCLUDED.evidencia)""")
    conn.execute(
        "UPDATE sii.source_file SET filas=%s,filas_seleccionadas=%s WHERE id=%s",
        (count, count, source_id),
    )
    return {
        "status": "ok",
        "rows_new": new,
        "geocoded": len(matched),
        "sha256": digest,
        "public_nominatim_requests": 0,
    }
