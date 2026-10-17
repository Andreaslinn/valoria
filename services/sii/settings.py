"""Never consult the application's DATABASE_URL or production settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def value(name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ[name]
    return str(dotenv_values(ROOT / ".env.local", interpolate=False).get(name) or default)


def enabled() -> bool:
    return value("SII_INGEST_ENABLED", "false").lower() == "true"


def local_url(url: str) -> str:
    parsed = make_url(url)
    if (
        parsed.drivername != "postgresql+psycopg"
        or parsed.host not in {"127.0.0.1", "localhost"}
        or parsed.port is None
        or parsed.port == 5432
        or parsed.database != "valoria_sii_local"
        or parsed.query
    ):
        raise ValueError(
            "SII requires loopback Postgres, explicit non-5432 port, database valoria_sii_local, no URL options"
        )
    return url


@dataclass(frozen=True)
class Settings:
    url: str
    data: Path

    @classmethod
    def load(cls) -> Settings:
        if not enabled():
            raise RuntimeError("SII_INGEST_ENABLED=false")
        return cls(
            local_url(value("SII_DATABASE_URL")),
            Path(value("SII_DATA_DIR", str(ROOT / "data" / "sii"))).resolve(),
        )
