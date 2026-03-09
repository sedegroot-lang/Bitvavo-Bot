# Watchdog Task Scheduler Setup
# Run as Administrator to register watchdog as a Windows Scheduled Task
# Checks bot health every 2 minutes and auto-restarts if needed

$TaskName = "BitvavoBot-Watchdog"
$BotRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = "python"
$WatchdogScript = Join-Path $BotRoot "scripts\watchdog.py"

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Bestaande taak verwijderd: $TaskName"
}

# Create trigger: every 2 minutes
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 2) -RepetitionDuration (New-TimeSpan -Days 365)

# Create action: run watchdog.py once
$action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$WatchdogScript`"" -WorkingDirectory $BotRoot

# Settings
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

# Register
Register-ScheduledTask -TaskName $TaskName -Trigger $trigger -Action $action -Settings $settings -Description "Bitvavo Bot health watchdog - auto-restarts bot if unhealthy" -RunLevel Highest

Write-Host ""
Write-Host "Watchdog taak geregistreerd: $TaskName" -ForegroundColor Green
Write-Host "  Interval: elke 2 minuten"
Write-Host "  Script: $WatchdogScript"
Write-Host ""
Write-Host "Controleer met: Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "Verwijder met:  Unregister-ScheduledTask -TaskName '$TaskName'"
