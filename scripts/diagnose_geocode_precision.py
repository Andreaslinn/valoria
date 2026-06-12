"""Read-only geocode precision honesty diagnostic.

Reports:
  - missing coordinates
  - coordinates by property_type
  - false address labels
  - repeated coordinate clusters likely to be centroid/fallback artifacts
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from domain.geocoding.quality import (  # noqa: E402
    REPEATED_COORDINATE_THRESHOLD,
    apply_geocoding_guardrails,
    has_valid_coordinates,
    normalized_precision_for,
)
from core.normalization.geocode_precision import canonical_geocode_precision  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.mappers import listing_from_orm  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402


@dataclass(frozen=True)
class ClusterRow:
    comuna: str
    lat: float
    lon: float
    total: int
    property_types: str
    original_precisions: str


async def main() -> int:
    args = _parse_args()
    async with get_session_factory()() as session:
        rows = (await session.execute(select(ListingORM).where(ListingORM.status == "active"))).scalars().all()
    original = [listing_from_orm(row) for row in rows]
    original_precision = {id(listing): listing.geocode_precision for listing in original}
    guarded = apply_geocoding_guardrails(original, repeated_threshold=args.cluster_threshold)

    print("== AVM geocode precision honesty diagnostic ==")
    _print_summary(guarded)
    _print_by_property_type(guarded)
    _print_false_address(rows, limit=args.examples)
    _print_repeated_clusters(rows, threshold=args.cluster_threshold, limit=args.examples)
    _print_degradations(guarded, original_precision, limit=args.examples)
    return 0


def _print_summary(listings) -> None:
    total = len(listings)
    with_coords = sum(has_valid_coordinates(listing) for listing in listings)
    missing_coords = total - with_coords
    precision_counts = Counter(normalized_precision_for(listing) for listing in listings)
    print(f"active_total\t{total}")
    print(f"with_coords\t{with_coords}")
    print(f"missing_coords\t{missing_coords}")
    print(f"missing_coords_pct\t{_pct(missing_coords, total)}")
    print("\nprecision_after_guardrails")
    for precision, count in precision_counts.most_common():
        print(f"{precision}\t{count}")


def _print_by_property_type(listings) -> None:
    grouped: dict[str, list] = defaultdict(list)
    for listing in listings:
        grouped[listing.property_type or "unknown"].append(listing)
    print("\nby_property_type")
    print("property_type\tactive\twith_coords\tmissing_coords\tmissing_coords_pct\tpoor_geocoding")
    for property_type, rows in sorted(grouped.items()):
        with_coords = sum(has_valid_coordinates(row) for row in rows)
        missing = len(rows) - with_coords
        poor = sum(normalized_precision_for(row) in {"unknown", "comuna", "comuna_centroid"} or not has_valid_coordinates(row) for row in rows)
        print(f"{property_type}\t{len(rows)}\t{with_coords}\t{missing}\t{_pct(missing, len(rows))}\t{poor}")


def _print_false_address(rows, *, limit: int) -> None:
    false_rows = [
        row for row in rows
        if canonical_geocode_precision(row.geocode_precision) == "address" and (row.lat is None or row.lon is None)
    ]
    print("\nfalse_address_labels")
    print(f"total\t{len(false_rows)}")
    print("id\tproperty_type\tcomuna\treason\taddress_label\ttitle")
    for row in false_rows[:limit]:
        metadata = row.raw_metadata or {}
        print(
            f"{row.id}\t{row.property_type}\t{row.comuna}\t"
            f"{metadata.get('geocode_precision_reason') or ''}\t"
            f"{metadata.get('address_label') or ''}\t{_trim(row.title)}"
        )


def _print_repeated_clusters(rows, *, threshold: int, limit: int) -> None:
    clusters: dict[tuple[str, float, float], list[ListingORM]] = defaultdict(list)
    for row in rows:
        if row.lat is None or row.lon is None:
            continue
        clusters[(row.comuna or "unknown", round(float(row.lat), 7), round(float(row.lon), 7))].append(row)
    cluster_rows: list[ClusterRow] = []
    for (comuna, lat, lon), grouped in clusters.items():
        if len(grouped) < threshold:
            continue
        cluster_rows.append(
            ClusterRow(
                comuna=comuna,
                lat=lat,
                lon=lon,
                total=len(grouped),
                property_types=",".join(sorted({row.property_type or "unknown" for row in grouped})),
                original_precisions=",".join(sorted({canonical_geocode_precision(row.geocode_precision) for row in grouped})),
            )
        )
    cluster_rows.sort(key=lambda row: (-row.total, row.comuna, row.lat, row.lon))
    print("\nrepeated_coordinate_clusters")
    print("comuna\tlat\tlon\ttotal\tproperty_types\toriginal_precisions")
    for row in cluster_rows[:limit]:
        print(f"{row.comuna}\t{row.lat}\t{row.lon}\t{row.total}\t{row.property_types}\t{row.original_precisions}")


def _print_degradations(listings, original_precision: dict[int, str | None], *, limit: int) -> None:
    changed = [
        listing for listing in listings
        if original_precision.get(id(listing)) != listing.geocode_precision
    ]
    print("\nprecision_degradations_after_guardrails")
    print(f"total\t{len(changed)}")
    print("id\tproperty_type\tcomuna\tbefore\tafter\ttitle")
    for listing in changed[:limit]:
        print(
            f"{listing.id}\t{listing.property_type}\t{listing.comuna}\t"
            f"{canonical_geocode_precision(original_precision.get(id(listing)))}\t{listing.geocode_precision}\t{_trim(listing.title)}"
        )


def _pct(part: int, total: int) -> float:
    return round((part / total) * 100, 2) if total else 0.0


def _trim(value: str, *, max_len: int = 96) -> str:
    value = " ".join(str(value or "").split())
    return value if len(value) <= max_len else value[: max_len - 3] + "..."


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit geocode precision honesty.")
    parser.add_argument("--cluster-threshold", type=int, default=REPEATED_COORDINATE_THRESHOLD)
    parser.add_argument("--examples", type=int, default=20)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
