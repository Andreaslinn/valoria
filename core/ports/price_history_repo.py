"""Contrato del repositorio de historial de precios."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal


class PriceHistoryRepository(ABC):
    @abstractmethod
    async def record(
        self,
        *,
        listing_id: int,
        price_clp: Decimal,
        observed_at: datetime,
        price_uf: Decimal | None = None,
        price_clp_snapshot: Decimal | None = None,
        price_currency: str | None = None,
        uf_rate_used: Decimal | None = None,
        change_basis: str | None = None,
        is_artifact: bool = False,
        artifact_reason: str | None = None,
    ) -> None:
        """Graba un snapshot histórico de precio de un listing.

        Se llama desde el pipeline cada vez que el precio cambia vs. la
        última ingesta. La fecha `observed_at` corresponde al momento en
        que el precio anterior fue válido.
        """
