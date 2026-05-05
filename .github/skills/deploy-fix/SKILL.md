---
name: deploy-fix
description: End-to-end FIX cyclus voor de Bitvavo bot — test, log, commit, push, telegram, restart. Use this skill when the user says "deploy fix" or after writing the actual code change for a bug fix.
---

# Deploy-fix skill

Run the full deployment loop after a bug fix code change is in place.

## Steps (in order)

### 1. Run targeted tests
```powershell
.\.venv\Scripts\python.exe -m pytest tests/<relevant_file>.py -v
```
If failing, STOP and report — do not proceed.

### 2. Run full suite
```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -n auto -q
```
All must pass.

### 3. Run health check
```powershell
.\.venv\Scripts\python.exe scripts/helpers/ai_health_check.py
```
Report any ⚠️/❌ but proceed if not blocking.

### 4. Append FIX_LOG entry
Open `docs/FIX_LOG.md`, find the next FIX number, and append using the template at the bottom of that file. Include:
- ID, date (YYYY-MM-DD)
- Symptom (what the user saw)
- Root cause (one paragraph)
- Fix summary (files + nature of change)
- Tests added
- Verification (commands run, results)

### 5. Commit + push
```powershell
git add -A
git commit -m "fix: <short description> (FIX #NNN)"
git push
```
Capture the commit hash.

### 6. Telegram notification
```powershell
.\.venv\Scripts\python.exe -c "from notifier import send_telegram; send_telegram('FIX #NNN deployed: <description>. Tests passing. Commit <hash>.')"
```

### 7. Restart bot (if the fix affects the running bot loop)
Stop existing python processes for the bot, then restart via the foreground task or `start_automated.bat`.
```powershell
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*Bitvavo Bot*" } | Stop-Process -Force
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "trailing_bot.py" -WorkingDirectory $PWD
```
Verify new PIDs after a few seconds.

## Output to user
Dutch summary preferred:
```
FIX #NNN gedeployed ✅
- Tests: <X>/<X> passing
- Commit: <hash>
- Telegram: verstuurd (msg_id <id>)
- Bot: herstart, PIDs <list>
```
