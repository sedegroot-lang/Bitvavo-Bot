@echo off
REM Bitvavo Bot - Automated Startup (Enhanced)
REM This script does EVERYTHING - just double-click!
REM - Stops old processes
REM - Migrates to SQLite (if needed)
REM - Generates metrics
REM - Starts bot + scheduler
REM - Opens in visible window

echo ========================================
echo BITVAVO BOT - AUTOMATED STARTUP
echo ========================================
echo.

cd /d "%~dp0"

REM Stop existing Python processes
echo Stopping existing Python processes...
taskkill /F /IM python.exe >nul 2>&1
timeout /t 2 >nul
echo Cleanup complete
echo.

REM Start automated bot in PowerShell window - ALLES IN 1 VENSTER
echo Starting bot with all automation features...
echo.
powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0start_automated.ps1"

REM Als we hier komen, betekent dat PowerShell gesloten is
echo.
echo Bot gestopt.
echo.

echo ========================================
echo STARTUP COMPLETE!
echo ========================================
echo.
echo The bot is now running in ONE PowerShell window with:
echo   - Trading bot + all 7 subprocesses
echo   - Dashboard: http://localhost:5001
echo   - Automation scheduler
echo   - Live logs and output
echo.
echo Check the new window for detailed logs.
echo.
pause
