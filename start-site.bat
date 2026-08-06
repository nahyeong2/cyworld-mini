@echo off
setlocal
title Miniroom Server
cd /d "%~dp0"

set "BUNDLED_PYTHON=%~dp0.venv\Scripts\python.exe"

echo [1/2] Checking Miniroom runtime...
if not exist "%BUNDLED_PYTHON%" goto no_python

"%BUNDLED_PYTHON%" -c "import flask, pyotp, qrcode"
if errorlevel 1 goto no_packages

echo [2/2] Starting Miniroom...
echo.
echo Website: http://127.0.0.1:5000
echo Keep this window open. Press Ctrl+C to stop the website.
echo.

start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:5000'"
"%BUNDLED_PYTHON%" app.py

echo.
echo The server has stopped.
pause
exit /b 0

:no_python
echo ERROR: Python runtime was not found:
echo %BUNDLED_PYTHON%
goto failed

:no_packages
echo ERROR: Flask packages could not be loaded.

:failed
echo.
echo Please leave this window open and send a screenshot.
pause
exit /b 1
