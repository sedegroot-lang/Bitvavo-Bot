# Setup — Bitvavo Trading Bot

End-to-end onboarding for a fresh machine. Time: ~15 min.

## 1. Prerequisites

- Python 3.13 (or 3.11+)
- Git
- Optional: Ollama (for local AI agents — free, no API costs)
- Bitvavo account + API key/secret with trading permission

## 2. Clone

```powershell
git clone https://github.com/sedegroot-lang/Bitvavo-Bot.git
cd Bitvavo-Bot
```

## 3. Virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

## 4. Install dependencies

```powershell
# Minimum to run the bot:
pip install -r requirements-core.txt

# Add ML/AI features (XGBoost training, LangGraph agents):
pip install -r requirements-ml.txt

# Add dev tools (tests, lint):
pip install -r requirements-dev.txt
```

## 5. Configure secrets

Copy the env template and fill in your Bitvavo + Telegram credentials:

```powershell
Copy-Item .env.example .env
notepad .env
```

Required:
- `BITVAVO_API_KEY` / `BITVAVO_API_SECRET` — exchange access
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — notifications (optional but recommended)

## 6. Configure trading parameters (Windows-only — local override)

The bot uses a 3-layer config merge. **All your local changes go to one file** outside OneDrive:

```powershell
$localPath = Join-Path $env:LOCALAPPDATA "BotConfig\bot_config_local.json"
New-Item -ItemType Directory -Path (Split-Path $localPath) -Force | Out-Null
if (-not (Test-Path $localPath)) { '{}' | Out-File -Encoding utf8 $localPath }
notepad $localPath
```

This file loads LAST and wins over the OneDrive-synced base config. See [docs/CONFIG_REFERENCE.md](docs/CONFIG_REFERENCE.md) for all keys.

**Minimum sane defaults** (already provided in `config/bot_config.json`):
- `MAX_OPEN_TRADES`: 4
- `BASE_INVEST_EUR`: 25
- `MIN_SCORE_TO_BUY`: 7.0

## 7. First smoke test

```powershell
# Verify imports + config load
python -c "from modules.config import load_config; c = load_config(); print('config keys:', len(c))"

# Run unit tests
python -m pytest tests/ -q
```

Expected: ~all tests pass.

## 8. Start the bot

### Option A: All-in-one (recommended, Windows)
```powershell
.\start_automated.bat
```
Spawns: trailing_bot, dashboard V2 (`:5002`), AI supervisor, auto-retrain, auto-backup, monitor.

### Option B: Just the trading loop
```powershell
python trailing_bot.py
```

### Option C: Dashboard only (read-only inspection)
```powershell
python -m uvicorn tools.dashboard_v2.backend.main:app --host 127.0.0.1 --port 5002
```
Open <http://localhost:5002>.

## 9. Optional — local AI agents (Ollama)

Run `tools/agents_demo.py` to use a local LLM (free, offline) for trade reviews:

```powershell
# 1. Install Ollama:
winget install --id Ollama.Ollama --accept-source-agreements --accept-package-agreements

# 2. Pull a small model (~2GB):
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull llama3.2:3b

# 3. Run the LangGraph demo:
python tools\agents_demo.py
```

## 10. Health check

```powershell
python scripts\helpers\ai_health_check.py
```

Runs 7 automated checks: config, open trades, performance, budget, processes, errors, roadmap alignment.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Bitvavo authentication failed` | Re-check `.env` has correct `BITVAVO_API_KEY` / `BITVAVO_API_SECRET` |
| Telegram messages not arriving | `python -c "from notifier import send_telegram; print(send_telegram('test'))"` should return `True` |
| Bot exits immediately | Check `logs/bot_log.txt` for stack trace |
| Config changes ignored | Edit `%LOCALAPPDATA%\BotConfig\bot_config_local.json` (NOT `config/bot_config.json` — OneDrive reverts it) |
| `ModuleNotFoundError` | Activate venv (`.\.venv\Scripts\Activate.ps1`) and re-install requirements |

See also: [docs/FIX_LOG.md](docs/FIX_LOG.md), [docs/COPILOT_ROAD_TO_10.md](docs/COPILOT_ROAD_TO_10.md).
