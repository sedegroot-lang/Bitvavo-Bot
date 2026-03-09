@echo off
echo.
echo === VERIFICATIE BOT PROCESSEN ===
echo.
timeout /t 3 /nobreak > nul
python check_processes.py
echo.
echo Bot blijft draaien in het andere venster.
echo.
pause
