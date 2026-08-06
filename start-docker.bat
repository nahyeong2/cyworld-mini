@echo off
title Miniroom Docker
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-docker.ps1"
echo.
if errorlevel 1 (
  echo Docker execution failed. Review the message above.
) else (
  echo Docker execution completed successfully.
)
pause
