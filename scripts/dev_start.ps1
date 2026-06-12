param(
    [switch]$SkipBackend
)

$ErrorActionPreference = "Stop"

$PythonExe = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = ".\.venv-win\Scripts\python.exe"
}
if (-not (Test-Path $PythonExe)) {
    throw "No Windows virtualenv found. Create one with: python -m venv .venv"
}

Write-Host "Starting AVM local infrastructure..."
docker compose up -d postgres redis

Write-Host "Running Alembic migrations..."
& $PythonExe -m alembic upgrade head

if (-not $SkipBackend) {
    Write-Host "Starting FastAPI backend. Stop with Ctrl+C."
    & $PythonExe -m uvicorn api.main:app --reload
}

Write-Host "Frontend command:"
Write-Host "$PythonExe -m streamlit run ui/app.py"
