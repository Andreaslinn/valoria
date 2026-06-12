"""Coordenadas geográficas con cálculo de distancia Haversine."""
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt

_EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class Coordinates:
    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.lat <= 90.0:
            raise ValueError(f"Latitud inválida: {self.lat}")
        if not -180.0 <= self.lon <= 180.0:
            raise ValueError(f"Longitud inválida: {self.lon}")

    def distance_km(self, other: Coordinates) -> float:
        """Distancia Haversine en kilómetros."""
        lat1, lat2 = radians(self.lat), radians(other.lat)
        dlat = lat2 - lat1
        dlon = radians(other.lon - self.lon)
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        return 2 * _EARTH_RADIUS_KM * atan2(sqrt(a), sqrt(1 - a))
