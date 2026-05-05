---
mode: agent
description: Reconcile DCA-events + cost basis voor een specifieke market vanuit Bitvavo order history.
---

Argument: market symbol (bv. `ENJ-EUR`, `BTC-EUR`). Vraag de user als niet opgegeven.

## Stappen

### 1. Stop bot
```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*trailing_bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```
Wacht 2s, verifieer dat geen `trailing_bot.py` proces meer draait.

### 2. Maak / update reconcile script
Gebruik `tmp/reconcile_<symbol>.py` als template (kopieer van `tmp/reconcile_enj.py` als nodig). Vervang market en draai met juiste `dca_max` uit config.

### 3. Run reconcile
```powershell
.\.venv\Scripts\python.exe .\tmp\reconcile_<symbol>.py
```
Bewaar de BEFORE/AFTER output. Backup wordt automatisch gemaakt in `data/trade_log.json.bak.fix*.<ts>`.

### 4. Verifieer
Inspecteer `data/trade_log.json`:
- `amount` matched Bitvavo balance
- `invested_eur` ≈ som van BUY fills - som van SELL fills
- `dca_buys` == `len(dca_events)`
- `initial_invested_eur` is de eerste buy (NIET totale cost)

### 5. Restart bot
```powershell
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "trailing_bot.py" -WindowStyle Hidden -RedirectStandardOutput "logs\bot_stdout.log" -RedirectStandardError "logs\bot_stderr.log"
```

### 6. Telegram update (optioneel)
Stuur korte Telegram met "Reconciled <market>: dca_buys=X events=X invested=€Y".

### 7. Rapporteer
Geef in chat de BEFORE/AFTER state + bevestig restart succesvol.
