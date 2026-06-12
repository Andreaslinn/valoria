"""Small formatting helpers shared by API-facing services."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from core.assessment.confidence import confidence_label_for_score
from core.value_objects.price import Price


def price_clp_int(price: Price) -> int:
    return int(price.clp.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def price_uf_float(price: Price, uf_to_clp: Decimal) -> float:
    return float(price.to_uf(uf_to_clp).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def confidence_label(value: float) -> str:
    return confidence_label_for_score(value)
