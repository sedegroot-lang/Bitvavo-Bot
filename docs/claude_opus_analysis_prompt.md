# ULTRA-DEEP CODEBASE ANALYSIS PROMPT — BITVAVO TRADING BOT
> **Voor: Claude Opus** | Datum: 2026-03-13

---

## CONTEXT & OPDRACHT

Je bent een senior trading-systems architect met diepgaande kennis van:
- Python crypto-trading bots (Bitvavo exchange)
- ML-gedreven handelssystemen (XGBoost, LSTM, RL, ensemble-gating)
- Production-grade financiële software (threading, atomaire writes, circuit breakers)
- Refactoring van monolithische codebases naar modulaire architecturen

**Jouw taak**: Voer een **ultradiepe, meedogenloze analyse uit van de volledige Bitvavo Trading Bot codebase**. Lees ALLE bestanden die hieronder vermeld worden. Beoordeel elk component op een schaal van **1–10** (10 = productie-perfect, 1 = kritieke fouten). Geef per onderdeel **concrete, uitvoerbare verbeteradviezen** die Claude Sonnet 4.5 direct kan implementeren met file-edit tools.

**Analyseer dit in drie lagen:**
1. **Correctheid** — Werkt de logica zoals bedoeld?
2. **Robuustheid** — Wat gaat stuk onder edge cases, concurrency of API-fouten?
3. **Winst-impact** — Welke bugs/suboptimale logica kosten direct geld?

---

## BESTANDEN OM TE LEZEN (lees ze allemaal, in volgorde)

### Entry Point & Kern
```
trailing_bot.py                    (~4300 regels — de hoofdmonoliet)
```

### bot/ package
```
bot/__init__.py
bot/api.py                         (rate limiting, circuit breaker, caching, safe_call)
bot/helpers.py                     (as_float, as_int, as_bool)
bot/orders_impl.py                 (buy/sell executie)
bot/performance.py                 (performance snapshots)
bot/portfolio.py                   (portfolio analyse)
bot/shared.py                      (_SharedState singleton)
bot/signals.py                     (signal scoring + ML gate)
bot/sync_engine.py                 (exchange sync)
bot/trade_lifecycle.py             (trade open/close lifecycle)
bot/trailing.py                    (7-level stepped trailing stops)
```

### core/ package
```
core/__init__.py
core/adaptive_exit.py
core/avellaneda_stoikov.py
core/binance_lead_lag.py
core/correlation_shield.py
core/funding_rate_oracle.py
core/indicators.py                 (SMA, RSI, MACD, ATR, Bollinger, Stochastic)
core/kelly_sizing.py               (half-Kelly + volatility parity)
core/momentum_cascade.py
core/mtf_confluence.py
core/orderbook_imbalance.py
core/regime_engine.py              (4 regimes: TRENDING_UP, RANGING, HIGH_VOLATILITY, BEARISH)
core/reservation_manager.py
core/smart_execution.py
core/trade_investment.py
core/volume_profile.py
```

### modules/ package
```
modules/config.py                  (3-laags config merge: json + overrides + local)
modules/config_schema.py           (schema validatie)
modules/logging_utils.py
modules/trading.py
modules/trading_dca.py             (DCA manager)
modules/trading_liquidation.py
modules/trading_monitoring.py
modules/trading_risk.py
modules/trading_sync.py
modules/ml.py                      (predict_ensemble: XGBoost + LSTM + RL gate)
modules/ml_lstm.py
modules/reinforcement_learning.py
modules/signals/                   (plugin-systeem)
    __init__.py
    base.py
    [alle provider bestanden]
modules/metrics.py
modules/perf_monitor.py
modules/telegram_handler.py
modules/trade_archive.py
modules/trade_store.py
modules/trade_lifecycle.py
modules/trade_execution.py
modules/cost_basis.py
modules/trade_block_reasons.py
modules/external_trades.py
modules/quarantine_manager.py
modules/watchlist_manager.py
modules/data_integrity.py
modules/sync_validator.py
modules/database_manager.py
modules/storage.py
modules/json_compat.py
modules/event_hooks.py
modules/pairs_arbitrage.py
modules/pairs_executor.py
modules/grid_trading.py
modules/invested_sync.py
modules/websocket_client.py
modules/bitvavo_client.py
modules/api_rate_limiter.py
modules/ai_engine.py
modules/ai_markets.py
modules/ai_sentiment.py
modules/ai_feedback_loop.py
modules/ai_indicator_correlation.py
modules/advanced_metrics.py
modules/performance_analytics.py
modules/pnl_aggregator.py
modules/diversification.py
modules/dashboard_render.py
modules/external_sell_detector.py
```

### ai/ package
```
ai/ai_supervisor.py
ai/suggest_rules.py
ai/market_analysis.py
ai/ml_optimizer.py
ai/auto_retrain.py
ai/xgb_auto_train.py
ai/xgb_train_enhanced.py
ai/xgb_walk_forward.py
ai/process_ai_market_suggestions.py
```

### tests/
```
tests/conftest.py
tests/test_bot_api.py
tests/test_bot_trailing.py
tests/test_indicators.py
tests/test_signal_providers.py
tests/test_trading_behaviors.py
tests/test_integration.py
tests/test_critical_paths.py
tests/test_trade_investment.py
tests/test_trade_guards.py
tests/test_sync_removed.py
tests/test_pyramid_dca.py
[alle overige test bestanden]
```

### Config
```
config/bot_config.json
config/bot_config_overrides.json
config/config_schema.py (of waar ook staan)
```

---

## ANALYSE-STRUCTUUR

Gebruik **exact deze structuur** voor elk van de 15 componenten hieronder:

```
## [Naam Component]
**Score: X/10**
**Samenvatting**: [1-2 zinnen wat het doet en algemeen oordeel]

### Gevonden problemen
1. **[KRITIEK/HOOG/MEDIUM/LAAG]** — [Probleem beschrijving]
   - Locatie: `bestand.py` regel ~XXX
   - Impact: [Wat gaat er fout / wat kost het geld]
   - Fix voor Sonnet: [Exact wat te doen, inclusief code snippet of pseudo-code]

### Concrete verbeteradviezen
- [Specifieke actie die Sonnet kan uitvoeren]
```

---

## DE 15 COMPONENTEN OM TE ANALYSEREN

### 1. ARCHITECTUUR & REFACTORING STATUS
*Focus: Hoe ver is de monoliet-naar-modulair refactoring? Zijn er circulaire imports, god-objects, duplicatie? Welk deel van trailing_bot.py is al geëxtraheerd en welke logica zit er nog gevaarlijk in de monoliet opgesloten?*

Specifieke vragen:
- Bestaat er state-duplicatie tussen trailing_bot.py globals en bot/shared.py?
- Zijn er functies in trailing_bot.py die in meerdere bot/-modules gedupliceerd zijn?
- Welke circulaire import-risico's bestaan er?
- Is de dependency-injectie via `state` consistent doorgevoerd?

---

### 2. HANDELSLOGICA — TRAILING STOP & PARTIAL TP
*Focus: bot/trailing.py, stepped trailing levels, partial take-profit*

Specifieke vragen:
- Is de 7-level stepped trailing correct geïmplementeerd? Zijn er off-by-one fouten in de level-selectie?
- Wordt `highest_price` correct bijgewerkt bij DCA (cost basis verandert)?
- Is de partial TP correctie op `invested_eur` na een verkoop atomair (thread-safe)?
- Hoe worden tp_levels_done bijgehouden als de bot herstart?
- Zijn er race-conditions tussen trailing_check en DCA_check op hetzelfde trade-object?

---

### 3. DCA LOGICA
*Focus: modules/trading_dca.py, DCAManager, DCA triggers*

Specifieke vragen:
- Is de DCA drop-percentage berekening correct relatief aan de huidige gemiddelde inkoopprijs of de initiële prijs?
- Wordt de cost-basis na elke DCA buy correct herberekend?
- Is DCA_MAX_BUYS correct geëxecuteerd onder concurrente loop-iteraties?
- Zijn DCA-bedragen correct geclipped naar MIN_ORDER_EUR?
- Kan DCA per ongeluk gefired worden als een trade al gesloten is?

---

### 4. SIGNAL PROVIDERS & SCORING SYSTEEM
*Focus: modules/signals/, bot/signals.py, MIN_SCORE_TO_BUY*

Specifieke vragen:
- Zijn alle signal providers onafhankelijk en hebben ze geen gedeelde mutable state?
- Is de score-normalisatie correct? Kunnen scores de range [0, 10] overschrijden?
- Zijn de candle requirements (minimale lengte) consistent across providers?
- Worden SignalContext-waarden (closes_1m, highs_1m etc.) correct gesynchroniseerd?
- Is het plugin-registratiesysteem in `__init__.py` correct en thread-safe?

---

### 5. ML / AI PIPELINE
*Focus: modules/ml.py, ai/xgb_auto_train.py, XGBoost + LSTM + RL ensemble*

Specifieke vragen:
- Wat is de feature-set die het XGboost-model gebruikt? Matcht dit met wat live wordt gecomputed?
- Is er feature-drift bescherming (training vs live feature mismatch)?
- Wordt het model thread-safe geladen en gecached?
- Zijn de ensemble-gewichten (xgb: 1.0, lstm: 0.9, rl: 0.7) statistisch onderbouwd?
- Is de RL-agent correct gereset/getraind bij herstart?
- Kan `predict_ensemble` None returnen en wordt dat correct afgehandeld?
- Hoe robuust is de auto-retrain cycle? Kan het concurrent draaien met live trading?

---

### 6. REGIME ENGINE
*Focus: core/regime_engine.py, 4 regimes, regime-based parameter aanpassing*

Specifieke vragen:
- Zijn de regime-criteria (TRENDING_UP, RANGING, HIGH_VOLATILITY, BEARISH) correct gedefinieerd op basis van echte marktindicatoren?
- Hoe snel reageert het regime op marktverandering? Is er hysteresis/debounce?
- Worden regime-aanpassingen (_REGIME_ADJ) correct toegepast op MAX_OPEN_TRADES, trailing, DCA?
- Is de `confidence: 0.674` waarde in de config een snapshot of wordt dit live herberekend?
- Zijn er gevallen waarbij het regime en de live markt out-of-sync kunnen zijn?

---

### 7. KELLY SIZING & POSITIEBEPALING
*Focus: core/kelly_sizing.py, POSITION_KELLY_FACTOR, volatility parity*

Specifieke vragen:
- Is de Kelly-formule correct geïmplementeerd (half-Kelly = echte Kelly × 0.5)?
- Hoe wordt de win-rate en edge berekend? Op basis van welke data window?
- Is volatility parity correct: `w_i = (1/σ_i) / Σ(1/σ_j)`?
- Kunnen Kelly-berekeningen resulteren in posities < MIN_ORDER_EUR of > MAX_ENTRY_EUR?
- Is BASE_AMOUNT_EUR × POSITION_KELLY_FACTOR × regime_mult correct gecombineerd?

---

### 8. RISK MANAGEMENT
*Focus: modules/trading_risk.py, circuit breaker, max daily loss, drawdown*

Specifieke vragen:
- Worden RISK_MAX_DAILY_LOSS en RISK_MAX_WEEKLY_LOSS correct bijgehouden over bot-restarts?
- Is de circuit breaker (CIRCUIT_BREAKER_MIN_WIN_RATE) correct: telt het alle trades of alleen recente?
- Hoe werkt RISK_MAX_DRAWDOWN_PCT? Relatief aan welk baseline?
- Worden risicolimieten gecontroleerd VÓÓR een buy-order of alleen daarna?
- Is het FLOODGUARD-systeem correct geïntegreerd met de hoofdloop?

---

### 9. API LAYER & RATE LIMITING
*Focus: bot/api.py, safe_call, circuit breaker, response caching*

Specifieke vragen:
- Is de exponentiële backoff correct geïmplementeerd (base delay × 2^retry)?
- Zijn de circuit breaker drempels per endpoint correct geïsoleerd?
- Is de response cache thread-safe (TTL expiry onder concurrente calls)?
- Worden alle API-responses die `None` returnen correct afgehandeld door alle callers?
- Is de 10-seconden timeout implementation Windows-compatible (thread-based, geen `signal.alarm`)?
- Kan de rate limiter starvation veroorzaken bij burst-requests?

---

### 10. CONFIG SYSTEEM & SCHEMA VALIDATIE
*Focus: modules/config.py, modules/config_schema.py, 3-laags merge*

Specifieke vragen:
- Is de merge-volgorde correct: `bot_config.json` → `overrides.json` → `local_config.json` (elk wint van vorige)?
- Worden runtime-state-keys (die beginnen met `_`) correct gefilterd bij save?
- Is schema-validatie volledig? Zijn alle kritieke keys (TRAILING_ACTIVATION_PCT, DCA_DROP_PCT etc.) gevalideerd?
- Is hot-reload (CONFIG_HOT_RELOAD_SECONDS) thread-safe? Kan een reload een lopende trade-check corruppen?
- Zijn er config-keys die in de schema ontbreken maar wel in bot_config.json aanwezig zijn?

---

### 11. DATA PERSISTENTIE & TRADE STORE
*Focus: modules/trade_store.py, modules/trade_archive.py, atomaire writes*

Specifieke vragen:
- Is het `tmp + os.replace()` patroon consistent in alle schrijf-operaties?
- Wat gebeurt er als de bot crasht tijdens een `os.replace()`? Is data consistent?
- Worden trade_log.json en trade_archive.json correct gesynchroniseerd?
- Is de debounce-mechanisme (min 2s) voor save_trades correct geïmplementeerd?
- Worden JSONL-bestanden correct geschreven (een JSON object per regel, UTF-8)?
- Is er bescherming tegen bestand-corruptie bij simultane writes vanuit meerdere threads?

---

### 12. THREADING & CONCURRENCY
*Focus: threading model, state.trades_lock (RLock), debouncing*

Specifieke vragen:
- Zijn alle `state.open_trades` accessen correct beveiligd met `state.trades_lock`?
- Kunnen deadlocks optreden als `trades_lock` genest wordt verkregen?
- Is de main bot-loop re-entrant-safe? Wat als een loop-iteratie langer duurt dan SLEEP_SECONDS?
- Worden WebSocket callbacks correct geïsoleerd van de main thread?
- Zijn er mutable shared objects (lijsten, dicts) toegankelijk zonder lock?

---

### 13. TEST SUITE & KWALITEIT
*Focus: tests/ directory, dekking, kwaliteit van test cases*

Specifieke vragen:
- Wat is de **geschatte test coverage** over de kritieke code paden?
- Zijn er kritieke paden (trade close, DCA trigger, trailing stop) zonder tests?
- Testen de tests echte logica of zijn ze te triviaal (alleen happy-path)?
- Worden threading/concurrency scenarios getest?
- Zijn mock-objecten correct geconfigureerd (geen echte API calls)?
- Zijn er flaky tests of tests met impliciete volgorde-afhankelijkheden?

---

### 14. SECURITY
*Focus: OWASP-relevante issues, API keys, input validatie, Telegram*

Specifieke vragen:
- Staat de Telegram Bot Token in plaintext in bot_config.json? (Kritiek!)
- Worden API keys correct uit environment variables geladen en nooit naar disk geschreven?
- Is de Flask dashboard authenticatie correct geïmplementeerd?
- Worden externe API-responses gesanitized voor gebruik in berekeningen?
- Zijn er injection-risico's in log-strings die vanuit externe bronnen komen?
- Kunnen de event_hooks vanuit onvertrouwde input getriggerd worden?

---

### 15. TRADING PERFORMANCE & WINSTOPTIMALISATIE
*Focus: Enter/exit timing, fee impact, slippage, signal kwaliteit*

Specifieke vragen:
- Is FEE_TAKER (0.0025) correct verwerkt in alle profit-berekeningen?
- Wordt slippage (SLIPPAGE_PCT: 0.001) correct meegenomen in entry/exit-prijsberekeningen?
- Is de TRAILING_ACTIVATION_PCT (0.015 = 1.5%) optimaal voor de huidige whitelist-markten?
- Zijn de STEPPED_TRAILING_LEVELS zo geconfigureerd dat ze winst maximaliseren in trending markten?
- Is MIN_SCORE_TO_BUY (7.0) een effectieve filter? Hoe correleert de score met werkelijke winstgevendheid?
- Wordt de cost-buffer (DCA_SL_BUFFER_PCT: 0.04) correct toegepast zodat DCA-trades niet te vroeg gesloten worden?

---

## EINDRAPPORT EISEN

Na alle 15 componenten, geef:

### OVERALL SCORE DASHBOARD
```
Component                          Score  Status
─────────────────────────────────────────────────
1. Architectuur & Refactoring       X/10  [🔴/🟡/🟢]
2. Trailing Stop & Partial TP       X/10
3. DCA Logica                       X/10
4. Signal Providers & Scoring       X/10
5. ML / AI Pipeline                 X/10
6. Regime Engine                    X/10
7. Kelly Sizing & Positiebepaling   X/10
8. Risk Management                  X/10
9. API Layer & Rate Limiting        X/10
10. Config Systeem                  X/10
11. Data Persistentie               X/10
12. Threading & Concurrency         X/10
13. Test Suite                      X/10
14. Security                        X/10
15. Trading Performance             X/10
─────────────────────────────────────────────────
TOTAAL GEMIDDELDE                   X/10
```

### TOP 5 MEEST KRITIEKE FIXES (volgorde: geldimpact)
Voor elk: exact bestand + regelnummer + kant-en-klaar code-fix die Sonnet kan uitvoeren.

### TOP 5 QUICK WINS (< 1 uur implementatie, hoge impact)
Voor elk: exact bestand + regelnummer + kant-en-klaar code-fix.

### REFACTORING ROADMAP (prioriteit volgorde)
Welke delen van trailing_bot.py moeten als volgende worden geëxtraheerd, en naar welk module?

### AANBEVOLEN TEST CASES (die nu ontbreken maar kritiek zijn)
Geef voor elk minstens de test-functie naam + wat het test + een pseudo-code implementatie.

---

## ANALYSE-RICHTLIJNEN

1. Lees elk bestand volledig. Sla niets over.
2. Cross-refereer tussen bestanden. Een bug in `bot/api.py` die pas manifest wordt via `trailing_bot.py` is een échte bug.
3. Test de logica mentaal met edge-cases: Wat als `candles` leeg is? Wat als `balance` None is? Wat als de bot herstart tijdens een open DCA?
4. Wees meedogenloos maar constructief. Dit bot draait met echt geld.
5. Geef ALLEEN concrete, implementeerbare fixes. Geen vage adviezen zoals "verbeter de code kwaliteit".
6. Elk code-snippet dat je geeft moet direct door Sonnet gebruikt kunnen worden als `newString` in een `replace_string_in_file` call.
7. Als je een patroon ziet dat goed is, benoem dat kort (1 zin). Focus op problemen.
8. Let specifiek op financiële edge cases: negatieve balances, NaN-waarden in berekeningen, integer overflow bij hoge token-prijzen.

---

## SPECIALE AANDACHTSPUNTEN

Op basis van de codebase-structuur zijn dit bekende risicogebieden die extra aandacht verdienen:

- **`_SALDO_COOLDOWN_UNTIL` in bot_config.json**: Dit is een runtime-state key die in de json staat. Dit mag niet. Hoe is dit er ingeslopen?
- **`_REGIME_ADJ` en `_REGIME_RESULT` in bot_config.json**: Zijn dit ook runtime-state keys die niet opgeslagen mogen worden?
- **`CONFIG_MANUAL_EDIT_TS: 1770940000`**: Dit timestamp is uit de toekomst (2026). Wat is de impact hiervan?
- **`DCA_MAX_BUYS: 9` vs `DCA_MAX_ORDERS: 9`**: Zijn dit duplicaten? Welke wordt daadwerkelijk gebruikt?
- **`TAKE_PROFIT_TARGETS` array én `TAKE_PROFIT_TARGET_1/2/3/4/5` keys**: Zijn dit duplicaten? Worden ze gesynchroniseerd?
- **`STOP_LOSS_ENABLED: false` EN `ENABLE_STOP_LOSS: false`**: Twee keys voor hetzelfde? Welke wint?
- **`MAX_OPEN_TRADES: 3` in de config maar regime past `max_trades_mult: 0.7` toe**: Resulteert dit in 2.1 trades (naar beneden afgerond naar 2)? Is dit de bedoeling?
- **Telegram Bot Token in plaintext**: `"TELEGRAM_BOT_TOKEN": "[REDACTED]"` — dit is een beveiligingsrisico.

---

*Einde van de analyse-prompt. Begin nu met lezen van trailing_bot.py en werk systematisch door alle bestanden heen.*
