"""Streaming local jobs; raw versions remain immutable and replayable."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import psycopg
from bs4 import BeautifulSoup
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

from services.sii.parsing import COMUNAS, FILE_RE, catastro_row, comuna, dates, decimal
from services.sii.settings import Settings, local_url

PUBLIC_INDEX = "https://www.sii.cl/destacados/transparencia/"
JOB_NAMES = ("sii_f2890_fetch", "sii_catastro_import", "sii_rebuild")


def connect(settings: Settings):
    url = make_url(local_url(settings.url))
    return psycopg.connect(
        host=url.host,
        port=url.port,
        dbname=url.database,
        user=url.username,
        password=url.password,
        connect_timeout=5,
        autocommit=True,
    )


@contextmanager
def job(name: str):
    settings = Settings.load()  # flag + local URL validation BEFORE any I/O
    settings.data.mkdir(parents=True, exist_ok=True)
    with connect(settings) as conn:
        # Serialize all SII writers, including different job names and processes.
        if not conn.execute("SELECT pg_try_advisory_lock(289020261017)").fetchone()[0]:
            raise RuntimeError("sii_job_already_running")
        run_id = conn.execute(
            "INSERT INTO sii.job_run(job) VALUES (%s) RETURNING id", (name,)
        ).fetchone()[0]
        counters = {}
        try:
            yield settings, conn, counters
            conn.execute(
                "UPDATE sii.job_run SET finished_at=now(),successful=true,counters=%s WHERE id=%s",
                (Jsonb(counters), run_id),
            )
        except Exception as exc:
            # Do not persist exception messages that may include connection details.
            conn.execute(
                "UPDATE sii.job_run SET finished_at=now(),successful=false,error=%s WHERE id=%s",
                (type(exc).__name__, run_id),
            )
            raise
        finally:
            conn.execute("SELECT pg_advisory_unlock(289020261017)")


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source(conn, path, kind, digest, *, semestre=None, code=None, date=None):
    return conn.execute(
        """INSERT INTO sii.source_file(tipo,nombre,hash,ruta,semestre,comuna,fecha)
        VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tipo,nombre,hash) DO NOTHING RETURNING id""",
        (kind, path.name, digest, str(path), semestre, code, date),
    ).fetchone()


def catastro_import():
    with job("sii_catastro_import") as (settings, conn, counters):
        inbox = settings.data / "inbox"
        inbox.mkdir(exist_ok=True)
        counters.update(files_new=0, rows_new=0, files_unchanged=0, comunas={})
        for path in sorted(inbox.iterdir()):
            if not path.is_file():
                continue
            match = FILE_RE.fullmatch(path.name)
            if not match:
                if path.name.upper().startswith("BRTMPCATAS"):
                    raise ValueError(f"unsupported_catastro_filename: {path.name}")
                continue
            kind, year, half, code = match.groups()
            code = int(code)
            if code not in COMUNAS:
                raise ValueError(f"unsupported_commune: {code}")
            semestre = f"{year}-{half}"
            digest = file_hash(path)
            destination = settings.data / "processed" / digest / path.name
            with conn.transaction():
                saved = source(conn, path, kind, digest, semestre=semestre, code=code)
                if saved:
                    source_id = saved[0]
                    if kind == "N":
                        sql = """COPY sii.predio(source_file_id,comuna,manzana,predio,direccion_raw,
                            calle,numero,unidad,destino,tipo,m2_terreno,avaluo,contribucion,raw_line,semestre) FROM STDIN"""
                    else:
                        sql = """COPY sii.linea_construccion(source_file_id,comuna,manzana,predio,
                            n_linea,destino,material,calidad,anio,m2,abierta,condicion,pisos,raw_line) FROM STDIN"""
                    count = 0
                    seen_codes = {}
                    with (
                        path.open(encoding="latin1", newline="") as stream,
                        conn.cursor().copy(sql) as copy,
                    ):
                        for count, raw in enumerate(stream, 1):
                            try:
                                row = catastro_row(raw, kind, code, source_id)
                            except ValueError as exc:
                                raise ValueError(f"{path.name}:row {count}: {exc}") from exc
                            copy.write_row((*row, semestre) if kind == "N" else row)
                            seen_codes[row[1]] = seen_codes.get(row[1], 0) + 1
                    if not count:
                        raise ValueError(f"empty_catastro: {path.name}")
                    conn.execute(
                        "UPDATE sii.source_file SET filas=%s,filas_seleccionadas=%s,ruta=%s WHERE id=%s",
                        (count, count, str(destination), source_id),
                    )
                    counters["rows_new"] += count
                    counters["files_new"] += 1
                else:
                    counters["files_unchanged"] += 1
                    table = "predio" if kind == "N" else "linea_construccion"
                    existing = conn.execute(
                        "SELECT id FROM sii.source_file WHERE tipo=%s AND nombre=%s AND hash=%s",
                        (kind, path.name, digest),
                    ).fetchone()[0]
                    seen_codes = dict(
                        conn.execute(
                            f"SELECT comuna,count(*) FROM sii.{table} WHERE source_file_id=%s GROUP BY comuna",
                            (existing,),
                        ).fetchall()
                    )
            # Commit before move: a failed move is recoverable via hash on the next run.
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if file_hash(destination) != digest:
                    raise ValueError("processed_file_hash_mismatch")
                path.unlink()
            else:
                shutil.move(str(path), str(destination))
            counters["comunas"][str(code)] = {
                "comuna_archivo": code,
                "codigos_filas": seen_codes,
                "nombre_tabla_oficial": COMUNAS[code],
                "nombre_en_fila": None,
                "semestre": semestre,
            }
        return counters


HEADERS = [
    "COMUNA",
    "MANZANA",
    "PREDIO",
    "FECHA_INSCRIPCION",
    "FECHA_ESCRITURA",
    "MONTO_PESOS",
    "MONTO_UF",
]


def import_f2890(conn, archive: Path, date):
    digest = file_hash(archive)
    with conn.transaction():
        saved = source(conn, archive, "F2890", digest, date=date)
        if not saved:
            return {"files_new": 0, "rows_new": 0, "sha256": digest, "version": archive.name}
        source_id = saved[0]
        total = selected = 0
        with zipfile.ZipFile(archive) as z:
            members = [i for i in z.infolist() if not i.is_dir()]
            if len(members) != 1 or not members[0].filename.lower().endswith(".txt"):
                raise ValueError("unexpected_f2890_zip_members")
            if members[0].file_size > 2_000_000_000:
                raise ValueError("f2890_uncompressed_too_large")
            with (
                z.open(members[0]) as binary,
                io.TextIOWrapper(binary, encoding="latin1", newline="") as stream,
            ):
                header = next(csv.reader([next(stream)], delimiter=";"))
                if header not in (
                    HEADERS,
                    ["COMUNA", "MANZANA", "PREDIO", "FI", "FE", "CLP", "UF"],
                ):
                    raise ValueError(f"f2890_header_mismatch: {header}")
                sql = """COPY sii.transferencia_raw(source_file_id,fila,comuna,manzana,predio,
                         fi,fe,clp,uf,raw_line,campos,errores_parseo) FROM STDIN"""
                with conn.cursor().copy(sql) as copy:
                    for total, raw in enumerate(stream, 1):
                        f = next(csv.reader([raw], delimiter=";"))
                        if len(f) != 7:
                            raise ValueError(f"f2890_row_{total + 1}: expected 7 fields")
                        code = comuna(f[0])
                        if code is None:
                            continue  # immutable ZIP retains national rows outside the requested scope
                        fi, fe, errors = dates(f[3], f[4])
                        parsed = []
                        for name, original, converter in (
                            ("manzana", f[1], int),
                            ("predio", f[2], int),
                            ("clp", f[5], decimal),
                            ("uf", f[6], decimal),
                        ):
                            try:
                                parsed.append(converter(original))
                            except (ValueError, ArithmeticError):
                                parsed.append(None)
                                errors.append(name + "_invalido")
                        block, parcel, clp, uf = parsed
                        copy.write_row(
                            (
                                source_id,
                                total + 1,
                                code,
                                block,
                                parcel,
                                fi,
                                fe,
                                clp,
                                uf,
                                raw,
                                Jsonb(dict(zip(header, f, strict=True))),
                                errors,
                            )
                        )
                        selected += 1
        conn.execute(
            "UPDATE sii.source_file SET filas=%s,filas_seleccionadas=%s WHERE id=%s",
            (total, selected, source_id),
        )
    return {
        "files_new": 1,
        "rows_new": selected,
        "national_rows": total,
        "sha256": digest,
        "version": archive.name,
    }


def f2890_fetch(local_zip: Path | None = None):
    import re

    with job("sii_f2890_fetch") as (settings, conn, counters):
        raw_dir = settings.data / "raw" / "f2890"
        raw_dir.mkdir(parents=True, exist_ok=True)
        if local_zip is None:
            with httpx.Client(timeout=60, follow_redirects=False) as http:
                response = http.get(PUBLIC_INDEX)
                response.raise_for_status()
                links = []
                for a in BeautifulSoup(response.text, "html.parser").find_all("a", href=True):
                    url = urljoin(PUBLIC_INDEX, a["href"])
                    parsed = urlparse(url)
                    match = re.fullmatch(
                        r"/destacados/transparencia/F2890_(\d{2}-\d{2}-\d{4})\.zip", parsed.path
                    )
                    if (
                        parsed.scheme == "https"
                        and parsed.netloc in {"www.sii.cl", "sii.cl"}
                        and match
                    ):
                        links.append((datetime.strptime(match[1], "%d-%m-%Y").date(), url))
                if not links:
                    raise ValueError("no_public_f2890_zip_link")
                version_date, url = max(links)
                metadata = raw_dir / "http.json"
                previous = json.loads(metadata.read_text()) if metadata.exists() else {}
                headers = (
                    {"If-None-Match": previous["etag"]}
                    if previous.get("url") == url and previous.get("etag")
                    else {}
                )
                with http.stream("GET", url, headers=headers) as response:
                    if response.status_code == 304:
                        archive = Path(previous["archive"])
                        if not archive.is_file() or file_hash(archive) != previous["sha256"]:
                            raise ValueError("cached_f2890_hash_mismatch")
                    else:
                        response.raise_for_status()
                        with tempfile.TemporaryDirectory(dir=raw_dir) as tmp:
                            archive = Path(tmp) / Path(urlparse(url).path).name
                            size = 0
                            with archive.open("wb") as stream:
                                for chunk in response.iter_bytes(1024 * 1024):
                                    size += len(chunk)
                                    if size > 1_000_000_000:
                                        raise ValueError("f2890_download_too_large")
                                    stream.write(chunk)
                            digest = file_hash(archive)
                            destination = raw_dir / digest / archive.name
                            destination.parent.mkdir(exist_ok=True)
                            if not destination.exists():
                                shutil.move(str(archive), str(destination))
                            archive = destination
                        metadata.write_text(
                            json.dumps(
                                {
                                    "url": url,
                                    "etag": response.headers.get("etag"),
                                    "sha256": digest,
                                    "archive": str(archive),
                                }
                            ),
                            encoding="utf8",
                        )
        else:
            local_zip = local_zip.resolve()
            match = re.fullmatch(r"F2890_(\d{2}-\d{2}-\d{4})\.zip", local_zip.name)
            if not match:
                raise ValueError("unexpected_local_f2890_name")
            version_date = datetime.strptime(match[1], "%d-%m-%Y").date()
            destination = raw_dir / file_hash(local_zip) / local_zip.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copyfile(local_zip, destination)
            archive = destination
        counters.update(import_f2890(conn, archive, version_date))
        return counters


def rebuild():
    from services.sii.geocoding import geocode

    with job("sii_rebuild") as (settings, conn, counters):
        if not conn.execute("SELECT to_regclass('public.ingestion_uf_calendar')").fetchone()[0]:
            raise RuntimeError("existing_ingestion_uf_calendar_required_in_local_database")
        with conn.transaction():
            # Repeatable read also freezes the pre-existing UF calendar for this rebuild.
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            conn.execute("SET LOCAL work_mem='64MB'")
            # This job joins full snapshots; avoid millions of random heap/index
            # probes when freshly imported table statistics underestimate joins.
            conn.execute("SET LOCAL enable_nestloop=off")
            conn.execute("SET LOCAL enable_mergejoin=off")
            conn.execute("SET LOCAL jit=off")
            conn.execute("SET LOCAL max_parallel_workers_per_gather=0")
            conn.execute(
                (Path(__file__).with_name("rebuild.sql")).read_text(encoding="utf8"), prepare=False
            )
            after = conn.execute("SELECT count(*) FROM sii.transferencia").fetchone()[0]
            new = conn.execute("SELECT rows_new FROM rebuild_counters").fetchone()[0]
            counters.update(rows_new=new, rows_current=after)
            counters["geo"] = geocode(conn, settings)
        return counters
