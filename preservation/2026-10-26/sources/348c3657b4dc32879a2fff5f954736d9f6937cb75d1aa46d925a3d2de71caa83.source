"""Contrato del servicio de geocoding best-effort."""
from __future__ import annotations

from abc import ABC, abstractmethod

from core.value_objects.location import Coordinates


class GeocodingService(ABC):
    @abstractmethod
    async def geocode(self, address: str, comuna: str) -> Coordinates | None:
        """Resuelve una dirección/comuna a coordenadas o None.

        La implementación concreta debe ser best-effort: ante errores de red,
        timeouts, resultados vacíos o payloads inválidos debe retornar None sin
        romper el pipeline.
        """
