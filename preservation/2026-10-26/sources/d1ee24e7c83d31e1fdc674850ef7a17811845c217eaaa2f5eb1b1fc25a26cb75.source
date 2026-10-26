"""Tasar-specific endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.deps import CurrentUser, DbSession
from services.recent_user_activity import RecentUserActivityService

router = APIRouter(prefix="/tasar", tags=["tasar"])


class RecentUserActivityEventOut(BaseModel):
    id: str
    event_type: str
    title: str
    description: str
    occurred_at: datetime
    source: str
    valuation_id: int | None = None
    listing_id: int | None = None
    report_id: int | None = None
    comuna: str | None = None
    property_type: str | None = None
    estimated_value_uf: float | None = None
    range_low_uf: float | None = None
    range_high_uf: float | None = None
    trend_points_uf: list[float] = Field(default_factory=list)
    confidence: str | None = None
    status: str | None = None
    reason: str | None = None


class RecentUserActivityOut(BaseModel):
    status: str
    user_id: int
    events_count: int
    events: list[RecentUserActivityEventOut] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@router.get("/activity/recent", response_model=RecentUserActivityOut)
async def recent_activity(
    current_user: CurrentUser,
    session: DbSession,
    limit: int = Query(default=3, ge=1, le=5),
) -> RecentUserActivityOut:
    assert current_user.id is not None
    activity = await RecentUserActivityService(session).get_recent_activity(
        user_id=current_user.id,
        limit=limit,
    )
    return RecentUserActivityOut.model_validate(activity, from_attributes=True)
