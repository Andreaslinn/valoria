"""Authentication endpoints for private beta users."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from api.deps import CurrentUser, RateLimiterDep, UserServiceDep
from api.rate_limit import (
    RateLimitRule,
    client_ip_identifier,
    enforce_rate_limit,
    normalized_account_identifier,
)
from config import Settings, get_settings
from api.security import create_access_token
from core.exceptions import ValidationError
from services.users import PUBLIC_AUTH_ERROR, validate_email, validate_password

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


class RegisterIn(BaseModel):
    email: str
    password: str


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    limiter: RateLimiterDep,
    user_service: UserServiceDep = None,  # type: ignore[assignment]
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    # OAuth2PasswordRequestForm names the field "username"; for AVM it is the email.
    client_ip = client_ip_identifier(request)
    await enforce_rate_limit(
        limiter,
        RateLimitRule(
            namespace="auth:login:ip",
            max_requests=settings.rate_limit_login_ip_max,
            window_seconds=settings.rate_limit_login_ip_window_seconds,
        ),
        client_ip,
    )
    await enforce_rate_limit(
        limiter,
        RateLimitRule(
            namespace="auth:login:account",
            max_requests=settings.rate_limit_login_account_max,
            window_seconds=settings.rate_limit_login_account_window_seconds,
        ),
        f"{client_ip}:{normalized_account_identifier(form.username)}",
    )
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


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    payload: RegisterIn,
    limiter: RateLimiterDep,
    user_service: UserServiceDep = None,  # type: ignore[assignment]
    settings: Settings = Depends(get_settings),
) -> UserOut:
    await enforce_rate_limit(
        limiter,
        RateLimitRule(
            namespace="auth:register:ip",
            max_requests=settings.rate_limit_register_ip_max,
            window_seconds=settings.rate_limit_register_ip_window_seconds,
        ),
        client_ip_identifier(request),
    )
    if not settings.beta_signup_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Registro beta deshabilitado")

    try:
        email = validate_email(payload.email)
        validate_password(payload.password)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    if await user_service.find_by_email(email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El usuario ya existe")

    try:
        user = await user_service.create_user(email, payload.password, "beta_user")
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    assert user.id is not None
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
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
