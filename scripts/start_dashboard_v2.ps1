# Start Dashboard V2 (FastAPI + PWA on port 5002)
# Robust launcher — auto-installs deps if missing, pauses on exit so you can
# read errors when double-clicked.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$port = $env:DASH_V2_PORT
if (-not $port) { $port = "5002" }

Write-Host ""
Write-Host " ============================================================" -ForegroundColor DarkCyan
Write-Host "  Bitvavo Bot Dashboard V2  (FastAPI + PWA)" -ForegroundColor Cyan
Write-Host "  Local:   http://127.0.0.1:$port" -ForegroundColor Green
Write-Host "  LAN:     http://$([System.Net.Dns]::GetHostName()):$port" -ForegroundColor Green
Write-Host "  API:     http://127.0.0.1:$port/api/all" -ForegroundColor Gray
Write-Host " ============================================================" -ForegroundColor DarkCyan
Write-Host ""

# Make sure fastapi/uvicorn are installed
& $python -c "import fastapi, uvicorn, cachetools" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing FastAPI dependencies (one-time)..." -ForegroundColor Yellow
    & $python -m pip install -q fastapi "uvicorn[standard]" cachetools
}

try {
    & $python -m uvicorn tools.dashboard_v2.backend.main:app --host 0.0.0.0 --port $port
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "Dashboard stopped (exit code $LASTEXITCODE)." -ForegroundColor DarkGray
if ($Host.Name -eq "ConsoleHost") { Read-Host "Press Enter to close" }
