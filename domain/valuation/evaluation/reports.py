"""Report writers for offline valuation engine evaluation."""
from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from domain.valuation.evaluation.evaluator import EngineEvaluationRow


def write_evaluation_reports(
    *,
    output_dir: Path,
    rows: list[EngineEvaluationRow],
    summary: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            **metadata,
        },
        "summary": summary,
        "rows": [row.to_dict() for row in rows],
    }
    json_path = output_dir / "valuation_engine_benchmark.json"
    md_path = output_dir / "valuation_engine_benchmark.md"
    csv_path = output_dir / "valuation_engine_benchmark_rows.csv"

    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    _write_csv(csv_path, rows)
    return {"json": str(json_path), "markdown": str(md_path), "csv": str(csv_path)}


def _markdown(payload: dict[str, Any]) -> str:
    metadata = payload["metadata"]
    summary = payload["summary"]
    global_summary = summary.get("global", {})
    lines = [
        "# Valuation Engine Benchmark",
        "",
        f"Generated at: `{metadata.get('generated_at')}`",
        f"Engines: `{', '.join(metadata.get('engines', []))}`",
        f"Git commit: `{metadata.get('git_commit')}`",
        f"Git status: `{metadata.get('git_status')}`",
        "",
        "## Global",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key, value in global_summary.items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Segments", ""])
    for segment_name, segment_rows in summary.items():
        if segment_name == "global":
            continue
        lines.extend([f"### {segment_name}", "", "| Segment | MAPE | Median APE | Coverage | Cases |", "| --- | ---: | ---: | ---: | ---: |"])
        for key, row in segment_rows.items():
            lines.append(
                f"| `{key}` | {row.get('mape_pct')} | {row.get('median_ape_pct')} | "
                f"{row.get('coverage_pct')} | {row.get('total_cases')} |"
            )
        lines.append("")
    limitations = metadata.get("limitations") or []
    if limitations:
        lines.extend(["## Limitations", ""])
        lines.extend(f"- {item}" for item in limitations)
        lines.append("")
    return "\n".join(lines)


def _write_csv(path: Path, rows: list[EngineEvaluationRow]) -> None:
    fieldnames = [
        "case_id",
        "target_id",
        "engine_name",
        "engine_version",
        "status",
        "actual_price_clp",
        "estimated_price_clp",
        "absolute_percentage_error",
        "signed_percentage_error",
        "elapsed_ms",
        "property_type",
        "comuna",
        "geocode_precision",
        "has_land_area",
        "comparables_used",
        "warnings",
        "error_code",
        "error_message",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            data = row.to_dict()
            data["warnings"] = ";".join(data["warnings"])
            writer.writerow({key: data.get(key) for key in fieldnames})
