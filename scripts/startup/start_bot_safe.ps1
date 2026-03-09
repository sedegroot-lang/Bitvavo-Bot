# Safe wrapper: stop all bot-related processes, archive logs, then start a clean start_bot
$venvPython = Join-Path -Path $PSScriptRoot -ChildPath '.venv\Scripts\python.exe'
Write-Host "Stopping any existing bot processes..."
& $venvPython tools\stop_all_bot_processes.py
Write-Host "Archiving logs and starting a clean start_bot..."
& $venvPython tools\cleanup_and_start.py
Write-Host "Done."
