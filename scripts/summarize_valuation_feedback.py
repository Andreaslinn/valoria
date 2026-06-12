"""Summarize private beta valuation feedback JSONL files."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.valuation_feedback import DEFAULT_FEEDBACK_DIR, FEEDBACK_DIR_ENV  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("reports/valuation_feedback")


def main() -> int:
    args = _parse_args()
    input_dir = Path(args.input_dir)
    records = load_feedback_records(input_dir)
    summary = summarize_feedback(records)
    md_path, json_path = write_feedback_summary(summary, output_dir=Path(args.output_dir))
    print("== AVM Valuation Feedback Summary ==")
    print(f"records\t{summary['summary']['total_feedback']}")
    print(f"latest_feedback_at\t{summary['summary']['latest_feedback_at']}")
    print(f"markdown\t{md_path}")
    print(f"json\t{json_path}")
    return 0


def load_feedback_records(input_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("valuation_feedback_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
    return records


def summarize_feedback(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    return {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_feedback": len(rows),
            "latest_feedback_at": max((str(row.get("timestamp")) for row in rows if row.get("timestamp")), default=None),
        },
        "by_feedback": dict(Counter(str(row.get("feedback") or "unknown") for row in rows)),
        "by_property_type": _group_counts(rows, "property_type"),
        "by_comuna": _group_counts(rows, "comuna"),
        "by_comparable_quality_level": _group_counts(rows, "comparable_quality_level"),
        "by_confidence": _group_counts(rows, "confidence"),
        "avg_estimated_value_clp_by_feedback": _avg_by(rows, "feedback", "estimated_value_clp"),
        "comments": _comments(rows, limit=50),
    }


def write_feedback_summary(
    summary: dict[str, Any],
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "valuation_feedback_summary.json"
    md_path = output_dir / "valuation_feedback_summary.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(summary), encoding="utf-8")
    return md_path, json_path


def _group_counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(Counter(str(row.get(key) or "unknown") for row in rows))


def _avg_by(rows: list[dict[str, Any]], group_key: str, value_key: str) -> dict[str, float | None]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = _number(row.get(value_key))
        if value is None:
            continue
        grouped[str(row.get(group_key) or "unknown")].append(value)
    return {key: round(mean(values), 2) if values else None for key, values in sorted(grouped.items())}


def _comments(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    comments = []
    for row in rows:
        comment = str(row.get("comment") or "").strip()
        if not comment:
            continue
        comments.append(
            {
                "timestamp": row.get("timestamp"),
                "comuna": row.get("comuna"),
                "property_type": row.get("property_type"),
                "feedback": row.get("feedback"),
                "comment": comment,
            }
        )
    return comments[-limit:]


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# AVM Valuation Feedback Summary",
        "",
        f"- Generated at: `{summary['summary']['generated_at']}`",
        f"- Total feedback: {summary['summary']['total_feedback']}",
        f"- Latest feedback at: {summary['summary']['latest_feedback_at']}",
        "",
        "## By Feedback",
        "",
        _table_from_counts(summary["by_feedback"], "feedback"),
        "",
        "## By Property Type",
        "",
        _table_from_counts(summary["by_property_type"], "property_type"),
        "",
        "## By Comuna",
        "",
        _table_from_counts(summary["by_comuna"], "comuna"),
        "",
        "## Recent Comments",
        "",
        _comments_table(summary["comments"]),
    ]
    return "\n".join(lines) + "\n"


def _table_from_counts(values: dict[str, int], label: str) -> str:
    if not values:
        return "_No data._"
    lines = [f"| {label} | count |", "|---|---|"]
    for key, count in sorted(values.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {key} | {count} |")
    return "\n".join(lines)


def _comments_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No comments._"
    lines = ["| timestamp | comuna | type | feedback | comment |", "|---|---|---|---|---|"]
    for row in rows:
        comment = str(row.get("comment") or "").replace("|", "/")
        lines.append(
            f"| {row.get('timestamp')} | {row.get('comuna')} | {row.get('property_type')} | "
            f"{row.get('feedback')} | {comment} |"
        )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize AVM valuation feedback JSONL files.")
    parser.add_argument(
        "--input-dir",
        default=os.getenv(FEEDBACK_DIR_ENV, str(DEFAULT_FEEDBACK_DIR)),
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
