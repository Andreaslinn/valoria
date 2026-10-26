"""Score normalizado en [0, 1] para rankings y confianza."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Score:
    value: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"Score debe estar en [0, 1]: {self.value}")

    @classmethod
    def clamped(cls, value: float) -> Score:
        """Construye un Score recortando el valor al rango válido."""
        return cls(max(0.0, min(1.0, value)))
