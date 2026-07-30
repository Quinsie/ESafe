@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\apply-scenario1-fix.ps1"
if errorlevel 1 (
  echo.
  echo Scenario 1 Docker deployment failed. Keep this window open and notify Codex.
  pause
  exit /b 1
)
echo.
echo Scenario 1 Docker deployment completed.
pause
