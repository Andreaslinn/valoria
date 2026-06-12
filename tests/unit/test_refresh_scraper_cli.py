from __future__ import annotations

from datetime import UTC, datetime

from scripts import refresh_scraper as refresh_cli
from workers.refresh_scraper import RefreshStats


def test_parse_args_accepts_operational_controls():
    args = refresh_cli.parse_args(
        [
            "--limit",
            "5",
            "--stale-days",
            "14",
            "--cooldown-hours",
            "2",
            "--dry-run",
            "--source",
            "yapo",
            "--only-active",
            "--comuna",
            "nunoa",
            "--property-type",
            "apartment",
            "--sleep",
            "1.5",
            "--order",
            "oldest_seen",
            "--max-errors",
            "2",
            "--stop-on-block",
            "--examples",
            "4",
        ]
    )

    assert args.limit == 5
    assert args.stale_days == 14
    assert args.cooldown_hours == 2
    assert args.dry_run is True
    assert args.source == "yapo"
    assert args.only_active is True
    assert args.comuna == "nunoa"
    assert args.property_type == "apartment"
    assert args.sleep == 1.5
    assert args.order == "oldest_seen"
    assert args.max_errors == 2
    assert args.stop_on_block is True
    assert args.examples == 4


async def test_run_refresh_once_calls_worker_with_limit_and_stale_days(monkeypatch):
    args = refresh_cli.parse_args(["--limit", "7", "--stale-days", "21", "--cooldown-hours", "3"])
    session_factory = object()
    http_client = object()
    captured = {}
    traceability = iter(
        [
            refresh_cli.RefreshTraceability(
                active_with_last_refresh_attempted_at=10,
                max_last_refresh_attempted_at=datetime(2026, 6, 1, tzinfo=UTC),
            ),
            refresh_cli.RefreshTraceability(
                active_with_last_refresh_attempted_at=12,
                max_last_refresh_attempted_at=datetime(2026, 6, 2, tzinfo=UTC),
            ),
        ]
    )

    async def fake_collect_refresh_traceability(received_session_factory):
        assert received_session_factory is session_factory
        return next(traceability)

    async def fake_run_refresh_scraper(received_session_factory, **kwargs):
        captured.update(kwargs)
        assert received_session_factory is session_factory
        return RefreshStats(selected=7, fetched=7, processed=6, timeouts=1)

    monkeypatch.setattr(refresh_cli, "collect_refresh_traceability", fake_collect_refresh_traceability)
    monkeypatch.setattr(refresh_cli, "run_refresh_scraper", fake_run_refresh_scraper)

    summary = await refresh_cli.run_refresh_once(
        args,
        session_factory=session_factory,
        http_client=http_client,
    )

    assert captured["http_client"] is http_client
    assert captured["limit"] == 7
    assert captured["stale_days"] == 21
    assert captured["cooldown_hours"] == 3
    assert summary.mode == "run"
    assert summary.attempts_realized == 7
    assert summary.traceability_delta == 2


async def test_dry_run_selects_candidates_without_scheduler_or_worker(monkeypatch):
    args = refresh_cli.parse_args(["--limit", "3", "--stale-days", "30", "--dry-run"])
    session_factory = object()
    captured = {}

    async def fake_collect_refresh_traceability(_session_factory):
        return refresh_cli.RefreshTraceability(
            active_with_last_refresh_attempted_at=0,
            max_last_refresh_attempted_at=None,
        )

    async def fake_select_refresh_candidates(received_session_factory, **kwargs):
        captured.update(kwargs)
        assert received_session_factory is session_factory
        return [object(), object(), object()]

    async def fake_count_refresh_candidates(received_session_factory, **kwargs):
        assert received_session_factory is session_factory
        return 9

    async def fail_run_refresh_scraper(*_args, **_kwargs):
        raise AssertionError("dry-run must not run the refresh worker")

    monkeypatch.setattr(refresh_cli, "collect_refresh_traceability", fake_collect_refresh_traceability)
    monkeypatch.setattr(refresh_cli, "count_refresh_candidates", fake_count_refresh_candidates)
    monkeypatch.setattr(refresh_cli, "select_refresh_candidates", fake_select_refresh_candidates)
    monkeypatch.setattr(refresh_cli, "run_refresh_scraper", fail_run_refresh_scraper)

    summary = await refresh_cli.run_refresh_once(args, session_factory=session_factory)

    assert captured["limit"] == 3
    assert captured["stale_days"] == 30
    assert captured["source"] == "yapo"
    assert summary.mode == "dry-run"
    assert summary.stats.candidates_total == 9
    assert summary.stats.selected == 3
    assert summary.attempts_realized == 0
    assert summary.traceability_delta == 0


def test_print_summary_includes_operational_traceability(capsys):
    summary = refresh_cli.RefreshRunSummary(
        mode="run",
        source="yapo",
        limit=5,
        stale_days=30,
        cooldown_hours=24,
        order="watchlist_first",
        stats=RefreshStats(
            selected=5,
            candidates_total=12,
            attempted=5,
            fetched=4,
            processed=3,
            refreshed_ok=3,
            updated=2,
            unchanged=1,
            removed=1,
            inactive=1,
            timeouts=1,
            server_errors=1,
            unexpected_errors=2,
        ),
        traceability_before=refresh_cli.RefreshTraceability(
            active_with_last_refresh_attempted_at=0,
            max_last_refresh_attempted_at=None,
        ),
        traceability_after=refresh_cli.RefreshTraceability(
            active_with_last_refresh_attempted_at=3,
            max_last_refresh_attempted_at=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        ),
    )

    refresh_cli.print_summary(summary)

    out = capsys.readouterr().out
    assert "fuente: yapo" in out
    assert "candidates_total\t12" in out
    assert "selected_candidates\t5" in out
    assert "attempts_realized\t5" in out
    assert "actualizados\t2" in out
    assert "sin_cambios\t1" in out
    assert "http_errors\t3" in out
    assert "price_changes_detected\t0" in out
    assert "traceability_before_active_with_last_refresh_attempted_at\t0" in out
    assert "traceability_after_active_with_last_refresh_attempted_at\t3" in out
    assert "traceability_delta_active_with_last_refresh_attempted_at\t3" in out
    assert "traceability_after_max_last_refresh_attempted_at\t2026-06-02T12:00:00+00:00" in out
    assert "scheduler_required\tFalse" in out
