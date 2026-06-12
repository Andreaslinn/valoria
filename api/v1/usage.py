"""Authenticated product usage event endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from api.deps import CurrentUser, DbSession
from infrastructure.db.models import UsageLogORM
from services.product_usage import ALLOWED_EVENT_TYPES, sanitize_properties

router = APIRouter(prefix="/usage", tags=["usage"])

_CLIENT_CONTEXT_KEYS = {
    "session_id",
    "session_started_at",
    "session_duration_seconds",
}


class UsageEventRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=64)
    feature: str | None = Field(default=None, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UsageEventOut(BaseModel):
    id: int
    event_type: str
    user_id: int
    payload: dict[str, Any]
    created_at: datetime


@router.post("/events", response_model=UsageEventOut, status_code=status.HTTP_201_CREATED)
async def create_usage_event(
    payload: UsageEventRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> UsageEventOut:
    assert current_user.id is not None
    event_type = payload.event_type.strip()
    if event_type not in ALLOWED_EVENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported product usage event: {event_type}",
        )

    usage_log = UsageLogORM(
        user_id=current_user.id,
        event_type=event_type,
        payload={
            "feature": _clean_feature(payload.feature),
            "metadata": _safe_metadata(payload.metadata),
        },
    )
    session.add(usage_log)
    await session.commit()
    await session.refresh(usage_log)
    return UsageEventOut(
        id=usage_log.id,
        event_type=usage_log.event_type,
        user_id=current_user.id,
        payload=usage_log.payload or {},
        created_at=usage_log.created_at,
    )


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    clean = sanitize_properties(metadata)
    for key in _CLIENT_CONTEXT_KEYS:
        if key in metadata:
            clean[key] = _safe_context_value(metadata[key])
    return clean


def _safe_context_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)[:120]


def _clean_feature(value: str | None) -> str | None:
    text = str(value or "").strip().lower()
    return text[:80] if text else None
