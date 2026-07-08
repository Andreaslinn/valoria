"""Contract for the service that provides the current UF to CLP rate."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class UFRateInfo:
    rate: Decimal
    source: str
    is_fallback: bool = False
    cache_hit: bool = False
    rate_date: date | None = None
    fetched_at: datetime | None = None
    is_stale: bool = False
    stale_reason: str | None = None


class UFService(ABC):
    @abstractmethod
    async def get_current_rate(self) -> Decimal:
        """Current UF to CLP rate.

        Implementations should cache real values. They must not invent or return
        a hardcoded fallback rate when the remote source is unavailable.
        """

    async def get_current_rate_info(self) -> UFRateInfo:
        rate = await self.get_current_rate()
        return UFRateInfo(rate=rate, source="service", is_fallback=False, cache_hit=False)
