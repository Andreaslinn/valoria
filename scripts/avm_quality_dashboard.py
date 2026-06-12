"""Internal AVM quality dashboard.

Builds a consolidated, read-only health report from:
- the current data sufficiency snapshot
- historical data sufficiency JSON files
- historical evaluation benchmark JSON files

Usage:
    python scripts/avm_quality_dashboard.py --output-dir reports/avm_quality
"""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.data_sufficiency_report import _load_active_listings
from scripts.data_sufficiency_report import build_report as build_data_sufficiency_report

DEFAULT_OUTPUT_DIR = Path("reports/avm_quality")
DEFAULT_DATA_SUFFICIENCY_DIR = Path("reports/data_sufficiency")
DEFAULT_BENCHMARK_DIR = Path("reports/evaluation_benchmark")


@dataclass(frozen=True)
class DashboardArtifacts:
    json_path: Path
    csv_path: Path
    markdown_path: Path


def build_dashboard(
    current_data_sufficiency: dict[str, Any],
    *,
    data_sufficiency_history: Sequence[dict[str, Any]] = (),
    benchmark_history: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    current_summary = current_data_sufficiency["summary"]
    latest_benchmark = _latest_report(benchmark_history)
    benchmark_summary = latest_benchmark.get("summary") if latest_benchmark else None
    benchmark_metrics = (benchmark_summary or {}).get("metrics") or {}

    return {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(),
            "active_listings": current_summary["active_total"],
            "useful_listings": current_summary["avm_useful_total"],
            "useful_coverage_pct": _pct(current_summary["avm_useful_total"], current_summary["active_total"]),
            "low_data_mode_comunas": current_summary["low_data_comunas"],
            "sufficient_data_comunas": current_summary["sufficient_data_comunas"],
            "latest_benchmark_status": (benchmark_summary or {}).get("status"),
            "latest_mape_pct": benchmark_metrics.get("mape_pct"),
            "latest_benchmark_coverage_pct": (benchmark_summary or {}).get("coverage_pct"),
            "latest_avg_comparables_used": (benchmark_summary or {}).get("avg_comparables_used"),
        },
        "current": {
            "coverage_by_comuna": current_data_sufficiency["by_comuna"],
            "geocode_precision": current_data_sufficiency["geocode_precision"],
            "property_types": current_data_sufficiency["by_property_type"],
            "top_discard_reasons": current_data_sufficiency["top_discard_reasons"],
            "low_data_mode_comunas": [
                row for row in current_data_sufficiency["by_comuna"] if row.get("low_data_mode")
            ],
        },
        "history": {
            "db_growth": _db_growth_rows(data_sufficiency_history, current_data_sufficiency),
            "mape": _mape_history_rows(benchmark_history),
            "benchmarks": _benchmark_history_rows(benchmark_history),
        },
        "interpretation": _interpret_dashboard(current_data_sufficiency, benchmark_summary),
    }


def write_dashboard(dashboard: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> DashboardArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"avm_quality_dashboard_{stamp}.json"
    csv_path = output_dir / f"avm_quality_dashboard_comunas_{stamp}.csv"
    markdown_path = output_dir / f"avm_quality_dashboard_{stamp}.md"

    json_path.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_comuna_csv(dashboard["current"]["coverage_by_comuna"], csv_path)
    markdown_path.write_text(_markdown_dashboard(dashboard), encoding="utf-8")
    return DashboardArtifacts(json_path=json_path, csv_path=csv_path, markdown_path=markdown_path)


def load_json_reports(directory: Path, pattern: str) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    reports: list[dict[str, Any]] = []
    for path in sorted(directory.glob(pattern)):
        try:
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return reports


def print_console_dashboard(dashboard: dict[str, Any], artifacts: DashboardArtifacts | None = None) -> None:
    summary = dashboard["summary"]
    print("== AVM Quality Dashboard ==")
    print(f"active_listings\t{summary['active_listings']}")
    print(f"useful_listings\t{summary['useful_listings']}")
    print(f"useful_coverage_pct\t{summary['useful_coverage_pct']}")
    print(f"low_data_mode_comunas\t{summary['low_data_mode_comunas']}")
    print(f"sufficient_data_comunas\t{summary['sufficient_data_comunas']}")
    print(f"latest_benchmark_status\t{summary['latest_benchmark_status']}")
    print(f"latest_mape_pct\t{summary['latest_mape_pct']}")
    print(f"latest_benchmark_coverage_pct\t{summary['latest_benchmark_coverage_pct']}")

    print("\n== Geocode precision ==")
    for precision, count in sorted(dashboard["current"]["geocode_precision"].items()):
        print(f"{precision}\t{count}")

    print("\n== Property types ==")
    for property_type, count in sorted(dashboard["current"]["property_types"].items()):
        print(f"{property_type}\t{count}")

    print("\n== Top discard reasons ==")
    for reason, count in dashboard["current"]["top_discard_reasons"].items():
        print(f"{reason}\t{count}")

    print("\n== Interpretation ==")
    for item in dashboard["interpretation"]:
        print(f"- {item}")

    if artifacts is not None:
        print("\n== Files ==")
        print(f"json\t{artifacts.json_path}")
        print(f"csv\t{artifacts.csv_path}")
        print(f"markdown\t{artifacts.markdown_path}")


def _latest_report(reports: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    if not reports:
        return None
    return sorted(reports, key=lambda report: report.get("summary", {}).get("generated_at") or "")[-1]


def _db_growth_rows(
    data_sufficiency_history: Sequence[dict[str, Any]],
    current_data_sufficiency: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = [_data_growth_row(report) for report in data_sufficiency_history]
    rows.append(_data_growth_row(current_data_sufficiency))
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        deduped[row["generated_at"]] = row
    return sorted(deduped.values(), key=lambda row: row["generated_at"])


def _data_growth_row(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    return {
        "generated_at": summary.get("generated_at"),
        "active_listings": summary.get("active_total"),
        "useful_listings": summary.get("avm_useful_total"),
        "low_data_mode_comunas": summary.get("low_data_comunas"),
        "sufficient_data_comunas": summary.get("sufficient_data_comunas"),
    }


def _mape_history_rows(benchmark_history: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for report in benchmark_history:
        summary = report.get("summary", {})
        metrics = summary.get("metrics") or {}
        rows.append(
            {
                "generated_at": summary.get("generated_at"),
                "status": summary.get("status"),
                "mape_pct": metrics.get("mape_pct"),
                "coverage_pct": summary.get("coverage_pct"),
                "avg_comparables_used": summary.get("avg_comparables_used"),
                "low_data_mode_rate_pct": summary.get("low_data_mode_rate_pct"),
            }
        )
    return sorted(rows, key=lambda row: row.get("generated_at") or "")


def _benchmark_history_rows(benchmark_history: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for report in benchmark_history:
        summary = report.get("summary", {})
        rows.append(
            {
                "generated_at": summary.get("generated_at"),
                "status": summary.get("status"),
                "total_active_listings": summary.get("total_active_listings"),
                "unique_eval_targets": summary.get("unique_eval_targets"),
                "successful_valuations": summary.get("successful_valuations"),
                "failed_valuations": summary.get("failed_valuations"),
                "coverage_pct": summary.get("coverage_pct"),
            }
        )
    return sorted(rows, key=lambda row: row.get("generated_at") or "")


def _interpret_dashboard(
    current_data_sufficiency: dict[str, Any],
    benchmark_summary: dict[str, Any] | None,
) -> list[str]:
    summary = current_data_sufficiency["summary"]
    geocode = current_data_sufficiency["geocode_precision"]
    active = summary["active_total"]
    unknown_geo_pct = _pct(geocode.get("unknown", 0), active)
    low_data = summary["low_data_comunas"]

    items = []
    if active == 0:
        items.append("No hay listings activos; el AVM no tiene base operativa.")
    elif summary["avm_useful_total"] < active:
        items.append("Hay listings activos que no son utiles para AVM; revisar precio, m2 y property_type.")
    else:
        items.append("Todos los listings activos actuales califican como utiles para AVM segun reglas basicas.")

    if low_data:
        items.append(f"{low_data} comunas estan en LOW_DATA_MODE; esas tasaciones deben tratarse con cautela.")
    if unknown_geo_pct is not None and unknown_geo_pct >= 50:
        items.append(f"Geocoding unknown alto ({unknown_geo_pct}%); priorizar extraccion de ubicacion.")

    if benchmark_summary is None:
        items.append("No hay benchmark historico disponible; ejecutar scripts/evaluation_benchmark.py.")
    elif benchmark_summary.get("status") != "ok":
        items.append("El benchmark mas reciente no tiene data suficiente para medir accuracy.")
    else:
        metrics = benchmark_summary.get("metrics") or {}
        items.append(
            f"Benchmark mas reciente: MAPE {metrics.get('mape_pct')}%, "
            f"coverage {benchmark_summary.get('coverage_pct')}%."
        )
    return items


def _markdown_dashboard(dashboard: dict[str, Any]) -> str:
    summary = dashboard["summary"]
    lines = [
        "# AVM Quality Dashboard",
        "",
        "## Executive Summary",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Active listings: {summary['active_listings']}",
        f"- Useful listings: {summary['useful_listings']}",
        f"- Useful coverage: {summary['useful_coverage_pct']}%",
        f"- LOW_DATA_MODE comunas: {summary['low_data_mode_comunas']}",
        f"- Sufficient data comunas: {summary['sufficient_data_comunas']}",
        f"- Latest benchmark status: `{summary['latest_benchmark_status']}`",
        f"- Latest MAPE: {summary['latest_mape_pct']}%",
        f"- Latest benchmark coverage: {summary['latest_benchmark_coverage_pct']}%",
        f"- Latest avg comparables used: {summary['latest_avg_comparables_used']}",
        "",
        "## Interpretation",
        "",
        "\n".join(f"- {item}" for item in dashboard["interpretation"]),
        "",
        "## Coverage By Comuna",
        "",
        _comuna_table(dashboard["current"]["coverage_by_comuna"]),
        "",
        "## Geocode Precision",
        "",
        _simple_table("precision", dashboard["current"]["geocode_precision"]),
        "",
        "## Property Types",
        "",
        _simple_table("property_type", dashboard["current"]["property_types"]),
        "",
        "## Top Discard Reasons",
        "",
        _simple_table("reason", dashboard["current"]["top_discard_reasons"]),
        "",
        "## DB Growth",
        "",
        _history_table(dashboard["history"]["db_growth"], ["generated_at", "active_listings", "useful_listings"]),
        "",
        "## MAPE History",
        "",
        _history_table(
            dashboard["history"]["mape"],
            ["generated_at", "status", "mape_pct", "coverage_pct", "avg_comparables_used"],
        ),
    ]
    return "\n".join(lines) + "\n"


def _simple_table(label: str, values: dict[str, int]) -> str:
    if not values:
        return "_No data._"
    lines = [f"| {label} | count |", "|---|---:|"]
    for key, count in sorted(values.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {key} | {count} |")
    return "\n".join(lines)


def _comuna_table(rows: Sequence[dict[str, Any]]) -> str:
    if not rows:
        return "_No comuna data._"
    lines = [
        "| Comuna | Active | Useful | Valid m2 | Valid price | LOW_DATA_MODE | Sufficient |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['comuna']} | {row['active_listings']} | {row['avm_useful_listings']} | "
            f"{row['valid_m2_listings']} | {row['valid_price_listings']} | "
            f"{row['low_data_mode']} | {row['data_sufficient']} |"
        )
    return "\n".join(lines)


def _history_table(rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> str:
    if not rows:
        return "_No history available._"
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for row in rows[-12:]:
        lines.append("| " + " | ".join(str(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _write_comuna_csv(rows: Sequence[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "comuna",
        "active_listings",
        "avm_useful_listings",
        "valid_m2_listings",
        "valid_price_listings",
        "known_property_type_listings",
        "low_data_mode",
        "data_sufficient",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{key: row.get(key) for key in fieldnames} for row in rows])


def _pct(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return round(float(numerator) / float(denominator) * 100, 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate internal AVM quality dashboard.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for dashboard outputs.")
    parser.add_argument(
        "--data-sufficiency-dir",
        default=str(DEFAULT_DATA_SUFFICIENCY_DIR),
        help="Directory with data_sufficiency_*.json history.",
    )
    parser.add_argument(
        "--benchmark-dir",
        default=str(DEFAULT_BENCHMARK_DIR),
        help="Directory with evaluation_benchmark_*.json history.",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    listings = await _load_active_listings()
    current_data_sufficiency = build_data_sufficiency_report(listings)
    data_history = load_json_reports(Path(args.data_sufficiency_dir), "data_sufficiency_*.json")
    benchmark_history = load_json_reports(Path(args.benchmark_dir), "evaluation_benchmark_*.json")
    dashboard = build_dashboard(
        current_data_sufficiency,
        data_sufficiency_history=data_history,
        benchmark_history=benchmark_history,
    )
    artifacts = write_dashboard(dashboard, output_dir=Path(args.output_dir))
    print_console_dashboard(dashboard, artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
