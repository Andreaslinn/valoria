"""Display-only price conversion helpers.

These helpers must not be used as canonical price recovery. They are only for
presenting a current UF/CLP equivalent in API/UI payloads.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def uf_to_clp_display(price_uf: Decimal | int | float | str | None, uf_rate: Decimal) -> int | None:
    if price_uf is None or uf_rate <= 0:
        return None
    value = Decimal(str(price_uf)) * uf_rate
    if value <= 0:
        return None
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def clp_to_uf_display(price_clp: Decimal | int | float | str | None, uf_rate: Decimal) -> float | None:
    if price_clp is None or uf_rate <= 0:
        return None
    value = Decimal(str(price_clp)) / uf_rate
    if value <= 0:
        return None
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
