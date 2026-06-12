"""Compare legacy CLP-only Radar opportunities against canonical price basis."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constants import (  # noqa: E402
    LOW_DATA_THRESHOLD,
    MIN_RADAR_DATASET_SIZE,
    MIN_UNDERVALUATION,
    MIN_UNDERVALUATION_LOW_DATA,
    LEGACY_UF_ARTIFACT_RATE,
)
from core.entities.listing import Listing  # noqa: E402
from core.exceptions import InsufficientDataError  # noqa: E402
from core.normalization.property_type import normalize_property_type as _property_type  # noqa: E402
from domain.radar.detector import detect_opportunities  # noqa: E402
from domain.radar.price_basis import radar_price_basis  # noqa: E402
from domain.valuation.comparables import valuate  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.mappers import listing_from_orm  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402


@dataclass(frozen=True)
class RadarAuditOpportunity:
    listing_id: int | None
    external_id: str | None
    title: str
    comuna: str
    property_type: str
    price_clp: str
    price_uf: str | None
    price_currency: str | None
    price_basis_used: str
    price_data_quality: str
    discount_pct: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Radar price provenance impact.")
    parser.add_argument("--uf-rate", type=Decimal, default=LEGACY_UF_ARTIFACT_RATE)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--examples", type=int, default=30)
    parser.add_argument("--output-dir", default="reports/radar_price_provenance")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    async with get_session_factory()() as session:
        stmt = select(ListingORM).where(ListingORM.status == "active").order_by(ListingORM.id.asc())
        if args.limit:
            stmt = stmt.limit(args.limit)
        listings = [listing_from_orm(row) for row in (await session.execute(stmt)).scalars().all()]

    legacy = _legacy_detect_opportunities(listings, args.uf_rate)
    canonical = detect_opportunities(listings, args.uf_rate).opportunities
    legacy_ids = {_key(item.listing) for item in legacy}
    canonical_ids = {_key(item.listing) for item in canonical}
    disappeared = [item for item in legacy if _key(item.listing) not in canonical_ids]
    appeared = [item for item in canonical if _key(item.listing) not in legacy_ids]
    legacy_excluded = [
        listing for listing in listings
        if listing.is_active and radar_price_basis(listing).exclude_reason == "legacy_uf_missing_price_uf"
    ]
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "uf_rate_used": str(args.uf_rate),
        "active_listings_evaluated": len([listing for listing in listings if listing.is_active]),
        "legacy_opportunities": len(legacy),
        "canonical_opportunities": len(canonical),
        "disappeared": len(disappeared),
        "appeared": len(appeared),
        "legacy_price_excluded": len(legacy_excluded),
        "legacy_examples": [asdict(_audit_item(item)) for item in legacy[:args.examples]],
        "canonical_examples": [asdict(_audit_item(item)) for item in canonical[:args.examples]],
        "disappeared_examples": [asdict(_audit_item(item)) for item in disappeared[:args.examples]],
        "appeared_examples": [asdict(_audit_item(item)) for item in appeared[:args.examples]],
        "legacy_excluded_examples": [
            {
                "listing_id": listing.id,
                "external_id": listing.external_id,
                "title": listing.title,
                "comuna": listing.comuna,
                "property_type": listing.property_type,
                "price_clp": str(listing.price.clp),
                "price_currency": listing.price_currency,
                "price_uf_source": listing.price_uf_source,
                "reason": radar_price_basis(listing).exclude_reason,
            }
            for listing in legacy_excluded[:args.examples]
        ],
    }
    _write_report(report, Path(args.output_dir))
    print(json.dumps({k: report[k] for k in (
        "active_listings_evaluated",
        "legacy_opportunities",
        "canonical_opportunities",
        "disappeared",
        "appeared",
        "legacy_price_excluded",
    )}, ensure_ascii=False, indent=2))
    return 0


def _legacy_detect_opportunities(listings: Sequence[Listing], uf_rate: Decimal):
    from core.entities.opportunity import Opportunity, RadarResult

    active = [listing for listing in listings if listing.is_active]
    by_type: dict[str, list[Listing]] = defaultdict(list)
    for listing in active:
        by_type[_property_type(listing)].append(listing)
    if not any(len(rows) >= MIN_RADAR_DATASET_SIZE for rows in by_type.values()):
        return []

    opportunities = []
    for target in active:
        target_type = _property_type(target)
        same_type_count = len(by_type.get(target_type, ()))
        if same_type_count < MIN_RADAR_DATASET_SIZE:
            continue
        low_data_mode = same_type_count < LOW_DATA_THRESHOLD
        min_discount = MIN_UNDERVALUATION_LOW_DATA if low_data_mode else MIN_UNDERVALUATION
        candidates = [
            listing for listing in active
            if _property_type(listing) == target_type and _key(listing) != _key(target)
        ]
        try:
            valuation = valuate(_listing_as_property(target), candidates, uf_rate)
        except InsufficientDataError:
            continue
        estimated = valuation.estimated_price.clp
        if estimated <= 0:
            continue
        discount = float((estimated - target.price.clp) / estimated)
        if discount < min_discount:
            continue
        basis = radar_price_basis(target)
        opportunities.append(
            Opportunity(
                listing=target,
                market_price=valuation.estimated_price,
                discount_pct=min(discount, 1.0),
                confidence=valuation.confidence,
                comparables_used=valuation.comparables_used,
                valuation_result=valuation,
                price_currency=basis.price_currency,
                price_uf=basis.price_uf,
                price_clp_snapshot=basis.price_clp_snapshot,
                price_basis_used="legacy_clp",
                price_data_quality=basis.price_data_quality,
            )
        )
    opportunities.sort(key=lambda item: item.ranking_score, reverse=True)
    return RadarResult(
        opportunities=opportunities,
        total_listings_analyzed=len(active),
        low_data_mode=False,
    ).opportunities


def _listing_as_property(listing: Listing):
    from core.entities.listing import Property

    return Property(
        id=listing.property_id,
        comuna=listing.comuna,
        m2=float(listing.m2 or 0),
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


def _audit_item(opportunity) -> RadarAuditOpportunity:
    basis = radar_price_basis(opportunity.listing)
    return RadarAuditOpportunity(
        listing_id=opportunity.listing.id,
        external_id=opportunity.listing.external_id,
        title=opportunity.listing.title,
        comuna=opportunity.listing.comuna,
        property_type=opportunity.listing.property_type,
        price_clp=str(opportunity.listing.price.clp),
        price_uf=str(basis.price_uf) if basis.price_uf is not None else None,
        price_currency=basis.price_currency,
        price_basis_used=opportunity.price_basis_used or basis.price_basis_used,
        price_data_quality=opportunity.price_data_quality or basis.price_data_quality,
        discount_pct=round(opportunity.discount_pct * 100, 2),
    )


def _key(listing: Listing) -> str:
    if listing.id is not None:
        return f"id:{listing.id}"
    return f"fp:{listing.fingerprint}"


def _write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"radar_price_provenance_{stamp}"
    json_payload = json.dumps(report, ensure_ascii=False, indent=2)
    (output_dir / f"{stem}.json").write_text(json_payload, encoding="utf-8")
    (output_dir / "radar_price_provenance_latest.json").write_text(json_payload, encoding="utf-8")
    md_payload = _markdown(report)
    (output_dir / f"{stem}.md").write_text(md_payload, encoding="utf-8")
    (output_dir / "radar_price_provenance_latest.md").write_text(md_payload, encoding="utf-8")


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Radar Price Provenance Audit",
        "",
        f"- Active listings evaluated: {report['active_listings_evaluated']}",
        f"- Legacy opportunities: {report['legacy_opportunities']}",
        f"- Canonical opportunities: {report['canonical_opportunities']}",
        f"- Disappeared: {report['disappeared']}",
        f"- Appeared: {report['appeared']}",
        f"- Legacy price excluded: {report['legacy_price_excluded']}",
        "",
        "## Disappeared Examples",
        "",
        "| listing_id | external_id | comuna | currency | basis | quality | discount_pct |",
        "| --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for row in report["disappeared_examples"]:
        lines.append(
            f"| {row['listing_id']} | {row['external_id']} | {row['comuna']} | "
            f"{row['price_currency']} | {row['price_basis_used']} | {row['price_data_quality']} | "
            f"{row['discount_pct']} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
