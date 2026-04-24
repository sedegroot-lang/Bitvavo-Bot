@echo off
REM ============================================================
REM  Bitvavo Bot - Dashboard V2 launcher (double-click ready)
REM  Opens the new FastAPI + PWA dashboard on http://127.0.0.1:5002
REM ============================================================
cd /d "%~dp0"
title Bitvavo Bot Dashboard V2
echo.
echo  ============================================================
echo   Bitvavo Bot Dashboard V2  (FastAPI + PWA)
echo   Local: http://127.0.0.1:5002
echo   API:   http://127.0.0.1:5002/api/all
echo  ============================================================
echo.

REM Prefer the project venv
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    set "PY=%VENV_PY%"
) else (
    set "PY=python"
)

REM Make sure fastapi is installed (silent if already there)
"%PY%" -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo Installing FastAPI dependencies (one-time^)...
    "%PY%" -m pip install -q fastapi "uvicorn[standard]" cachetools
)

"%PY%" -m uvicorn tools.dashboard_v2.backend.main:app --host 0.0.0.0 --port 5002

echo.
echo Dashboard stopped (exit code %ERRORLEVEL%).
pause
