"""Read-only data freshness report for beta operations."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import AlertORM, ListingORM, PriceHistoryORM  # noqa: E402


@dataclass(frozen=True)
class DataFreshnessReport:
    generated_at: datetime
    total_listings: int
    active_listings: int
    incomplete_listings: int
    removed_listings: int
    max_scraped_at: datetime | None
    max_last_seen_at: datetime | None
    max_last_refresh_attempted_at: datetime | None
    price_history_points: int
    max_price_history_observed_at: datetime | None
    alerts_total: int
    alerts_unread: int
    by_source: dict[str, int]
    by_status: dict[str, int]
    by_last_refresh_status: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": _iso(self.generated_at),
            "total_listings": self.total_listings,
            "active_listings": self.active_listings,
            "incomplete_listings": self.incomplete_listings,
            "removed_listings": self.removed_listings,
            "max_scraped_at": _iso(self.max_scraped_at),
            "max_last_seen_at": _iso(self.max_last_seen_at),
            "max_last_refresh_attempted_at": _iso(self.max_last_refresh_attempted_at),
            "price_history_points": self.price_history_points,
            "max_price_history_observed_at": _iso(self.max_price_history_observed_at),
            "alerts_total": self.alerts_total,
            "alerts_unread": self.alerts_unread,
            "by_source": dict(sorted(self.by_source.items())),
            "by_status": dict(sorted(self.by_status.items())),
            "by_last_refresh_status": dict(sorted(self.by_last_refresh_status.items())),
        }


async def collect_data_freshness_report() -> DataFreshnessReport:
    async with get_session_factory()() as session:
        totals = (
            await session.execute(
                select(
                    func.count(ListingORM.id),
                    func.count().filter(ListingORM.status == "active"),
                    func.count().filter(ListingORM.status == "incomplete"),
                    func.count().filter(ListingORM.status == "removed"),
                    func.max(ListingORM.scraped_at),
                    func.max(ListingORM.last_seen_at),
                    func.max(ListingORM.last_refresh_attempted_at),
                )
            )
        ).one()
        price_history = (
            await session.execute(
                select(
                    func.count(PriceHistoryORM.id),
                    func.max(PriceHistoryORM.observed_at),
                )
            )
        ).one()
        alerts = (
            await session.execute(
                select(
                    func.count(AlertORM.id),
                    func.count().filter(AlertORM.is_read.is_(False)),
                )
            )
        ).one()
        source_rows = (
            await session.execute(
                select(ListingORM.source, func.count())
                .group_by(ListingORM.source)
                .order_by(ListingORM.source)
            )
        ).all()
        status_rows = (
            await session.execute(
                select(ListingORM.status, func.count())
                .group_by(ListingORM.status)
                .order_by(ListingORM.status)
            )
        ).all()
        refresh_rows = (
            await session.execute(
                select(ListingORM.last_refresh_status, func.count())
                .where(ListingORM.last_refresh_status.is_not(None))
                .group_by(ListingORM.last_refresh_status)
                .order_by(ListingORM.last_refresh_status)
            )
        ).all()

    return DataFreshnessReport(
        generated_at=datetime.now(UTC),
        total_listings=int(totals[0] or 0),
        active_listings=int(totals[1] or 0),
        incomplete_listings=int(totals[2] or 0),
        removed_listings=int(totals[3] or 0),
        max_scraped_at=totals[4],
        max_last_seen_at=totals[5],
        max_last_refresh_attempted_at=totals[6],
        price_history_points=int(price_history[0] or 0),
        max_price_history_observed_at=price_history[1],
        alerts_total=int(alerts[0] or 0),
        alerts_unread=int(alerts[1] or 0),
        by_source=_rows_to_counts(source_rows),
        by_status=_rows_to_counts(status_rows),
        by_last_refresh_status=_rows_to_counts(refresh_rows),
    )


def report_markdown(report: DataFreshnessReport) -> str:
    payload = report.to_dict()
    lines = [
        "# AVM Data Freshness",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Total listings: {payload['total_listings']}",
        f"- Active listings: {payload['active_listings']}",
        f"- Incomplete listings: {payload['incomplete_listings']}",
        f"- Removed listings: {payload['removed_listings']}",
        f"- Last scraped_at: `{payload['max_scraped_at']}`",
        f"- Last last_seen_at: `{payload['max_last_seen_at']}`",
        f"- Last refresh attempted: `{payload['max_last_refresh_attempted_at']}`",
        f"- Price history points: {payload['price_history_points']}",
        f"- Last price_history observed_at: `{payload['max_price_history_observed_at']}`",
        f"- Alerts total: {payload['alerts_total']}",
        f"- Alerts unread: {payload['alerts_unread']}",
        "",
        "## By Source",
        "",
        _mapping_table(payload["by_source"]),
        "",
        "## By Status",
        "",
        _mapping_table(payload["by_status"]),
        "",
        "## By Last Refresh Status",
        "",
        _mapping_table(payload["by_last_refresh_status"]),
        "",
    ]
    return "\n".join(lines)


def print_console_report(report: DataFreshnessReport) -> None:
    payload = report.to_dict()
    print("== AVM Data Freshness ==")
    for key, value in payload.items():
        if isinstance(value, dict):
            print(f"{key}:")
            for item_key, count in value.items():
                print(f"  {item_key}: {count}")
        else:
            print(f"{key}\t{value}")


def write_outputs(report: DataFreshnessReport, output_base: str | None) -> tuple[Path, Path] | None:
    if not output_base:
        return None
    base = Path(output_base)
    json_path = base if base.suffix == ".json" else base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(report_markdown(report), encoding="utf-8")
    return md_path, json_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a read-only AVM data freshness report.")
    parser.add_argument(
        "--output",
        help="Optional output base path. Writes .md and .json files.",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = await collect_data_freshness_report()
    print_console_report(report)
    artifacts = write_outputs(report, args.output)
    if artifacts is not None:
        md_path, json_path = artifacts
        print(f"report_md\t{md_path}")
        print(f"report_json\t{json_path}")
    return 0


def _rows_to_counts(rows: list[tuple[Any, Any]]) -> dict[str, int]:
    return {str(key or "unknown"): int(value or 0) for key, value in rows}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _mapping_table(values: dict[str, int]) -> str:
    if not values:
        return "_No data._"
    lines = ["| value | count |", "|---|---:|"]
    lines.extend(f"| {key} | {value} |" for key, value in values.items())
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
