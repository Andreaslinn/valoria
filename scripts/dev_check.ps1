$ErrorActionPreference = "Stop"

Write-Host "Compiling project packages..."
.\.venv-win\Scripts\python.exe -m compileall api config core domain infrastructure services tests workers scripts audits ui

Write-Host "Running tests..."
.\.venv-win\Scripts\python.exe -m pytest

Write-Host "Running audit checks..."
.\.venv-win\Scripts\python.exe scripts\check_health.py
