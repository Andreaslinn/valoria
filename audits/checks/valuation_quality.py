"""Checks that look for silent valuation model quality issues."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from audits.registry import CheckResult, register_check
from config.constants import LEGACY_UF_ARTIFACT_RATE, MIN_COMPARABLES
from core.entities.listing import Property
from core.exceptions import InsufficientDataError
from domain.valuation.comparables import valuate
from infrastructure.db.database import get_session_factory
from infrastructure.db.mappers import listing_from_orm
from infrastructure.db.models import ListingORM

LOW_CONFIDENCE_THRESHOLD = 0.5
MAX_SAMPLE_SIZE = 25


@register_check
async def check_valuation_quality() -> CheckResult:
    try:
        async with get_session_factory()() as session:
            rows = (
                await session.execute(
                    select(ListingORM)
                    .where(ListingORM.status == "active")
                    .order_by(ListingORM.scraped_at.desc())
                    .limit(MAX_SAMPLE_SIZE)
                )
            ).scalars().all()
    except Exception as e:
        return {
            "name": "valuation_quality",
            "status": "ERROR",
            "message": "No se pudo evaluar calidad de tasaciones por falla de DB.",
            "details": {"error": str(e)},
        }

    listings = [listing_from_orm(row) for row in rows]
    if len(listings) < MIN_COMPARABLES + 1:
        return {
            "name": "valuation_quality",
            "status": "WARNING",
            "message": "Dataset insuficiente para auditar tasaciones por comparables.",
            "details": {
                "active_sample_size": len(listings),
                "min_required": MIN_COMPARABLES + 1,
            },
        }

    insufficient = 0
    low_confidence = 0
    incoherent = 0
    evaluated = 0

    for target in listings:
        candidates = [item for item in listings if item.fingerprint != target.fingerprint]
        prop = Property(
            id=None,
            comuna=target.comuna,
            m2=target.m2,
            property_type=target.property_type,
            built_area_m2=target.built_area_m2,
            land_area_m2=target.land_area_m2,
            usable_area_m2=target.usable_area_m2,
            bedrooms=target.bedrooms,
            bathrooms=target.bathrooms,
            parking=target.parking,
            coordinates=target.coordinates,
        )
        try:
            result = valuate(prop, candidates, LEGACY_UF_ARTIFACT_RATE)
        except InsufficientDataError:
            insufficient += 1
            continue
        evaluated += 1
        if result.comparables_used < MIN_COMPARABLES:
            insufficient += 1
        if result.confidence.value < LOW_CONFIDENCE_THRESHOLD:
            low_confidence += 1
        if _is_incoherent(result.estimated_price.clp, target.price.clp):
            incoherent += 1

    status = "OK"
    if insufficient or low_confidence or incoherent:
        status = "WARNING"

    return {
        "name": "valuation_quality",
        "status": status,
        "message": "Muestra de tasaciones sin senales sospechosas." if status == "OK" else "Se detectaron senales a revisar en tasaciones.",
        "details": {
            "sample_size": len(listings),
            "evaluated": evaluated,
            "insufficient_comparables": insufficient,
            "low_confidence": low_confidence,
            "incoherent_estimates": incoherent,
            "min_comparables": MIN_COMPARABLES,
            "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
        },
    }


def _is_incoherent(estimated: Decimal, published: Decimal) -> bool:
    if estimated <= 0 or published <= 0:
        return True
    ratio = estimated / published
    return ratio < Decimal("0.30") or ratio > Decimal("3.00")
