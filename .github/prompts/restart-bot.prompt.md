---
mode: agent
description: Stop alle bot-processen en herstart via start_automated.bat (of trailing_bot.py direct).
---

## Stappen

### 1. Identificeer huidige processen
```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*Bitvavo Bot*' } | Select-Object ProcessId, @{N='Cmd';E={$_.CommandLine.Substring(0,[Math]::Min(120,$_.CommandLine.Length))}} | Format-Table -AutoSize
```

### 2. Stop alle bot processen
```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*Bitvavo Bot*' -and $_.CommandLine -notlike '*run_shadow*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 3
```

### 3. Verifieer alle gestopt
```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*trailing_bot.py*' } | Measure-Object | Select-Object -ExpandProperty Count
```
Moet `0` zijn.

### 4. Restart
**Optie A — alleen trailing_bot:**
```powershell
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "trailing_bot.py" -WindowStyle Hidden -RedirectStandardOutput "logs\bot_stdout.log" -RedirectStandardError "logs\bot_stderr.log"
```

**Optie B — alle subprocessen (dashboard, ai_supervisor, scheduler):**
```powershell
Start-Process -FilePath ".\start_automated.bat" -WindowStyle Hidden
```

### 5. Wacht 5s + verifieer
```powershell
Start-Sleep 5
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*trailing_bot.py*' } | Select-Object ProcessId
Get-Content .\logs\bot_log.txt -Tail 10
```

### 6. Rapporteer
- Oude PIDs (gestopt)
- Nieuwe PIDs (running)
- Eventuele errors uit eerste log-regels
