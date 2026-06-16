from __future__ import annotations

from datetime import UTC, datetime

from scripts.data_freshness_report import DataFreshnessReport, report_markdown


def test_data_freshness_report_serializes_datetimes_and_counts() -> None:
    generated_at = datetime(2026, 6, 16, 10, 0, tzinfo=UTC)
    report = DataFreshnessReport(
        generated_at=generated_at,
        total_listings=10,
        active_listings=8,
        incomplete_listings=1,
        removed_listings=1,
        max_scraped_at=generated_at,
        max_last_seen_at=generated_at,
        max_last_refresh_attempted_at=None,
        price_history_points=20,
        max_price_history_observed_at=generated_at,
        alerts_total=2,
        alerts_unread=1,
        by_source={"yapo": 10},
        by_status={"active": 8, "removed": 1},
        by_last_refresh_status={"ok": 3},
    )

    payload = report.to_dict()

    assert payload["generated_at"] == "2026-06-16T10:00:00+00:00"
    assert payload["max_last_refresh_attempted_at"] is None
    assert payload["by_source"] == {"yapo": 10}


def test_report_markdown_includes_core_freshness_fields() -> None:
    generated_at = datetime(2026, 6, 16, 10, 0, tzinfo=UTC)
    report = DataFreshnessReport(
        generated_at=generated_at,
        total_listings=10,
        active_listings=8,
        incomplete_listings=1,
        removed_listings=1,
        max_scraped_at=generated_at,
        max_last_seen_at=generated_at,
        max_last_refresh_attempted_at=generated_at,
        price_history_points=20,
        max_price_history_observed_at=generated_at,
        alerts_total=2,
        alerts_unread=1,
        by_source={"yapo": 10},
        by_status={"active": 8},
        by_last_refresh_status={"ok": 3},
    )

    markdown = report_markdown(report)

    assert "Last scraped_at" in markdown
    assert "Last refresh attempted" in markdown
    assert "Price history points: 20" in markdown
