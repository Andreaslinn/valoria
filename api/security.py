"""Helpers de seguridad: hash bcrypt + emisión/verificación de JWT.

Los tokens JWT transportan `sub` (username) + `role`. El `sub` es el campo
estándar de JWT para identificar el sujeto; lo usamos para cargar el User
en cada request autenticado.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from config.settings import Settings

# bcrypt tiene un límite duro de 72 bytes en el input. Para passwords más
# largos truncamos en lugar de rechazar — es lo mismo que hacía passlib
# históricamente y es transparente al usuario. La entropía de los primeros
# 72 bytes de un password de largo arbitrario sigue siendo alta.
_BCRYPT_MAX_BYTES = 72


# ─────────────────────────────────────────────────────────
#  Password hashing
# ─────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    """Hashea un password en claro con bcrypt (rounds=12 por default)."""
    if not password:
        raise ValueError("password no puede ser vacío")
    password_bytes = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica un password contra su hash. Nunca lanza — retorna bool."""
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:_BCRYPT_MAX_BYTES],
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        # Hash corrupto o no-bcrypt → falla segura
        return False


# ─────────────────────────────────────────────────────────
#  JWT
# ─────────────────────────────────────────────────────────
class TokenError(Exception):
    """El token es inválido, expirado o manipulado."""


def create_access_token(
    *,
    email: str | None = None,
    username: str | None = None,
    role: str,
    settings: Settings,
    expires_delta: timedelta | None = None,
) -> str:
    """Emite un JWT firmado con HS256. El payload lleva `sub`, `role`, `exp`."""
    subject = email or username
    if not subject:
        raise ValueError("email requerido")
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_expiration_minutes)
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    """Valida firma + expiración. Retorna el payload. Lanza TokenError si falla."""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        raise TokenError(str(e)) from e
