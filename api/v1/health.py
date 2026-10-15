"""Versioned health endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from api.deps import CurrentAdmin
import audits.checks  # noqa: F401
from audits.registry import run_all_checks, summarize_status

router = APIRouter(prefix="/health", tags=["meta"])


@router.get("/ingestion")
async def source_health() -> dict:
    from infrastructure.db.database import get_session_factory
    from services.ingestion_state import ingestion_health
    from sqlalchemy.exc import SQLAlchemyError
    try:
        return await ingestion_health(get_session_factory())
    except (SQLAlchemyError, TypeError):
        # Liveness remains separate; never report fresh data when ledger is unavailable.
        return {"status": "degraded", "reason": "ingestion_state_unavailable", "sources": {}}


@router.get("")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/capabilities")
async def capabilities() -> dict:
    from services.v2_contract import v2_capabilities
    return v2_capabilities()


@router.get("/full")
async def full_health(_admin: CurrentAdmin) -> dict:
    checks = await run_all_checks()
    return {
        "status": summarize_status(checks),
        "checks": checks,
    }
