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

Local scheduler defaults keep refresh controlled and do not run discovery unless
explicitly enabled:

```dotenv
SCHEDULER_ENABLE_DISCOVERY=false
SCHEDULER_ENABLE_PORTAL=false
SCHEDULER_STARTUP_CATCHUP_ENABLED=false
SCHEDULER_STARTUP_REFRESH_ENABLED=true
SCHEDULER_STARTUP_ALERTS_ENABLED=true
SCHEDULER_STARTUP_MIN_STALE_HOURS=24
SCHEDULER_REFRESH_LIMIT=5
SCHEDULER_REFRESH_STALE_DAYS=30
SCHEDULER_REFRESH_COOLDOWN_HOURS=24
```

Increase those values intentionally only after checking recent refresh logs.
Keep `SCHEDULER_ENABLE_PORTAL=false` for beta operations until the
PortalInmobiliario source is stable.

## Normal cron vs startup catch-up

The normal scheduler registers only:

- `refresh_scraper`
- `alerts_job`

`discovery_scraper` is not registered unless `SCHEDULER_ENABLE_DISCOVERY=true`.
PortalInmobiliario is also off unless `SCHEDULER_ENABLE_PORTAL=true`.

Startup catch-up is a separate opt-in layer that runs once before the normal
cron scheduler starts. It checks database freshness, skips if the latest refresh
or alert activity is recent, verifies that the configured cron has a missed
window since the last known run, and runs a bounded cycle only when the data is
stale enough:

```powershell
$env:AVM_START_SCHEDULER = "true"
$env:SCHEDULER_STARTUP_CATCHUP_ENABLED = "true"
$env:SCHEDULER_REFRESH_LIMIT = "5"
$env:SCHEDULER_ENABLE_DISCOVERY = "false"
$env:SCHEDULER_ENABLE_PORTAL = "false"
.\scripts\start_avm.ps1
```

You can also run the scheduler directly:

```powershell
$env:SCHEDULER_STARTUP_CATCHUP_ENABLED = "true"
$env:SCHEDULER_REFRESH_LIMIT = "5"
$env:SCHEDULER_ENABLE_DISCOVERY = "false"
$env:SCHEDULER_ENABLE_PORTAL = "false"
python -m workers.scheduler
```

With Portal disabled, scheduler refresh selects only `yapo` candidates. Alerts
catch-up uses the existing price-drop dedupe and does not scrape.

Startup catch-up logs include:

- effective scheduler config and safe defaults
- discovery and Portal enabled/disabled state
- refresh decision: run/skip, reason, candidates, limit, cooldown
- refresh result: attempted, fetched, ok, updated, unchanged, captcha, 403, 429, 5xx, errors
- alerts decision and result
- next normal cron runs after the scheduler starts

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

Manual refresh is for an operator-triggered bounded run. It is not tied to web
requests and should stay limited, for example `--limit 5`, during beta.

## Do not enable yet

For local/beta operations, keep these disabled unless there is a separate
explicit approval:

- `SCHEDULER_ENABLE_DISCOVERY=true`
- `SCHEDULER_ENABLE_PORTAL=true`
- large `SCHEDULER_REFRESH_LIMIT` values
- web-request-triggered refresh or scraping
