"""Precio inmutable en CLP con conversión UF ↔ CLP.

Usamos Decimal en lugar de float para evitar errores de redondeo acumulados
cuando se suman/restan montos en el cálculo de comparables.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Price:
    clp: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.clp, Decimal):
            raise TypeError(f"Price.clp debe ser Decimal, recibido {type(self.clp).__name__}")
        if self.clp < 0:
            raise ValueError(f"Price no puede ser negativo: {self.clp}")

    # ── Factories ───────────────────────────────────────────
    @classmethod
    def from_clp(cls, amount: Decimal | int | float | str) -> Price:
        return cls(clp=Decimal(str(amount)))

    @classmethod
    def from_uf(cls, uf: Decimal | int | float | str, uf_to_clp: Decimal) -> Price:
        if uf_to_clp <= 0:
            raise ValueError("uf_to_clp debe ser positivo")
        uf_dec = Decimal(str(uf))
        return cls(clp=uf_dec * uf_to_clp)

    # ── Conversión ──────────────────────────────────────────
    def to_uf(self, uf_to_clp: Decimal) -> Decimal:
        if uf_to_clp <= 0:
            raise ValueError("uf_to_clp debe ser positivo")
        return self.clp / uf_to_clp

    # ── Aritmética ──────────────────────────────────────────
    def __add__(self, other: Price) -> Price:
        return Price(clp=self.clp + other.clp)

    def __sub__(self, other: Price) -> Price:
        result = self.clp - other.clp
        if result < 0:
            raise ValueError("Resta produce precio negativo")
        return Price(clp=result)

    def __mul__(self, factor: Decimal | int | float) -> Price:
        return Price(clp=self.clp * Decimal(str(factor)))

    def __lt__(self, other: Price) -> bool:
        return self.clp < other.clp

    def __le__(self, other: Price) -> bool:
        return self.clp <= other.clp
