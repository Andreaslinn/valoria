"""Entidad User del dominio para beta privada."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Role = Literal["admin", "beta_user"]


@dataclass(init=False)
class User:
    id: int | None
    email: str
    password_hash: str
    role: Role
    is_active: bool
    created_at: datetime | None = None
    last_login_at: datetime | None = None

    def __init__(
        self,
        id: int | None,
        email: str | None = None,
        password_hash: str = "",
        role: Role = "beta_user",
        is_active: bool = True,
        created_at: datetime | None = None,
        last_login_at: datetime | None = None,
        username: str | None = None,
    ) -> None:
        # Compatibilidad temporal con tests/scripts antiguos que aun pasan username.
        self.id = id
        self.email = (email or username or "").strip().lower()
        self.password_hash = password_hash
        self.role = role
        self.is_active = is_active
        self.created_at = created_at
        self.last_login_at = last_login_at

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def username(self) -> str:
        return self.email
