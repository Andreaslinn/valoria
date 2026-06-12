"""Admin-only user management endpoints for private beta."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from api.deps import CurrentAdmin, UserServiceDep
from core.entities.user import Role
from core.exceptions import ValidationError

router = APIRouter(prefix="/users", tags=["users"])


class UserCreateIn(BaseModel):
    email: str
    password: str
    role: Role = "beta_user"


class PasswordChangeIn(BaseModel):
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool
    created_at: datetime | None = None
    last_login_at: datetime | None = None


@router.get("", response_model=list[UserOut])
async def list_users(
    _admin: CurrentAdmin,
    user_service: UserServiceDep,
) -> list[UserOut]:
    return [_to_out(user) for user in await user_service.list_users()]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateIn,
    _admin: CurrentAdmin,
    user_service: UserServiceDep,
) -> UserOut:
    try:
        return _to_out(await user_service.create_user(payload.email, payload.password, payload.role))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{user_id}/activate", response_model=UserOut)
async def activate_user(
    user_id: int,
    _admin: CurrentAdmin,
    user_service: UserServiceDep,
) -> UserOut:
    try:
        return _to_out(await user_service.activate_user(user_id))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/{user_id}/deactivate", response_model=UserOut)
async def deactivate_user(
    user_id: int,
    _admin: CurrentAdmin,
    user_service: UserServiceDep,
) -> UserOut:
    try:
        return _to_out(await user_service.deactivate_user(user_id))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/{user_id}/password", response_model=UserOut)
async def change_password(
    user_id: int,
    payload: PasswordChangeIn,
    _admin: CurrentAdmin,
    user_service: UserServiceDep,
) -> UserOut:
    try:
        return _to_out(await user_service.change_password(user_id, payload.password))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


def _to_out(user) -> UserOut:
    assert user.id is not None
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )
