"""Aggregate privacy-conscious beta product usage metrics.

Usage:
    python scripts/product_usage_report.py --input-dir reports/product_usage --output-dir reports/product_usage
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_INPUT_DIR = Path("reports/product_usage")
DEFAULT_OUTPUT_DIR = Path("reports/product_usage")


def load_events(input_dir: Path = DEFAULT_INPUT_DIR) -> list[dict[str, Any]]:
    if not input_dir.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("product_usage_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def build_usage_report(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    sessions = {event.get("session_id") for event in events if event.get("session_id")}
    users_by_day = _users_by_day(events)
    returning_users = _returning_users(users_by_day)
    session_durations = _session_durations(events)
    event_counts = Counter(str(event.get("event_type") or "unknown") for event in events)
    valuation_events = [event for event in events if event.get("event_type") == "valuation_submitted"]
    radar_completed = [event for event in events if event.get("event_type") == "radar_completed"]

    return {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(),
            "events": len(events),
            "sessions": len(sessions),
            "identified_users": len({event.get("user_hash") for event in events if event.get("user_hash")}),
            "returning_users": len(returning_users),
            "avg_session_duration_seconds": _avg(session_durations),
            "p50_session_duration_seconds": _percentile_or_none(session_durations, 50),
            "valuations_submitted": event_counts.get("valuation_submitted", 0),
            "valuations_completed": event_counts.get("valuation_completed", 0),
            "valuation_failures": event_counts.get("valuation_failed", 0),
            "radar_requests": event_counts.get("radar_requested", 0),
            "radar_completed": event_counts.get("radar_completed", 0),
        },
        "event_counts": dict(event_counts),
        "comunas_consulted": dict(_property_counter(valuation_events, "comuna")),
        "property_types": dict(_property_counter(valuation_events, "property_type")),
        "radar": {
            "avg_results_count": _avg(_property_numbers(radar_completed, "radar_results_count")),
            "avg_comunas_count": _avg(_property_numbers(radar_completed, "radar_comunas_count")),
        },
        "daily": _daily_rows(events),
    }


def write_usage_report(report: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"product_usage_report_{stamp}.json"
    csv_path = output_dir / f"product_usage_daily_{stamp}.csv"
    markdown_path = output_dir / f"product_usage_report_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_daily_csv(report["daily"], csv_path)
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "markdown": markdown_path}


def print_usage_report(report: dict[str, Any], artifacts: dict[str, Path] | None = None) -> None:
    summary = report["summary"]
    print("== Product usage beta ==")
    for key, value in summary.items():
        print(f"{key}\t{value}")
    print("\n== Comunas consultadas ==")
    for comuna, count in report["comunas_consulted"].items():
        print(f"{comuna}\t{count}")
    print("\n== Property types ==")
    for property_type, count in report["property_types"].items():
        print(f"{property_type}\t{count}")
    if artifacts:
        print("\n== Files ==")
        for label, path in artifacts.items():
            print(f"{label}\t{path}")


def _users_by_day(events: Sequence[dict[str, Any]]) -> dict[str, set[str]]:
    users: dict[str, set[str]] = defaultdict(set)
    for event in events:
        user_hash = event.get("user_hash")
        day = _event_day(event)
        if user_hash and day:
            users[day].add(str(user_hash))
    return users


def _returning_users(users_by_day: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    returning: set[str] = set()
    for day in sorted(users_by_day):
        for user_hash in users_by_day[day]:
            if user_hash in seen:
                returning.add(user_hash)
            seen.add(user_hash)
    return returning


def _session_durations(events: Sequence[dict[str, Any]]) -> list[float]:
    by_session: dict[str, float] = {}
    for event in events:
        session_id = event.get("session_id")
        duration = event.get("session_duration_seconds")
        if not session_id or not isinstance(duration, int | float):
            continue
        by_session[str(session_id)] = max(float(duration), by_session.get(str(session_id), 0.0))
    return list(by_session.values())


def _property_counter(events: Iterable[dict[str, Any]], key: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for event in events:
        value = (event.get("properties") or {}).get(key)
        if value:
            counter[str(value)] += 1
    return Counter(dict(counter.most_common(20)))


def _property_numbers(events: Iterable[dict[str, Any]], key: str) -> list[float]:
    values = []
    for event in events:
        value = (event.get("properties") or {}).get(key)
        if isinstance(value, int | float):
            values.append(float(value))
    return values


def _daily_rows(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        day = _event_day(event)
        if day:
            grouped[day].append(event)
    rows = []
    for day, day_events in sorted(grouped.items()):
        counts = Counter(str(event.get("event_type") or "unknown") for event in day_events)
        rows.append(
            {
                "date": day,
                "events": len(day_events),
                "sessions": len({event.get("session_id") for event in day_events if event.get("session_id")}),
                "users": len({event.get("user_hash") for event in day_events if event.get("user_hash")}),
                "valuations_submitted": counts.get("valuation_submitted", 0),
                "valuations_completed": counts.get("valuation_completed", 0),
                "radar_requests": counts.get("radar_requested", 0),
                "radar_completed": counts.get("radar_completed", 0),
            }
        )
    return rows


def _event_day(event: dict[str, Any]) -> str | None:
    occurred_at = event.get("occurred_at")
    if not isinstance(occurred_at, str) or len(occurred_at) < 10:
        return None
    return occurred_at[:10]


def _write_daily_csv(rows: Sequence[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "date",
        "events",
        "sessions",
        "users",
        "valuations_submitted",
        "valuations_completed",
        "radar_requests",
        "radar_completed",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    return "\n".join(
        [
            "# Product Usage Beta Report",
            "",
            "## Summary",
            "",
            *[f"- {key}: {value}" for key, value in summary.items()],
            "",
            "## Comunas Consultadas",
            "",
            _simple_table("comuna", report["comunas_consulted"]),
            "",
            "## Property Types",
            "",
            _simple_table("property_type", report["property_types"]),
            "",
            "## Event Counts",
            "",
            _simple_table("event", report["event_counts"]),
            "",
            "## Daily",
            "",
            _daily_table(report["daily"]),
        ]
    ) + "\n"


def _simple_table(label: str, values: dict[str, int]) -> str:
    if not values:
        return "_No data._"
    lines = [f"| {label} | count |", "|---|---:|"]
    for key, value in values.items():
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def _daily_table(rows: Sequence[dict[str, Any]]) -> str:
    if not rows:
        return "_No data._"
    columns = list(rows[0])
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _avg(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _percentile_or_none(values: Sequence[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (percentile / 100)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate beta product usage metrics.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR), help="Directory with product_usage_*.jsonl files.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for report outputs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_usage_report(load_events(Path(args.input_dir)))
    artifacts = write_usage_report(report, output_dir=Path(args.output_dir))
    print_usage_report(report, artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
