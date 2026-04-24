# Start Dashboard V2 (FastAPI + PWA)
# Run from project root.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$port = $env:DASH_V2_PORT
if (-not $port) { $port = "5002" }

Write-Host ""
Write-Host "Bitvavo Bot Dashboard V2" -ForegroundColor Cyan
Write-Host "  Local:   http://127.0.0.1:$port" -ForegroundColor Green
Write-Host "  LAN:     http://$([System.Net.Dns]::GetHostName()):$port" -ForegroundColor Green
Write-Host "  API:     http://127.0.0.1:$port/api/all" -ForegroundColor Gray
Write-Host ""

& $python -m uvicorn tools.dashboard_v2.backend.main:app --host 0.0.0.0 --port $port
