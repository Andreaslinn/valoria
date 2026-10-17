"""Opt-in tests on a disposable local Docker instance, NEVER the loaded database.

SII_TEST_POSTGRES=true SII_DATABASE_URL=...127.0.0.1:55433/valoria_sii_local pytest ...
"""

import csv
import os
import zipfile
from datetime import date
from decimal import Decimal

import psycopg
import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command
from services.sii.jobs import catastro_import, connect, f2890_fetch, rebuild
from services.sii.settings import ROOT, Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("SII_TEST_POSTGRES") != "true",
    reason="requires disposable Docker Postgres on 55433",
)


@pytest.fixture
def pg(monkeypatch, tmp_path):
    monkeypatch.setenv("SII_INGEST_ENABLED", "true")
    monkeypatch.setenv("SII_DATA_DIR", str(tmp_path / "data"))
    settings = Settings.load()
    assert make_url(settings.url).port == 55433, (
        "Destructive tests only allowed on dedicated disposable port 55433"
    )
    config = Config(str(ROOT / "sii_migrations.ini"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    with connect(settings) as conn:
        # Synthetic fixture, using the existing persistent calendar's table contract.
        conn.execute("""CREATE TABLE IF NOT EXISTS public.ingestion_uf_calendar
            (date date PRIMARY KEY,value numeric NOT NULL,source text NOT NULL,fetched_at timestamptz NOT NULL)""")
        conn.execute("DELETE FROM public.ingestion_uf_calendar")
        conn.execute(
            "INSERT INTO public.ingestion_uf_calendar VALUES('2026-01-01',40000,'fixture',now()),('2026-01-02',50000,'fixture',now())"
        )
        yield conn, settings, config


def seed(conn):
    ids = []
    for kind in ("N", "NL", "F2890"):
        ids.append(
            conn.execute(
                """INSERT INTO sii.source_file(tipo,nombre,hash,ruta,comuna,semestre,fecha)
            VALUES (%s,%s,%s,'fixture',15108,'2026-2','2026-10-01') RETURNING id""",
                (kind, kind, "0" * 64),
            ).fetchone()[0]
        )
    return ids


def parcel(conn, ids, block, number, kind="depto", surface=100, opened=10):
    destino = {"depto": "H", "casa": "H", "estac": "Z", "bodega": "L"}[kind]
    raw_address = (
        "CALLE 100" + {"depto": " DP 1", "casa": "", "estac": " BOX 1", "bodega": " BOD 1"}[kind]
    )
    conn.execute(
        """INSERT INTO sii.predio(source_file_id,comuna,manzana,predio,direccion_raw,calle,numero,
        destino,tipo,m2_terreno,avaluo,contribucion,semestre,raw_line)
        VALUES(%s,15108,%s,%s,%s,'CALLE','100',%s,%s,100,100000,10,'2026-2','fixture')""",
        (ids[0], block, number, raw_address, destino, kind),
    )
    for line, area, is_open in ((1, surface - opened, False), (2, opened, True)):
        conn.execute(
            """INSERT INTO sii.linea_construccion(source_file_id,comuna,manzana,predio,n_linea,
            destino,material,calidad,anio,m2,abierta,condicion,pisos,raw_line)
            VALUES(%s,15108,%s,%s,%s,'H','B','2',2020,%s,%s,%s,1,'fixture')""",
            (ids[1], block, number, line, area, is_open, "CA" if is_open else ""),
        )


def transfer(conn, ids, block, number, uf=5000, clp=None, fe="2026-01-01", fi="2026-01-02"):
    fila = conn.execute("SELECT count(*)+2 FROM sii.transferencia_raw").fetchone()[0]
    return conn.execute(
        """INSERT INTO sii.transferencia_raw(source_file_id,fila,comuna,manzana,predio,
        fi,fe,clp,uf,raw_line,campos) VALUES(%s,%s,15108,%s,%s,%s,%s,%s,%s,'fixture','{}') RETURNING id""",
        (ids[2], fila, block, number, fi, fe, clp, uf),
    ).fetchone()[0]


def test_conversion_closed_surface_and_missing_exact_day(pg):
    conn, _, _ = pg
    ids = seed(conn)
    for number in range(1, 5):
        parcel(conn, ids, number, number)
    a = transfer(conn, ids, 1, 1, uf=None, clp=200000000)
    b = transfer(conn, ids, 2, 2, uf=None, clp=200000000, fe=None)
    c = transfer(conn, ids, 3, 3, uf=6000, clp=200000000)
    d = transfer(conn, ids, 4, 4, uf=None, clp=200000000, fe="2025-12-31")
    assert rebuild()["rows_new"] == 4
    row = conn.execute(
        "SELECT monto_uf,uf_usada,uf_fecha,m2_h,m2_cerrado,uf_m2_h,uf_m2_cerrado FROM sii.transferencia WHERE raw_id=%s",
        (a,),
    ).fetchone()
    assert row[:6] == (
        Decimal(5000),
        Decimal(40000),
        date(2026, 1, 1),
        Decimal(100),
        Decimal(90),
        Decimal(50),
    )
    assert float(row[6]) == pytest.approx(5000 / 90)
    assert conn.execute(
        "SELECT monto_uf,uf_fecha FROM sii.transferencia WHERE raw_id=%s", (b,)
    ).fetchone() == (Decimal(4000), date(2026, 1, 2))
    assert conn.execute(
        "SELECT monto_uf,uf_usada FROM sii.transferencia WHERE raw_id=%s", (c,)
    ).fetchone() == (Decimal(6000), None)
    assert conn.execute(
        "SELECT cierre_comparable,motivos_exclusion FROM sii.transferencia WHERE raw_id=%s", (d,)
    ).fetchone() == (False, ["sin_uf_fecha_exacta"])
    from services.sii.reporting import health

    report = health()
    assert report["counts"]["transferencia"] == 4
    assert report["por_comuna"][0]["deptos"] == 3
    assert report["por_comuna"][0]["mediana_depto_uf_m2_h"] == 50
    assert report["catastro"][0]["semestre"] == "2026-2"
    assert rebuild()["rows_new"] == 0


def test_duplicate_ranking_happens_before_operation_filters(pg):
    conn, _, _ = pg
    ids = seed(conn)
    parcel(conn, ids, 1, 1)
    small = transfer(conn, ids, 1, 1, uf=4000)
    large = transfer(conn, ids, 1, 1, uf=5000)
    rebuild()
    assert conn.execute(
        "SELECT cierre_comparable,motivos_exclusion FROM sii.transferencia WHERE raw_id=%s",
        (small,),
    ).fetchone() == (False, ["duplicado_rol_fecha"])
    assert conn.execute(
        "SELECT cierre_comparable FROM sii.transferencia WHERE raw_id=%s", (large,)
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("DELETE FROM sii.transferencia_raw")
    assert conn.execute("SELECT count(*) FROM sii.transferencia_raw").fetchone()[0] == 2


def test_repeated_packages_apartment_lots_and_house_block_scope(pg):
    conn, _, _ = pg
    ids = seed(conn)
    for n in (1, 2):
        parcel(conn, ids, 10, n)
        transfer(conn, ids, 10, n, uf=5000)
    parcel(conn, ids, 20, 1)
    parcel(conn, ids, 20, 2, kind="estac")
    transfer(conn, ids, 20, 1, uf=6000)
    transfer(conn, ids, 20, 2, uf=0)
    for n in range(1, 11):
        parcel(conn, ids, 30, n)
        transfer(conn, ids, 30, n, uf=5000 + n)
    for n in range(1, 4):
        parcel(conn, ids, 40, n, kind="casa")
        transfer(conn, ids, 40, n, uf=6000 + n)
    for block in (41, 42, 43):
        parcel(conn, ids, block, 1, kind="casa")
        transfer(conn, ids, block, 1, uf=6100 + block)
    rebuild()

    def reasons(block):
        return conn.execute(
            "SELECT motivos_exclusion FROM sii.transferencia WHERE manzana=%s ORDER BY predio",
            (block,),
        ).fetchall()

    assert all("monto_repetido_en_grupo" in r[0] for r in reasons(10))
    assert "paquete_estac_bodega_sin_monto" in reasons(20)[0][0]
    assert all("lote_10_deptos" in r[0] for r in reasons(30))
    assert all("bloque_3_casas_misma_manzana" in r[0] for r in reasons(40))
    assert all(reasons(b) == [([],)] for b in (41, 42, 43))


def test_import_hash_replay_and_raw_date_errors(pg, tmp_path):
    conn, settings, _ = pg
    inbox = settings.data / "inbox"
    inbox.mkdir(parents=True)
    role = "15108|10|1|CALLE 100 DP 1|100000|10|H|0|0|0|0|0|0|0|100|U|0|0|0|\r\n"
    line = "15108|10|1|1|B|2|2020|100|H||1|\r\n"
    (inbox / "BRTMPCATASN_2026_2_15108").write_bytes(role.encode("latin1"))
    (inbox / "BRTMPCATASNL_2026_2_15108").write_bytes(line.encode("latin1"))
    assert catastro_import()["rows_new"] == 2
    (inbox / "BRTMPCATASN_2026_2_15108").write_bytes(role.encode("latin1"))
    assert catastro_import()["rows_new"] == 0
    archive = tmp_path / "F2890_01-10-2026.zip"
    content = "COMUNA;MANZANA;PREDIO;FI;FE;CLP;UF\r\nLAS CONDES;10;1;20260102;20260101;;5000\r\nLAS CONDES;10;1;20260102;21210;;6000\r\nLAS CONDES;;2;20260102;20260101;;NaN\r\n"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("F2890_01-10-2026.txt", content.encode("latin1"))
    assert f2890_fetch(archive)["rows_new"] == 3
    assert f2890_fetch(archive)["rows_new"] == 0
    rebuild()
    rows = conn.execute(
        "SELECT raw_line,errores_parseo FROM sii.transferencia_raw ORDER BY fila"
    ).fetchall()
    assert rows[1] == ("LAS CONDES;10;1;20260102;21210;;6000\r\n", ["fe_invalida"])
    assert conn.execute(
        "SELECT manzana,errores_parseo FROM sii.transferencia_raw WHERE predio=2"
    ).fetchone() == (None, ["manzana_invalido", "uf_invalido"])
    assert conn.execute(
        "SELECT motivos_exclusion FROM sii.transferencia WHERE fe IS NULL"
    ).fetchone()[0] == ["fe_invalida"]


def test_geocoding_all_methods_and_no_network(pg):
    conn, settings, _ = pg
    ids = seed(conn)
    for n, street, number in (
        (1, "CALLE", 100),
        (2, "CALLE", 200),
        (3, "CALLE", 150),
        (4, "CALLLE", 100),
    ):
        parcel(conn, ids, 10, n)
        conn.execute(
            "UPDATE sii.predio SET calle=%s,numero=%s WHERE predio=%s", (street, str(number), n)
        )
    path = settings.data / "osm" / "addresses.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", newline="", encoding="utf8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["comuna", "calle", "numero", "lat", "lon", "osm_id"])
        writer.writerow([15108, "CALLE", 100, -33.4, -70.6, "node/1"])
        writer.writerow([15108, "CALLE", 200, -33.4005, -70.6, "node/2"])
    result = rebuild()
    assert result["geo"]["public_nominatim_requests"] == 0
    assert conn.execute("SELECT metodo FROM sii.geo_predio ORDER BY predio").fetchall() == [
        ("osm_exacto",),
        ("osm_exacto",),
        ("interpolado",),
        ("errata_corregida",),
    ]
    assert rebuild()["geo"]["rows_new"] == 0


def test_downgrade_drops_only_sii_and_preserves_calendar(pg):
    conn, _, config = pg
    ids = seed(conn)
    parcel(conn, ids, 1, 1)
    transfer(conn, ids, 1, 1)
    before = conn.execute("SELECT * FROM public.ingestion_uf_calendar ORDER BY date").fetchall()
    command.downgrade(config, "base")
    assert conn.execute("SELECT to_regnamespace('sii')").fetchone()[0] is None
    assert (
        conn.execute("SELECT * FROM public.ingestion_uf_calendar ORDER BY date").fetchall()
        == before
    )
    command.upgrade(config, "head")
    assert conn.execute("SELECT count(*) FROM sii.transferencia_raw").fetchone()[0] == 0


def test_complete_versions_replace_stale_aggregates_atomically(pg):
    conn, _, _ = pg
    ids = seed(conn)
    parcel(conn, ids, 1, 1)
    transfer(conn, ids, 1, 1)
    rebuild()
    # A newer role file without matching construction semester is not activated.
    new_role = conn.execute(
        """INSERT INTO sii.source_file(tipo,nombre,hash,ruta,comuna,semestre)
        VALUES('N','new-roles',%s,'fixture',15108,'2027-1') RETURNING id""",
        ("1" * 64,),
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO sii.predio(source_file_id,comuna,manzana,predio,direccion_raw,calle,numero,
        destino,tipo,m2_terreno,avaluo,contribucion,semestre,raw_line)
        VALUES(%s,15108,1,1,'CALLE 100 DP 1','CALLE','100','H','depto',100,1000,10,'2027-1','fixture')""",
        (new_role,),
    )
    rebuild()
    assert conn.execute("SELECT predio_source_file_id,m2_h FROM sii.transferencia").fetchone() == (
        ids[0],
        Decimal(100),
    )
    new_line = conn.execute(
        """INSERT INTO sii.source_file(tipo,nombre,hash,ruta,comuna,semestre)
        VALUES('NL','new-lines',%s,'fixture',15108,'2027-1') RETURNING id""",
        ("2" * 64,),
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO sii.linea_construccion(source_file_id,comuna,manzana,predio,n_linea,
        destino,material,calidad,anio,m2,abierta,condicion,pisos,raw_line)
        VALUES(%s,15108,1,1,1,'H','B','2',2020,150,false,'',1,'fixture')""",
        (new_line,),
    )
    assert rebuild()["rows_new"] == 0
    assert conn.execute("SELECT predio_source_file_id,m2_h FROM sii.transferencia").fetchone() == (
        new_role,
        Decimal(150),
    )
