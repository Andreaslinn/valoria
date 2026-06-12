"""Checks for opportunity radar behavior."""
from __future__ import annotations

from statistics import mean

from sqlalchemy import select

from audits.registry import CheckResult, register_check
from config.constants import LEGACY_UF_ARTIFACT_RATE, MIN_RADAR_DATASET_SIZE
from domain.radar.detector import detect_opportunities
from infrastructure.db.database import get_session_factory
from infrastructure.db.mappers import listing_from_orm
from infrastructure.db.models import ListingORM

MAX_RADAR_SAMPLE_SIZE = 200


@register_check
async def check_radar_quality() -> CheckResult:
    try:
        async with get_session_factory()() as session:
            rows = (
                await session.execute(
                    select(ListingORM)
                    .where(ListingORM.status == "active")
                    .order_by(ListingORM.scraped_at.desc())
                    .limit(MAX_RADAR_SAMPLE_SIZE)
                )
            ).scalars().all()
    except Exception as e:
        return {
            "name": "radar_quality",
            "status": "ERROR",
            "message": "No se pudo evaluar radar por falla de DB.",
            "details": {"error": str(e)},
        }

    listings = [listing_from_orm(row) for row in rows]
    result = detect_opportunities(listings, LEGACY_UF_ARTIFACT_RATE)
    scores = [item.ranking_score for item in result.opportunities]
    avg_score = mean(scores) if scores else 0.0

    warnings: list[str] = []
    if len(listings) < MIN_RADAR_DATASET_SIZE:
        warnings.append("dataset_too_small")
    if len(listings) >= MIN_RADAR_DATASET_SIZE and not result.opportunities:
        warnings.append("no_opportunities_detected")
    if scores and (avg_score < 0.02 or avg_score > 0.95):
        warnings.append("suspicious_average_score")

    return {
        "name": "radar_quality",
        "status": "WARNING" if warnings else "OK",
        "message": "Radar sin senales sospechosas." if not warnings else "Radar requiere revision.",
        "details": {
            "active_sample_size": len(listings),
            "min_dataset_size": MIN_RADAR_DATASET_SIZE,
            "opportunity_count": len(result.opportunities),
            "average_score": round(avg_score, 4),
            "low_data_mode": result.low_data_mode,
            "warnings": warnings,
        },
    }
