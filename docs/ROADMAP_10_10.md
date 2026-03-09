# Roadmap: Van 5.5 → 10 / 10
**Datum:** 2026-02-22  
**Basis:** OPUS_BOT_REVIEW_POST_IMPROVEMENTS (5.5/10)  
**Doel:** Productie-grade trading bot met bewezen edge

---

## Huidige scores vs doelscores

| Criterium | Nu | Doel | Gap |
|-----------|-----|------|-----|
| Winstgevendheid | 3 | 10 | **-7** |
| Risicobeheer | 6 | 10 | -4 |
| Strategie-logica | 5 | 10 | -5 |
| AI/ML kwaliteit | 4 | 10 | **-6** |
| Data-integriteit | 7 | 10 | -3 |
| Code-architectuur | 5 | 10 | -5 |
| Configuratie | 7 | 10 | -3 |
| Monitoring | 5 | 10 | -5 |
| Testing | 7 | 10 | -3 |
| Operationeel | 5 | 10 | -5 |

**Prioritering:** Grootste ROI = Winstgevendheid + AI/ML + Strategie. De rest is kwaliteit/stabiliteit.

---

## FASE 1 — Bewijs van Edge (Week 1-2)
> **Doel:** Weten of de strategie écht werkt. Zonder dit heeft verdere optimalisatie geen zin.

### 1.1 Walk-Forward XGBoost validatie
**Actie:** `python ai/xgb_walk_forward.py`  
**Verwacht:** Per-fold metrics (accuracy, precision, recall) over 6 maanden data  
**Doel:** Sharpe > 0.5 per fold, accuracy > 55%  
**Slaagt, ga naar 1.2. Faalt → strategie herdenken voor verdere investering.**

### 1.2 Backtest BTC/ETH/SOL (30 dagen)
```bash
python scripts/backtest_engine.py --market BTC-EUR --days 30
python scripts/backtest_engine.py --market ETH-EUR --days 30
python scripts/backtest_engine.py --market SOL-EUR --days 30
```
**Doel:** Netto P&L > 0 na fees op alle 3 markten  
**Metrics:** Win rate, gemiddeld P&L/trade, max drawdown, Sharpe ratio

### 1.3 A/B paper trade (7 dagen live)
```bash
python scripts/ab_paper_trade.py --config-a config/bot_config.json --days 7
```
**Doel:** Live bevestiging van backtest resultaten zonder echt geld  
**Drempel:** ≥ 55% win rate, gem. profit > €0.10/trade

### 1.4 Analyseer historische verliezende trades
```python
# Voer uit in Python console
import json
d = json.load(open('data/trade_log.json'))
losses = [t for t in d['closed'] if float(t.get('profit',0)) < -0.5 and t.get('reason') not in ['sync_removed','saldo_flood_guard']]
# Groepeer op: markt, tijdstip, RSI bij entry, score bij entry
```
**Doel:** Patronen vinden in echte verliezen → betere entry-filters

**Score na Fase 1:** Winstgevendheid 3→5, Strategie 5→6

---

## FASE 2 — Strategie Versterking (Week 2-4)
> **Doel:** Betere entries, minder valse signalen, hogere win rate.

### 2.1 Entry-kwaliteitsfilters aanscherpen
Gebaseerd op analyse Fase 1.4. Kandidaten:
- Verhoog `MIN_SCORE_TO_BUY` van 10 naar 12 (minder maar betere trades)
- Voeg 4H trend filter toe: block entries onder 4H SMA (macro trend)
- `MOMENTUM_FILTER_THRESHOLD` aanpassen naar -8 (was -12)
- Voeg volume-bevestiging toe: 24h volume > 1.5× 7-daags gemiddelde

**Bestand:** `config/bot_config.json` + `modules/signals/`

### 2.2 Mean-Reversion Scalper tunen
- Backtest `mean_reversion_scalper.py` apart: welk VWAP Z-score geeft beste resultaten?
- Test Z-score drempels: -1.5, -2.0, -2.5
- Voeg RSI divergentie toe als extra bevestiging

### 2.3 Partial TP optimalisatie
Analyseer huidige TP-statistieken:
```python
stats = json.load(open('data/partial_tp_stats.json'))
# L1=233x (€354), L2=131x (€264), L3=62x (€131)
# L3 hit rate slechts 26% van L2 — target wellicht te hoog
```
**Aanpassing:** L3 target van 12% naar 9% (hogere hit rate, meer gerealiseerde winst)

### 2.4 Stale buyprijs bug definitief fixen
**Probleem:** Na herstart laadt bot oude koopprijzen (OP-EUR: €0.2585 i.p.v. €0.1071)  
**Locatie:** `trailing_bot.py` — state-laden logica bij startup  
**Fix:** Bij laden van trade state: valideer koopprijs tegen actuele Bitvavo balances  
```python
# In startup sync: als |buy_price - current_price| > 50%, vraag Bitvavo order history
# voor validatie van werkelijke aankoopprijs
```
**Impact:** Voorkomt onterechte stop-loss triggers na herstart

### 2.5 Activeer Pyramid-Up DCA (na backtest bewijs)
Alleen activeren als Fase 1 positief uitvalt:
```json
"DCA_ENABLED": true,
"DCA_PYRAMID_UP": true,
"DCA_PYRAMID_MIN_PROFIT_PCT": 0.04,
"DCA_PYRAMID_MAX_ADDS": 2,
"DCA_PYRAMID_SCALE_DOWN": 0.6
```

**Score na Fase 2:** Winstgevendheid 5→7, Strategie 6→8

---

## FASE 3 — AI/ML Volwassenheid (Week 3-6)
> **Doel:** ML-model dat daadwerkelijk bijdraagt aan betere beslissingen.

### 3.1 Feature importance analyse
```bash
python ai/xgb_walk_forward.py --output-features reports/feature_importance.json
```
**Verwijder features met importance < 1%** — minder noise, betere generalisatie  
**Kandidaten om toe te voegen:** bid-ask spread, order book imbalance, funding rate

### 3.2 Training data kwaliteitsbeheer
- Toevoegen: datakwaliteitscheck vóór training (missende waarden, outliers)
- Minimaal 2000 samples per markt voor training (nu: 250 → verhoog `min_samples`)
- Label noise reductie: gebruik 3-candle bevestiging voor target_threshold

**Bestand:** `ai/xgb_train_enhanced.py`, `ai/xgb_walk_forward.py`
```json
"AI_RETRAIN_ARGS": {
  "limit": 2000,
  "min_samples": 500,
  "target_threshold": 0.01
}
```

### 3.3 Per-markt XGBoost modellen
Huidige architectuur: 1 globaal model voor alle markten  
**Probleem:** BTC en RENDER hebben compleet verschillende karakteristieken  
**Fix:** Train apart model per markt (of per marktcategorie: major/alt/meme)
```
models/xgb_BTC-EUR.json
models/xgb_ETH-EUR.json  
models/xgb_alts.json
```

### 3.4 Ensemble confidence threshold verhogen
```json
"ENSEMBLE_MIN_CONFIDENCE": 0.75  // was 0.70
```
Accepteer alleen signalen waarbij XGB > 75% zeker is — minder maar betere entries

### 3.5 AI Supervisor validatie toevoegen
**Probleem:** AI supervisor wijzigt config-parameters zonder bewijs dat dit helpt  
**Fix:** Voeg A/B test toe: parameter mutatie alleen doorvoeren als paper trade resultaat verbetert over 24h  
**Bestand:** `ai/ai_supervisor.py`

### 3.6 Regime detectie uitbreiden
Voeg toe: volatility regime (laag/middel/hoog)  
- In hoge volatiliteit: kleinere positiegrootte, wijdere stops  
- In lage volatiliteit: mean-reversion strategie dominant  
**Bestand:** `modules/market_regime.py`

**Score na Fase 3:** AI/ML 4→8, Strategie 8→9

---

## FASE 4 — Operationele Robuustheid (Week 4-8)
> **Doel:** Bot draait 24/7 zonder handmatige tussenkomst.

### 4.1 VPS migratie
**Platform:** Hetzner CX21 (~€5/maand) of DigitalOcean Droplet  
**Stappen:**
1. Maak Docker image: `docker build -t bitvavo-bot .`
2. Upload naar VPS: `docker-compose up -d`
3. Zet auto-restart op: `restart: always` in docker-compose.yml
4. Test: kill alle processen, bevestig auto-restart binnen 60s

**Voordeel:** Geen Windows-afhankelijkheid, stabiele connectie, geen slaapstand

### 4.2 Auto-restart watchdog verbeteren
Huidige `start_automated.bat` is fragiel. Vervang door:  
**Optie A (Docker):** `restart: always` — automatisch na crash  
**Optie B (systemd op Linux VPS):**
```ini
[Service]
ExecStart=/usr/bin/python3 /app/trailing_bot.py
Restart=always
RestartSec=30
```

### 4.3 Health monitoring
```python
# Nieuwe module: modules/health_monitor.py
# Controleert elke 5 minuten:
# - Bot draait?
# - Laatste heartbeat < 10 min geleden?
# - API bereikbaar?
# - Open trades gesynchroniseerd?
# → Stuurt Telegram alert als iets faalt
```

### 4.4 Telegram alerting uitbreiden
Voeg toe: dagelijks rapport om 08:00 met:
- Open posities + unrealized P&L
- Beste/slechtste trade van de dag
- API health status
- Budget gebruik per segment

**Bestand:** `notifier.py`

### 4.5 Graceful shutdown
Bij SIGTERM/SIGINT: sla state op, sluit geen posities (tenzij expliciet gevraagd)  
**Bestand:** `trailing_bot.py` — signal handler

**Score na Fase 4:** Operationeel 5→9, Monitoring 5→8

---

## FASE 5 — Code Architectuur (Week 6-10)
> **Doel:** Onderhoudbare codebase die veilig aangepast kan worden.

### 5.1 trailing_bot.py opsplitsen (geleidelijk)
**Risico: HOOG — doe dit in kleine stappen, elke stap met tests**  
Volgorde:
1. Extraheer `bot_loop()` → `modules/bot_loop.py` (~500 regels)
2. Extraheer `open_trade_async()` → `modules/trade_executor.py`
3. Extraheer config loading → `core/config_loader.py`
4. Extraheer state management → `core/state_manager.py`

**Doel:** trailing_bot.py van ~5100 naar <500 regels (alleen orchestratie)

### 5.2 Stille except:pass elimineren
**Zoek alle `except` zonder logging:**
```bash
grep -n "except.*:" trailing_bot.py | grep -v "log\|logger\|print\|raise"
```
**Vervang elk exemplaar door:**
```python
except Exception as e:
    log(f"[ERROR] {context}: {e}", level='error')
```
Doel: 0 stille fouten in financiële code paths

### 5.3 Config state vervuiling oplossen
**Verplaats runtime state uit bot_config.json:**
```
bot_config.json         → alleen configuratie (statisch)
data/runtime_state.json → runtime waarden (_circuit_breaker_until_ts, etc.)
```
**Bestand:** `core/config_loader.py` + `core/state_manager.py`

### 5.4 Duplicate config keys opruimen
| Verwijder | Behoud | 
|-----------|--------|
| `STOP_LOSS_ENABLED` | `ENABLE_STOP_LOSS` |
| `STOP_LOSS_HARD_PCT` | `HARD_SL_ALT_PCT` |
| `DCA_MAX_ORDERS` | `DCA_MAX_BUYS` |
| `STOP_LOSS_PERCENT` | `HARD_SL_ALT_PCT` |

**Test na elke verwijdering dat alle tests nog slagen.**

### 5.5 Core/ modules aansluiten of verwijderen
Huidige situatie: 91% van `core/` is dode code  
**Audit elke module:**
```bash
grep -r "from core\." trailing_bot.py modules/ ai/
```
→ Niet gebruikt: verwijder of markeer als `# DEPRECATED`  
→ Wel nuttig: integreer in actieve code paths

**Score na Fase 5:** Code-architectuur 5→8

---

## FASE 6 — Data-integriteit & Testing (Week 8-12)
> **Doel:** Vertrouwen in elke output van de bot.

### 6.1 Tests voor sync_removed fix
```python
# tests/test_trading_sync.py
def test_sync_removed_respects_disable_flag():
    # Mock: DISABLE_SYNC_REMOVE=True, trade exists in memory but not on exchange
    # Assert: trade is NOT removed from state

def test_sync_removed_api_glitch_protection():
    # Mock: API returns empty balances
    # Assert: no trades removed
```

### 6.2 Tests voor pyramid-up DCA
```python
# tests/test_trading_dca.py  
def test_pyramid_up_only_fires_in_profit():
def test_pyramid_up_respects_max_adds():
def test_pyramid_up_scale_down_per_add():
```

### 6.3 Integration tests voor kritieke flows
**Momenteel ontbrekend:**
- `open_trade_async()` end-to-end test
- `place_sell_order()` end-to-end test
- Bot restart met bestaande state test
- Stop-loss trigger test (inclusief stale-price validatie)

### 6.4 P&L reconciliatie tool
```python
# scripts/reconcile_pnl.py
# Vergelijkt:
# 1. trade_log.json closed trades P&L
# 2. Bitvavo transaction history P&L
# 3. Account balance verschil
# → Rapporteert discrepanties > €0.10
```

### 6.5 Dagelijkse data backup
```python
# Automatisch in bot startup:
# Backup trade_log.json, expectancy_stats.json naar backups/<datum>/
# Behoud 30 dagen history
```

**Score na Fase 6:** Data-integriteit 7→9, Testing 7→9

---

## FASE 7 — Configuratie & Monitoring Perfectie (Week 10-14)
> **Doel:** Alles is meetbaar, configureerbaar en gedocumenteerd.

### 7.1 Config schema validatie
```python
# Bij elke start: valideer bot_config.json tegen schema
# Schema check: types, ranges, conflicten
# Blokkeer bot start als config ongeldig is
```

### 7.2 Live dashboard
**Optie A:** Eenvoudig: Telegram-bot commando's (`/status`, `/trades`, `/pnl`)  
**Optie B:** Web dashboard op VPS poort 8080 (Flask + Bootstrap)  
**Metrics:**
- Real-time P&L (dag/week/totaal)
- Open posities met unrealized P&L
- Win rate laatste 50 trades
- AI/XGBoost confidence scores
- Budget gebruik

### 7.3 Anomalie detectie
```python
# Alert als:
# - Win rate 7-daags < 40% → reduce position size
# - 3 opeenvolgende verliezen > 3% → pause 2 uur
# - Daily loss > 5% portfolio → stop bot, notify
# - Spread > 1.5% (abnormaal) → skip market
```

### 7.4 Performance benchmark
Maandelijkse vergelijking vs benchmark:
- Bot P&L vs buy-and-hold BTC
- Bot P&L vs buy-and-hold portfolio (gewogen whitelist)
- Sharpe ratio vs baseline (0.0)

### 7.5 Config documentatie
Eén markdown bestand (`docs/CONFIG_REFERENCE.md`):
- Elke parameter: type, default, bereik, effect
- Conflicterende parameters gemarkeerd
- Voorbeeldconfiguraties per use-case (conservatief/agressief/paper)

**Score na Fase 7:** Configuratie 7→10, Monitoring 5→10

---

## Totaalplanning

| Fase | Duur | Prioriteit | Scores die verbeteren |
|------|------|-----------|----------------------|
| **1 — Edge bewijs** | Week 1-2 | 🔴 KRITIEK | Winstgevendheid +2, Strategie +1 |
| **2 — Strategie** | Week 2-4 | 🔴 HOOG | Winstgevendheid +2, Strategie +2 |
| **3 — AI/ML** | Week 3-6 | 🔴 HOOG | AI/ML +4, Strategie +1 |
| **4 — Operationeel** | Week 4-8 | 🟡 MIDDEL | Operationeel +4, Monitoring +3 |
| **5 — Architectuur** | Week 6-10 | 🟡 MIDDEL | Code +3, Config +1 |
| **6 — Testing** | Week 8-12 | 🟢 KWALITEIT | Testing +2, Data +2 |
| **7 — Perfectie** | Week 10-14 | 🟢 KWALITEIT | Config +3, Monitoring +2 |

---

## Verwachte eindscore per fase

| Na Fase | Score | Toename |
|---------|-------|---------|
| Nu (basis) | 5.5 | — |
| Na Fase 1 | 6.2 | +0.7 |
| Na Fase 2 | 7.1 | +0.9 |
| Na Fase 3 | 8.0 | +0.9 |
| Na Fase 4 | 8.5 | +0.5 |
| Na Fase 5 | 8.9 | +0.4 |
| Na Fase 6 | 9.3 | +0.4 |
| Na Fase 7 | **10.0** | +0.7 |

---

## Directe volgende stap (nu)

```bash
# Stap 1: valideer of strategie werkt
python ai/xgb_walk_forward.py

# Stap 2: backtest 3 markten
python scripts/backtest_engine.py --market BTC-EUR --days 30
python scripts/backtest_engine.py --market ETH-EUR --days 30

# Stap 3: bekijk resultaten → go/no-go voor Fase 2+
```

**Als backtest positief (P&L > 0, WR > 55%):** doorloop alle fasen.  
**Als backtest negatief:** stop met optimaliseren en heronderzoek de fundamentele strategie-aannames vóór verdere investering.

---

*Laatste update: 2026-02-22*  
*Basis: OPUS_BOT_REVIEW_POST_IMPROVEMENTS (5.5/10)*
