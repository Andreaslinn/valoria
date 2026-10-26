"""Filtros de calidad para oportunidades detectadas por el radar.

La UI o el service layer deciden qué umbrales aplicar según el contexto
(ej.: "top 10 oportunidades con confianza alta"). Estos helpers NO modifican
el detector; simplemente refinan la lista que él produce.
"""
from __future__ import annotations

from collections.abc import Sequence

from config.constants import MIN_COMPARABLES
from core.entities.opportunity import Opportunity

# Umbral por defecto de confianza: debajo de esto el estimado es poco fiable.
DEFAULT_MIN_CONFIDENCE = 0.5


def apply_quality_filters(
    opportunities: Sequence[Opportunity],
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    min_comparables: int = MIN_COMPARABLES,
    min_discount: float | None = None,
) -> list[Opportunity]:
    """Filtra oportunidades por calidad de la señal.

    Args:
        min_confidence: descarta valuaciones con confianza baja.
        min_comparables: exige un mínimo de comparables usados.
        min_discount: si se provee, filtra bajo ese descuento (además del
            umbral aplicado por el detector en tiempo de detección).
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence fuera de [0, 1]: {min_confidence}")
    if min_comparables < 0:
        raise ValueError(f"min_comparables debe ser ≥ 0: {min_comparables}")
    if min_discount is not None and not 0.0 <= min_discount <= 1.0:
        raise ValueError(f"min_discount fuera de [0, 1]: {min_discount}")

    def passes(o: Opportunity) -> bool:
        if o.confidence.value < min_confidence:
            return False
        if o.comparables_used < min_comparables:
            return False
        if min_discount is not None and o.discount_pct < min_discount:
            return False
        return True

    return [o for o in opportunities if passes(o)]


def top_n(opportunities: Sequence[Opportunity], n: int) -> list[Opportunity]:
    """Conserva los N primeros (se asume ya ordenados por ranking_score DESC)."""
    if n < 0:
        raise ValueError(f"n debe ser ≥ 0: {n}")
    return list(opportunities[:n])
