from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_local_startup_scheduler_is_opt_in_and_non_blocking() -> None:
    script = (ROOT / "scripts" / "start_avm.ps1").read_text(encoding="utf-8")

    assert 'Name "AVM_START_SCHEDULER"' in script
    assert 'Name "START_SCHEDULER" -DefaultValue "false"' in script
    assert "-m workers.scheduler" in script
    assert "-WindowStyle Hidden" in script
    assert "-PassThru" in script
    assert "Start-Sleep -Seconds 2" in script
    assert "Scheduler disabled. Set AVM_START_SCHEDULER=true" in script


def test_local_startup_scheduler_writes_operational_artifacts() -> None:
    script = (ROOT / "scripts" / "start_avm.ps1").read_text(encoding="utf-8")

    assert 'Join-Path $LogDir "scheduler-$Timestamp.log"' in script
    assert 'Join-Path $LogDir "run-scheduler-$Timestamp.ps1"' in script
    assert 'Join-Path $LogDir "scheduler-$Timestamp.pid"' in script
    assert "Set-Content -Path $SchedulerPidFile -Value $SchedulerProcess.Id" in script
    assert "Stop-Process -Id $($SchedulerProcess.Id)" in script


def test_local_scheduler_defaults_are_documented_as_safe() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "local_scheduler_refresh.md").read_text(encoding="utf-8")

    assert "AVM_START_SCHEDULER=false" in env_example
    assert "SCHEDULER_ENABLE_DISCOVERY=false" in env_example
    assert "SCHEDULER_ENABLE_PORTAL=false" in env_example
    assert "SCHEDULER_DISCOVERY_MAX_PAGES=0" in env_example
    assert "SCHEDULER_DISCOVERY_SLEEP_SECONDS=2.0" in env_example
    assert "SCHEDULER_REFRESH_LIMIT=5" in env_example
    assert 'SCHEDULER_ALERTS_CRON="0 13 * * *"' in env_example
    assert "AVM local startup does not start the scheduler by default" in docs
    assert "python -m workers.scheduler" in docs
    assert "python scripts\\refresh_scraper.py --dry-run --limit 5 --stale-days 30" in docs
    assert "SCHEDULER_ENABLE_PORTAL=false" in docs
