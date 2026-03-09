# Bitvavo Bot — Deployment Guide

## Vereisten

- Python 3.11+ (getest met 3.13)
- Bitvavo API key + secret
- Windows / Linux / Docker

## Installatie

```bash
git clone <repo>
cd bitvavo-bot
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Configuratie

### 1. Environment variabelen

Maak `.env` in de root:

```env
BITVAVO_API_KEY=your_api_key
BITVAVO_API_SECRET=your_api_secret
TELEGRAM_BOT_TOKEN=your_bot_token      # optioneel
TELEGRAM_CHAT_ID=your_chat_id          # optioneel
```

### 2. Bot config

`config/bot_config.json` bevat alle trading parameters. Zie
[CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) voor alle keys.

Belangrijkste settings:
```json
{
  "TEST_MODE": false,
  "LIVE_TRADING": true,
  "BASE_TRADE_AMOUNT_EUR": 12,
  "MIN_SCORE_TO_BUY": 9.0,
  "ALLOWED_MARKETS": ["BTC-EUR", "ETH-EUR", "ADA-EUR", ...]
}
```

### 3. Runtime state

`data/bot_state.json` bevat runtime state (heartbeat, circuit breaker). Wordt
automatisch beheerd — niet handmatig wijzigen.

## Starten

### Windows (aanbevolen)

```cmd
start_automated.bat
```

Dit start:
1. `trailing_bot.py` — hoofdbot
2. `ai/ai_supervisor.py` — AI parameter tuner
3. Flask dashboard (port 5001) — automatisch gestart

### Handmatig

```bash
python trailing_bot.py              # bot
python ai/ai_supervisor.py          # AI (optioneel)
python modules/dashboard_service.py  # dashboard (optioneel)
```

### Docker

```bash
docker-compose up -d
```

Zie `docker-compose.yml` voor services en ports.

## Dashboard

Open `http://localhost:5001` na starten. Features:
- Live trades overzicht
- P&L grafiek
- Config editor
- Market scores

## Monitoring

- **Logs**: `logs/` directory, per dag geroteerd
- **Telegram**: Alerts bij buy/sell/errors (als geconfigureerd)
- **AI heartbeat**: `ai/ai_heartbeat.json` — controleer `last_run`
- **Bot state**: `data/bot_state.json` — controleer `LAST_HEARTBEAT_TS`

## Troubleshooting

Zie [TROUBLESHOOTING.md](TROUBLESHOOTING.md) voor veelvoorkomende problemen.
