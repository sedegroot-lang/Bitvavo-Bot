param(
    [string]$LogPath = "bot_log.txt",
    [int]$MaxSizeMB = 5,
    [switch]$DryRun
)

$resolved = Resolve-Path -LiteralPath $LogPath -ErrorAction SilentlyContinue
if (-not $resolved) {
    Write-Host "[trim_logs] Bestand niet gevonden: $LogPath" -ForegroundColor Yellow
    exit 0
}

$logFile = Get-Item -LiteralPath $resolved
$limitBytes = [Math]::Max(1, $MaxSizeMB * 1MB)

if ($logFile.Length -le $limitBytes) {
    Write-Host "[trim_logs] Geen actie nodig. Grootte=$([Math]::Round($logFile.Length/1MB,2)) MB <= limiet $MaxSizeMB MB"
    exit 0
}

$backupPath = "$($logFile.FullName).trim.bak"
if (-not $DryRun) {
    Copy-Item -LiteralPath $logFile.FullName -Destination $backupPath -Force
    Write-Host "[trim_logs] Backup gemaakt: $backupPath" -ForegroundColor Cyan
} else {
    Write-Host "[trim_logs] Dry-run: backup zou worden gemaakt: $backupPath" -ForegroundColor Gray
}

$bytesToKeep = [Math]::Min($logFile.Length, $limitBytes)
$startOffset = $logFile.Length - $bytesToKeep

$stream = [System.IO.File]::Open($logFile.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
try {
    $stream.Seek($startOffset, [System.IO.SeekOrigin]::Begin) | Out-Null
    $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $true)
    $content = $reader.ReadToEnd()
    $reader.Close()
}
finally {
    $stream.Close()
}

if ($startOffset -gt 0) {
    $newlineIndex = $content.IndexOf("`n")
    if ($newlineIndex -ge 0 -and $newlineIndex -lt $content.Length - 1) {
        $content = $content.Substring($newlineIndex + 1)
    }
}

if ($DryRun) {
    $newSize = [System.Text.Encoding]::UTF8.GetByteCount($content)
    Write-Host "[trim_logs] Dry-run afgerond. Nieuwe grootte zou ongeveer $([Math]::Round($newSize/1MB,2)) MB zijn." -ForegroundColor Gray
    exit 0
}

$tempFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($tempFile, $content, [System.Text.Encoding]::UTF8)
Move-Item -Force -LiteralPath $tempFile -Destination $logFile.FullName

$newInfo = Get-Item -LiteralPath $logFile.FullName
Write-Host "[trim_logs] Klaar. Nieuwe grootte=$([Math]::Round($newInfo.Length/1MB,2)) MB" -ForegroundColor Green
