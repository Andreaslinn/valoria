from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import workers.scheduler as scheduler_module
from workers.alerts_job import AlertJobStats
from workers.refresh_scraper import DEFAULT_REFRESH_LIMIT as WORKER_DEFAULT_REFRESH_LIMIT
from workers.refresh_scraper import RefreshStats
from workers.scheduler import (
    ALERTS_JOB_ID,
    DEFAULT_SCHEDULER_REFRESH_LIMIT,
    DISCOVERY_JOB_ID,
    PORTFOLIO_SNAPSHOTS_JOB_ID,
    REFRESH_JOB_ID,
    UF_DAILY_SNAPSHOT_JOB_ID,
    SchedulerConfig,
    SchedulerJobs,
    StartupFreshness,
    build_scheduler,
    scheduler_config_from_env,
    should_run_startup_alerts,
    should_run_startup_refresh,
)


async def _discovery() -> None:
    return None


async def _refresh() -> None:
    return None


async def _alerts() -> None:
    return None


async def _uf_snapshot() -> None:
    return None


async def _portfolio_snapshots() -> None:
    return None


def test_scheduler_registers_limited_jobs_by_default() -> None:
    scheduler = build_scheduler(
        jobs=SchedulerJobs(
            discovery=_discovery,
            refresh=_refresh,
            alerts=_alerts,
            uf_daily_snapshot=_uf_snapshot,
            portfolio_snapshots=_portfolio_snapshots,
        ),
        config=SchedulerConfig(),
    )
    jobs = scheduler.get_jobs()

    assert SchedulerConfig().refresh_limit == 5
    assert len(jobs) == 3
    assert {job.id for job in jobs} == {
        REFRESH_JOB_ID,
        ALERTS_JOB_ID,
        UF_DAILY_SNAPSHOT_JOB_ID,
    }


def test_scheduler_registers_discovery_when_explicitly_enabled() -> None:
    scheduler = build_scheduler(
        jobs=SchedulerJobs(discovery=_discovery, refresh=_refresh, alerts=_alerts, uf_daily_snapshot=_uf_snapshot),
        config=SchedulerConfig(enable_discovery=True),
    )
    jobs = scheduler.get_jobs()

    assert len(jobs) == 4
    assert {job.id for job in jobs} == {
        DISCOVERY_JOB_ID,
        REFRESH_JOB_ID,
        ALERTS_JOB_ID,
        UF_DAILY_SNAPSHOT_JOB_ID,
    }


def test_scheduler_registers_portfolio_snapshots_when_enabled() -> None:
    scheduler = build_scheduler(
        jobs=SchedulerJobs(
            discovery=_discovery,
            refresh=_refresh,
            alerts=_alerts,
            uf_daily_snapshot=_uf_snapshot,
            portfolio_snapshots=_portfolio_snapshots,
        ),
        config=SchedulerConfig(enable_portfolio_snapshots=True),
    )
    jobs_by_id = {job.id: job for job in scheduler.get_jobs()}

    assert PORTFOLIO_SNAPSHOTS_JOB_ID in jobs_by_id
    assert jobs_by_id[PORTFOLIO_SNAPSHOTS_JOB_ID].func is _portfolio_snapshots
    assert _trigger_fields(jobs_by_id[PORTFOLIO_SNAPSHOTS_JOB_ID].trigger) == {
        "minute": "0",
        "hour": "14",
        "day_of_week": "*",
    }


def test_scheduler_jobs_call_their_configured_functions() -> None:
    scheduler = build_scheduler(
        jobs=SchedulerJobs(
            discovery=_discovery,
            refresh=_refresh,
            alerts=_alerts,
            uf_daily_snapshot=_uf_snapshot,
            portfolio_snapshots=_portfolio_snapshots,
        ),
        config=SchedulerConfig(enable_discovery=True),
    )

    jobs_by_id = {job.id: job for job in scheduler.get_jobs()}

    assert jobs_by_id[DISCOVERY_JOB_ID].func is _discovery
    assert jobs_by_id[REFRESH_JOB_ID].func is _refresh
    assert jobs_by_id[ALERTS_JOB_ID].func is _alerts
    assert jobs_by_id[UF_DAILY_SNAPSHOT_JOB_ID].func is _uf_snapshot


def test_default_alerts_schedule_runs_after_listing_update_jobs() -> None:
    config = SchedulerConfig(enable_discovery=True)
    scheduler = build_scheduler(
        jobs=SchedulerJobs(discovery=_discovery, refresh=_refresh, alerts=_alerts, uf_daily_snapshot=_uf_snapshot),
        config=config,
    )
    jobs_by_id = {job.id: job for job in scheduler.get_jobs()}

    assert _minute_of_day(config.discovery_cron) < _minute_of_day(config.alerts_cron)
    assert _minute_of_day(config.refresh_cron) < _minute_of_day(config.alerts_cron)
    assert _minute_of_day(config.alerts_cron) < _minute_of_day(config.portfolio_snapshots_cron)
    assert _trigger_fields(jobs_by_id[DISCOVERY_JOB_ID].trigger) == {
        "minute": "0",
        "hour": "10",
        "day_of_week": "*",
    }
    assert _trigger_fields(jobs_by_id[REFRESH_JOB_ID].trigger) == {
        "minute": "0",
        "hour": "12",
        "day_of_week": "mon,wed,fri",
    }
    assert _trigger_fields(jobs_by_id[ALERTS_JOB_ID].trigger) == {
        "minute": "0",
        "hour": "13",
        "day_of_week": "*",
    }
    assert _trigger_fields(jobs_by_id[UF_DAILY_SNAPSHOT_JOB_ID].trigger) == {
        "minute": "0",
        "hour": "8",
        "day_of_week": "*",
    }


async def test_alerts_job_waits_until_listing_update_lock_is_released(monkeypatch) -> None:
    calls: list[tuple[object, float, int]] = []

    async def fake_run_alerts_job(
        session_factory,
        *,
        threshold_pct: float,
        lookback_days: int,
    ) -> AlertJobStats:
        calls.append((session_factory, threshold_pct, lookback_days))
        return AlertJobStats()

    session_factory = object()
    monkeypatch.setattr(scheduler_module, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(scheduler_module, "run_alerts_job", fake_run_alerts_job)

    lock = scheduler_module._DISCOVERY_REFRESH_LOCK
    await lock.acquire()
    try:
        task = asyncio.create_task(scheduler_module.alerts_job())
        await asyncio.sleep(0)

        assert calls == []
    finally:
        lock.release()

    await task

    assert calls == [(session_factory, 5.0, 30)]


def test_scheduler_env_vars_modify_schedules_and_limits(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULER_DISCOVERY_CRON", "5 6 * * *")
    monkeypatch.setenv("SCHEDULER_DISCOVERY_MAX_PAGES", "1")
    monkeypatch.setenv("SCHEDULER_DISCOVERY_SLEEP_SECONDS", "3.5")
    monkeypatch.setenv("SCHEDULER_ENABLE_DISCOVERY", "true")
    monkeypatch.setenv("SCHEDULER_ENABLE_PORTAL", "true")
    monkeypatch.setenv("SCHEDULER_STARTUP_CATCHUP_ENABLED", "true")
    monkeypatch.setenv("SCHEDULER_STARTUP_REFRESH_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_STARTUP_ALERTS_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_STARTUP_MIN_STALE_HOURS", "48")
    monkeypatch.setenv("SCHEDULER_REFRESH_CRON", "10 7 * * tue,thu")
    monkeypatch.setenv("SCHEDULER_ALERTS_CRON", "15 8 * * *")
    monkeypatch.setenv("SCHEDULER_REFRESH_LIMIT", "17")
    monkeypatch.setenv("SCHEDULER_REFRESH_STALE_DAYS", "12")
    monkeypatch.setenv("SCHEDULER_REFRESH_COOLDOWN_HOURS", "36")
    monkeypatch.setenv("SCHEDULER_ALERTS_THRESHOLD_PCT", "7.5")
    monkeypatch.setenv("SCHEDULER_ALERTS_LOOKBACK_DAYS", "14")
    monkeypatch.setenv("SCHEDULER_ENABLE_UF_DAILY_SNAPSHOT", "true")
    monkeypatch.setenv("UF_REFRESH_ON_STARTUP", "false")
    monkeypatch.setenv("UF_REFRESH_HOUR", "9")
    monkeypatch.setenv("PORTFOLIO_SNAPSHOTS_ENABLED", "true")
    monkeypatch.setenv("PORTFOLIO_SNAPSHOTS_CRON", "30 15 * * *")
    monkeypatch.setenv("PORTFOLIO_SNAPSHOTS_LIMIT_USERS", "3")
    monkeypatch.setenv("PORTFOLIO_SNAPSHOTS_LIMIT_ITEMS_PER_USER", "4")
    monkeypatch.setenv("PORTFOLIO_SNAPSHOTS_MIN_INTERVAL_HOURS", "21")
    monkeypatch.setenv("PORTFOLIO_SNAPSHOTS_DRY_RUN", "true")
    monkeypatch.setenv("PORTFOLIO_SNAPSHOTS_USER_ID", "42")
    monkeypatch.setenv("PORTFOLIO_SNAPSHOTS_STARTUP_CATCHUP_ENABLED", "true")

    config = scheduler_config_from_env()
    scheduler = build_scheduler(
        jobs=SchedulerJobs(discovery=_discovery, refresh=_refresh, alerts=_alerts, uf_daily_snapshot=_uf_snapshot)
    )
    jobs_by_id = {job.id: job for job in scheduler.get_jobs()}

    assert config.discovery_cron == "5 6 * * *"
    assert config.discovery_max_pages == 1
    assert config.discovery_sleep_seconds == 3.5
    assert config.enable_discovery is True
    assert config.enable_portal is True
    assert config.startup_catchup_enabled is True
    assert config.startup_refresh_enabled is False
    assert config.startup_alerts_enabled is False
    assert config.startup_min_stale_hours == 48
    assert config.refresh_cron == "10 7 * * tue,thu"
    assert config.alerts_cron == "15 8 * * *"
    assert config.refresh_limit == 17
    assert config.refresh_stale_days == 12
    assert config.refresh_cooldown_hours == 36
    assert config.alerts_threshold_pct == 7.5
    assert config.alerts_lookback_days == 14
    assert config.enable_uf_daily_snapshot is True
    assert config.uf_refresh_on_startup is False
    assert config.uf_refresh_hour == 9
    assert config.enable_portfolio_snapshots is True
    assert config.portfolio_snapshots_cron == "30 15 * * *"
    assert config.portfolio_snapshots_limit_users == 3
    assert config.portfolio_snapshots_limit_items_per_user == 4
    assert config.portfolio_snapshots_min_interval_hours == 21
    assert config.portfolio_snapshots_dry_run is True
    assert config.portfolio_snapshots_user_id == 42
    assert config.portfolio_snapshots_startup_catchup_enabled is True
    assert _trigger_fields(jobs_by_id[DISCOVERY_JOB_ID].trigger) == {
        "minute": "5",
        "hour": "6",
        "day_of_week": "*",
    }
    assert _trigger_fields(jobs_by_id[REFRESH_JOB_ID].trigger) == {
        "minute": "10",
        "hour": "7",
        "day_of_week": "tue,thu",
    }
    assert _trigger_fields(jobs_by_id[ALERTS_JOB_ID].trigger) == {
        "minute": "15",
        "hour": "8",
        "day_of_week": "*",
    }
    assert _trigger_fields(jobs_by_id[UF_DAILY_SNAPSHOT_JOB_ID].trigger) == {
        "minute": "0",
        "hour": "9",
        "day_of_week": "*",
    }


def test_discovery_and_refresh_do_not_share_the_same_function() -> None:
    scheduler = build_scheduler(
        jobs=SchedulerJobs(discovery=_discovery, refresh=_refresh, alerts=_alerts, uf_daily_snapshot=_uf_snapshot),
        config=SchedulerConfig(enable_discovery=True),
    )

    jobs_by_id = {job.id: job for job in scheduler.get_jobs()}

    assert jobs_by_id[DISCOVERY_JOB_ID].func is not jobs_by_id[REFRESH_JOB_ID].func


def test_scheduler_env_defaults_do_not_fall_back_to_worker_refresh_limit() -> None:
    config = scheduler_config_from_env({})

    assert DEFAULT_SCHEDULER_REFRESH_LIMIT == 5
    assert WORKER_DEFAULT_REFRESH_LIMIT == 100
    assert config.refresh_limit == DEFAULT_SCHEDULER_REFRESH_LIMIT
    assert config.discovery_max_pages == 0
    assert config.enable_discovery is False
    assert config.enable_portal is False
    assert config.startup_catchup_enabled is False
    assert config.enable_uf_daily_snapshot is True
    assert config.enable_portfolio_snapshots is False
    assert config.portfolio_snapshots_limit_users == 10
    assert config.portfolio_snapshots_limit_items_per_user == 20


def test_discovery_yapo_targets_use_all_configured_targets_by_default() -> None:
    targets = scheduler_module._discovery_yapo_targets(SchedulerConfig())

    assert len(targets) == len(scheduler_module.YAPO_TARGETS)
    assert targets[0]["label"] == "general"
    assert any(target["label"] == "providencia" for target in targets)
    assert any(target["label"] == "providencia_house" for target in targets)


def test_discovery_yapo_targets_can_be_capped_for_beta() -> None:
    targets = scheduler_module._discovery_yapo_targets(SchedulerConfig(discovery_max_pages=1))

    assert len(targets) == len(scheduler_module.YAPO_TARGETS)
    assert {target["max_pages"] for target in targets} == {1}


async def test_startup_catchup_disabled_does_not_collect_or_run(monkeypatch) -> None:
    async def fail_collect_startup_freshness(*_args, **_kwargs):
        raise AssertionError("catch-up disabled must not touch freshness queries")

    monkeypatch.setattr(
        scheduler_module,
        "collect_startup_freshness",
        fail_collect_startup_freshness,
    )

    called = False

    async def fake_uf_snapshot():
        nonlocal called
        called = True

    monkeypatch.setattr(scheduler_module, "uf_daily_snapshot_job", fake_uf_snapshot)

    result = await scheduler_module.run_startup_catchup(config=SchedulerConfig())

    assert result.refresh_decision.run is False
    assert result.refresh_decision.reason == "startup_catchup_disabled"
    assert result.alerts_decision.run is False
    assert result.alerts_decision.reason == "startup_catchup_disabled"
    assert result.refresh_stats is None
    assert result.alerts_stats is None
    assert called is True


def test_startup_refresh_skips_when_recent() -> None:
    now = datetime(2026, 6, 18, 12, tzinfo=UTC)
    config = SchedulerConfig(startup_catchup_enabled=True, enable_uf_daily_snapshot=False)
    freshness = StartupFreshness(
        generated_at=now,
        refresh_candidates=12,
        latest_refresh_attempted_at=now - timedelta(hours=2),
    )

    decision = should_run_startup_refresh(config, freshness, now=now)

    assert decision.run is False
    assert decision.reason == "refresh_recent"
    assert decision.candidates == 12
    assert decision.limit == 5


def test_startup_refresh_skips_when_no_cron_window_was_missed() -> None:
    now = datetime(2026, 6, 18, 12, tzinfo=UTC)
    config = SchedulerConfig(
        startup_catchup_enabled=True,
        refresh_cron="0 23 31 12 *",
        startup_min_stale_hours=1,
    )
    freshness = StartupFreshness(
        generated_at=now,
        refresh_candidates=4,
        latest_refresh_attempted_at=now - timedelta(days=10),
    )

    decision = should_run_startup_refresh(config, freshness, now=now)

    assert decision.run is False
    assert decision.reason == "no_missed_refresh_window"


async def test_startup_catchup_runs_stale_refresh_with_safe_limit(monkeypatch) -> None:
    now = datetime(2026, 6, 18, 12, tzinfo=UTC)
    captured: dict[str, object] = {}

    async def fake_collect_startup_freshness(session_factory, config, *, now):
        captured["session_factory"] = session_factory
        captured["stale_days"] = config.refresh_stale_days
        return StartupFreshness(
            generated_at=now,
            refresh_candidates=9,
            latest_refresh_attempted_at=now - timedelta(days=3),
            latest_alert_created_at=now,
        )

    async def fake_run_startup_refresh(config, session_factory, *, now):
        captured["refresh_limit"] = config.refresh_limit
        captured["refresh_now"] = now
        return RefreshStats(
            candidates_total=9,
            selected=config.refresh_limit,
            attempted=config.refresh_limit,
            fetched=config.refresh_limit,
            refreshed_ok=config.refresh_limit,
        )

    monkeypatch.setattr(
        scheduler_module,
        "collect_startup_freshness",
        fake_collect_startup_freshness,
    )
    monkeypatch.setattr(scheduler_module, "_run_startup_refresh", fake_run_startup_refresh)

    session_factory = object()
    result = await scheduler_module.run_startup_catchup(
        config=SchedulerConfig(startup_catchup_enabled=True),
        session_factory=session_factory,
        now=now,
    )

    assert captured["session_factory"] is session_factory
    assert captured["refresh_limit"] == 5
    assert captured["refresh_now"] == now
    assert result.refresh_decision.run is True
    assert result.refresh_decision.reason == "refresh_stale"
    assert result.refresh_stats is not None
    assert result.refresh_stats.attempted == 5
    assert result.alerts_decision.reason == "alerts_recent"


async def test_startup_refresh_uses_yapo_only_when_portal_is_disabled(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_refresh_scraper(received_session_factory, **kwargs):
        captured["session_factory"] = received_session_factory
        captured.update(kwargs)
        return RefreshStats()

    monkeypatch.setattr(scheduler_module, "run_refresh_scraper", fake_run_refresh_scraper)

    session_factory = object()
    await scheduler_module._run_startup_refresh(
        SchedulerConfig(startup_catchup_enabled=True, enable_portal=False),
        session_factory,
    )

    assert captured["session_factory"] is session_factory
    assert captured["source"] == "yapo"
    assert captured["limit"] == 5
    assert captured["stop_on_block"] is True


def test_startup_alerts_run_or_skip_by_configuration() -> None:
    now = datetime(2026, 6, 18, 12, tzinfo=UTC)
    stale_freshness = StartupFreshness(
        generated_at=now,
        latest_alert_created_at=now - timedelta(days=2),
    )
    recent_freshness = StartupFreshness(
        generated_at=now,
        latest_alert_created_at=now - timedelta(hours=2),
    )

    disabled = should_run_startup_alerts(
        SchedulerConfig(startup_catchup_enabled=True, startup_alerts_enabled=False),
        stale_freshness,
        now=now,
    )
    stale = should_run_startup_alerts(
        SchedulerConfig(startup_catchup_enabled=True),
        stale_freshness,
        now=now,
    )
    recent = should_run_startup_alerts(
        SchedulerConfig(startup_catchup_enabled=True),
        recent_freshness,
        now=now,
    )

    assert disabled.run is False
    assert disabled.reason == "startup_alerts_disabled"
    assert stale.run is True
    assert stale.reason == "alerts_stale"
    assert recent.run is False
    assert recent.reason == "alerts_recent"


async def test_startup_refresh_failure_does_not_prevent_scheduler_registration(
    monkeypatch,
) -> None:
    now = datetime(2026, 6, 18, 12, tzinfo=UTC)

    async def fake_collect_startup_freshness(_session_factory, _config, *, now):
        return StartupFreshness(
            generated_at=now,
            refresh_candidates=5,
            latest_refresh_attempted_at=now - timedelta(days=5),
            latest_alert_created_at=now,
        )

    async def fail_run_startup_refresh(*_args, **_kwargs):
        raise RuntimeError("network failure")

    monkeypatch.setattr(
        scheduler_module,
        "collect_startup_freshness",
        fake_collect_startup_freshness,
    )
    monkeypatch.setattr(scheduler_module, "_run_startup_refresh", fail_run_startup_refresh)

    config = SchedulerConfig(startup_catchup_enabled=True, enable_uf_daily_snapshot=False)
    result = await scheduler_module.run_startup_catchup(
        config=config,
        session_factory=object(),
        now=now,
    )
    scheduler = build_scheduler(
        jobs=SchedulerJobs(discovery=_discovery, refresh=_refresh, alerts=_alerts, uf_daily_snapshot=_uf_snapshot),
        config=config,
    )

    assert result.refresh_decision.run is False
    assert result.refresh_decision.reason == "startup_refresh_failed"
    assert {job.id for job in scheduler.get_jobs()} == {REFRESH_JOB_ID, ALERTS_JOB_ID}


def _trigger_fields(trigger) -> dict[str, str]:
    fields = {field.name: str(field) for field in trigger.fields}
    return {
        "minute": fields["minute"],
        "hour": fields["hour"],
        "day_of_week": fields["day_of_week"],
    }


def _minute_of_day(cron: str) -> int:
    minute, hour, *_ = cron.split()
    return int(hour) * 60 + int(minute)
