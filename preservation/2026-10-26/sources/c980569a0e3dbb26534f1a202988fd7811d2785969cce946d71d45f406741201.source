"""Contrato del repositorio de usuarios."""
from __future__ import annotations

from abc import ABC, abstractmethod

from core.entities.user import User


class UserRepository(ABC):
    @abstractmethod
    async def find_by_username(self, username: str) -> User | None: ...

    @abstractmethod
    async def find_by_id(self, user_id: int) -> User | None: ...

    @abstractmethod
    async def save(self, user: User) -> User:
        """Inserta (id=None) o actualiza (id != None)."""
