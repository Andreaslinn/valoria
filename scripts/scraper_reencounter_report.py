"""Scraper reencounter diagnostics using listings.last_seen_at.

Read-only report for measuring whether stored listings are being seen again by
the ingestion pipeline.

Usage:
    python scripts/scraper_reencounter_report.py --output-dir reports/scraper_reencounter
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("reports/scraper_reencounter")
REQUIRED_COLUMNS = (
    "id",
    "source",
    "comuna",
    "property_type",
    "status",
    "created_at",
    "last_seen_at",
)


class MissingRequiredColumnsError(RuntimeError):
    def __init__(self, missing_columns: list[str]) -> None:
        self.missing_columns = missing_columns
        super().__init__(f"Missing required listings columns: {', '.join(missing_columns)}")


@dataclass(frozen=True)
class ReportArtifacts:
    markdown_path: Path
    json_path: Path
    snapshot_markdown_path: Path
    snapshot_json_path: Path


def build_report(
    listings: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _coerce_datetime(generated_at) or datetime.now(UTC)
    rows = [_normalise_row(row) for row in listings]
    active = [row for row in rows if row["status"] == "active"]

    summary = {
        "generated_at": now.isoformat(),
        "measurement_field": "last_seen_at",
        "total_listings": len(rows),
        "active_listings": len(active),
        "seen_last_24h": _seen_count(active, now - timedelta(hours=24)),
        "seen_last_7d": _seen_count(active, now - timedelta(days=7)),
        "seen_last_30d": _seen_count(active, now - timedelta(days=30)),
        "not_seen_over_30d": _not_seen_count(active, now - timedelta(days=30)),
        "not_seen_over_45d": _not_seen_count(active, now - timedelta(days=45)),
        "reencounter_7d_pct": _reencounter_pct(active, now - timedelta(days=7)),
        "reencounter_30d_pct": _reencounter_pct(active, now - timedelta(days=30)),
        "reencounter_7d_denominator": _known_before_count(active, now - timedelta(days=7)),
        "reencounter_30d_denominator": _known_before_count(active, now - timedelta(days=30)),
        "last_seen_at_missing": sum(row["last_seen_at"] is None for row in active),
        "oldest_last_seen_at": _min_seen(active),
        "newest_last_seen_at": _max_seen(active),
        "all_seen_last_24h": _seen_count(rows, now - timedelta(hours=24)),
        "all_seen_last_7d": _seen_count(rows, now - timedelta(days=7)),
        "all_seen_last_30d": _seen_count(rows, now - timedelta(days=30)),
    }

    return {
        "generated_at": now.isoformat(),
        "status": "ok",
        "measurement_field": "last_seen_at",
        "summary": summary,
        "distributions": {
            "by_source": _dimension(rows, "source", now),
            "by_comuna": _dimension(rows, "comuna", now),
            "by_property_type": _dimension(rows, "property_type", now),
            "by_status": _dimension(rows, "status", now),
        },
        "notes": [
            "Recency is measured with listings.last_seen_at.",
            "Summary recency counts only active listings.",
            "Segment rows include all listings in that segment and also expose active_listings.",
            "Reencounter percentage excludes listings created inside the measured window.",
        ],
    }


def build_schema_error_report(
    missing_columns: list[str],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _coerce_datetime(generated_at) or datetime.now(UTC)
    return {
        "generated_at": now.isoformat(),
        "status": "schema_error",
        "measurement_field": "last_seen_at",
        "summary": {
            "generated_at": now.isoformat(),
            "measurement_field": "last_seen_at",
            "total_listings": 0,
            "active_listings": 0,
            "seen_last_24h": 0,
            "seen_last_7d": 0,
            "seen_last_30d": 0,
            "not_seen_over_30d": 0,
            "not_seen_over_45d": 0,
            "reencounter_7d_pct": 0.0,
            "reencounter_30d_pct": 0.0,
            "reencounter_7d_denominator": 0,
            "reencounter_30d_denominator": 0,
            "last_seen_at_missing": 0,
            "oldest_last_seen_at": None,
            "newest_last_seen_at": None,
            "all_seen_last_24h": 0,
            "all_seen_last_7d": 0,
            "all_seen_last_30d": 0,
            "schema_error": "missing_required_columns",
            "missing_columns": missing_columns,
        },
        "distributions": {
            "by_source": [],
            "by_comuna": [],
            "by_property_type": [],
            "by_status": [],
        },
        "notes": [
            "The report could not compute recency metrics because required listings columns are missing.",
            "Apply the last_seen_at migration before running this diagnostic against this database.",
            f"Missing columns: {', '.join(missing_columns)}",
        ],
    }


def write_report(report: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> ReportArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    markdown = markdown_report(report)
    payload = json.dumps(report, ensure_ascii=False, indent=2)

    markdown_path = output_dir / "latest.md"
    json_path = output_dir / "latest.json"
    snapshot_markdown_path = output_dir / f"scraper_reencounter_{stamp}.md"
    snapshot_json_path = output_dir / f"scraper_reencounter_{stamp}.json"

    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(payload, encoding="utf-8")
    snapshot_markdown_path.write_text(markdown, encoding="utf-8")
    snapshot_json_path.write_text(payload, encoding="utf-8")

    return ReportArtifacts(
        markdown_path=markdown_path,
        json_path=json_path,
        snapshot_markdown_path=snapshot_markdown_path,
        snapshot_json_path=snapshot_json_path,
    )


def markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Scraper Reencounter Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Status: `{report.get('status', 'ok')}`",
        f"- Measurement field: `listings.{report['measurement_field']}`",
        f"- Total listings: {summary['total_listings']}",
        f"- Active listings: {summary['active_listings']}",
        f"- Seen last 24h: {summary['seen_last_24h']}",
        f"- Seen last 7d: {summary['seen_last_7d']}",
        f"- Seen last 30d: {summary['seen_last_30d']}",
        f"- Not seen over 30d: {summary['not_seen_over_30d']}",
        f"- Not seen over 45d: {summary['not_seen_over_45d']}",
        f"- Reencounter 7d: {summary['reencounter_7d_pct']}%",
        f"- Reencounter 30d: {summary['reencounter_30d_pct']}%",
        f"- Active rows missing last_seen_at: {summary['last_seen_at_missing']}",
        "",
        "## By Source",
        "",
        _markdown_table(report["distributions"]["by_source"]),
        "",
        "## By Comuna",
        "",
        _markdown_table(report["distributions"]["by_comuna"]),
        "",
        "## By Property Type",
        "",
        _markdown_table(report["distributions"]["by_property_type"]),
        "",
        "## By Status",
        "",
        _markdown_table(report["distributions"]["by_status"]),
        "",
        "## Notes",
        "",
        _bullet_list(report["notes"]),
    ]
    return "\n".join(lines) + "\n"


def print_console_report(report: dict[str, Any], artifacts: ReportArtifacts | None = None) -> None:
    summary = report["summary"]
    print("== AVM scraper reencounter ==")
    print(f"measurement_field\tlistings.{report['measurement_field']}")
    print(f"active_listings\t{summary['active_listings']}")
    print(f"seen_last_24h\t{summary['seen_last_24h']}")
    print(f"seen_last_7d\t{summary['seen_last_7d']}")
    print(f"seen_last_30d\t{summary['seen_last_30d']}")
    print(f"not_seen_over_30d\t{summary['not_seen_over_30d']}")
    print(f"not_seen_over_45d\t{summary['not_seen_over_45d']}")
    print(f"reencounter_7d_pct\t{summary['reencounter_7d_pct']}")
    print(f"reencounter_30d_pct\t{summary['reencounter_30d_pct']}")

    if artifacts is not None:
        print("\n== Files ==")
        print(f"markdown\t{artifacts.markdown_path}")
        print(f"json\t{artifacts.json_path}")
        print(f"snapshot_markdown\t{artifacts.snapshot_markdown_path}")
        print(f"snapshot_json\t{artifacts.snapshot_json_path}")


async def load_dataset(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> list[dict[str, Any]]:
    factory = session_factory or get_session_factory()
    async with factory() as session:
        columns = await _listing_columns(session)
        missing = [column for column in REQUIRED_COLUMNS if column not in columns]
        if missing:
            raise MissingRequiredColumnsError(missing)
        result = await session.execute(
            text(
                """
                SELECT
                  id,
                  source,
                  comuna,
                  property_type,
                  status,
                  created_at,
                  last_seen_at
                FROM listings
                """
            )
        )
        return [dict(row._mapping) for row in result.all()]


def _dimension(rows: list[dict[str, Any]], key: str, now: datetime) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)

    return [
        {"value": value, **_segment_metrics(group, now)}
        for value, group in sorted(
            grouped.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
    ]


def _segment_metrics(rows: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    return {
        "total_listings": len(rows),
        "active_listings": sum(row["status"] == "active" for row in rows),
        "seen_last_24h": _seen_count(rows, now - timedelta(hours=24)),
        "seen_last_7d": _seen_count(rows, now - timedelta(days=7)),
        "seen_last_30d": _seen_count(rows, now - timedelta(days=30)),
        "not_seen_over_30d": _not_seen_count(rows, now - timedelta(days=30)),
        "not_seen_over_45d": _not_seen_count(rows, now - timedelta(days=45)),
        "reencounter_7d_pct": _reencounter_pct(rows, now - timedelta(days=7)),
        "reencounter_30d_pct": _reencounter_pct(rows, now - timedelta(days=30)),
        "last_seen_at_missing": sum(row["last_seen_at"] is None for row in rows),
    }


def _normalise_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "source": _norm(row.get("source")),
        "comuna": _norm(row.get("comuna")),
        "property_type": _norm(row.get("property_type")),
        "status": _norm(row.get("status")),
        "created_at": _coerce_datetime(row.get("created_at")),
        "last_seen_at": _coerce_datetime(row.get("last_seen_at")),
    }


def _seen_count(rows: list[dict[str, Any]], cutoff: datetime) -> int:
    return sum(row["last_seen_at"] is not None and row["last_seen_at"] >= cutoff for row in rows)


def _not_seen_count(rows: list[dict[str, Any]], cutoff: datetime) -> int:
    return sum(row["last_seen_at"] is None or row["last_seen_at"] < cutoff for row in rows)


def _known_before_count(rows: list[dict[str, Any]], cutoff: datetime) -> int:
    return sum(row["created_at"] is not None and row["created_at"] < cutoff for row in rows)


def _reencounter_pct(rows: list[dict[str, Any]], cutoff: datetime) -> float:
    known_before = [
        row
        for row in rows
        if row["created_at"] is not None and row["created_at"] < cutoff
    ]
    if not known_before:
        return 0.0
    reencountered = _seen_count(known_before, cutoff)
    return _pct(reencountered, len(known_before))


def _min_seen(rows: list[dict[str, Any]]) -> str | None:
    values = [row["last_seen_at"] for row in rows if row["last_seen_at"] is not None]
    return min(values).isoformat() if values else None


def _max_seen(rows: list[dict[str, Any]]) -> str | None:
    values = [row["last_seen_at"] for row in rows if row["last_seen_at"] is not None]
    return max(values).isoformat() if values else None


def _pct(part: int | float, total: int | float) -> float:
    if not total:
        return 0.0
    return round(float(part) / float(total) * 100, 2)


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text or "unknown"


def _markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No data._"
    columns = [
        "value",
        "total_listings",
        "active_listings",
        "seen_last_24h",
        "seen_last_7d",
        "seen_last_30d",
        "not_seen_over_30d",
        "not_seen_over_45d",
        "reencounter_7d_pct",
        "reencounter_30d_pct",
    ]
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate scraper reencounter diagnostics.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for Markdown and JSON outputs.",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    try:
        listings = await load_dataset()
        report = build_report(listings)
    except MissingRequiredColumnsError as exc:
        report = build_schema_error_report(exc.missing_columns)
    artifacts = write_report(report, output_dir=Path(args.output_dir))
    print_console_report(report, artifacts)
    return 2 if report.get("status") == "schema_error" else 0


async def _listing_columns(session: AsyncSession) -> set[str]:
    connection = await session.connection()
    return await connection.run_sync(
        lambda sync_connection: {
            str(column["name"])
            for column in inspect(sync_connection).get_columns(ListingORM.__tablename__)
        }
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
