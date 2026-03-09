# Auto Sync Validator - PowerShell version
# Setup: Run this in PowerShell as Administrator:
# $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-File 'C:\Users\Sedeg\OneDrive\Dokumente\Bitvavo Bot\auto_sync_check.ps1'"
# $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration ([TimeSpan]::MaxValue)
# Register-ScheduledTask -TaskName "BitvavoSyncCheck" -Action $action -Trigger $trigger -Description "Validate Bitvavo sync every 30 minutes"

Set-Location "C:\Users\Sedeg\OneDrive\Dokumente\Bitvavo Bot"

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path "logs\sync_validator.log" -Value "[$timestamp] Running sync validation"

& .venv\Scripts\python.exe scripts\helpers\validate_sync.py --auto-fix 2>&1 | Add-Content -Path "logs\sync_validator.log"

if ($LASTEXITCODE -ne 0) {
    Add-Content -Path "logs\sync_validator.log" -Value "[$timestamp] SYNC ISSUES DETECTED"
} else {
    Add-Content -Path "logs\sync_validator.log" -Value "[$timestamp] Sync OK"
}
