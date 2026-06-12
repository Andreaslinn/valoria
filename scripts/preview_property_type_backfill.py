"""Preview read-only para backfill de property_type y superficies.

No escribe en la base. Usa las mismas reglas que ingestion para sugerir cambios.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from domain.ingestion.data_cleaning import extract_area_fields, infer_property_type  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402


@dataclass(frozen=True)
class BackfillSuggestion:
    listing_id: int
    title: str
    source: str
    url: str | None
    status: str
    comuna: str
    current_property_type: str | None
    suggested_property_type: str
    reason: str
    confidence: float
    current_built_area_m2: float | None
    suggested_built_area_m2: float | None
    current_land_area_m2: float | None
    suggested_land_area_m2: float | None
    current_usable_area_m2: float | None
    suggested_usable_area_m2: float | None
    source_fields: tuple[str, ...]

    @property
    def changes_property_type(self) -> bool:
        return self.current_property_type != self.suggested_property_type

    @property
    def fills_built_area(self) -> bool:
        return self.current_built_area_m2 is None and self.suggested_built_area_m2 is not None

    @property
    def fills_land_area(self) -> bool:
        return self.current_land_area_m2 is None and self.suggested_land_area_m2 is not None

    @property
    def fills_usable_area(self) -> bool:
        return self.current_usable_area_m2 is None and self.suggested_usable_area_m2 is not None

    @property
    def has_any_change(self) -> bool:
        return (
            self.changes_property_type
            or self.fills_built_area
            or self.fills_land_area
            or self.fills_usable_area
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview property_type/area backfill.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--comuna")
    parser.add_argument("--include-inactive", action="store_true")
    parser.add_argument("--changed-only", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--examples", type=int, default=25)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    async with get_session_factory()() as session:
        stmt = select(ListingORM).order_by(ListingORM.id)
        if not args.include_inactive:
            stmt = stmt.where(ListingORM.status == "active")
        if args.comuna:
            stmt = stmt.where(ListingORM.comuna == args.comuna)
        if args.limit:
            stmt = stmt.limit(args.limit)
        listings = list((await session.execute(stmt)).scalars())

    suggestions = [build_suggestion(listing) for listing in listings]
    if args.changed_only:
        suggestions = [suggestion for suggestion in suggestions if suggestion.has_any_change]

    if args.summary_only:
        print_summary(suggestions)
    else:
        print_preview(suggestions, examples=args.examples)
    return 0


def build_suggestion(listing: ListingORM, *, overwrite: bool = False) -> BackfillSuggestion:
    raw = _raw_from_listing(listing)
    property_guess = infer_property_type(raw, title=listing.title)
    areas = extract_area_fields(raw, title=listing.title)

    suggested_property_type = property_guess.value
    suggested_built = areas.get("built_area_m2")
    suggested_land = areas.get("land_area_m2")
    suggested_usable = areas.get("usable_area_m2")

    if suggested_property_type == "house":
        suggested_built = suggested_built or _positive(listing.built_area_m2) or _positive(listing.m2)
    elif suggested_property_type == "apartment":
        suggested_usable = suggested_usable or _positive(listing.usable_area_m2) or _positive(listing.m2)
        suggested_built = suggested_built or _positive(listing.built_area_m2) or suggested_usable
        suggested_land = None

    if not overwrite:
        suggested_built = listing.built_area_m2 if listing.built_area_m2 is not None else suggested_built
        suggested_land = listing.land_area_m2 if listing.land_area_m2 is not None else suggested_land
        suggested_usable = listing.usable_area_m2 if listing.usable_area_m2 is not None else suggested_usable

    return BackfillSuggestion(
        listing_id=listing.id,
        title=listing.title,
        source=listing.source,
        url=listing.url,
        status=listing.status,
        comuna=listing.comuna,
        current_property_type=listing.property_type,
        suggested_property_type=suggested_property_type,
        reason=property_guess.reason,
        confidence=property_guess.confidence,
        current_built_area_m2=listing.built_area_m2,
        suggested_built_area_m2=suggested_built,
        current_land_area_m2=listing.land_area_m2,
        suggested_land_area_m2=suggested_land,
        current_usable_area_m2=listing.usable_area_m2,
        suggested_usable_area_m2=suggested_usable,
        source_fields=property_guess.source_fields,
    )


def _raw_from_listing(listing: ListingORM) -> dict[str, Any]:
    raw_metadata = listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}
    return {
        "source": listing.source,
        "external_id": listing.external_id,
        "property_type": raw_metadata.get("property_type"),
        "category": raw_metadata.get("category"),
        "categoria": raw_metadata.get("categoria"),
        "description": raw_metadata.get("description"),
        "descripcion": raw_metadata.get("descripcion"),
        "title": listing.title,
        "comuna": listing.comuna,
        "m2": listing.m2,
        "built_area_m2": listing.built_area_m2,
        "land_area_m2": listing.land_area_m2,
        "usable_area_m2": listing.usable_area_m2,
        "url": listing.url,
        "raw_metadata": raw_metadata,
    }


def _positive(value: float | None) -> float | None:
    return value if value is not None and value > 0 else None


def print_preview(suggestions: list[BackfillSuggestion], *, examples: int) -> None:
    print_summary(suggestions)
    changed = [suggestion for suggestion in suggestions if suggestion.has_any_change]
    print("\nexamples")
    print(
        "id\tstatus\tcomuna\tcurrent_type\tsuggested_type\treason\tconfidence\t"
        "built_current->suggested\tland_current->suggested\tusable_current->suggested\t"
        "source_fields\tsource\turl\ttitle"
    )
    for suggestion in changed[:examples]:
        print(
            f"{suggestion.listing_id}\t{suggestion.status}\t{suggestion.comuna}\t"
            f"{suggestion.current_property_type}\t{suggestion.suggested_property_type}\t"
            f"{suggestion.reason}\t{suggestion.confidence:.2f}\t"
            f"{suggestion.current_built_area_m2}->{suggestion.suggested_built_area_m2}\t"
            f"{suggestion.current_land_area_m2}->{suggestion.suggested_land_area_m2}\t"
            f"{suggestion.current_usable_area_m2}->{suggestion.suggested_usable_area_m2}\t"
            f"{','.join(suggestion.source_fields)}\t{suggestion.source}\t"
            f"{suggestion.url or ''}\t{suggestion.title[:100]}"
        )


def print_summary(suggestions: list[BackfillSuggestion]) -> None:
    current = Counter(suggestion.current_property_type or "NULL" for suggestion in suggestions)
    suggested = Counter(suggestion.suggested_property_type for suggestion in suggestions)
    pair_counts = Counter(
        (suggestion.current_property_type or "NULL", suggestion.suggested_property_type)
        for suggestion in suggestions
        if suggestion.changes_property_type
    )
    house_suggestions = [s for s in suggestions if s.suggested_property_type == "house"]
    houses_with_built = sum(1 for suggestion in house_suggestions if suggestion.suggested_built_area_m2 is not None)
    houses_with_land = sum(1 for suggestion in house_suggestions if suggestion.suggested_land_area_m2 is not None)
    print("\nsummary")
    print(f"rows_previewed\t{len(suggestions)}")
    print(f"rows_with_any_change\t{sum(suggestion.has_any_change for suggestion in suggestions)}")
    print(f"property_type_changes\t{sum(suggestion.changes_property_type for suggestion in suggestions)}")
    print(f"suggested_houses\t{len(house_suggestions)}")
    print(f"suggested_houses_with_built_area\t{houses_with_built}")
    print(f"suggested_houses_with_land_area\t{houses_with_land}")
    print(f"unknown_current\t{current.get('unknown', 0)}")
    print(f"unknown_suggested\t{suggested.get('unknown', 0)}")
    print("\ncurrent_distribution")
    for key, value in current.most_common():
        print(f"{key}\t{value}")
    print("\nsuggested_distribution")
    for key, value in suggested.most_common():
        print(f"{key}\t{value}")
    print("\nproperty_type_change_pairs")
    for (current_type, suggested_type), value in pair_counts.most_common():
        print(f"{current_type}->{suggested_type}\t{value}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
