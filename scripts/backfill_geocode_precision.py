"""Conservative backfill for legacy NULL geocode_precision values.

Safe by default: dry-run unless --apply is provided. This script never changes
lat/lon and never calls external geocoding services.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402

TARGET_PRECISION = "unknown"


@dataclass(frozen=True)
class BackfillDecision:
    should_update: bool
    target_precision: str | None
    group: str
    reason: str


def classify_candidate(
    *,
    geocode_precision: str | None,
    lat: float | None,
    lon: float | None,
    target_precision: str = TARGET_PRECISION,
) -> BackfillDecision:
    if geocode_precision is not None:
        return BackfillDecision(
            should_update=False,
            target_precision=None,
            group="already_classified",
            reason="geocode_precision_not_null",
        )
    if lat is not None and lon is not None:
        return BackfillDecision(
            should_update=True,
            target_precision=target_precision,
            group="null_precision_with_coordinates",
            reason="legacy_null_precision_with_lat_lon",
        )
    return BackfillDecision(
        should_update=True,
        target_precision=target_precision,
        group="null_precision_missing_coordinates",
        reason="legacy_null_precision_missing_lat_lon",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill NULL geocode_precision conservatively.")
    parser.add_argument("--apply", action="store_true", help="Write changes. Omit for dry-run.")
    parser.add_argument("--dry-run", action="store_true", help="Preview only. This is the default.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-inactive", action="store_true")
    parser.add_argument("--examples", type=int, default=25)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    if args.apply and args.dry_run:
        print("ERROR: --apply and --dry-run are mutually exclusive.", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit < 1:
        print("ERROR: --limit debe ser mayor a 0.", file=sys.stderr)
        return 2

    async with get_session_factory()() as session:
        try:
            stmt = select(ListingORM).where(ListingORM.geocode_precision.is_(None)).order_by(
                ListingORM.id
            )
            if not args.include_inactive:
                stmt = stmt.where(ListingORM.status == "active")
            if args.limit:
                stmt = stmt.limit(args.limit)

            listings = list((await session.execute(stmt)).scalars())
            decisions = [
                (listing, classify_candidate(
                    geocode_precision=listing.geocode_precision,
                    lat=listing.lat,
                    lon=listing.lon,
                ))
                for listing in listings
            ]
            to_update = [
                (listing, decision)
                for listing, decision in decisions
                if decision.should_update and decision.target_precision is not None
            ]

            print_summary(
                decisions,
                apply=args.apply,
                include_inactive=args.include_inactive,
                examples=args.examples,
            )

            if args.apply:
                for listing, decision in to_update:
                    listing.geocode_precision = decision.target_precision
                    session.add(listing)
                await session.commit()
                print(f"\nrows_updated\t{len(to_update)}")
            else:
                await session.rollback()
                print(f"\nrows_to_update\t{len(to_update)}")
        except SQLAlchemyError:
            await session.rollback()
            raise
    return 0


def print_summary(
    decisions: list[tuple[ListingORM, BackfillDecision]],
    *,
    apply: bool,
    include_inactive: bool,
    examples: int,
) -> None:
    mode = "apply" if apply else "dry-run"
    total = len(decisions)
    active = sum(listing.status == "active" for listing, _ in decisions)
    with_coords = sum(listing.lat is not None and listing.lon is not None for listing, _ in decisions)
    missing_coords = total - with_coords
    by_comuna = Counter(listing.comuna or "unknown" for listing, _ in decisions)
    by_group = Counter(decision.group for _, decision in decisions)

    print("== AVM geocode_precision conservative backfill ==")
    print(f"mode\t{mode}")
    print(f"target_precision\t{TARGET_PRECISION}")
    print(f"include_inactive\t{include_inactive}")
    print(f"total_candidates\t{total}")
    print(f"active_candidates\t{active}")
    print(f"with_lat_lon\t{with_coords}")
    print(f"missing_lat_lon\t{missing_coords}")
    print(f"before_null_precision\t{total}")
    print("after_null_precision_simulated\t0")

    print("\nby_group")
    for key, value in by_group.most_common():
        print(f"{key}\t{value}")

    print("\nby_comuna")
    for comuna, value in by_comuna.most_common():
        print(f"{comuna}\t{value}")

    print("\nexamples")
    print("id\tstatus\tcomuna\tlat\tlon\tcurrent_precision\ttarget_precision\treason\ttitle\turl")
    for listing, decision in decisions[:examples]:
        print(
            f"{listing.id}\t{listing.status}\t{listing.comuna}\t{listing.lat}\t{listing.lon}\t"
            f"{listing.geocode_precision}\t{decision.target_precision}\t{decision.reason}\t"
            f"{listing.title[:100]}\t{listing.url or ''}"
        )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
