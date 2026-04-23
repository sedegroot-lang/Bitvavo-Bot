#!/usr/bin/env pwsh
# Bitvavo Bot - Unified Startup (ALL IN ONE WINDOW)
# Starts bot + dashboard + all subprocesses in THIS PowerShell window
# No hidden processes, all output visible, easy to stop with Ctrl+C

param(
    [string]$ProjectDir = $PSScriptRoot,
    [switch]$NoScheduler,
    [switch]$SkipCleanup
)

$ErrorActionPreference = "Continue"

Write-Host ("=" * 80) -ForegroundColor Blue
Write-Host "BITVAVO BOT - UNIFIED STARTUP (ALL IN 1 WINDOW)" -ForegroundColor Blue
Write-Host ("=" * 80) -ForegroundColor Blue
Write-Host ""

# Step 1: Cleanup old processes (ULTRA AGGRESSIVE)
if (-not $SkipCleanup) {
    Write-Host "Stopping existing Python processes..." -ForegroundColor Yellow
    
    # Kill all Python processes (multiple attempts)
    Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    
    # Wait for mutex release (Windows needs time to clean up)
    Start-Sleep -Seconds 3
    
    # Clean lock files and PIDs
    Remove-Item "$ProjectDir\locks\*" -Force -ErrorAction SilentlyContinue
    
    Write-Host "   [OK] Cleanup complete (waited 3s for mutex release)" -ForegroundColor Green
    Write-Host ""
}

# Step 2: Verify paths
Set-Location $ProjectDir

$pythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$botScript = Join-Path $ProjectDir "scripts\startup\start_bot.py"

if (-not (Test-Path $pythonExe)) {
    Write-Host "[ERROR] Python not found at $pythonExe" -ForegroundColor Red
    pause
    exit 1
}

if (-not (Test-Path $botScript)) {
    Write-Host "[ERROR] Bot script not found at $botScript" -ForegroundColor Red
    pause
    exit 1
}

# Step 3: Show what's starting
Write-Host "Configuration:" -ForegroundColor Cyan
Write-Host "   Project:  $ProjectDir"
Write-Host "   Python:   $pythonExe"
Write-Host ""
Write-Host "What's starting in THIS window:" -ForegroundColor Cyan
Write-Host "   [OK] Trading bot (main loop)"
Write-Host "   [OK] Flask dashboard -> http://localhost:5001"
Write-Host "   [OK] AI Supervisor"
Write-Host "   [OK] Monitoring daemon"
Write-Host "   [OK] Auto backup service"
Write-Host "   [OK] Auto retrain service"
Write-Host "   [OK] Pairs arbitrage runner"
Write-Host "   [OK] Scheduler (metrics, health checks)"
Write-Host ""
Write-Host "[INFO] ALL processes run in THIS window - you see ALL output" -ForegroundColor Yellow
Write-Host "[INFO] To stop: Press Ctrl+C" -ForegroundColor Yellow
Write-Host ""
Write-Host ("=" * 80) -ForegroundColor Green
Write-Host "STARTING BOT NOW..." -ForegroundColor Green
Write-Host ("=" * 80) -ForegroundColor Green
Write-Host ""

# Step 4: Start bot (BLOCKS - all output comes here)
try {
    & $pythonExe $botScript
} catch {
    Write-Host ""
    Write-Host ("=" * 80) -ForegroundColor Red
    Write-Host "[ERROR] BOT CRASHED: $_" -ForegroundColor Red
    Write-Host ("=" * 80) -ForegroundColor Red
    Write-Host ""
    Write-Host "Check logs in: $ProjectDir\logs\" -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 1
}

# Bot stopped gracefully (Ctrl+C or exit)
Write-Host ""
Write-Host ("=" * 80) -ForegroundColor Yellow
Write-Host "[STOPPED] BOT STOPPED" -ForegroundColor Yellow  
Write-Host ("=" * 80) -ForegroundColor Yellow
Write-Host ""
Write-Host "All subprocesses have been terminated." -ForegroundColor Green
Write-Host ""
Write-Host "Press any key to close window or Ctrl+C to exit..." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
