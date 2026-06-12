"""Internal AVM data sufficiency diagnostic.

Read-only report for understanding where the AVM has enough active, usable data
and where it should be treated as low confidence.

Usage:
    python scripts/data_sufficiency_report.py --output-dir reports/data_sufficiency
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constants import MIN_COMPARABLES  # noqa: E402
from core.entities.listing import Listing, Property  # noqa: E402
from core.normalization.geocode_precision import normalize_geocode_precision  # noqa: E402
from core.normalization.property_type import normalize_property_type as _property_type  # noqa: E402
from domain.valuation.comparables import candidate_discard_reason  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("reports/data_sufficiency")
LOW_DATA_MODE_THRESHOLD = 8
KNOWN_PROPERTY_TYPES = {"apartment", "house", "office", "land"}


@dataclass(frozen=True)
class ComunaSufficiencyRow:
    comuna: str
    active_listings: int
    avm_useful_listings: int
    valid_m2_listings: int
    valid_price_listings: int
    known_property_type_listings: int
    low_data_mode: bool
    data_sufficient: bool


@dataclass(frozen=True)
class ComunaPropertyTypeSufficiencyRow:
    comuna: str
    property_type: str
    active_listings: int
    avm_useful_listings: int
    valid_m2_listings: int
    valid_price_listings: int
    low_data_mode: bool
    data_sufficient: bool


@dataclass(frozen=True)
class ReportArtifacts:
    csv_path: Path
    markdown_path: Path
    json_path: Path


def build_report(listings: Sequence[Listing]) -> dict[str, Any]:
    active = [listing for listing in listings if listing.is_active]
    comuna_rows = _comuna_rows(active)
    comuna_property_type_rows = _comuna_property_type_rows(active)
    discard_reasons = _top_discard_reasons(active)
    return {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(),
            "active_total": len(active),
            "avm_useful_total": sum(row.avm_useful_listings for row in comuna_rows),
            "valid_m2_total": sum(_has_valid_m2(listing) for listing in active),
            "valid_price_total": sum(_has_valid_price(listing) for listing in active),
            "low_data_comunas": sum(row.low_data_mode for row in comuna_rows),
            "sufficient_data_comunas": sum(row.data_sufficient for row in comuna_rows),
            "low_data_property_type_segments": sum(row.low_data_mode for row in comuna_property_type_rows),
            "sufficient_data_property_type_segments": sum(row.data_sufficient for row in comuna_property_type_rows),
            "min_comparables": MIN_COMPARABLES,
            "low_data_mode_threshold": LOW_DATA_MODE_THRESHOLD,
        },
        "by_comuna": [asdict(row) for row in comuna_rows],
        "by_comuna_property_type": [asdict(row) for row in comuna_property_type_rows],
        "by_property_type": dict(Counter(_property_type(listing.property_type) for listing in active)),
        "geocode_precision": dict(_geocode_precision_counts(active)),
        "top_discard_reasons": dict(discard_reasons),
    }


def write_report(report: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> ReportArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"data_sufficiency_{stamp}.csv"
    markdown_path = output_dir / f"data_sufficiency_{stamp}.md"
    json_path = output_dir / f"data_sufficiency_{stamp}.json"
    _write_csv(report["by_comuna"], csv_path)
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return ReportArtifacts(csv_path=csv_path, markdown_path=markdown_path, json_path=json_path)


def print_console_report(report: dict[str, Any], artifacts: ReportArtifacts | None = None) -> None:
    summary = report["summary"]
    print("== AVM data sufficiency ==")
    print(f"active_total\t{summary['active_total']}")
    print(f"avm_useful_total\t{summary['avm_useful_total']}")
    print(f"valid_m2_total\t{summary['valid_m2_total']}")
    print(f"valid_price_total\t{summary['valid_price_total']}")
    print(f"low_data_comunas\t{summary['low_data_comunas']}")
    print(f"sufficient_data_comunas\t{summary['sufficient_data_comunas']}")

    print("\n== Property types ==")
    for property_type, count in sorted(report["by_property_type"].items()):
        print(f"{property_type}\t{count}")

    print("\n== Geocode precision ==")
    for precision, count in sorted(report["geocode_precision"].items()):
        print(f"{precision}\t{count}")

    print("\n== Comunas ==")
    print("comuna\tactive\tuseful\tlow_data_mode\tdata_sufficient")
    for row in report["by_comuna"]:
        print(
            f"{row['comuna']}\t{row['active_listings']}\t{row['avm_useful_listings']}\t"
            f"{row['low_data_mode']}\t{row['data_sufficient']}"
        )

    print("\n== Comunas by property_type ==")
    print("comuna\tproperty_type\tactive\tuseful\tlow_data_mode\tdata_sufficient")
    for row in report["by_comuna_property_type"]:
        print(
            f"{row['comuna']}\t{row['property_type']}\t{row['active_listings']}\t"
            f"{row['avm_useful_listings']}\t{row['low_data_mode']}\t{row['data_sufficient']}"
        )

    print("\n== Top discard reasons ==")
    for reason, count in report["top_discard_reasons"].items():
        print(f"{reason}\t{count}")

    if artifacts is not None:
        print("\n== Files ==")
        print(f"csv\t{artifacts.csv_path}")
        print(f"markdown\t{artifacts.markdown_path}")
        print(f"json\t{artifacts.json_path}")


def _comuna_rows(active: Sequence[Listing]) -> list[ComunaSufficiencyRow]:
    by_comuna: dict[str, list[Listing]] = defaultdict(list)
    for listing in active:
        by_comuna[listing.comuna or "unknown"].append(listing)
    rows = []
    for comuna, listings in sorted(by_comuna.items()):
        useful = [listing for listing in listings if _is_avm_useful(listing)]
        rows.append(
            ComunaSufficiencyRow(
                comuna=comuna,
                active_listings=len(listings),
                avm_useful_listings=len(useful),
                valid_m2_listings=sum(_has_valid_m2(listing) for listing in listings),
                valid_price_listings=sum(_has_valid_price(listing) for listing in listings),
                known_property_type_listings=sum(_property_type(listing.property_type) in KNOWN_PROPERTY_TYPES for listing in listings),
                low_data_mode=len(useful) < LOW_DATA_MODE_THRESHOLD,
                data_sufficient=len(useful) >= MIN_COMPARABLES,
            )
        )
    return rows


def _comuna_property_type_rows(active: Sequence[Listing]) -> list[ComunaPropertyTypeSufficiencyRow]:
    by_segment: dict[tuple[str, str], list[Listing]] = defaultdict(list)
    for listing in active:
        by_segment[(listing.comuna or "unknown", _property_type(listing.property_type))].append(listing)
    rows = []
    for (comuna, property_type), listings in sorted(by_segment.items()):
        useful = [listing for listing in listings if _is_avm_useful(listing)]
        rows.append(
            ComunaPropertyTypeSufficiencyRow(
                comuna=comuna,
                property_type=property_type,
                active_listings=len(listings),
                avm_useful_listings=len(useful),
                valid_m2_listings=sum(_has_valid_m2(listing) for listing in listings),
                valid_price_listings=sum(_has_valid_price(listing) for listing in listings),
                low_data_mode=len(useful) < LOW_DATA_MODE_THRESHOLD,
                data_sufficient=len(useful) >= MIN_COMPARABLES,
            )
        )
    return rows


def _top_discard_reasons(active: Sequence[Listing]) -> Counter[str]:
    targets = [listing for listing in active if _has_valid_m2(listing) and _has_valid_price(listing)]
    reasons: Counter[str] = Counter()
    for target_listing in targets:
        target = _target_from_listing(target_listing)
        for candidate in active:
            if _same_listing(target_listing, candidate):
                continue
            reason = candidate_discard_reason(target, candidate)
            if reason is not None:
                reasons[reason] += 1
    return Counter(dict(reasons.most_common(12)))


def _target_from_listing(listing: Listing) -> Property:
    built_area = _built_area(listing) or 0
    return Property(
        id=listing.property_id,
        comuna=listing.comuna,
        m2=built_area,
        bedrooms=listing.bedrooms,
        bathrooms=listing.bathrooms,
        parking=listing.parking,
        property_type=_property_type(listing.property_type),
        built_area_m2=built_area,
        land_area_m2=listing.land_area_m2,
        usable_area_m2=listing.usable_area_m2,
        coordinates=listing.coordinates,
    )


def _same_listing(left: Listing, right: Listing) -> bool:
    if left.id is not None and left.id == right.id:
        return True
    if left.fingerprint and left.fingerprint == right.fingerprint:
        return True
    return bool(left.source and left.external_id and left.source == right.source and left.external_id == right.external_id)


def _geocode_precision_counts(active: Iterable[Listing]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for listing in active:
        counts[
            normalize_geocode_precision(
                listing.geocode_precision,
                has_coords=listing.coordinates is not None,
                raw_metadata=listing.raw_metadata,
                comuna=listing.comuna,
            )
        ] += 1
    return counts


def _is_avm_useful(listing: Listing) -> bool:
    return _has_valid_m2(listing) and _has_valid_price(listing) and _property_type(listing.property_type) in KNOWN_PROPERTY_TYPES


def _has_valid_m2(listing: Listing) -> bool:
    area = _built_area(listing)
    return area is not None and area > 0


def _has_valid_price(listing: Listing) -> bool:
    return listing.price.clp > 0


def _built_area(listing: Listing) -> float | None:
    return listing.built_area_m2 or listing.usable_area_m2 or listing.m2


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [field.name for field in ComunaSufficiencyRow.__dataclass_fields__.values()]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# AVM Data Sufficiency Report",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Active listings: {summary['active_total']}",
        f"- AVM useful listings: {summary['avm_useful_total']}",
        f"- Listings with valid m2: {summary['valid_m2_total']}",
        f"- Listings with valid price: {summary['valid_price_total']}",
        f"- LOW_DATA_MODE comunas: {summary['low_data_comunas']}",
        f"- Sufficient data comunas: {summary['sufficient_data_comunas']}",
        f"- MIN_COMPARABLES: {summary['min_comparables']}",
        f"- LOW_DATA_MODE threshold: {summary['low_data_mode_threshold']}",
        "",
        "## Listings by property_type",
        "",
        _simple_table("property_type", report["by_property_type"]),
        "",
        "## Geocode precision",
        "",
        _simple_table("geocode_precision", report["geocode_precision"]),
        "",
        "## Comunas",
        "",
        _comuna_table(report["by_comuna"]),
        "",
        "## Comunas by property_type",
        "",
        _comuna_property_type_table(report["by_comuna_property_type"]),
        "",
        "## Top discard reasons",
        "",
        _simple_table("reason", report["top_discard_reasons"]),
    ]
    return "\n".join(lines) + "\n"


def _simple_table(label: str, values: dict[str, int]) -> str:
    if not values:
        return "_No data._"
    lines = [f"| {label} | count |", "|---|---:|"]
    for key, count in sorted(values.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {key} | {count} |")
    return "\n".join(lines)


def _comuna_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No active listings._"
    lines = [
        "| Comuna | Active | Useful AVM | Valid m2 | Valid price | LOW_DATA_MODE | Sufficient |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['comuna']} | {row['active_listings']} | {row['avm_useful_listings']} | "
            f"{row['valid_m2_listings']} | {row['valid_price_listings']} | "
            f"{row['low_data_mode']} | {row['data_sufficient']} |"
        )
    return "\n".join(lines)


def _comuna_property_type_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No active listings._"
    lines = [
        "| Comuna | Property type | Active | Useful AVM | Valid m2 | Valid price | LOW_DATA_MODE | Sufficient |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['comuna']} | {row['property_type']} | {row['active_listings']} | "
            f"{row['avm_useful_listings']} | {row['valid_m2_listings']} | {row['valid_price_listings']} | "
            f"{row['low_data_mode']} | {row['data_sufficient']} |"
        )
    return "\n".join(lines)


async def _load_active_listings() -> list[Listing]:
    async with get_session_factory()() as session:
        repo = SqlAlchemyListingRepository(session)
        return list(await repo.list_active(limit=None))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate AVM data sufficiency diagnostics.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for CSV/Markdown/JSON outputs.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    listings = await _load_active_listings()
    report = build_report(listings)
    artifacts = write_report(report, output_dir=Path(args.output_dir))
    print_console_report(report, artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
