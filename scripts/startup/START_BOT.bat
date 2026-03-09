@echo off
REM Bitvavo Bot Starter
REM Uses venv Python to avoid Windows spawn duplicates

echo.
echo ========================================
echo   STARTING BITVAVO BOT
echo ========================================
echo.
echo [INFO] Stopping old Python processes...
taskkill /F /IM python.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

echo [INFO] Clearing old PID files...
del /Q ..\logs\*.pid* >nul 2>&1

echo [INFO] Starting bot with venv Python...
echo.
..\.venv\Scripts\python.exe start_bot.py

echo.
echo [INFO] Bot stopped.
pause
