@echo off
REM Documentation Sync Utility
REM Manually sync all documentation files

echo.
echo ================================================
echo    BITVAVO BOT - DOCUMENTATION SYNC
echo ================================================
echo.

cd /d "%~dp0\..\..\"

echo [1/3] Verifying cross-references...
python scripts\helpers\sync_documentation.py --verify
if errorlevel 1 (
    echo.
    echo ERROR: Cross-reference verification failed!
    pause
    exit /b 1
)

echo.
echo [2/3] Updating bot status in documentation...
python scripts\helpers\sync_documentation.py --status-only

echo.
echo [3/3] Logging to CHANGELOG.md...
python scripts\helpers\sync_documentation.py --log

echo.
echo ================================================
echo    DOCUMENTATION SYNC COMPLETE
echo ================================================
echo.
echo Updated files:
echo   - docs\BOT_SYSTEM_OVERVIEW.md
echo   - docs\TODO.md
echo   - CHANGELOG.md
echo.
pause
