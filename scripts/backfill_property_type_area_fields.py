"""Backfill controlado de property_type y superficies.

Dry-run por defecto. Requiere --apply para escribir.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
for path in (PROJECT_ROOT, SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from preview_property_type_backfill import BackfillSuggestion, build_suggestion  # noqa: E402

from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill property_type and area fields.")
    parser.add_argument("--apply", action="store_true", help="Write changes. Omit for dry-run.")
    parser.add_argument("--dry-run", action="store_true", help="Preview only. This is the default.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing area fields.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--comuna")
    parser.add_argument("--include-inactive", action="store_true")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    if args.apply and args.dry_run:
        raise SystemExit("--apply and --dry-run are mutually exclusive")
    async with get_session_factory()() as session:
        stmt = select(ListingORM).order_by(ListingORM.id)
        if not args.include_inactive:
            stmt = stmt.where(ListingORM.status == "active")
        if args.comuna:
            stmt = stmt.where(ListingORM.comuna == args.comuna)
        if args.limit:
            stmt = stmt.limit(args.limit)
        try:
            listings = list((await session.execute(stmt)).scalars())

            before = Counter(listing.property_type or "NULL" for listing in listings)
            after = Counter(before)
            updates = []
            for listing in listings:
                current_type = listing.property_type or "NULL"
                suggestion = build_suggestion(listing, overwrite=args.overwrite)
                changed_fields = apply_suggestion(
                    listing,
                    suggestion,
                    apply=args.apply,
                    overwrite=args.overwrite,
                )
                if changed_fields:
                    updates.append((listing.id, changed_fields, suggestion))
                    next_type = (
                        suggestion.suggested_property_type
                        if "property_type" in changed_fields
                        else current_type
                    )
                    after[current_type] -= 1
                    after[next_type] += 1

            print_summary(before, after, updates, total_reviewed=len(listings), apply=args.apply)

            if args.apply:
                await session.commit()
            else:
                await session.rollback()
        except Exception:
            await session.rollback()
            raise
    return 0


def apply_suggestion(
    listing: ListingORM,
    suggestion,
    *,
    apply: bool,
    overwrite: bool,
) -> list[str]:
    changed: list[str] = []
    if _should_update_property_type(listing, suggestion):
        changed.append("property_type")
        if apply:
            listing.property_type = suggestion.suggested_property_type
    if _should_update(listing.built_area_m2, suggestion.suggested_built_area_m2, overwrite=overwrite):
        changed.append("built_area_m2")
        if apply:
            listing.built_area_m2 = suggestion.suggested_built_area_m2
    if _should_update(listing.land_area_m2, suggestion.suggested_land_area_m2, overwrite=overwrite):
        changed.append("land_area_m2")
        if apply:
            listing.land_area_m2 = suggestion.suggested_land_area_m2
    if _should_update(listing.usable_area_m2, suggestion.suggested_usable_area_m2, overwrite=overwrite):
        changed.append("usable_area_m2")
        if apply:
            listing.usable_area_m2 = suggestion.suggested_usable_area_m2
    return changed


def _should_update(current: float | None, suggested: float | None, *, overwrite: bool) -> bool:
    if suggested is None:
        return False
    if current is None:
        return True
    return overwrite and current != suggested


def _should_update_property_type(listing: ListingORM, suggestion: BackfillSuggestion) -> bool:
    if listing.property_type == suggestion.suggested_property_type:
        return False
    if suggestion.suggested_property_type == "unknown":
        return False
    if suggestion.confidence < 0.88:
        return False
    return not _has_manual_property_type_signal(listing)


def _has_manual_property_type_signal(listing: ListingORM) -> bool:
    metadata = listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}
    return bool(
        metadata.get("property_type_manually_curated")
        or metadata.get("manual_property_type")
        or metadata.get("curated_property_type")
        or metadata.get("property_type_source") == "manual"
    )


def print_summary(
    before: Counter,
    after: Counter,
    updates: list,
    *,
    total_reviewed: int,
    apply: bool,
) -> None:
    mode = "apply" if apply else "dry-run"
    house_land_area_updates = [
        (listing_id, fields, suggestion)
        for listing_id, fields, suggestion in updates
        if "land_area_m2" in fields and suggestion.suggested_property_type == "house"
    ]
    print(f"mode\t{mode}")
    print(f"total_reviewed\t{total_reviewed}")
    print("before")
    for key, value in before.most_common():
        print(f"{key}\t{value}")
    print("after")
    for key, value in after.most_common():
        print(f"{key}\t{value}")
    print("updates")
    print(f"rows_with_changes\t{len(updates)}")
    print(f"property_type_changes\t{sum('property_type' in fields for _, fields, _ in updates)}")
    print(f"built_area_fills\t{sum('built_area_m2' in fields for _, fields, _ in updates)}")
    print(f"land_area_fills\t{sum('land_area_m2' in fields for _, fields, _ in updates)}")
    print(f"house_land_area_fills\t{len(house_land_area_updates)}")
    print(f"usable_area_fills\t{sum('usable_area_m2' in fields for _, fields, _ in updates)}")
    print(f"unknown_before\t{before.get('unknown', 0)}")
    print(f"unknown_after\t{after.get('unknown', 0)}")
    print("updates_by_property_type")
    for property_type, count in _updates_by_property_type(updates).most_common():
        print(f"{property_type}\t{count}")
    print("updates_by_comuna")
    for comuna, count in _updates_by_comuna(updates).most_common(30):
        print(f"{comuna}\t{count}")
    print("house_land_area_examples")
    for listing_id, fields, suggestion in house_land_area_updates[:25]:
        print(
            f"{listing_id}\t{','.join(fields)}\t{suggestion.comuna}\t"
            f"{suggestion.current_land_area_m2}->{suggestion.suggested_land_area_m2}\t"
            f"{suggestion.title[:100]}"
        )
    for listing_id, fields, suggestion in updates[:50]:
        print(
            f"{listing_id}\t{','.join(fields)}\t{suggestion.current_property_type}"
            f"->{suggestion.suggested_property_type}\t{suggestion.reason}\t{suggestion.title[:100]}"
        )


def _updates_by_property_type(updates: list) -> Counter:
    return Counter(suggestion.suggested_property_type for _, _, suggestion in updates)


def _updates_by_comuna(updates: list) -> Counter:
    return Counter(suggestion.comuna for _, _, suggestion in updates)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
