"""Read-only report for coordinate-based geographic microzones."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from domain.geocoding.geographic_microzones import (  # noqa: E402
    DEFAULT_GRID_METERS,
    MIN_COMPARABLES_PER_GEO_MICROZONE,
    build_geographic_microzone_report,
)
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("reports/geocoding")


async def load_listings() -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        result = await session.execute(select(ListingORM))
        return [_orm_to_dict(row) for row in result.scalars().all()]


def write_report(report: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        **report,
    }
    json_path = output_dir / "geographic_microzones_latest.json"
    md_path = output_dir / "geographic_microzones_latest.md"
    json_text = json.dumps(_json_safe(payload), ensure_ascii=False, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(_markdown_report(payload), encoding="utf-8")
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    (output_dir / f"geographic_microzones_{stamp}.json").write_text(json_text, encoding="utf-8")
    return md_path, json_path


def print_console_report(report: dict[str, Any], *, md_path: Path | None = None, json_path: Path | None = None) -> None:
    summary = report["summary"]
    print("== AVM Geographic Microzones ==")
    for key, value in summary.items():
        print(f"{key}\t{value}")
    print("\n== Exclusion reasons ==")
    for row in report["reason_counts"]:
        print(f"{row['value']}\t{row['count']}\t{row['pct']}%")
    print("\n== Query sources ==")
    for row in report["query_source_counts"]:
        print(f"{row['value']}\t{row['count']}\t{row['pct']}%")
    if md_path and json_path:
        print("\n== Files ==")
        print(f"markdown\t{md_path}")
        print(f"json\t{json_path}")


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# AVM Geographic Microzones",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Active listings: {summary['active_listings']}",
        f"- Listings with coordinates: {summary['with_coordinates']}",
        f"- Geographic microzone listings: {summary['geographic_microzone_listings']} ({summary['geographic_microzone_coverage_pct']}%)",
        f"- Geographic microzones: {summary['geographic_microzone_count']}",
        f"- Sufficient microzones: {summary['sufficient_microzone_count']}",
        f"- Grid meters: {summary['grid_meters']}",
        f"- Min comparables: {summary['min_comparables']}",
        "",
        "## Exclusion Reasons",
        "",
        _markdown_table(report["reason_counts"]),
        "",
        "## Query Sources",
        "",
        _markdown_table(report["query_source_counts"]),
        "",
        "## Query Confidence",
        "",
        _markdown_table(report["query_confidence_counts"]),
        "",
        "## Coverage By Comuna",
        "",
        _markdown_table(report["by_comuna"][:40]),
        "",
        "## Microzones",
        "",
        _markdown_table(report["microzones"][:40]),
        "",
        "## Examples",
        "",
        _markdown_table(report["examples"]),
        "",
        "## Excluded Examples",
        "",
        _markdown_table(report["excluded_examples"]),
    ]
    return "\n".join(lines) + "\n"


def _markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No data._"
    columns = list(rows[0])
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _orm_to_dict(row: ListingORM) -> dict[str, Any]:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate read-only geographic microzone coverage report.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--grid-meters", type=int, default=DEFAULT_GRID_METERS)
    parser.add_argument("--min-comparables", type=int, default=MIN_COMPARABLES_PER_GEO_MICROZONE)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    listings = await load_listings()
    report = build_geographic_microzone_report(
        listings,
        grid_meters=args.grid_meters,
        min_comparables=args.min_comparables,
    )
    md_path, json_path = write_report(report, output_dir=Path(args.output_dir))
    print_console_report(report, md_path=md_path, json_path=json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
