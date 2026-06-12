"""Detector de oportunidades: listings subvaluados vs. el mercado.

Usa `domain.valuation.valuate` como motor — cada listing se tasa contra los
demás listings activos como universo de referencia. Si su precio está por
debajo del estimado en al menos MIN_UNDERVALUATION, se marca como oportunidad.

Modos:
    · property_type dataset < MIN_RADAR_DATASET_SIZE → no evalúa ese tipo.
    · property_type dataset < LOW_DATA_THRESHOLD     → modo conservador para ese tipo.
    · property_type dataset ≥ LOW_DATA_THRESHOLD     → modo normal para ese tipo.

Función pura: no toca DB, red ni caché.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

from config.constants import (
    LOW_DATA_THRESHOLD,
    MIN_RADAR_DATASET_SIZE,
    MIN_UNDERVALUATION,
    MIN_UNDERVALUATION_LOW_DATA,
)
from core.entities.listing import Listing, Property
from core.entities.opportunity import Opportunity, RadarResult
from core.exceptions import InsufficientDataError
from core.normalization.property_type import normalize_property_type as _property_type
from domain.valuation.comparables import valuate
from domain.radar.price_basis import canonical_discount_pct, radar_price_basis


def detect_opportunities(
    listings: Sequence[Listing],
    uf_to_clp: Decimal,
) -> RadarResult:
    """Recorre `listings` y retorna los que están subvaluados.

    Args:
        listings: universo completo (filtrado previamente por quien llama).
        uf_to_clp: tasa UF vigente (se propaga a cada ValuationResult).

    Returns:
        RadarResult con opportunities ordenadas por ranking_score DESC.
    """
    active = [listing for listing in listings if listing.is_active]

    active_by_property_type = _active_by_property_type(active)
    low_data_by_property_type = {
        property_type: len(rows) < LOW_DATA_THRESHOLD
        for property_type, rows in active_by_property_type.items()
    }

    if not any(len(rows) >= MIN_RADAR_DATASET_SIZE for rows in active_by_property_type.values()):
        return RadarResult(
            opportunities=[],
            total_listings_analyzed=len(active),
            low_data_mode=True,
            low_data_by_property_type=low_data_by_property_type,
        )

    opportunities: list[Opportunity] = []
    for target_listing in active:
        target_type = _property_type(target_listing)
        same_type_count = len(active_by_property_type.get(target_type, ()))
        if same_type_count < MIN_RADAR_DATASET_SIZE:
            continue
        low_data_mode = low_data_by_property_type.get(target_type, True)
        min_undervaluation = (
            MIN_UNDERVALUATION_LOW_DATA if low_data_mode else MIN_UNDERVALUATION
        )
        opportunity = _evaluate_listing(
            target_listing, active, uf_to_clp, min_undervaluation
        )
        if opportunity is not None:
            opportunities.append(opportunity)

    opportunities.sort(key=lambda o: o.ranking_score, reverse=True)

    return RadarResult(
        opportunities=opportunities,
        total_listings_analyzed=len(active),
        low_data_mode=any(low_data_by_property_type.values()),
        low_data_by_property_type=low_data_by_property_type,
    )


# ─────────────────────────────────────────────────────────
#  Helpers internos
# ─────────────────────────────────────────────────────────
def _active_by_property_type(active: Sequence[Listing]) -> dict[str, list[Listing]]:
    by_type: dict[str, list[Listing]] = defaultdict(list)
    for listing in active:
        by_type[_property_type(listing)].append(listing)
    return dict(by_type)


def _evaluate_listing(
    target: Listing,
    universe: Sequence[Listing],
    uf_to_clp: Decimal,
    min_undervaluation: float,
) -> Opportunity | None:
    """Valora un listing contra los demás del universo; lo retorna si califica."""
    candidates = [
        listing
        for listing in _exclude_self(target, universe)
        if _same_property_type(target, listing)
    ]
    target_property = _listing_as_property(target)

    try:
        valuation = valuate(target_property, candidates, uf_to_clp)
    except InsufficientDataError:
        return None

    estimated = valuation.estimated_price.clp
    basis = radar_price_basis(target)
    discount_f = canonical_discount_pct(
        market_price_clp=estimated,
        listing_basis=basis,
        uf_to_clp=uf_to_clp,
    )
    if discount_f is None:
        return None

    if discount_f < min_undervaluation:
        return None

    return Opportunity(
        listing=target,
        market_price=valuation.estimated_price,
        discount_pct=min(discount_f, 1.0),  # clamp defensivo
        confidence=valuation.confidence,
        comparables_used=valuation.comparables_used,
        valuation_result=valuation,
        price_currency=basis.price_currency,
        price_uf=basis.price_uf,
        price_clp_snapshot=basis.price_clp_snapshot,
        price_basis_used=basis.price_basis_used,
        price_data_quality=basis.price_data_quality,
    )


def _exclude_self(target: Listing, universe: Sequence[Listing]) -> list[Listing]:
    """Retorna `universe` sin el target.

    Usa id si está disponible (entidad persistida) o fingerprint como fallback
    (entidad en memoria). La DB garantiza unicidad de fingerprint, por lo que
    no hay ambigüedad en ambos caminos.
    """
    if target.id is not None:
        return [listing for listing in universe if listing.id != target.id]
    return [listing for listing in universe if listing.fingerprint != target.fingerprint]


def _same_property_type(a: Listing, b: Listing) -> bool:
    return _property_type(a) == _property_type(b)


def _listing_as_property(listing: Listing) -> Property:
    """Construye una Property a partir de los atributos físicos del listing."""
    return Property(
        id=None,
        comuna=listing.comuna,
        m2=listing.m2,
        property_type=listing.property_type,
        built_area_m2=listing.built_area_m2,
        land_area_m2=listing.land_area_m2,
        usable_area_m2=listing.usable_area_m2,
        bedrooms=listing.bedrooms,
        bathrooms=listing.bathrooms,
        parking=listing.parking,
        coordinates=listing.coordinates,
        geocode_precision=listing.geocode_precision,
        raw_metadata=listing.raw_metadata,
    )
