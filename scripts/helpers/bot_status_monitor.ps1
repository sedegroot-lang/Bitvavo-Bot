# Bot Status Monitor — runs in its own PowerShell window
# Polls heartbeat + trailing_bot process every POLL_SEC seconds and shows
# a colored status panel. Always shows whether the actual trading loop is alive.

param(
    [int]$PollSec = 15,
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = 'Continue'
$Host.UI.RawUI.WindowTitle = 'BITVAVO BOT — HEALTH MONITOR'

function Get-TrailingBotStatus {
    $procs = @()
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'trailing_bot\.py' }
    } catch {}
    return $procs
}

function Get-HeartbeatAge {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return -1 }
    try {
        $hb = Get-Content $Path -Raw | ConvertFrom-Json
        $ts = [double]($hb.ts)
        if ($ts -le 0) { return -1 }
        $now = [double][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        return [int]($now - $ts)
    } catch {
        return -1
    }
}

function Get-LastError {
    param([string]$LogPath, [int]$TailLines = 200)
    if (-not (Test-Path $LogPath)) { return $null }
    try {
        $lines = Get-Content $LogPath -Tail $TailLines -ErrorAction SilentlyContinue
        $err = $lines | Where-Object { $_ -match 'ERROR' } | Select-Object -Last 1
        return $err
    } catch { return $null }
}

$heartbeatPath = Join-Path $ProjectDir 'data\heartbeat.json'
$logPath = Join-Path $ProjectDir 'logs\bot_log.txt'
$monitorLogPath = Join-Path $ProjectDir 'scripts\helpers\logs\monitor.log'

while ($true) {
    Clear-Host
    $now = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Write-Host ("=" * 72) -ForegroundColor DarkCyan
    Write-Host "  BITVAVO BOT — HEALTH MONITOR    $now" -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor DarkCyan
    Write-Host ""

    # 1) Trailing bot process check
    $trailingProcs = Get-TrailingBotStatus
    if ($trailingProcs.Count -gt 0) {
        $oldest = ($trailingProcs | Sort-Object CreationDate | Select-Object -First 1)
        $age = [int]((Get-Date) - $oldest.CreationDate).TotalSeconds
        $color = if ($age -lt 60) { 'Yellow' } else { 'Green' }
        Write-Host "  [TRADING BOT]   ALIVE   pid=$($oldest.ProcessId)  age=${age}s  ($($trailingProcs.Count) proc)" -ForegroundColor $color
    } else {
        Write-Host "  [TRADING BOT]   *** OFFLINE *** (trailing_bot.py not running!)" -ForegroundColor Red
    }

    # 2) Heartbeat freshness
    $hbAge = Get-HeartbeatAge -Path $heartbeatPath
    if ($hbAge -lt 0) {
        Write-Host "  [HEARTBEAT]     no heartbeat file" -ForegroundColor DarkYellow
    } elseif ($hbAge -lt 90) {
        Write-Host "  [HEARTBEAT]     fresh ($hbAge s old)" -ForegroundColor Green
    } elseif ($hbAge -lt 300) {
        Write-Host "  [HEARTBEAT]     STALE ($hbAge s old)" -ForegroundColor Yellow
    } else {
        Write-Host "  [HEARTBEAT]     *** DEAD *** ($hbAge s old)" -ForegroundColor Red
    }

    # 3) Heartbeat content
    if ((Test-Path $heartbeatPath) -and ($hbAge -ge 0)) {
        try {
            $hb = Get-Content $heartbeatPath -Raw | ConvertFrom-Json
            Write-Host ""
            Write-Host "  Open trades:    $($hb.open_trades)  exposure=EUR $([math]::Round($hb.open_exposure_eur,2))" -ForegroundColor White
            Write-Host "  EUR free:       EUR $([math]::Round($hb.eur_balance,2))" -ForegroundColor White
            $scan = $hb.last_scan_stats
            if ($scan) {
                $scanAge = [int]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [double]$scan.timestamp)
                Write-Host "  Last scan:      ${scanAge}s ago — $($scan.evaluated)/$($scan.total_markets) markets — passed=$($scan.passed_min_score)  regime=$($scan.regime)" -ForegroundColor Gray
            }
        } catch {}
    }

    # 4) Recent monitor restarts (crash-loop detector)
    if (Test-Path $monitorLogPath) {
        try {
            $recentRestarts = (Get-Content $monitorLogPath -Tail 50 -ErrorAction SilentlyContinue |
                Select-String 'Starting trailing_bot').Count
            if ($recentRestarts -gt 5) {
                Write-Host ""
                Write-Host "  [WARNING] $recentRestarts recent trailing_bot restarts in monitor.log — possible crash-loop!" -ForegroundColor Red
            }
        } catch {}
    }

    # 5) Last error from bot_log
    $lastErr = Get-LastError -LogPath $logPath
    if ($lastErr) {
        Write-Host ""
        Write-Host "  Last ERROR in log:" -ForegroundColor DarkYellow
        $errTrunc = if ($lastErr.Length -gt 110) { $lastErr.Substring(0,110) + '...' } else { $lastErr }
        Write-Host "    $errTrunc" -ForegroundColor DarkYellow
    }

    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor DarkCyan
    Write-Host "  Refresh every ${PollSec}s. Close window to stop monitor." -ForegroundColor DarkGray
    Start-Sleep -Seconds $PollSec
}
