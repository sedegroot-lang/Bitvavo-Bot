param(
    [string]$ProjectDir = "C:\Users\Sedeg\OneDrive\Dokumente\Bitvavo Bot",
    [int]$WaitSeconds = 2
)

Write-Host "[restart_bot_stack] Stop alle Python-processen..."
Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine
        return ($cmdLine -notmatch 'streamlit' -and $cmdLine -notmatch 'dashboard')
    } catch { return $true }
} | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "[restart_bot_stack] Wacht $WaitSeconds seconde(n)..."
Start-Sleep -Seconds $WaitSeconds

Write-Host "[restart_bot_stack] Start start_bot.py"
$pythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$ProjectDir'; & '$pythonExe' scripts\startup\start_bot.py"
