@echo off
setlocal

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\start_avm.ps1"

if errorlevel 1 (
  echo.
  echo AVM-v2 startup failed. Check logs\startup for details.
  pause
  exit /b %errorlevel%
)

echo.
echo AVM-v2 startup command finished.
pause
