"""Metadata-only backfill for recovered Yapo geographic signals.

Dry-run is the default. This script never calls a geocoder and never mutates
lat/lon or geocode_precision.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from domain.geocoding.geo_signals import (  # noqa: E402
    GEO_SIGNAL_RECOVERY_VERSION,
    enrich_raw_metadata_with_geo_signals,
)
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402
from scripts.geocode_listings import build_geocoding_query_plan  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("reports/geocoding")
SAFE_GEOCODING_SOURCES = {
    "detail_exact_address",
    "metadata_address",
    "metadata_street_hint",
    "card_text",
    "detail_text",
    "existing_microzone_metadata",
}
SAFE_SIGNAL_TYPES = {"street", "avenue", "metro", "intersection"}


@dataclass
class GeoSignalBackfillStats:
    dry_run: bool = True
    evaluated: int = 0
    changed: int = 0
    new_candidates: int = 0
    fallback_with_any_new_candidates: int = 0
    fallback_with_recoverable_candidates: int = 0
    fallback_with_low_confidence_title_candidates: int = 0
    rejected_count: int = 0
    by_signal_type: Counter[str] = field(default_factory=Counter)
    by_source: Counter[str] = field(default_factory=Counter)
    by_confidence: Counter[str] = field(default_factory=Counter)
    by_comuna: Counter[str] = field(default_factory=Counter)
    by_property_type: Counter[str] = field(default_factory=Counter)
    rejected_reasons: Counter[str] = field(default_factory=Counter)
    examples: list[dict[str, Any]] = field(default_factory=list)


async def run_backfill(
    *,
    apply: bool = False,
    limit: int | None = None,
    only_active: bool = False,
    only_missing_coordinates: bool = False,
    comuna: str | None = None,
    property_type: str | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    examples_limit: int = 20,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict[str, Any]:
    factory = session_factory or get_session_factory()
    stats = GeoSignalBackfillStats(dry_run=not apply)
    async with factory() as session:
        listings = await load_candidates(
            session,
            limit=limit,
            only_active=only_active,
            only_missing_coordinates=only_missing_coordinates,
            comuna=comuna,
            property_type=property_type,
        )
        stats.evaluated = len(listings)
        for listing in listings:
            _process_listing(listing, stats, apply=apply, examples_limit=examples_limit)
        if apply:
            await session.commit()
        else:
            await session.rollback()
    report = build_report(stats)
    write_report(report, output_dir=output_dir)
    return report


async def load_candidates(
    session: AsyncSession,
    *,
    limit: int | None,
    only_active: bool = False,
    only_missing_coordinates: bool = False,
    comuna: str | None = None,
    property_type: str | None = None,
) -> list[ListingORM]:
    conditions = [ListingORM.source == "yapo"]
    if only_active:
        conditions.append(ListingORM.status == "active")
    if only_missing_coordinates:
        conditions.append(or_(ListingORM.lat.is_(None), ListingORM.lon.is_(None)))
    if comuna:
        conditions.append(ListingORM.comuna == comuna)
    if property_type:
        conditions.append(ListingORM.property_type == property_type)
    stmt = select(ListingORM).where(*conditions).order_by(ListingORM.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def build_report(stats: GeoSignalBackfillStats) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "created_by_version": GEO_SIGNAL_RECOVERY_VERSION,
        "dry_run": stats.dry_run,
        "summary": {
            "listings_evaluated": stats.evaluated,
            "listings_with_metadata_changes": stats.changed,
            "new_candidates_detected": stats.new_candidates,
            "fallback_with_any_new_candidates": stats.fallback_with_any_new_candidates,
            "fallback_with_recoverable_candidates": stats.fallback_with_recoverable_candidates,
            "fallback_with_low_confidence_title_candidates": stats.fallback_with_low_confidence_title_candidates,
            "rejected_signals": stats.rejected_count,
        },
        "candidates_by_signal_type": dict(stats.by_signal_type),
        "candidates_by_source": dict(stats.by_source),
        "candidates_by_confidence": dict(stats.by_confidence),
        "candidates_by_comuna": dict(stats.by_comuna),
        "candidates_by_property_type": dict(stats.by_property_type),
        "rejected_reasons": dict(stats.rejected_reasons),
        "examples": stats.examples,
    }


def write_report(report: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "geo_signal_recovery_latest.json"
    md_path = output_dir / "geo_signal_recovery_latest.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    return json_path, md_path


def _process_listing(
    listing: ListingORM,
    stats: GeoSignalBackfillStats,
    *,
    apply: bool,
    examples_limit: int,
) -> None:
    before = dict(listing.raw_metadata or {})
    before_candidates = _candidate_keys(before)
    before_plan = build_geocoding_query_plan(listing)
    after = enrich_raw_metadata_with_geo_signals(before, title=listing.title, url=listing.url)
    after_candidates = _candidate_keys(after)
    new_keys = after_candidates - before_candidates
    new_items = [
        item
        for item in after.get("geo_signal_candidates", [])
        if isinstance(item, dict)
        and (str(item.get("signal_type") or ""), str(item.get("normalized_value") or ""), str(item.get("source") or "")) in new_keys
    ]
    if not new_items and after.get("geo_signal_rejected") == before.get("geo_signal_rejected"):
        return

    stats.changed += 1
    stats.new_candidates += len(new_items)
    if before_plan.query_source == "comuna_fallback":
        if new_items:
            stats.fallback_with_any_new_candidates += 1
        if any(_is_recoverable_for_future_geocoding(item) for item in new_items):
            stats.fallback_with_recoverable_candidates += 1
        if any(_is_low_confidence_title_candidate(item) for item in new_items):
            stats.fallback_with_low_confidence_title_candidates += 1
    for item in new_items:
        stats.by_signal_type[str(item.get("signal_type") or "unknown")] += 1
        stats.by_source[str(item.get("source") or "unknown")] += 1
        stats.by_confidence[str(item.get("confidence") or "unknown")] += 1
        stats.by_comuna[listing.comuna or "unknown"] += 1
        stats.by_property_type[listing.property_type or "unknown"] += 1
    rejected = after.get("geo_signal_rejected")
    if isinstance(rejected, list):
        before_rejected = before.get("geo_signal_rejected") if isinstance(before.get("geo_signal_rejected"), list) else []
        new_rejected = rejected[len(before_rejected):]
        stats.rejected_count += len(new_rejected)
        for item in new_rejected:
            if isinstance(item, dict):
                stats.rejected_reasons[str(item.get("reason") or "unknown")] += 1
    if len(stats.examples) < examples_limit:
        stats.examples.append(
            {
                "listing_id": listing.id,
                "title": listing.title,
                "comuna": listing.comuna,
                "property_type": listing.property_type,
                "before_query_source": before_plan.query_source,
                "new_candidates": new_items[:6],
            }
        )
    if apply:
        listing.raw_metadata = after


def _candidate_keys(metadata: dict[str, Any]) -> set[tuple[str, str, str]]:
    candidates = metadata.get("geo_signal_candidates")
    if not isinstance(candidates, list):
        return set()
    keys: set[tuple[str, str, str]] = set()
    for item in candidates:
        if isinstance(item, dict):
            keys.add((
                str(item.get("signal_type") or ""),
                str(item.get("normalized_value") or ""),
                str(item.get("source") or ""),
            ))
    return keys


def _is_recoverable_for_future_geocoding(item: dict[str, Any]) -> bool:
    return (
        str(item.get("source") or "") in SAFE_GEOCODING_SOURCES
        and str(item.get("confidence") or "") in {"medium", "high"}
        and str(item.get("signal_type") or "") in SAFE_SIGNAL_TYPES
    )


def _is_low_confidence_title_candidate(item: dict[str, Any]) -> bool:
    return (
        str(item.get("source") or "") in {"title", "url_slug"}
        and str(item.get("confidence") or "") == "low"
        and str(item.get("signal_type") or "") in SAFE_SIGNAL_TYPES | {"plaza", "parque", "mall", "barrio", "sector"}
    )


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Geo Signal Recovery",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Dry run: {report['dry_run']}",
        f"- Listings evaluated: {summary['listings_evaluated']}",
        f"- Listings with metadata changes: {summary['listings_with_metadata_changes']}",
        f"- New candidates detected: {summary['new_candidates_detected']}",
        f"- Fallback with any new candidates: {summary['fallback_with_any_new_candidates']}",
        f"- Fallback with recoverable candidates: {summary['fallback_with_recoverable_candidates']}",
        f"- Fallback with low-confidence title candidates: {summary['fallback_with_low_confidence_title_candidates']}",
        f"- Rejected signals: {summary['rejected_signals']}",
        "",
        "## Candidates By Type",
        _table(report["candidates_by_signal_type"]),
        "",
        "## Candidates By Source",
        _table(report["candidates_by_source"]),
        "",
        "## Candidates By Confidence",
        _table(report["candidates_by_confidence"]),
        "",
        "## Rejected Reasons",
        _table(report["rejected_reasons"]),
        "",
        "## Examples",
    ]
    for example in report["examples"][:20]:
        lines.append(f"- {example['listing_id']} {example['comuna']} {example['before_query_source']}: {example['title']}")
        for candidate in example["new_candidates"]:
            lines.append(
                f"  - {candidate.get('signal_type')} / {candidate.get('source')} / "
                f"{candidate.get('confidence')}: {candidate.get('value')}"
            )
    return "\n".join(lines) + "\n"


def _table(counter: dict[str, int]) -> str:
    if not counter:
        return "_No rows._"
    rows = ["| value | count |", "|---|---:|"]
    for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
        rows.append(f"| {key} | {value} |")
    return "\n".join(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover Yapo geo signals into raw_metadata only.")
    parser.add_argument("--apply", action="store_true", help="Persist raw_metadata changes. Dry-run is default.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only-active", action="store_true")
    parser.add_argument("--only-missing-coordinates", action="store_true")
    parser.add_argument("--commune", "--comuna", dest="comuna")
    parser.add_argument("--property-type", choices=["apartment", "house"])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--examples-limit", type=int, default=20)
    return parser.parse_args(argv)


async def async_main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    return await run_backfill(
        apply=args.apply,
        limit=args.limit,
        only_active=args.only_active,
        only_missing_coordinates=args.only_missing_coordinates,
        comuna=args.comuna,
        property_type=args.property_type,
        output_dir=args.output_dir,
        examples_limit=args.examples_limit,
    )


def main() -> None:
    report = asyncio.run(async_main())
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
