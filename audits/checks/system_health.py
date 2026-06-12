"""System-level health checks."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from audits.registry import CheckResult, register_check
from config import get_settings
from infrastructure.db.database import get_session_factory


@register_check
async def check_db_connection() -> CheckResult:
    try:
        async with get_session_factory()() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        return {
            "name": "db_connection",
            "status": "ERROR",
            "message": "No se pudo conectar a la base de datos.",
            "details": {"error": str(e)},
        }

    return {
        "name": "db_connection",
        "status": "OK",
        "message": "Conexion a DB disponible.",
        "details": {},
    }


@register_check
def check_api_internal_health() -> CheckResult:
    try:
        from api.main import create_app

        response = TestClient(create_app()).get("/health")
    except Exception as e:
        return {
            "name": "api_internal_health",
            "status": "ERROR",
            "message": "No se pudo ejecutar health interno de FastAPI.",
            "details": {"error": str(e)},
        }

    return {
        "name": "api_internal_health",
        "status": "OK" if response.status_code == 200 else "ERROR",
        "message": "API health interno responde." if response.status_code == 200 else "API health interno fallo.",
        "details": {"status_code": response.status_code, "body": _safe_json(response)},
    }


@register_check
def check_config_loaded() -> CheckResult:
    try:
        settings = get_settings()
    except Exception as e:
        return {
            "name": "config_loaded",
            "status": "ERROR",
            "message": "No se pudo cargar configuracion.",
            "details": {"error": str(e)},
        }

    missing: list[str] = []
    if not settings.database_url:
        missing.append("database_url")
    if not settings.jwt_secret_key or len(settings.jwt_secret_key) < 32:
        missing.append("jwt_secret_key")

    return {
        "name": "config_loaded",
        "status": "WARNING" if missing else "OK",
        "message": "Configuracion cargada correctamente." if not missing else "Configuracion cargada con valores incompletos.",
        "details": {
            "environment": settings.environment,
            "log_level": settings.log_level,
            "missing": missing,
        },
    }


def _safe_json(response) -> dict | str:
    try:
        return response.json()
    except ValueError:
        return response.text
