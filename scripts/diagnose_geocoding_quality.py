"""Read-only diagnostics for listing geocoding quality.

This script does not update the database. It only reads listings and prints
quality summaries for beta readiness.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.normalization.geocode_precision import canonical_geocode_precision  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402

RiskLevel = Literal["OK", "WARNING", "CRITICAL", "SUSPECT"]

CHILE_LAT_RANGE = (-56.0, -17.0)
CHILE_LON_RANGE = (-76.0, -66.0)
RM_LAT_RANGE = (-34.4, -32.8)
RM_LON_RANGE = (-71.8, -69.8)
REPEATED_COORD_THRESHOLD = 5

PRECISION_BUCKETS = (
    "address",
    "street",
    "comuna",
    "comuna_centroid",
    "unknown",
)


@dataclass(frozen=True)
class GeoListing:
    id: int
    status: str
    comuna: str
    title: str
    url: str | None
    source: str
    geocode_precision: str | None
    lat: float | None
    lon: float | None


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    reason: str


def normalize_precision(value: str | None) -> str:
    return canonical_geocode_precision(value)


def coordinate_issue(
    lat: float | None,
    lon: float | None,
    *,
    focus_rm: bool = True,
) -> str | None:
    if lat is None or lon is None:
        return "missing_coordinates"
    if lat == 0 and lon == 0:
        return "zero_zero"
    if not (CHILE_LAT_RANGE[0] <= lat <= CHILE_LAT_RANGE[1]):
        return "outside_chile"
    if not (CHILE_LON_RANGE[0] <= lon <= CHILE_LON_RANGE[1]):
        return "outside_chile"
    if focus_rm and not (RM_LAT_RANGE[0] <= lat <= RM_LAT_RANGE[1]):
        return "outside_rm"
    if focus_rm and not (RM_LON_RANGE[0] <= lon <= RM_LON_RANGE[1]):
        return "outside_rm"
    return None


def classify_geocode_risk(
    *,
    precision: str | None,
    lat: float | None,
    lon: float | None,
    repeated_coord_count: int = 1,
    focus_rm: bool = True,
) -> RiskAssessment:
    coord_issue = coordinate_issue(lat, lon, focus_rm=focus_rm)
    if coord_issue is not None:
        return RiskAssessment("CRITICAL", coord_issue)

    normalized = normalize_precision(precision)
    if repeated_coord_count >= REPEATED_COORD_THRESHOLD and normalized == "address":
        return RiskAssessment("SUSPECT", "high_precision_repeated_coordinates")
    if repeated_coord_count >= REPEATED_COORD_THRESHOLD and normalized == "unknown":
        return RiskAssessment("SUSPECT", "unknown_precision_repeated_coordinates")
    if normalized in {"unknown", "comuna", "comuna_centroid"}:
        return RiskAssessment("WARNING", f"low_precision_{normalized}")
    return RiskAssessment("OK", "usable_geocoding_signal")


def pct(part: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round((part / total) * 100, 2)


def build_report(listings: list[GeoListing], *, focus_rm: bool = True) -> dict:
    active = [listing for listing in listings if listing.status == "active"]
    repeated_active = _coord_counts(active)
    assessments = {
        listing.id: classify_geocode_risk(
            precision=listing.geocode_precision,
            lat=listing.lat,
            lon=listing.lon,
            repeated_coord_count=repeated_active.get(_coord_key(listing), 1),
            focus_rm=focus_rm,
        )
        for listing in active
    }
    return {
        "summary": _summary(listings, active, assessments),
        "precision_total": _precision_counts(listings),
        "precision_active": _precision_counts(active),
        "comuna_precision_active": _comuna_precision_counts(active),
        "top_comunas_missing_precision": _top_comunas_missing_precision(active),
        "repeated_coordinates": _repeated_coordinates(active),
        "risk_counts": Counter(assessment.level for assessment in assessments.values()),
        "risk_reasons": Counter(assessment.reason for assessment in assessments.values()),
        "problem_examples": _problem_examples(active, assessments),
    }


def print_report(report: dict) -> None:
    summary = report["summary"]
    print("== AVM geocoding quality diagnostic ==")
    for key, value in summary.items():
        print(f"{key}\t{value}")

    _print_counter("\n== geocode_precision total ==", report["precision_total"])
    _print_counter("\n== geocode_precision active ==", report["precision_active"])
    _print_counter("\n== risk counts active ==", report["risk_counts"])
    _print_counter("\n== risk reasons active ==", report["risk_reasons"])

    print("\n== active by comuna + geocode_precision ==")
    print("comuna\tgeocode_precision\tcount")
    for (comuna, precision), count in sorted(report["comuna_precision_active"].items()):
        print(f"{comuna}\t{precision}\t{count}")

    print("\n== top comunas missing geocode_precision ==")
    print("comuna\tmissing_precision\tactive\tpct")
    for comuna, missing, active, percentage in report["top_comunas_missing_precision"]:
        print(f"{comuna}\t{missing}\t{active}\t{percentage}")

    print("\n== repeated coordinates active (n >= 5) ==")
    print("lat\tlon\tcount\tcomunas\tprecisions")
    for lat, lon, count, comunas, precisions in report["repeated_coordinates"][:20]:
        print(f"{lat}\t{lon}\t{count}\t{comunas}\t{precisions}")

    print("\n== problematic examples ==")
    print("id\tstatus\tcomuna\tprecision\tlat\tlon\trisk\treason\tsource\ttitle\turl")
    for listing, assessment in report["problem_examples"]:
        print(
            f"{listing.id}\t{listing.status}\t{listing.comuna}\t"
            f"{normalize_precision(listing.geocode_precision)}\t{listing.lat}\t{listing.lon}\t"
            f"{assessment.level}\t{assessment.reason}\t{listing.source}\t"
            f"{listing.title[:100]}\t{listing.url or ''}"
        )

    print("\n== recommendations ==")
    print("- Do not assume address precision when geocode_precision is unknown/null.")
    print("- Safe backfill done/possible: mark null precision as unknown, not address.")
    print("- Prioritize re-geocoding active listings with null/unknown precision and repeated coordinates.")
    print("- Consider penalizing unknown geocode_precision in distance scoring in a later block.")


def _summary(
    listings: list[GeoListing],
    active: list[GeoListing],
    assessments: dict[int, RiskAssessment],
) -> dict[str, int | float]:
    active_total = len(active)
    active_missing_precision = sum(normalize_precision(row.geocode_precision) == "unknown" for row in active)
    active_missing_coordinates = sum(row.lat is None or row.lon is None for row in active)
    active_coords_precision_null = sum(
        row.lat is not None
        and row.lon is not None
        and normalize_precision(row.geocode_precision) == "unknown"
        for row in active
    )
    outside_chile = sum(assessment.reason == "outside_chile" for assessment in assessments.values())
    outside_rm = sum(assessment.reason == "outside_rm" for assessment in assessments.values())
    zero_zero = sum(assessment.reason == "zero_zero" for assessment in assessments.values())
    return {
        "total_listings": len(listings),
        "active_listings": active_total,
        "active_missing_geocode_precision": active_missing_precision,
        "active_missing_geocode_precision_pct": pct(active_missing_precision, active_total),
        "active_missing_lat_lon": active_missing_coordinates,
        "active_missing_lat_lon_pct": pct(active_missing_coordinates, active_total),
        "active_lat_lon_precision_null": active_coords_precision_null,
        "active_outside_chile": outside_chile,
        "active_outside_rm": outside_rm,
        "active_zero_zero": zero_zero,
    }


def _precision_counts(listings: list[GeoListing]) -> Counter[str]:
    counts: Counter[str] = Counter(dict.fromkeys(PRECISION_BUCKETS, 0))
    for listing in listings:
        counts[normalize_precision(listing.geocode_precision)] += 1
    return Counter({key: value for key, value in counts.items() if value > 0})


def _comuna_precision_counts(listings: list[GeoListing]) -> Counter[tuple[str, str]]:
    return Counter(
        (listing.comuna or "unknown", normalize_precision(listing.geocode_precision))
        for listing in listings
    )


def _top_comunas_missing_precision(listings: list[GeoListing]) -> list[tuple[str, int, int, float]]:
    active_by_comuna: dict[str, list[GeoListing]] = defaultdict(list)
    for listing in listings:
        active_by_comuna[listing.comuna or "unknown"].append(listing)
    rows = []
    for comuna, rows_for_comuna in active_by_comuna.items():
        missing = sum(normalize_precision(row.geocode_precision) == "unknown" for row in rows_for_comuna)
        if missing:
            rows.append((comuna, missing, len(rows_for_comuna), pct(missing, len(rows_for_comuna))))
    return sorted(rows, key=lambda row: (-row[1], row[0]))[:15]


def _coord_key(listing: GeoListing) -> tuple[float, float] | None:
    if listing.lat is None or listing.lon is None:
        return None
    return (round(listing.lat, 7), round(listing.lon, 7))


def _coord_counts(listings: list[GeoListing]) -> Counter[tuple[float, float] | None]:
    return Counter(_coord_key(listing) for listing in listings if _coord_key(listing) is not None)


def _repeated_coordinates(listings: list[GeoListing]) -> list[tuple[float, float, int, str, str]]:
    groups: dict[tuple[float, float], list[GeoListing]] = defaultdict(list)
    for listing in listings:
        key = _coord_key(listing)
        if key is not None:
            groups[key].append(listing)
    rows = []
    for (lat, lon), grouped in groups.items():
        if len(grouped) < REPEATED_COORD_THRESHOLD:
            continue
        comunas = ",".join(sorted({row.comuna for row in grouped}))
        precisions = ",".join(sorted({normalize_precision(row.geocode_precision) for row in grouped}))
        rows.append((lat, lon, len(grouped), comunas, precisions))
    return sorted(rows, key=lambda row: (-row[2], row[0], row[1]))


def _problem_examples(
    active: list[GeoListing],
    assessments: dict[int, RiskAssessment],
    *,
    limit: int = 25,
) -> list[tuple[GeoListing, RiskAssessment]]:
    priority = {"CRITICAL": 0, "SUSPECT": 1, "WARNING": 2, "OK": 3}
    rows = [
        (listing, assessments[listing.id])
        for listing in active
        if assessments[listing.id].level != "OK"
    ]
    rows.sort(key=lambda item: (priority[item[1].level], item[0].comuna, item[0].id))
    return rows[:limit]


def _print_counter(title: str, counter: Counter) -> None:
    print(title)
    print("key\tcount")
    for key, value in counter.most_common():
        print(f"{key}\t{value}")


async def load_listings() -> list[GeoListing]:
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(
                    ListingORM.id,
                    ListingORM.status,
                    ListingORM.comuna,
                    ListingORM.title,
                    ListingORM.url,
                    ListingORM.source,
                    ListingORM.geocode_precision,
                    ListingORM.lat,
                    ListingORM.lon,
                ).order_by(ListingORM.id)
            )
        ).all()
    return [
        GeoListing(
            id=row.id,
            status=row.status,
            comuna=row.comuna,
            title=row.title,
            url=row.url,
            source=row.source,
            geocode_precision=row.geocode_precision,
            lat=row.lat,
            lon=row.lon,
        )
        for row in rows
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only geocoding quality diagnostics.")
    parser.add_argument(
        "--no-rm-focus",
        action="store_true",
        help="Do not flag coordinates outside the Santiago/RM bounding box.",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    listings = await load_listings()
    report = build_report(listings, focus_rm=not args.no_rm_focus)
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
