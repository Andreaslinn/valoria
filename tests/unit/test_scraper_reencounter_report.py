from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.scraper_reencounter_report import (
    build_report,
    build_schema_error_report,
    markdown_report,
    write_report,
)

NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)


def _listing(
    *,
    id: int,
    source: str = "yapo",
    comuna: str = "nunoa",
    property_type: str = "apartment",
    status: str = "active",
    created_days_ago: int = 40,
    last_seen_days_ago: int | None = 1,
) -> dict:
    return {
        "id": id,
        "source": source,
        "comuna": comuna,
        "property_type": property_type,
        "status": status,
        "created_at": NOW - timedelta(days=created_days_ago),
        "last_seen_at": None if last_seen_days_ago is None else NOW - timedelta(days=last_seen_days_ago),
    }


def test_build_report_uses_last_seen_for_active_recency_and_reencounter() -> None:
    report = build_report(
        [
            _listing(id=1, source="yapo", comuna="nunoa", last_seen_days_ago=2),
            _listing(id=2, source="portalinmobiliario", comuna="las_condes", last_seen_days_ago=20),
            _listing(id=3, source="yapo", comuna="nunoa", property_type="house", last_seen_days_ago=50),
            _listing(id=4, source="yapo", comuna="nunoa", created_days_ago=2, last_seen_days_ago=0),
            _listing(id=5, source="manual", comuna="providencia", status="removed", last_seen_days_ago=1),
        ],
        generated_at=NOW,
    )

    summary = report["summary"]
    assert summary["measurement_field"] == "last_seen_at"
    assert summary["total_listings"] == 5
    assert summary["active_listings"] == 4
    assert summary["seen_last_24h"] == 1
    assert summary["seen_last_7d"] == 2
    assert summary["seen_last_30d"] == 3
    assert summary["not_seen_over_30d"] == 1
    assert summary["not_seen_over_45d"] == 1
    assert summary["reencounter_7d_denominator"] == 3
    assert summary["reencounter_30d_denominator"] == 3
    assert summary["reencounter_7d_pct"] == 33.33
    assert summary["reencounter_30d_pct"] == 66.67


def test_build_report_splits_metrics_by_requested_dimensions() -> None:
    report = build_report(
        [
            _listing(id=1, source="yapo", comuna="nunoa", property_type="apartment"),
            _listing(id=2, source="yapo", comuna="nunoa", property_type="house", last_seen_days_ago=50),
            _listing(id=3, source="manual", comuna="providencia", property_type="apartment", status="removed"),
        ],
        generated_at=NOW,
    )

    by_source = {row["value"]: row for row in report["distributions"]["by_source"]}
    by_comuna = {row["value"]: row for row in report["distributions"]["by_comuna"]}
    by_property_type = {row["value"]: row for row in report["distributions"]["by_property_type"]}
    by_status = {row["value"]: row for row in report["distributions"]["by_status"]}

    assert by_source["yapo"]["total_listings"] == 2
    assert by_source["yapo"]["not_seen_over_45d"] == 1
    assert by_comuna["nunoa"]["active_listings"] == 2
    assert by_property_type["apartment"]["total_listings"] == 2
    assert by_status["removed"]["total_listings"] == 1
    assert by_status["active"]["active_listings"] == 2


def test_markdown_and_json_report_are_written() -> None:
    report = build_report([_listing(id=1)], generated_at=NOW)
    output_dir = Path("reports/test_scraper_reencounter_report")

    shutil.rmtree(output_dir, ignore_errors=True)
    try:
        artifacts = write_report(report, output_dir=output_dir)

        assert artifacts.markdown_path == output_dir / "latest.md"
        assert artifacts.json_path == output_dir / "latest.json"
        assert artifacts.snapshot_markdown_path.exists()
        assert artifacts.snapshot_json_path.exists()
        assert "# Scraper Reencounter Report" in markdown_report(report)
        payload = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
        assert payload["summary"]["active_listings"] == 1
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_schema_error_report_is_written_when_last_seen_column_is_missing() -> None:
    report = build_schema_error_report(["last_seen_at"], generated_at=NOW)
    markdown = markdown_report(report)

    assert report["status"] == "schema_error"
    assert report["summary"]["missing_columns"] == ["last_seen_at"]
    assert "Apply the last_seen_at migration" in markdown
