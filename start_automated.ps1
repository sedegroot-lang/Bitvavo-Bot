#!/usr/bin/env pwsh
# Bitvavo Bot - Unified Startup (ALL IN ONE WINDOW + Health Monitor sidecar)
# Starts bot + dashboard + all subprocesses in THIS window AND opens a separate
# Health Monitor window that continuously verifies trailing_bot is alive.

param(
    [string]$ProjectDir = $PSScriptRoot,
    [switch]$NoScheduler,
    [switch]$SkipCleanup,
    [switch]$NoStatusWindow
)

$ErrorActionPreference = "Continue"
$Host.UI.RawUI.WindowTitle = 'BITVAVO BOT - MAIN'

function Write-Banner {
    param([string]$Text, [string]$Color = 'Cyan')
    $line = '=' * 78
    Write-Host $line -ForegroundColor $Color
    Write-Host "  $Text" -ForegroundColor $Color
    Write-Host $line -ForegroundColor $Color
}

function Write-Step {
    param([string]$Symbol, [string]$Text, [string]$Color = 'White')
    Write-Host "  $Symbol $Text" -ForegroundColor $Color
}

Clear-Host
Write-Banner "BITVAVO BOT - UNIFIED STARTUP" "Blue"
Write-Host ""

# ---------------------------------------------------------------------------
# Step 1: Cleanup
# ---------------------------------------------------------------------------
if (-not $SkipCleanup) {
    Write-Host "  Stopping existing Python processes..." -ForegroundColor Yellow
    Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3

    Remove-Item "$ProjectDir\locks\*" -Force -ErrorAction SilentlyContinue

    Write-Step "[OK]" "Cleanup complete (3s mutex release window)" "Green"
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Step 2: Verify paths
# ---------------------------------------------------------------------------
Set-Location $ProjectDir
$pythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$botScript = Join-Path $ProjectDir "scripts\startup\start_bot.py"
$statusScript = Join-Path $ProjectDir "scripts\helpers\bot_status_monitor.ps1"

if (-not (Test-Path $pythonExe)) { Write-Host "[ERROR] Python not found: $pythonExe" -ForegroundColor Red; pause; exit 1 }
if (-not (Test-Path $botScript)) { Write-Host "[ERROR] Bot script not found: $botScript" -ForegroundColor Red; pause; exit 1 }

# ---------------------------------------------------------------------------
# Step 3: Show config
# ---------------------------------------------------------------------------
Write-Host "  Configuration:" -ForegroundColor Cyan
Write-Host "    Project: $ProjectDir" -ForegroundColor Gray
Write-Host "    Python:  $pythonExe" -ForegroundColor Gray
Write-Host ""
Write-Host "  Services starting in THIS window:" -ForegroundColor Cyan
Write-Step "[*]" "Trading bot (main loop, managed by monitor.py)" "White"
Write-Step "[*]" "Flask dashboard  -> http://localhost:5001" "White"
Write-Step "[*]" "AI Supervisor" "White"
Write-Step "[*]" "Monitoring daemon" "White"
Write-Step "[*]" "Auto backup service" "White"
Write-Step "[*]" "Auto retrain service (XGB weekly)" "White"
Write-Step "[*]" "Pairs arbitrage runner" "White"
Write-Step "[*]" "Scheduler (metrics, health checks)" "White"
Write-Host ""

# ---------------------------------------------------------------------------
# Step 4: Spawn Health Monitor sidecar window
# ---------------------------------------------------------------------------
if (-not $NoStatusWindow -and (Test-Path $statusScript)) {
    Write-Step "[OK]" "Opening Health Monitor sidecar window..." "Green"
    try {
        Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$statusScript`"" `
            -WindowStyle Normal | Out-Null
        Write-Step "[OK]" "Health Monitor running in separate window (refresh 15s)" "Green"
    } catch {
        Write-Host "  [WARN] Could not open Health Monitor window: $_" -ForegroundColor Yellow
    }
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Step 5: Schedule a post-start verification banner
# ---------------------------------------------------------------------------
$verifyJob = Start-Job -ScriptBlock {
    param($projDir)
    Start-Sleep -Seconds 60
    $hbPath = Join-Path $projDir 'data\heartbeat.json'
    $alive = $false
    $botPid = 0
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'trailing_bot\.py' }
        if ($procs) { $alive = $true; $botPid = ($procs | Select-Object -First 1).ProcessId }
    } catch {}
    $hbAge = -1
    if (Test-Path $hbPath) {
        try {
            $hb = Get-Content $hbPath -Raw | ConvertFrom-Json
            $hbAge = [int]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [double]$hb.ts)
        } catch {}
    }
    if ($alive -and $hbAge -ge 0 -and $hbAge -lt 120) {
        return "OK|trading_bot ALIVE pid=$botPid heartbeat=${hbAge}s"
    } elseif ($alive) {
        return "WARN|trading_bot ALIVE pid=$botPid but heartbeat stale (${hbAge}s)"
    } else {
        return "FAIL|trading_bot NOT RUNNING after 60s - check Health Monitor or logs/bot_log.txt"
    }
} -ArgumentList $ProjectDir

$null = Register-ObjectEvent -InputObject $verifyJob -EventName StateChanged -Action {
    if ($EventArgs.JobStateInfo.State -eq 'Completed') {
        $result = Receive-Job $Sender
        $parts = $result -split '\|', 2
        $status = $parts[0]; $msg = $parts[1]
        Write-Host ""
        switch ($status) {
            'OK'   { Write-Host ("=" * 78) -ForegroundColor Green
                     Write-Host "  POST-START CHECK [60s]: OK - $msg" -ForegroundColor Green
                     Write-Host ("=" * 78) -ForegroundColor Green }
            'WARN' { Write-Host ("=" * 78) -ForegroundColor Yellow
                     Write-Host "  POST-START CHECK [60s]: WARNING - $msg" -ForegroundColor Yellow
                     Write-Host ("=" * 78) -ForegroundColor Yellow }
            'FAIL' { Write-Host ("=" * 78) -ForegroundColor Red
                     Write-Host "  POST-START CHECK [60s]: FAILED - $msg" -ForegroundColor Red
                     Write-Host ("=" * 78) -ForegroundColor Red }
        }
        Remove-Job $Sender -Force -ErrorAction SilentlyContinue
    }
} | Out-Null

# ---------------------------------------------------------------------------
# Step 6: Launch the bot
# ---------------------------------------------------------------------------
Write-Host "  [INFO] All process output appears in THIS window" -ForegroundColor DarkYellow
Write-Host "  [INFO] Stop with Ctrl+C (closes all subprocesses)" -ForegroundColor DarkYellow
Write-Host ""
Write-Banner "STARTING BOT NOW" "Green"
Write-Host ""

try {
    & $pythonExe $botScript
} catch {
    Write-Host ""
    Write-Banner "BOT CRASHED: $_" "Red"
    Write-Host "  Check logs: $ProjectDir\logs\" -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 1
} finally {
    try { if ($verifyJob) { Stop-Job $verifyJob -ErrorAction SilentlyContinue; Remove-Job $verifyJob -Force -ErrorAction SilentlyContinue } } catch {}
}

Write-Host ""
Write-Banner "BOT STOPPED" "Yellow"
Write-Host "  All subprocesses terminated." -ForegroundColor Green
Write-Host ""
Write-Host "  Press any key to close window..." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
