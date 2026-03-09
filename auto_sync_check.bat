@echo off
REM Auto Sync Validator - Runs every 30 minutes via Task Scheduler
REM Setup: schtasks /create /tn "BitvavoSyncCheck" /tr "C:\Users\Sedeg\OneDrive\Dokumente\Bitvavo Bot\auto_sync_check.bat" /sc minute /mo 30 /st 00:00

cd /d "%~dp0"
echo [%date% %time%] Running sync validation >> logs\sync_validator.log
.venv\Scripts\python.exe scripts\helpers\validate_sync.py --auto-fix >> logs\sync_validator.log 2>&1
if errorlevel 1 (
    echo [%date% %time%] SYNC ISSUES DETECTED - Check logs\sync_validator.log >> logs\sync_validator.log
) else (
    echo [%date% %time%] Sync OK >> logs\sync_validator.log
)
