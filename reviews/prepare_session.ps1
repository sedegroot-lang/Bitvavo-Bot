# Prepare files for Opus Review Session
# Usage: .\reviews\prepare_session.ps1 -Session 1

param(
    [Parameter(Mandatory=$true)]
    [int]$Session
)

$outputFile = "reviews\session${Session}_files.txt"

Write-Host "Preparing files for Session $Session..." -ForegroundColor Cyan

# Session file mappings
$sessionFiles = @{
    1 = @(
        "bot\trailing.py",
        "bot\api.py"
    )
    2 = @(
        "trailing_bot.py",
        "bot\helpers.py",
        "config\bot_config.json"
    )
    3 = @(
        "bot\signals.py",
        "bot\performance.py"
    )
    4 = @(
        "ai\ai_supervisor.py",
        "ai\suggest_rules.py",
        "config\bot_config.json"
    )
    5 = @(
        "bot\api.py",
        "trailing_bot.py"
    )
    6 = @(
        "utils.py"
    )
    7 = @(
        "ai\ml_optimizer.py",
        "ai\xgb_auto_train.py"
    )
    8 = @(
        "trailing_bot.py",
        "bot\trailing.py",
        "bot\signals.py"
    )
}

if (-not $sessionFiles.ContainsKey($Session)) {
    Write-Host "❌ Invalid session number. Use 1-8." -ForegroundColor Red
    exit 1
}

$files = $sessionFiles[$Session]

# Create output file
"=" * 80 | Out-File $outputFile
"OPUS 4.6 REVIEW - SESSION $Session" | Out-File $outputFile -Append
"Generated: $(Get-Date)" | Out-File $outputFile -Append
"=" * 80 | Out-File $outputFile -Append
"" | Out-File $outputFile -Append

foreach ($file in $files) {
    if (Test-Path $file) {
        Write-Host "✅ Adding $file" -ForegroundColor Green
        
        "-" * 80 | Out-File $outputFile -Append
        "FILE: $file" | Out-File $outputFile -Append
        "-" * 80 | Out-File $outputFile -Append
        "" | Out-File $outputFile -Append
        
        Get-Content $file -Raw | Out-File $outputFile -Append
        
        "" | Out-File $outputFile -Append
        "" | Out-File $outputFile -Append
    } else {
        Write-Host "⚠️  File not found: $file" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "✅ Files prepared for Session $Session" -ForegroundColor Green
Write-Host "📄 Output: $outputFile" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Open $outputFile" -ForegroundColor White
Write-Host "2. Copy entire content (Ctrl+A, Ctrl+C)" -ForegroundColor White
Write-Host "3. Start NEW Opus 4.6 chat" -ForegroundColor White
Write-Host "4. Paste prompt from OPUS_REVIEW_PLAN.md Session $Session" -ForegroundColor White
Write-Host "5. Paste file contents from $outputFile" -ForegroundColor White
Write-Host "6. Let Opus analyze!" -ForegroundColor White
Write-Host ""

# Open file automatically
notepad $outputFile
