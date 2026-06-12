"""Contrato que debe cumplir cualquier repositorio de listings.

Las implementaciones concretas (SQLAlchemy, in-memory para tests) viven en
infrastructure/db/repositories/.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from core.entities.listing import Listing


class ListingRepository(ABC):
    @abstractmethod
    async def save(self, listing: Listing) -> Listing:
        """Persiste el listing. Devuelve la entidad con el id asignado."""

    @abstractmethod
    async def find_by_id(self, listing_id: int) -> Listing | None: ...

    @abstractmethod
    async def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        comuna: str | None = None,
        status: str | None = None,
    ) -> Sequence[Listing]:
        """Listings paginados para lectura API/UI."""

    @abstractmethod
    async def list_active(self, *, limit: int | None = None) -> Sequence[Listing]:
        """Listings activos, usados por el radar."""

    @abstractmethod
    async def find_by_fingerprint(self, fingerprint: str) -> Listing | None:
        """Usado por el pipeline de ingesta para detectar duplicados."""

    @abstractmethod
    async def find_by_source_external_id(self, source: str, external_id: str) -> Listing | None:
        """Identidad primaria del aviso en su portal de origen."""

    @abstractmethod
    async def find_active_in_comuna(
        self,
        comuna_slug: str,
        *,
        property_type: str | None = None,
    ) -> Sequence[Listing]:
        """Listings activos en una comuna — input del motor de comparables."""

    @abstractmethod
    async def count_active(self) -> int:
        """Tamaño del dataset activo — gate para low_data_mode en el radar."""
