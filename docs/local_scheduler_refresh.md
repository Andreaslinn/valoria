# Local scheduler and refresh operations

AVM local startup does not start the scheduler by default. This keeps normal
development startup unchanged and avoids accidental large refresh batches.

## Start without scheduler

```powershell
.\start_avm.bat
```

or:

```powershell
.\scripts\start_avm.ps1
```

## Start with scheduler

Set `AVM_START_SCHEDULER=true` in `.env`, or set it only for the current
PowerShell session:

```powershell
$env:AVM_START_SCHEDULER = "true"
.\scripts\start_avm.ps1
```

The startup script launches `python -m workers.scheduler` as a separate hidden
PowerShell process, validates that it stays alive, prints the PID, and writes:

- `logs\startup\scheduler-<timestamp>.log`
- `logs\startup\scheduler-<timestamp>.pid`
- `logs\startup\run-scheduler-<timestamp>.ps1`

Local scheduler defaults keep refresh controlled:

```dotenv
SCHEDULER_REFRESH_LIMIT=5
SCHEDULER_REFRESH_STALE_DAYS=30
SCHEDULER_REFRESH_COOLDOWN_HOURS=24
```

Increase those values intentionally only after checking recent refresh logs.

## Stop scheduler

Use the PID printed by startup:

```powershell
Stop-Process -Id <PID>
```

Or read the latest PID file:

```powershell
$pidFile = Get-ChildItem logs\startup\scheduler-*.pid | Sort-Object LastWriteTime | Select-Object -Last 1
Stop-Process -Id (Get-Content $pidFile.FullName)
```

## Manual refresh

Dry-run candidate selection without fetching URLs:

```powershell
python scripts\refresh_scraper.py --dry-run --limit 5 --stale-days 30
```

Controlled refresh attempt:

```powershell
python scripts\refresh_scraper.py --limit 5 --stale-days 30
```

The manual command prints selected candidates, attempts, outcome counters, and
database traceability before and after `last_refresh_attempted_at`.
