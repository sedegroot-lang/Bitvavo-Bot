@echo off
setlocal
cd /d "%~dp0\..\..\"
if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
)
REM check for existing dashboard processes; if present, do not start another
powershell -NoProfile -Command "if ((Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'dashboard_watchdog.py' }) -eq $null) { Start-Process -FilePath '.venv\Scripts\python.exe' -ArgumentList 'tools\dashboard\dashboard_watchdog.py' } else { Write-Output 'dashboard_watchdog already running' }"
