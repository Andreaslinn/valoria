"""Lightweight Radar dashboard summary.

This module deliberately does not run opportunity detection. It only exposes
scope and freshness metadata that is safe for the dashboard to load.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.entities.listing import Listing
from core.value_objects.price import Price
from domain.radar.eligibility import list_initial_radar_candidates
from domain.radar.freshness import RadarFreshnessConfig
from domain.radar.scope import parse_allowed_property_types
from infrastructure.db.models import ListingORM


async def build_radar_summary(
    session: AsyncSession,
    *,
    allowed_property_types: str,
    require_fresh_listings: bool = True,
    max_listing_staleness_days: int = 7,
    exclude_refresh_failed: bool = True,
    exclude_removed_or_unavailable: bool = True,
) -> dict[str, Any]:
    allowed = parse_allowed_property_types(allowed_property_types)
    rows = await session.scalars(
        select(ListingORM).where(ListingORM.property_type.in_(allowed))
    )
    listings = rows.all()
    now = datetime.now(UTC)
    config = RadarFreshnessConfig(
        require_fresh_listings=require_fresh_listings,
        max_listing_staleness_days=max_listing_staleness_days,
        exclude_refresh_failed=exclude_refresh_failed,
        exclude_removed_or_unavailable=exclude_removed_or_unavailable,
    )

    eligibility = list_initial_radar_candidates(
        [_to_domain_listing(row) for row in listings],
        allowed_property_types=allowed,
        freshness_config=config,
        now=now,
    )
    diagnostics = eligibility.diagnostics
    last_refresh_at = _latest_refresh_at(listings)
    status = "available" if listings else "empty"

    return {
        "status": status,
        "mode": "manual",
        "auto_run": False,
        "title": "Oportunidades bajo demanda",
        "summary": _summary_text(ready_for_radar_count=diagnostics.ready_for_radar_count),
        "last_run_at": None,
        "opportunities_count": None,
        "fresh_candidates_count": diagnostics.fresh_candidates_count,
        "ready_for_radar_count": diagnostics.ready_for_radar_count,
        "active_scope_count": diagnostics.active_scope_count,
        "excluded_stale_count": diagnostics.excluded_stale_count,
        "excluded_removed_count": diagnostics.excluded_removed_count,
        "excluded_missing_price_count": diagnostics.excluded_missing_price_count,
        "excluded_missing_area_count": diagnostics.excluded_missing_area_count,
        "allowed_property_types": list(allowed),
        "requires_manual_run": True,
        "last_refresh_at": last_refresh_at.isoformat() if last_refresh_at else None,
        "cta_path": "/app/radar",
        "source": "radar_shared_initial_eligibility_v1",
    }


def _summary_text(*, ready_for_radar_count: int) -> str:
    if ready_for_radar_count > 0:
        return (
            f"{ready_for_radar_count} publicaciones estan listas para "
            "evaluacion Radar bajo demanda."
        )
    return "Radar se mantiene manual; no hay candidatos frescos visibles en el resumen v0."


def _latest_refresh_at(listings: list[ListingORM]) -> datetime | None:
    values = [
        value
        for row in listings
        for value in (row.last_refresh_attempted_at, row.last_seen_at, row.scraped_at)
        if value is not None
    ]
    if not values:
        return None
    aware_values = [_as_aware_utc(value) for value in values]
    return max(aware_values)


def _to_domain_listing(row: ListingORM) -> Listing:
    return Listing(
        id=row.id,
        source=row.source,
        external_id=row.external_id,
        title=row.title,
        comuna=row.comuna,
        m2=row.m2,
        bedrooms=row.bedrooms,
        bathrooms=row.bathrooms,
        parking=row.parking,
        price=Price.from_clp(row.price_clp or Decimal("0")),
        status=row.status,
        fingerprint=row.fingerprint,
        scraped_at=row.scraped_at,
        last_seen_at=row.last_seen_at,
        last_refresh_attempted_at=row.last_refresh_attempted_at,
        last_refresh_status=row.last_refresh_status,
        url=row.url,
        property_type=row.property_type,
        built_area_m2=row.built_area_m2,
        land_area_m2=row.land_area_m2,
        usable_area_m2=row.usable_area_m2,
        geocode_precision=row.geocode_precision,
        property_id=row.property_id,
        price_uf=row.price_uf,
        price_currency=row.price_currency,
        price_uf_confidence=row.price_uf_confidence,
        price_uf_source=row.price_uf_source,
        price_recovery_method=row.price_recovery_method,
        raw_metadata=row.raw_metadata or {},
    )


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
