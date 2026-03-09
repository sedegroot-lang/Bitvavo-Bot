@echo off
REM Wrapper to start monitor.py using the workspace virtualenv
SETLOCAL ENABLEDELAYEDEXPANSION
REM adjust paths if your venv is in .venv
SET VENV=%~dp0.venv\Scripts\python.exe
IF NOT EXIST "%VENV%" (
  REM fallback to system python
  SET VENV=python
)
REM Change to script directory and start monitor.py detached via start command
cd /d "%~dp0"
start "BitvavoMonitor" "%VENV%" monitor.py
ENDLOCAL
:: avoid duplicate starts: if monitor already running, do not start a second
