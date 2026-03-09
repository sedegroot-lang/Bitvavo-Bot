# Bitvavo Trading Bot

Geautomatiseerde cryptocurrency trading bot voor het Bitvavo platform met AI-gestuurde strategie optimalisatie — DCA, trailing stop, grid trading en XGBoost-gebaseerde entry signals.

> ⚠️ **Vereiste:** Je hebt een Bitvavo account nodig om deze bot te kunnen gebruiken.

---

## 🚀 Snel aan de slag

### Installatie — 2 stappen

**Stap 1** — [Download de bot](https://github.com/sedegroot-lang/bitvavo-bot/archive/refs/heads/main.zip) en pak het ZIP-bestand uit

**Stap 2** — Dubbelklik **`setup.bat`**

De wizard regelt de rest:
- ✅ Vraagt of je een Bitvavo account hebt (anders: link naar gratis registratie)
- ✅ Vraagt je API sleutels (verborgen invoer, worden lokaal opgeslagen)
- ✅ Installeert automatisch alle benodigde packages
- ✅ Maakt `.env` aan
- ✅ Vraagt of je de bot direct wil starten

> **Vereiste:** Python 3.11+ — [download hier](https://www.python.org/downloads/) (vink "Add to PATH" aan)

---

### Geen Bitvavo account?

Registreer gratis via: 👉 **[https://bitvavo.com/invite?a=B8942E4528](https://bitvavo.com/invite?a=B8942E4528)**
Bitvavo is de #1 crypto exchange van Nederland (0,00%–0,25% kosten).

---

### 💛 Steun de bot

Deze bot is gratis. Vind je hem waardevol? Doneer via BTC:

```
1DUCu4ZGgKHZr22DvAxuWKBujcfpCLJoNy
```

---

### Handmatige installatie (gevorderd)

```bash
git clone https://github.com/sedegroot-lang/bitvavo-bot.git
cd bitvavo-bot
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # vul API keys in
start_automated.bat
```

---

## ✨ Functies

| Functie | Beschrijving |
|---|---|
| **Trailing Stop** | Dynamische stop loss die meebeweegt met de winst |
| **DCA Safety Buys** | Automatisch bijkopen bij prijsdaling (tot 9 levels) |
| **Grid Bot** | AI-geoptimaliseerde grid trading met take profit + stop loss |
| **HODL Scheduler** | Wekelijkse automatische DCA-inkopen per asset |
| **XGBoost AI** | Machine learning model voor entry-signalen |
| **AI Supervisor** | Automatische parameter-optimalisatie op basis van resultaten |
| **Pyramid-up** | Bijkopen bij stijgende prijzen |
| **Audit Log** | Elke trade vastgelegd met reden en tijdstip |
| **Flask Dashboard** | Real-time portfolio monitoring, charts, AI insights |

---

## 🏗️ Architectuur

```
trailing_bot.py          ← Hoofd trading engine
modules/                 ← Gedeelde modules (DCA, grid, risk, ML)
core/                    ← Kernlogica (signalen, prijs, config)
ai/                      ← AI/ML componenten (XGBoost, supervisor)
tools/dashboard_flask/   ← Web dashboard (Flask + Chart.js)
config/bot_config.json   ← Bot configuratie
data/                    ← Runtime data (trades, heartbeat)
logs/                    ← Logbestanden
```

---

## ⚙️ Configuratie

Hoofdconfiguratie: **`config/bot_config.json`**

| Parameter | Beschrijving | Standaard |
|---|---|---|
| `MIN_SCORE_TO_BUY` | Minimale AI score voor entry | 5 |
| `DEFAULT_TRAILING` | Trailing stop % | 4% |
| `MAX_OPEN_TRADES` | Max gelijktijdige trades | 5 |
| `BASE_AMOUNT_EUR` | Bedrag per trade | €12 |
| `DCA_MAX_BUYS` | Max DCA safety buys | 9 |

---

## 🔒 Veiligheid

- API keys staan **alleen** in `.env` — nooit in code of git
- `.env` is opgenomen in `.gitignore`
- Audit log registreert alle trades en beslissingen
- Rate limit guards voorkomen API-misbruik
- Stop loss op grid en trailing beschermt kapitaal

---

## 📖 Documentatie

- [BOT_SYSTEM_OVERVIEW.md](docs/BOT_SYSTEM_OVERVIEW.md) — Complete technische documentatie
- [CHANGELOG.md](CHANGELOG.md) — Wijzigingen log
- [ROADMAP.md](ROADMAP_PROFIT_OPTIMIZATION.md) — Toekomstige features

---

## ⚠️ Disclaimer

Cryptocurrency trading brengt risico's met zich mee. Deze bot is een hulpmiddel — geen garantie op winst. Gebruik op eigen risico. Beleg nooit meer dan je kunt missen.

---

**Vragen?** Open een issue op GitHub of neem contact op.


Voor een **volledige technische overview** van alle functies, modules en bestanden:
👉 **[BOT_SYSTEM_OVERVIEW.md](docs/BOT_SYSTEM_OVERVIEW.md)** - Complete systeem documentatie

**Andere belangrijke documenten:**
- 📋 [TODO.md](docs/TODO.md) - Active tasks & priorities
- 🤖 [AUTONOMOUS_EXECUTION_PROMPT.md](docs/AUTONOMOUS_EXECUTION_PROMPT.md) - AI execution guidelines
- 📝 [CHANGELOG.md](CHANGELOG.md) - Wijzigingen log

---

## 🏗️ Architectuur

```
┌─────────────────────────────────────────────────────────────────┐
│                         Bitvavo API                              │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────┼──────────────────────────────────┐
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Trading Engine                            │ │
│  │                  (trailing_bot.py)                           │ │
│  └─────────────────────────────────────────────────────────────┘ │
│         │              │              │              │           │
│         ▼              ▼              ▼              ▼           │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐     │
│  │  Signal   │  │  Position │  │   Trade   │  │   Risk    │     │
│  │  Scorer   │  │  Manager  │  │  Executor │  │  Manager  │     │
│  └───────────┘  └───────────┘  └───────────┘  └───────────┘     │
│                                                                  │
│  ┌─────────────────────────── Core ────────────────────────────┐ │
│  │ cache │ config │ error_handler │ health │ price_engine     │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─────────────────────────── AI/ML ───────────────────────────┐ │
│  │ ai_supervisor │ ml_optimizer │ xgb_trainer │ ensemble       │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│                     Bitvavo Trading Bot                          │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Streamlit Dashboard                            │
│            Real-time monitoring & analytics                       │
└──────────────────────────────────────────────────────────────────┘
```

## 📁 Project Structuur

```
Bitvavo Bot/
├── core/                    # Core business logic modules
│   ├── cache.py            # Thread-safe LRU cache with TTL
│   ├── config_manager.py   # Singleton configuration management
│   ├── error_handler.py    # Centralized error handling
│   ├── health_server.py    # HTTP health check endpoints
│   ├── position_manager.py # Position tracking & exposure
│   ├── price_engine.py     # Price fetching & caching
│   ├── reservation_manager.py # Thread-safe market reservations
│   ├── signal_scorer.py    # Technical analysis & signals
│   └── trade_executor.py   # Order execution & validation
├── ai/                      # AI and ML components
│   ├── ai_supervisor.py    # AI advisor for parameter tuning
│   ├── ml_optimizer.py     # ML-based optimization
│   └── xgb_auto_train.py   # XGBoost model training
├── modules/                 # Shared modules
│   ├── trading.py          # Trading utilities
│   ├── trading_dca.py      # DCA strategy
│   ├── trading_risk.py     # Risk management
│   └── ml.py               # ML ensemble predictions
├── config/                  # Configuration files
│   └── bot_config.json     # Main bot configuration
├── tools/                   # Utilities and dashboard
│   └── dashboard/          # Streamlit dashboard
├── tests/                   # Test suite (264+ tests)
├── data/                    # Runtime data
├── logs/                    # Log files
└── docs/                    # Documentation
```

## 🚀 Quick Start

### 1. Bot Starten

**Windows (aanbevolen):**
```batch
cd scripts\startup
START_BOT.bat
```

**Direct met Python:**
```bash
python scripts\startup\start_bot.py
```

### 2. Dashboard Starten

```batch
cd scripts\startup
start_dashboard.bat
```

Of handmatig:
```bash
.venv\Scripts\streamlit run tools\dashboard\dashboard_streamlit.py
```

## 📊 Dashboard

Het Streamlit dashboard toont:
- Real-time trading status
- Open posities en performance
- AI suggesties en markt regime
- Risk metrics en exposure
- Trade geschiedenis

Access: `http://localhost:8501` (na starten van dashboard)

## ⚙️ Configuratie

Hoofdconfiguratie: **`config/bot_config.json`**

Belangrijke parameters:
- `MIN_SCORE_TO_BUY` - Minimale score voor trade entry (huidige: 5)
- `DEFAULT_TRAILING` - Trailing stop percentage (4%)
- `MAX_OPEN_TRADES` - Maximum aantal gelijktijdige trades (2)
- `MAX_EUR_PER_TRADE` - Maximum EUR per trade (5.00)
- `RISK_SEGMENT_BASE_LIMITS` - Risk limits per segment (alts: 200, majors: 150, stable: 50)

## 🤖 AI Features

- **AI Supervisor** (`ai/ai_supervisor.py`) - Analyseert performance en stelt parameteraanpassingen voor
- **XGBoost Model** (`ai/ai_xgb_model.json`) - Machine learning model voor market scoring
- **Risk Management** (`modules/trading_risk.py`) - Segment-based drawdown protection

## 📈 Trading Strategy

- **DCA (Dollar Cost Averaging)** - Incrementele aankopen bij prijsdaling
- **Trailing Stop** - Dynamische stop loss die meebeweegt met winst
- **AI-driven Entry** - Machine learning gebaseerde market selectie
- **Risk Segmentation** - Verschillende risk limits voor majors/alts/stablecoins

## 🛠️ Handige Scripts

### Status Check
```bash
python scripts\helpers\check_processes.py
```

### Sync met Bitvavo
```bash
python scripts\helpers\sync_from_bitvavo.py
```

### Analyse
```bash
python scripts\helpers\analyze_bot_deep.py
python scripts\helpers\analyze_loss_trades.py
```

### Backtesting
```bash
python tools\backtest\backtest.py
python tools\backtest\parameter_sweep.py
```

## 📝 Belangrijke Bestanden

| Bestand | Locatie | Beschrijving |
|---------|---------|--------------|
| Hoofdconfiguratie | `config/bot_config.json` | Bot parameters |
| Trade log | `data/trade_log.json` | Alle trades en performance |
| Heartbeat | `data/heartbeat.json` | Bot status updates |
| Bot log | `logs/bot_log.txt` | Gedetailleerde logs |
| AI suggesties | `data/ai_suggestions.json` | AI parameter aanbevelingen |

## 🔒 Environment Variables

Maak een `.env` bestand in de root met:

```env
BITVAVO_API_KEY=your_api_key_here
BITVAVO_API_SECRET=your_api_secret_here
BITVAVO_OPERATOR_ID=your_operator_id  # Optioneel
```

## 📖 Documentatie

- [Project Structure](docs/PROJECT_STRUCTURE.md) - Volledige directory structuur
- [AI Portfolio](docs/AI_PORTFOLIO_README.md) - AI features documentatie
- [Cleanup Plan](docs/CLEANUP_PLAN.md) - Reorganisatie details
- [TODO](docs/TODO.md) - Development roadmap
- [Improvements](docs/BOT_IMPROVEMENTS_2025-11-07.md) - Recent verbeteringen

## 🧪 Testing

```bash
pytest tests/
```

## 🔄 Process Management

De bot gebruikt een multi-process architectuur:

1. **start_bot.py** - Main coordinator
2. **monitor.py** - Process watchdog
3. **trailing_bot.py** - Main trading engine
4. **ai_supervisor.py** - AI advisor

Stop alle processen met `Ctrl+C` in het start_bot.py venster.

## ⚠️ Risk Disclaimer

Deze bot is voor educatieve doeleinden. Cryptocurrency trading heeft risico's. Gebruik op eigen risico.

## 📊 Performance

Zie `data/trade_log.json` voor:
- Win ratio
- Gemiddelde winst/verlies
- Total P&L
- Trade geschiedenis

Dashboard toont real-time metrics.

## 🛡️ Risk Management

- **Segment-based limits** - Verschillende limits voor coin categorieën
- **Drawdown protection** - Stopt trading bij te grote verliezen
- **Position sizing** - Maximale exposure per trade
- **Max open trades** - Beperkt aantal gelijktijdige posities

## 🔧 Troubleshooting

### Bot start niet
1. Check processes: `python scripts\helpers\check_processes.py`
2. Check config: `config/bot_config.json` bestaat?
3. Check logs: `logs/bot_log.txt`

### Geen trades
1. Check MIN_SCORE_TO_BUY (huidige: 5)
2. Check risk limits in config
3. Check EUR balance
4. Check logs voor risk guard messages

### Dashboard niet beschikbaar
1. Herstart: `scripts\startup\start_dashboard.bat`
2. Check port 8501
3. Check `tools/dashboard/dashboard_streamlit.py` exists

## 📞 Support

Check de logs in `logs/` voor gedetailleerde foutmeldingen.

---

**Laatste reorganisatie:** November 16, 2025  
**Versie:** 2.0 (Gereorganiseerde structuur)
