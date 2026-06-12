from __future__ import annotations

import asyncio

import workers.scheduler as scheduler_module
from workers.alerts_job import AlertJobStats
from workers.scheduler import (
    ALERTS_JOB_ID,
    DISCOVERY_JOB_ID,
    REFRESH_JOB_ID,
    SchedulerConfig,
    SchedulerJobs,
    build_scheduler,
    scheduler_config_from_env,
)


async def _discovery() -> None:
    return None


async def _refresh() -> None:
    return None


async def _alerts() -> None:
    return None


def test_scheduler_registers_discovery_refresh_and_alert_jobs() -> None:
    scheduler = build_scheduler(
        jobs=SchedulerJobs(discovery=_discovery, refresh=_refresh, alerts=_alerts),
        config=SchedulerConfig(),
    )
    jobs = scheduler.get_jobs()

    assert len(jobs) == 3
    assert {job.id for job in jobs} == {
        DISCOVERY_JOB_ID,
        REFRESH_JOB_ID,
        ALERTS_JOB_ID,
    }


def test_scheduler_jobs_call_their_configured_functions() -> None:
    scheduler = build_scheduler(
        jobs=SchedulerJobs(discovery=_discovery, refresh=_refresh, alerts=_alerts),
        config=SchedulerConfig(),
    )

    jobs_by_id = {job.id: job for job in scheduler.get_jobs()}

    assert jobs_by_id[DISCOVERY_JOB_ID].func is _discovery
    assert jobs_by_id[REFRESH_JOB_ID].func is _refresh
    assert jobs_by_id[ALERTS_JOB_ID].func is _alerts


def test_default_alerts_schedule_runs_after_listing_update_jobs() -> None:
    config = SchedulerConfig()
    scheduler = build_scheduler(
        jobs=SchedulerJobs(discovery=_discovery, refresh=_refresh, alerts=_alerts),
        config=config,
    )
    jobs_by_id = {job.id: job for job in scheduler.get_jobs()}

    assert _minute_of_day(config.discovery_cron) < _minute_of_day(config.alerts_cron)
    assert _minute_of_day(config.refresh_cron) < _minute_of_day(config.alerts_cron)
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
    monkeypatch.setenv("SCHEDULER_REFRESH_CRON", "10 7 * * tue,thu")
    monkeypatch.setenv("SCHEDULER_ALERTS_CRON", "15 8 * * *")
    monkeypatch.setenv("SCHEDULER_REFRESH_LIMIT", "17")
    monkeypatch.setenv("SCHEDULER_REFRESH_STALE_DAYS", "12")
    monkeypatch.setenv("SCHEDULER_REFRESH_COOLDOWN_HOURS", "36")
    monkeypatch.setenv("SCHEDULER_ALERTS_THRESHOLD_PCT", "7.5")
    monkeypatch.setenv("SCHEDULER_ALERTS_LOOKBACK_DAYS", "14")

    config = scheduler_config_from_env()
    scheduler = build_scheduler(
        jobs=SchedulerJobs(discovery=_discovery, refresh=_refresh, alerts=_alerts)
    )
    jobs_by_id = {job.id: job for job in scheduler.get_jobs()}

    assert config.discovery_cron == "5 6 * * *"
    assert config.refresh_cron == "10 7 * * tue,thu"
    assert config.alerts_cron == "15 8 * * *"
    assert config.refresh_limit == 17
    assert config.refresh_stale_days == 12
    assert config.refresh_cooldown_hours == 36
    assert config.alerts_threshold_pct == 7.5
    assert config.alerts_lookback_days == 14
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


def test_discovery_and_refresh_do_not_share_the_same_function() -> None:
    scheduler = build_scheduler(
        jobs=SchedulerJobs(discovery=_discovery, refresh=_refresh, alerts=_alerts),
        config=SchedulerConfig(),
    )

    jobs_by_id = {job.id: job for job in scheduler.get_jobs()}

    assert jobs_by_id[DISCOVERY_JOB_ID].func is not jobs_by_id[REFRESH_JOB_ID].func


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
