"""Authentication endpoints for private beta users."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from api.deps import AppSettings, CurrentUser, UserServiceDep
from api.security import create_access_token
from services.users import PUBLIC_AUTH_ERROR

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Segundos hasta expiracion")


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool
    created_at: datetime | None = None
    last_login_at: datetime | None = None


@router.post("/login", response_model=TokenResponse)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    user_service: UserServiceDep = None,  # type: ignore[assignment]
    settings: AppSettings = None,  # type: ignore[assignment]
) -> TokenResponse:
    # OAuth2PasswordRequestForm names the field "username"; for AVM it is the email.
    user = await user_service.authenticate_user(form.username, form.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=PUBLIC_AUTH_ERROR,
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        email=user.email,
        role=user.role,
        settings=settings,
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expiration_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> None:
    return None


@router.get("/me", response_model=UserOut)
async def read_me(current_user: CurrentUser) -> UserOut:
    assert current_user.id is not None
    return UserOut(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
        last_login_at=current_user.last_login_at,
    )
