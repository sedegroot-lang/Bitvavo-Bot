@echo off
REM Double-click launcher for Dashboard V2
REM Bypasses PowerShell ExecutionPolicy on a per-process basis.
cd /d "%~dp0\.."
title Bitvavo Bot Dashboard V2 (port 5002)
echo.
echo === Bitvavo Bot Dashboard V2 ===
echo Local:  http://127.0.0.1:5002
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_dashboard_v2.ps1"
echo.
echo Dashboard stopped (exit code %ERRORLEVEL%).
pause
