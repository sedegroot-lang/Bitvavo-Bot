# Bitvavo Bot — Setup voor vriend

## ⚠️ BELANGRIJK: ZET DE BOT **NIET** IN ONEDRIVE!

OneDrive synct files in realtime en zal regelmatig je config bestanden **terugzetten naar oudere versies**. Dat veroorzaakt bugs die heel moeilijk te debuggen zijn (bot draait ineens met oude instellingen, trades sluiten verkeerd, enz.).

**Pak deze ZIP daarom uit op een plek BUITEN OneDrive**, bijvoorbeeld:
- `C:\BitvavoBot\`
- `D:\Trading\BitvavoBot\`
- `C:\Users\<naam>\Documents\BitvavoBot\` (zorg dat Documents NIET geredirect is naar OneDrive — check met klik-rechts op de map → Properties → Location)

❌ NIET: `C:\Users\<naam>\OneDrive\...`
❌ NIET: `C:\Users\<naam>\Documents\...` (als Documents in OneDrive staat)
❌ NIET: Dropbox, Google Drive, of elke andere cloud-sync map

## Wat zit er WEL in deze ZIP
- Alle code (`trailing_bot.py`, `bot/`, `core/`, `modules/`, `ai/`, `scripts/`, `tools/`)
- Config defaults (`config/bot_config.json`)
- Tests (`tests/`) en docs (`docs/`)
- Dashboard (`tools/dashboard_flask/` en `tools/dashboard_v2/`)

## Wat zit er NIET in (en moet je vriend zelf maken/leeg)
- `.env` — eigen Bitvavo API keys
- `data/` — trade log, archive, heartbeat (begint leeg, vult zich vanzelf)
- `logs/` — bot logs (vult zich vanzelf)
- `models/` — XGBoost model (eerst zonder AI draaien, of later trainen)
- `backups/` — backups (vult zich vanzelf)
- `.venv/` — virtual env (zelf maken, zie hieronder)

---

## Stap-voor-stap setup (Windows, PowerShell)

### 1. Pak de ZIP uit
Zet 'm uit op bv. `C:\BitvavoBot\`. **NIET in OneDrive!**

### 2. Python venv + dependencies
Python 3.11 of nieuwer is nodig (3.11 of 3.12 aanbevolen).
```powershell
cd C:\BitvavoBot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Maak `.env` aan in de root
Maak een bestand genaamd `.env` (precies zo, geen extensie) met:
```env
BITVAVO_API_KEY=jouw_eigen_key_hier
BITVAVO_API_SECRET=jouw_eigen_secret_hier
# Optioneel (voor Telegram notificaties):
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

API keys maak je aan op https://account.bitvavo.com/user/api
Geef ALLEEN de rechten: **View info + Trade**. NOOIT withdrawals aanzetten.

### 4. **BELANGRIJK: Lokale config (de plek waar AL je instellingen horen!)**
De bot leest 3 lagen config, waarbij de laatste wint:
1. `config/bot_config.json` — basisdefaults (NIET aanpassen)
2. `config/bot_config_overrides.json` — legacy overrides (NIET aanpassen)
3. `%LOCALAPPDATA%\BotConfig\bot_config_local.json` — **HIER zet je al je eigen instellingen**

Maak die laatste aan:
```powershell
$localDir = "$env:LOCALAPPDATA\BotConfig"
New-Item -ItemType Directory -Path $localDir -Force | Out-Null
'{}' | Out-File -Encoding utf8 "$localDir\bot_config_local.json"
notepad "$localDir\bot_config_local.json"
```

### 5. Veilige eerste config (kopieer dit in `bot_config_local.json`)
```json
{
  "MAX_OPEN_TRADES": 3,
  "BASE_INVESTMENT_EUR": 10,
  "DCA_MAX": 0,
  "MIN_SCORE_TO_BUY": 7.0,
  "AI_ENABLED": false,
  "GRID_ENABLED": false,
  "TELEGRAM_ENABLED": false
}
```
Hiermee:
- Max 3 trades tegelijk open
- €10 per trade (laag om te leren)
- Geen DCA (Dollar Cost Averaging)
- AI uit (geen XGBoost model nodig)
- Grid trading uit
- Geen Telegram berichten

### 6. Bot starten
```powershell
.\.venv\Scripts\python.exe trailing_bot.py
```

### 7. Dashboard starten (apart venster)
```powershell
.\.venv\Scripts\python.exe -m tools.dashboard_flask.app
```
→ Open http://127.0.0.1:5001 in browser.

---

## Tests draaien (om te checken of alles werkt)
```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

## Veelvoorkomende issues

### "Bot doet niks / scant maar koopt niet"
- Check `MIN_SCORE_TO_BUY` (default 7.0 is streng — verlaag NIET zomaar)
- Check EUR saldo op Bitvavo (minstens `BASE_INVESTMENT_EUR × MAX_OPEN_TRADES + 15% reserve`)
- Check `MAX_OPEN_TRADES` (minimum is 3, niet lager)

### "Config wordt niet gelezen / instellingen veranderen niet"
Vergeet niet dat `bot_config_local.json` in **`%LOCALAPPDATA%\BotConfig\`** staat, NIET in de projectmap. Controleer met:
```powershell
notepad "$env:LOCALAPPDATA\BotConfig\bot_config_local.json"
```

### "Module not found" / "ImportError"
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
Als sommige packages falen (zoals `xgboost` of `lightgbm`), dat is OK — zet `AI_ENABLED=false` in local config.

### "AI / XGBoost errors"
Bot werkt prima zonder ML. Zet in local config: `"AI_ENABLED": false`. Als je later wel AI wilt, draai eerst `python ai/xgb_train_enhanced.py` (heeft trade-historie nodig).

### "Het draait, maar mijn config wordt elke dag teruggezet"
Je hebt de bot in OneDrive/Dropbox/Google Drive gezet. Verplaats hem naar een lokale map (niet gesynced). Zie bovenaan deze README.

---

## Belangrijke files om te lezen
- `.github/copilot-instructions.md` — architectuur overview (Engels)
- `docs/FIX_LOG.md` — bekende bugs en hun fixes (handig bij problemen)
- `config/bot_config.json` — alle config keys met defaults

## Updates ophalen
Als de oorspronkelijke bot updates krijgt, kun je een nieuwe ZIP vragen of (als de code op GitHub staat) `git pull` gebruiken. **Trek nooit blindelings nieuwe code over je `data/` map** — die bevat je trade history.
