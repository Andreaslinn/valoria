"""Read-only diagnostics for AVM microzone text signals."""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from domain.geocoding.geographic_microzones import build_geographic_microzone_report  # noqa: E402
from domain.geocoding.microzones import signals_from_value  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.mappers import listing_from_orm  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402
from scripts.geographic_microzone_report import (  # noqa: E402
    write_report as write_geographic_microzone_report,
)


async def main() -> int:
    args = _parse_args()
    async with get_session_factory()() as session:
        result = await session.execute(select(ListingORM).where(ListingORM.status == "active"))
        listing_rows = result.scalars().all()
        listings = [listing_from_orm(row) for row in listing_rows]

    total = len(listings)
    useful = []
    rejected = Counter()
    by_comuna: dict[str, Counter[str]] = defaultdict(Counter)
    tokens = Counter()
    metros = Counter()
    avenues = Counter()
    intersections = Counter()

    for listing in listings:
        signals = signals_from_value(listing)
        if signals.reason.startswith("rejected:"):
            rejected[signals.reason] += 1
        if signals.confidence >= args.min_confidence:
            useful.append(listing)
            for token in signals.landmark_tokens:
                tokens[token] += 1
                by_comuna[listing.comuna][token] += 1
            if signals.nearby_metro:
                metros[signals.nearby_metro] += 1
            if signals.nearby_avenue:
                avenues[signals.nearby_avenue] += 1
            if signals.intersection_hint:
                intersections[signals.intersection_hint] += 1

    print("== AVM microzone diagnostic ==")
    print(f"active_total\t{total}")
    print(f"useful_microzone\t{len(useful)}")
    print(f"useful_microzone_pct\t{_pct(len(useful), total)}")

    _print_counter("\n== top tokens ==", tokens, args.limit)
    _print_counter("\n== top metros ==", metros, args.limit)
    _print_counter("\n== top avenues ==", avenues, args.limit)
    _print_counter("\n== top intersections ==", intersections, args.limit)
    _print_counter("\n== rejected false positives ==", rejected, args.limit)

    print("\n== signals by comuna ==")
    print("comuna\ttoken\tcount")
    rows = []
    for comuna, counter in by_comuna.items():
        for token, count in counter.most_common(5):
            rows.append((comuna, token, count))
    for comuna, token, count in sorted(rows, key=lambda row: (-row[2], row[0], row[1]))[: args.limit]:
        print(f"{comuna}\t{token}\t{count}")

    geographic_report = build_geographic_microzone_report([_orm_to_dict(row) for row in listing_rows])
    geo_summary = geographic_report["summary"]
    print("\n== geographic microzones (read-only) ==")
    print(f"grid_meters\t{geo_summary['grid_meters']}")
    print(f"with_coordinates\t{geo_summary['with_coordinates']}")
    print(f"geographic_microzone_listings\t{geo_summary['geographic_microzone_listings']}")
    print(f"geographic_microzone_coverage_pct\t{geo_summary['geographic_microzone_coverage_pct']}")
    print(f"geographic_microzone_count\t{geo_summary['geographic_microzone_count']}")
    print(f"sufficient_microzone_count\t{geo_summary['sufficient_microzone_count']}")
    if args.write_geographic_report:
        md_path, json_path = write_geographic_microzone_report(geographic_report, output_dir=Path(args.output_dir))
        print(f"geographic_markdown\t{md_path}")
        print(f"geographic_json\t{json_path}")
    return 0


def _print_counter(title: str, counter: Counter[str], limit: int) -> None:
    print(title)
    print("value\tcount")
    for value, count in counter.most_common(limit):
        print(f"{value}\t{count}")


def _pct(part: int, total: int) -> float:
    return round((part / total) * 100, 2) if total else 0.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose microzone extraction coverage.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--min-confidence", type=float, default=0.55)
    parser.add_argument("--write-geographic-report", action="store_true")
    parser.add_argument("--output-dir", default="reports/geocoding")
    return parser.parse_args()


def _orm_to_dict(row: ListingORM) -> dict[str, object]:
    return {
        "id": row.id,
        "title": row.title,
        "url": row.url,
        "comuna": row.comuna,
        "property_type": row.property_type,
        "lat": row.lat,
        "lon": row.lon,
        "geocode_precision": row.geocode_precision,
        "status": row.status,
        "raw_metadata": row.raw_metadata,
    }


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
