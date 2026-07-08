"""Future feature contract endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from api.deps import CurrentUser
from services.future_features import (
    FutureFeatureContract,
    get_default_future_feature_registry,
)

router = APIRouter(prefix="/future-features", tags=["future-features"])


class FutureFeatureOut(BaseModel):
    feature_key: str
    title: str
    status: str
    message: str
    required_data: list[str] = Field(default_factory=list)
    next_backend_step: str
    safe_to_show_in_beta: bool
    source: str
    last_checked_at: datetime | None = None
    classification: str
    future_fields: list[str] = Field(default_factory=list)
    related_ui_files: list[str] = Field(default_factory=list)
    backend_notes: list[str] = Field(default_factory=list)


@router.get("", response_model=list[FutureFeatureOut])
async def list_future_features(_current_user: CurrentUser) -> list[FutureFeatureOut]:
    registry = get_default_future_feature_registry()
    return [_feature_out(feature) for feature in registry.list_features()]


@router.get("/{feature_key}", response_model=FutureFeatureOut)
async def get_future_feature(
    feature_key: str,
    _current_user: CurrentUser,
) -> FutureFeatureOut:
    registry = get_default_future_feature_registry()
    feature = registry.get_feature(feature_key)
    if feature is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feature futura no encontrada",
        )
    return _feature_out(feature)


def _feature_out(feature: FutureFeatureContract) -> FutureFeatureOut:
    return FutureFeatureOut.model_validate(feature.to_payload())
