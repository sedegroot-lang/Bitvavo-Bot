# Autonomous Execution - Bitvavo Bot

## Core Rules
- **NO QUESTIONS** - decide autonomously
- **VERIFY** before "done": `get_errors()` + test
- **COMPACT OUTPUT** - max 5-10 lines per response
- **RESTART** via `start_automated.bat` only

## Output Format
```
✅ Fixed X
✅ Tested - 0 errors
```

## Bot Restart
```powershell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2
Start-Process cmd -ArgumentList "/c","start_automated.bat" -WorkingDirectory "C:\Users\Sedeg\OneDrive\Dokumente\Bitvavo Bot"
```

## Key Paths
- Config: `config/bot_config.json`
- Trades: `data/trade_log.json`
- Logs: `logs/bot_log.txt`

**This is a ZERO-QUESTION workspace. Make decisions, execute, verify, complete.**
