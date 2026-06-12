"""Read-only health check for the AVM data pipeline.

The goal is to detect source/scraper/data-quality degradation before it leaks
into valuations. The script writes stable `latest.md` and `latest.json` files
and compares against the previous `latest.json` when present.

Usage:
    python scripts/pipeline_health_check.py --output-dir reports/pipeline_health
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.assessment.status_codes import (  # noqa: E402
    STATUS_CRITICAL,
    STATUS_OK,
    STATUS_ORDER,
    STATUS_WARNING,
    PipelineAlertCode,
)
from core.normalization.geocode_precision import normalize_geocode_precision  # noqa: E402
from core.normalization.property_type import normalize_property_type as _property_type  # noqa: E402
from domain.geocoding.microzones import signals_from_value  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM, PriceHistoryORM  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("reports/pipeline_health")
USEFUL_COORD_PRECISIONS = {"address", "street"}


@dataclass(frozen=True)
class Threshold:
    code: str
    label: str
    warning_below: float | None = None
    critical_below: float | None = None
    warning_above: float | None = None
    critical_above: float | None = None


THRESHOLDS: tuple[Threshold, ...] = (
    Threshold(PipelineAlertCode.ACTIVE_LISTINGS_LOW, "Active listings", warning_below=1000, critical_below=500),
    Threshold(PipelineAlertCode.NEW_LISTINGS_LOW, "New active listings since baseline", warning_below=1),
    Threshold(PipelineAlertCode.PRICE_PARSE_RATE_LOW, "Price parse rate", warning_below=98, critical_below=95),
    Threshold(PipelineAlertCode.M2_PARSE_RATE_LOW, "M2 parse rate", warning_below=95, critical_below=90),
    Threshold(PipelineAlertCode.ROOMS_PARSE_RATE_LOW, "Bedrooms/bathrooms parse rate", warning_below=95, critical_below=90),
    Threshold(PipelineAlertCode.COMUNA_COVERAGE_LOW, "Covered comunas", warning_below=10, critical_below=5),
    Threshold(PipelineAlertCode.TOP_COMUNA_CONCENTRATION_HIGH, "Top comuna concentration", warning_above=25, critical_above=40),
    Threshold(PipelineAlertCode.USEFUL_COORDS_LOW, "Useful coordinate rate", warning_below=10, critical_below=3),
    Threshold(PipelineAlertCode.MICROZONE_RATE_LOW, "Useful microzone rate", warning_below=20, critical_below=10),
    Threshold(PipelineAlertCode.PRICE_HISTORY_USABLE_LOW, "Usable price history rate", warning_below=20, critical_below=10),
    Threshold(PipelineAlertCode.SINGLE_SOURCE_DEPENDENCY_HIGH, "Top source dependency", warning_above=80, critical_above=95),
)


def build_health_report(
    listings: list[dict[str, Any]],
    price_history_counts: dict[int, int],
    *,
    baseline: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    rows = [_listing_row(row, price_history_counts) for row in listings]
    active = [row for row in rows if row["status"] == "active"]
    active_keys = sorted(row["identity_key"] for row in active if row["identity_key"])
    previous_keys = set(_baseline_active_keys(baseline))
    new_keys = sorted(set(active_keys) - previous_keys) if previous_keys else []
    removed_keys = sorted(previous_keys - set(active_keys)) if previous_keys else []

    by_comuna = _counter_rows(active, "comuna")
    by_property_type = _counter_rows(active, "property_type")
    by_source = _counter_rows(rows, "source")
    top_comuna_pct = by_comuna[0]["pct"] if by_comuna else 0.0
    top_source_pct = by_source[0]["pct"] if by_source else 0.0

    metrics = {
        "total_listings": len(rows),
        "active_listings": len(active),
        "new_active_listings_since_baseline": len(new_keys) if previous_keys else None,
        "removed_active_listings_since_baseline": len(removed_keys) if previous_keys else None,
        "price_parse_rate_pct": _pct(sum(row["has_price"] for row in rows), len(rows)),
        "m2_parse_rate_pct": _pct(sum(row["has_m2"] for row in rows), len(rows)),
        "rooms_parse_rate_pct": _pct(sum(row["has_rooms"] for row in rows), len(rows)),
        "covered_comunas": len({row["comuna"] for row in active if row["comuna"] != "unknown"}),
        "top_comuna": by_comuna[0]["value"] if by_comuna else None,
        "top_comuna_pct": top_comuna_pct,
        "top_source": by_source[0]["value"] if by_source else None,
        "top_source_pct": top_source_pct,
        "useful_coords_pct": _pct(sum(row["has_useful_coords"] for row in active), len(active)),
        "useful_microzone_pct": _pct(sum(row["has_useful_microzone"] for row in active), len(active)),
        "price_history_usable_pct": _pct(sum(row["price_history_count"] >= 2 for row in active), len(active)),
        "house_land_area_coverage_pct": _coverage_pct(active, property_type="house", field="has_land_area"),
        "apartment_usable_area_coverage_pct": _coverage_pct(active, property_type="apartment", field="has_usable_area"),
        "area_parse_provenance_count": sum(row["has_area_parse_provenance"] for row in active),
        "area_parse_provenance_pct": _pct(sum(row["has_area_parse_provenance"] for row in active), len(active)),
    }
    baseline_summary = _baseline_summary(baseline, metrics)
    alerts = evaluate_health(metrics, has_baseline=bool(previous_keys))
    status = overall_status(alerts)

    return {
        "status": status,
        "generated_at": now.isoformat(),
        "baseline": baseline_summary,
        "metrics": metrics,
        "alerts": alerts,
        "distributions": {
            "by_comuna": by_comuna,
            "by_property_type": by_property_type,
            "by_source": by_source,
            "built_area_coverage_by_type": _area_coverage_by_type(active, "has_built_area"),
            "top_house_land_area_gaps_by_comuna": _top_area_gaps_by_comuna(
                active,
                property_type="house",
                field="has_land_area",
            ),
        },
        "snapshot": {
            "active_listing_keys": active_keys,
            "new_active_listing_keys_sample": new_keys[:50],
            "removed_active_listing_keys_sample": removed_keys[:50],
        },
    }


def evaluate_health(metrics: dict[str, Any], *, has_baseline: bool) -> list[dict[str, Any]]:
    checks = {
        PipelineAlertCode.ACTIVE_LISTINGS_LOW: metrics.get("active_listings"),
        PipelineAlertCode.NEW_LISTINGS_LOW: metrics.get("new_active_listings_since_baseline"),
        PipelineAlertCode.PRICE_PARSE_RATE_LOW: metrics.get("price_parse_rate_pct"),
        PipelineAlertCode.M2_PARSE_RATE_LOW: metrics.get("m2_parse_rate_pct"),
        PipelineAlertCode.ROOMS_PARSE_RATE_LOW: metrics.get("rooms_parse_rate_pct"),
        PipelineAlertCode.COMUNA_COVERAGE_LOW: metrics.get("covered_comunas"),
        PipelineAlertCode.TOP_COMUNA_CONCENTRATION_HIGH: metrics.get("top_comuna_pct"),
        PipelineAlertCode.USEFUL_COORDS_LOW: metrics.get("useful_coords_pct"),
        PipelineAlertCode.MICROZONE_RATE_LOW: metrics.get("useful_microzone_pct"),
        PipelineAlertCode.PRICE_HISTORY_USABLE_LOW: metrics.get("price_history_usable_pct"),
        PipelineAlertCode.SINGLE_SOURCE_DEPENDENCY_HIGH: metrics.get("top_source_pct"),
    }
    alerts = []
    for threshold in THRESHOLDS:
        if threshold.code == PipelineAlertCode.NEW_LISTINGS_LOW and not has_baseline:
            continue
        value = checks.get(threshold.code)
        alert = _evaluate_threshold(threshold, value)
        if alert is not None:
            alerts.append(alert)
    return alerts


def overall_status(alerts: list[dict[str, Any]]) -> str:
    if not alerts:
        return STATUS_OK
    return max((alert["status"] for alert in alerts), key=lambda status: STATUS_ORDER[status])


def write_health_report(report: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latest.json"
    md_path = output_dir / "latest.md"
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    archive_json = output_dir / f"pipeline_health_{stamp}.json"
    archive_md = output_dir / f"pipeline_health_{stamp}.md"

    payload = json.dumps(_json_safe(report), ensure_ascii=False, indent=2)
    markdown = _markdown_report(report)
    json_path.write_text(payload, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    archive_json.write_text(payload, encoding="utf-8")
    archive_md.write_text(markdown, encoding="utf-8")
    return md_path, json_path


def print_console_report(report: dict[str, Any], *, md_path: Path | None = None, json_path: Path | None = None) -> None:
    print("== AVM Pipeline Health ==")
    print(f"status\t{report['status']}")
    for key, value in report["metrics"].items():
        print(f"{key}\t{value}")
    print("\n== Alerts ==")
    if not report["alerts"]:
        print("none")
    for alert in report["alerts"]:
        print(f"{alert['status']}\t{alert['code']}\t{alert['message']}")
    if md_path and json_path:
        print("\n== Files ==")
        print(f"markdown\t{md_path}")
        print(f"json\t{json_path}")


def load_baseline(output_dir: Path) -> dict[str, Any] | None:
    path = output_dir / "latest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


async def load_dataset() -> tuple[list[dict[str, Any]], dict[int, int]]:
    async with get_session_factory()() as session:
        result = await session.execute(select(ListingORM))
        listings = [_orm_to_dict(row) for row in result.scalars().all()]
        history_result = await session.execute(
            select(PriceHistoryORM.listing_id, func.count(PriceHistoryORM.id)).group_by(PriceHistoryORM.listing_id)
        )
        price_history_counts = {int(listing_id): int(count) for listing_id, count in history_result.all()}
    return listings, price_history_counts


def _listing_row(row: dict[str, Any], price_history_counts: dict[int, int]) -> dict[str, Any]:
    raw_metadata = row.get("raw_metadata") if isinstance(row.get("raw_metadata"), dict) else {}
    quality_warnings = {str(item) for item in raw_metadata.get("data_quality_warnings", []) if item}
    price = _float_or_none(row.get("price_clp"))
    area = _built_area(row)
    bedrooms = row.get("bedrooms")
    bathrooms = row.get("bathrooms")
    signals = _signals_for_row(row)
    lat = _float_or_none(row.get("lat"))
    lon = _float_or_none(row.get("lon"))
    precision = normalize_geocode_precision(
        row.get("geocode_precision"),
        has_coords=lat is not None and lon is not None,
        raw_metadata=raw_metadata,
        comuna=_norm(row.get("comuna"), "unknown"),
    )
    return {
        "id": row.get("id"),
        "identity_key": _identity_key(row),
        "source": _norm(row.get("source"), "unknown"),
        "status": _norm(row.get("status"), "unknown"),
        "comuna": _norm(row.get("comuna"), "unknown"),
        "property_type": _property_type(row.get("property_type")),
        "has_price": price is not None and price > 0 and "missing_price" not in quality_warnings,
        "has_m2": area is not None and area > 0 and "missing_m2" not in quality_warnings,
        "has_built_area": _has_positive(row.get("built_area_m2")),
        "has_land_area": _has_positive(row.get("land_area_m2")),
        "has_usable_area": _has_positive(row.get("usable_area_m2")),
        "has_area_parse_provenance": bool(raw_metadata.get("area_parse_version")),
        "has_rooms": bedrooms is not None and bathrooms is not None and int(bathrooms or 0) > 0,
        "has_useful_coords": lat is not None and lon is not None and precision in USEFUL_COORD_PRECISIONS,
        "has_useful_microzone": signals.confidence >= 0.55 and bool(signals.landmark_tokens),
        "price_history_count": price_history_counts.get(int(row["id"]), 0) if row.get("id") is not None else 0,
    }


def _evaluate_threshold(threshold: Threshold, value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    numeric = float(value)
    if threshold.critical_below is not None and numeric <= threshold.critical_below:
        return _alert(threshold, STATUS_CRITICAL, value, f"<= {threshold.critical_below}")
    if threshold.warning_below is not None and numeric < threshold.warning_below:
        return _alert(threshold, STATUS_WARNING, value, f"< {threshold.warning_below}")
    if threshold.critical_above is not None and numeric >= threshold.critical_above:
        return _alert(threshold, STATUS_CRITICAL, value, f">= {threshold.critical_above}")
    if threshold.warning_above is not None and numeric > threshold.warning_above:
        return _alert(threshold, STATUS_WARNING, value, f"> {threshold.warning_above}")
    return None


def _alert(threshold: Threshold, status: str, value: Any, threshold_text: str) -> dict[str, Any]:
    return {
        "status": status,
        "code": threshold.code,
        "label": threshold.label,
        "value": value,
        "threshold": threshold_text,
        "message": f"{threshold.label}: {value} breached threshold {threshold_text}",
    }


def _counter_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counter = Counter(row.get(key) or "unknown" for row in rows)
    total = sum(counter.values())
    return [
        {"value": value, "count": count, "pct": _pct(count, total)}
        for value, count in counter.most_common()
    ]


def _coverage_pct(rows: list[dict[str, Any]], *, property_type: str, field: str) -> float:
    items = [row for row in rows if row["property_type"] == property_type]
    return _pct(sum(row[field] for row in items), len(items))


def _area_coverage_by_type(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["property_type"], []).append(row)
    return [
        {
            "property_type": property_type,
            "active_listings": len(items),
            "coverage_pct": _pct(sum(row[field] for row in items), len(items)),
        }
        for property_type, items in sorted(grouped.items())
    ]


def _top_area_gaps_by_comuna(
    rows: list[dict[str, Any]],
    *,
    property_type: str,
    field: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["property_type"] == property_type:
            grouped.setdefault(row["comuna"], []).append(row)
    result = []
    for comuna, items in grouped.items():
        missing = sum(not row[field] for row in items)
        result.append(
            {
                "comuna": comuna,
                "property_type": property_type,
                "active_listings": len(items),
                "missing_count": missing,
                "coverage_pct": _pct(len(items) - missing, len(items)),
            }
        )
    return sorted(result, key=lambda row: (-row["missing_count"], row["coverage_pct"], row["comuna"]))[:20]


def _baseline_active_keys(baseline: dict[str, Any] | None) -> list[str]:
    if not baseline:
        return []
    snapshot = baseline.get("snapshot") if isinstance(baseline.get("snapshot"), dict) else {}
    keys = snapshot.get("active_listing_keys")
    return [str(key) for key in keys] if isinstance(keys, list) else []


def _baseline_summary(baseline: dict[str, Any] | None, metrics: dict[str, Any]) -> dict[str, Any]:
    if not baseline:
        return {"available": False}
    previous_metrics = baseline.get("metrics") if isinstance(baseline.get("metrics"), dict) else {}
    return {
        "available": True,
        "generated_at": baseline.get("generated_at"),
        "active_listings_delta": _delta(metrics.get("active_listings"), previous_metrics.get("active_listings")),
        "price_parse_rate_delta": _delta(metrics.get("price_parse_rate_pct"), previous_metrics.get("price_parse_rate_pct")),
        "m2_parse_rate_delta": _delta(metrics.get("m2_parse_rate_pct"), previous_metrics.get("m2_parse_rate_pct")),
        "useful_coords_delta": _delta(metrics.get("useful_coords_pct"), previous_metrics.get("useful_coords_pct")),
        "microzone_delta": _delta(metrics.get("useful_microzone_pct"), previous_metrics.get("useful_microzone_pct")),
    }


def _delta(current: Any, previous: Any) -> float | int | None:
    if current is None or previous is None:
        return None
    value = float(current) - float(previous)
    if value.is_integer():
        return int(value)
    return round(value, 2)


def _signals_for_row(row: dict[str, Any]) -> Any:
    class Value:
        pass

    value = Value()
    value.title = row.get("title")
    value.raw_metadata = row.get("raw_metadata") if isinstance(row.get("raw_metadata"), dict) else {}
    return signals_from_value(value)


def _orm_to_dict(row: ListingORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source,
        "external_id": row.external_id,
        "fingerprint": row.fingerprint,
        "title": row.title,
        "comuna": row.comuna,
        "property_type": row.property_type,
        "m2": row.m2,
        "built_area_m2": row.built_area_m2,
        "usable_area_m2": row.usable_area_m2,
        "land_area_m2": row.land_area_m2,
        "bedrooms": row.bedrooms,
        "bathrooms": row.bathrooms,
        "lat": row.lat,
        "lon": row.lon,
        "geocode_precision": row.geocode_precision,
        "price_clp": row.price_clp,
        "status": row.status,
        "raw_metadata": row.raw_metadata,
    }


def _identity_key(row: dict[str, Any]) -> str:
    source = _norm(row.get("source"), "unknown")
    external_id = str(row.get("external_id") or "").strip()
    if external_id:
        return f"{source}|{external_id}"
    return f"fingerprint|{row.get('fingerprint') or row.get('id')}"


def _built_area(row: dict[str, Any]) -> float | None:
    for key in ("built_area_m2", "usable_area_m2", "m2"):
        value = _float_or_none(row.get(key))
        if value is not None and value > 0:
            return value
    return None


def _has_positive(value: Any) -> bool:
    parsed = _float_or_none(value)
    return parsed is not None and parsed > 0


def _pct(part: int | float, total: int | float) -> float:
    if not total:
        return 0.0
    return round(float(part) / float(total) * 100, 2)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm(value: Any, default: str) -> str:
    text = str(value or "").strip().lower()
    return text or default


def _markdown_report(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        "# AVM Pipeline Health",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Status: `{report['status']}`",
        f"- Active listings: {metrics['active_listings']}",
        f"- New active listings since baseline: {metrics['new_active_listings_since_baseline']}",
        f"- Price parse rate: {metrics['price_parse_rate_pct']}%",
        f"- M2 parse rate: {metrics['m2_parse_rate_pct']}%",
        f"- Bedrooms/bathrooms parse rate: {metrics['rooms_parse_rate_pct']}%",
        f"- Covered comunas: {metrics['covered_comunas']}",
        f"- Useful coords: {metrics['useful_coords_pct']}%",
        f"- Useful microzone: {metrics['useful_microzone_pct']}%",
        f"- Usable price history: {metrics['price_history_usable_pct']}%",
        f"- House land area coverage: {metrics['house_land_area_coverage_pct']}%",
        f"- Apartment usable area coverage: {metrics['apartment_usable_area_coverage_pct']}%",
        f"- Area parse provenance: {metrics['area_parse_provenance_count']} ({metrics['area_parse_provenance_pct']}%)",
        f"- Top source: {metrics['top_source']} ({metrics['top_source_pct']}%)",
        "",
        "## Alerts",
        "",
        _markdown_table(report["alerts"]) if report["alerts"] else "_No alerts._",
        "",
        "## Distribution By Comuna",
        "",
        _markdown_table(report["distributions"]["by_comuna"]),
        "",
        "## Distribution By Property Type",
        "",
        _markdown_table(report["distributions"]["by_property_type"]),
        "",
        "## Built Area Coverage By Property Type",
        "",
        _markdown_table(report["distributions"]["built_area_coverage_by_type"]),
        "",
        "## Worst House Land Area Coverage By Comuna",
        "",
        _markdown_table(report["distributions"]["top_house_land_area_gaps_by_comuna"]),
        "",
        "## Baseline Comparison",
        "",
        _markdown_table([report["baseline"]]),
    ]
    return "\n".join(lines) + "\n"


def _markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No data._"
    columns = list(rows[0].keys())
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate AVM data pipeline health report.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    baseline = load_baseline(output_dir)
    listings, price_history_counts = await load_dataset()
    report = build_health_report(listings, price_history_counts, baseline=baseline)
    md_path, json_path = write_health_report(report, output_dir=output_dir)
    print_console_report(report, md_path=md_path, json_path=json_path)
    return 0 if report["status"] != STATUS_CRITICAL else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
