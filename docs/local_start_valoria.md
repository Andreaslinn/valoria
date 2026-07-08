# Valoria local launcher

Use `start_valoria.bat` to start the current Valoria local beta stack on Windows without changing the legacy `start_avm.bat`.

## What it starts

- Docker services: `postgres` and `redis`
- FastAPI backend: `http://127.0.0.1:8000`
- Next.js frontend: `http://127.0.0.1:3000`
- Optional legacy Streamlit only with `-WithStreamlit`: `http://127.0.0.1:8501`

The launcher does not run scraper jobs, refresh jobs, scheduler jobs, migrations, deploys, engine changes, or DB resets.

## Comparable Quality v2

For local beta startup, the launcher runs the FastAPI process with:

```text
VALUATION_QUALITY_V2_APPLY_MODE=guarded
```

This activates the Comparable Quality v2 robust weighted median challenger only behind guardrails. The code default remains `off` when the variable is absent outside the local/beta launcher.

For this beta/local profile, keep the consensus orchestrator disabled so the guarded CQ v2 challenger is the active valuation path:

```text
VALORIA_USE_CONSENSUS=false
```

Rollback:

```powershell
$env:VALUATION_QUALITY_V2_APPLY_MODE="off"
```

Or set this in `.env`:

```text
VALUATION_QUALITY_V2_APPLY_MODE=off
```

Shadow mode:

```text
VALUATION_QUALITY_V2_APPLY_MODE=shadow
```

Current beta guardrails keep CQ v2 limited to apartments, block `estacion central`, `la reina`, and `macul`, and fallback when pool dispersion or delta vs baseline is too high.

## Usage

From the repository root:

```powershell
.\start_valoria.bat
```

Or call the PowerShell script directly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_valoria.ps1
```

Useful flags:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_valoria.ps1 -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_valoria.ps1 -NoFrontend
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_valoria.ps1 -NoBackend
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_valoria.ps1 -WithStreamlit
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_valoria.ps1 -NoBrowser
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_valoria.ps1 -SkipInstall
```

## Frontend environment

If `frontend\.env.local` does not exist, the launcher creates it with:

```text
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Existing `frontend\.env.local` files are left unchanged.

If `frontend\node_modules` is missing, the launcher runs `npm.cmd install` from `frontend\` unless `-SkipInstall` is provided.

## Occupied ports

The launcher never kills processes automatically.

- If port `8000` is occupied and `/health` plus `/api/v1/health` respond, the backend is treated as already running.
- If port `3000` is occupied and the response looks like Next.js, the frontend is treated as already running.
- Otherwise, the launcher prints the port owner and exits with an explanation.

## Health checks

Open these URLs after startup:

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/api/v1/health`
- `http://127.0.0.1:3000`

Logs and temporary runner scripts are written under `logs\startup`.
