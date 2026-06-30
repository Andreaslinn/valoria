@echo off
setlocal

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\start_valoria.ps1" %*

if errorlevel 1 (
  echo.
  echo Valoria startup failed. Check logs\startup for details.
  pause
  exit /b %errorlevel%
)

echo.
echo Valoria startup command finished.
pause
