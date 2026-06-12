"""Contrato del repositorio de propiedades (inmuebles físicos)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from core.entities.listing import Property


class PropertyRepository(ABC):
    @abstractmethod
    async def save(self, prop: Property) -> Property: ...

    @abstractmethod
    async def find_by_id(self, property_id: int) -> Property | None: ...

    @abstractmethod
    async def find_matching(
        self,
        comuna_slug: str,
        m2: float,
        bedrooms: int,
        bathrooms: int,
        parking: int,
        property_type: str | None = None,
        built_area_m2: float | None = None,
        land_area_m2: float | None = None,
    ) -> Property | None:
        """Busca una Property existente que matchee los atributos físicos.
        Usado por el pipeline para unificar listings del mismo inmueble.
        """
