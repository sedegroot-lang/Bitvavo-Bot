@echo off
chcp 65001 >nul
title Bitvavo Bot — Setup

echo.
echo  ══════════════════════════════════════════════════
echo    Bitvavo Trading Bot — Eerste keer installatie
echo  ══════════════════════════════════════════════════
echo.

cd /d "%~dp0"

REM ── Controleer of Python aanwezig is ──────────────────────────────────────
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo  [!] Python niet gevonden op dit systeem.
    echo.
    echo  Download Python 3.11 of hoger via:
    echo  https://www.python.org/downloads/
    echo.
    echo  Installeer Python, zorg dat je "Add to PATH" aanvinkt,
    echo  en dubbelklik daarna setup.bat opnieuw.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo  [OK] %PYVER% gevonden
echo.

REM ── Maak .venv aan als die nog niet bestaat ───────────────────────────────
if not exist ".venv\Scripts\python.exe" (
    echo  [..] Virtuele omgeving aanmaken...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo  [!] Fout bij aanmaken van .venv — zie bovenstaande melding.
        pause
        exit /b 1
    )
    echo  [OK] .venv aangemaakt
    echo.
)

REM ── Start de interactieve setup wizard ───────────────────────────────────
echo  [..] Setup wizard starten...
echo.
".venv\Scripts\python.exe" setup.py

exit /b 0
