# Fix Log — Bitvavo Trading Bot

> **IMPORTANT**: Every Copilot session MUST read this file before making any fix.
> Check if the issue has been addressed here before. After fixing a bug, log it below.

---

## #050 — Telegram-spam "heartbeat stale or missing" terwijl bot gewoon draait (2026-04-26)

### Symptom
Gebruiker krijgt herhaaldelijk Telegram-meldingen:
> `ALERT: heartbeat stale or missing (last_ts=...). Bot may be down.`

Terwijl `data/heartbeat.json` vers is (age ~30-60s), bot draait, trades gaan door. Echte false-positives.

### Root cause
`modules/trading_monitoring.py::start_heartbeat_monitor`:
1. Eén transient OS-error tijdens `os.replace()` (Windows/OneDrive race) → `OSError` werd niet opgevangen → `ts=None` → alert pad.
2. Geen retry, geen "consecutive confirmation" — eerste hiccup alert direct.
3. Lege/half-geschreven JSON gaf `JSONDecodeError` (wel gevangen) maar `ts` bleef None → ook alert pad bij volgende loop.

### Fix
1. `_alerts_enabled()`: nieuwe config flag `HEARTBEAT_STALE_ALERT_ENABLED` (default `True`), per loop hot-reloadbaar.
2. **Retry-loop** binnen monitor: 3x read met 100/200/300ms backoff voor transient OSError/JSONDecodeError.
3. **Consecutive confirmation**: alert pas na 3 opeenvolgende stale checks (~3 minuten bij interval=60s) — niet bij 1 hiccup.
4. Read als `utf-8-sig` (verdraagt BOM), accept `ts` of `timestamp` veld.
5. In `bot_config_local.json`: `HEARTBEAT_STALE_ALERT_ENABLED = false` om de Telegram-melding helemaal uit te zetten.

### Lesson
Atomic `os.replace()` op Windows + OneDrive geeft soms transient OS-errors zelfs als de write succesvol is. Lezers moeten ALTIJD retry + last-known-good fallback hebben, NIET één read = waarheid. Dit was hetzelfde patroon als FIX #048 maar dan in de monitor i.p.v. dashboard.

---

## #049 — Trade-card toonde verkeerde "Geïnvesteerd" + inconsistente P/L na partial sell (2026-04-25)

### Symptom
LTC trade-card op dashboard toont:
- Geïnvesteerd: €320,03 (de originele aankoop)
- Huidige waarde: €145,44
- P/L: €-174,59 / +1,67%

→ getallen kloppen niet bij elkaar (€-174 met +1,67%?). Gebruiker dacht dat de bot de partial sell had gemist.

### Root cause
Bot detecteerde de partial sell wel correct: `invested_eur` stond op €143,06 (current cost basis), `initial_invested_eur` op €320,03 (immutable origineel). Maar:
- **Backend** (`tools/dashboard_v2/backend/main.py:322`): `invested = initial_invested_eur or invested_eur` → gebruikte de €320 voor `unrealised_pnl_eur`-berekening, terwijl `unrealised_pnl_pct` los uit `cur/buy_price` kwam → tegenstrijdige getallen.
- **Frontend** (`index.html:192`): toonde `initial_invested_eur` als "Geïnvesteerd" zonder uitleg over de partial sell.

### Fix
1. Backend: `invested = invested_eur or initial_invested_eur` (huidige cost basis wint). Nieuwe velden: `invested_eur_current`, `partially_sold`, `total_pnl_eur` (incl. al-teruggehaalde EUR).
2. Frontend: toont `invested_eur_current`, badge "deels verkocht" + sub-regel met origineel + teruggekomen EUR.

### Lesson
Cost basis voor live P/L = `invested_eur` (mutable, current). `initial_invested_eur` is alleen voor context/historie. Twee getallen op dezelfde card moeten ALTIJD dezelfde basis gebruiken anders krijg je inconsistente outputs (€-174 vs +1.67%).

---

## #048 — Dashboard V2 toonde lege pagina (heartbeat null) door stale uvicorn-proces (2026-04-25)

### Symptom
Dashboard pagina laadt wel, maar alle KPI/portfolio velden zijn leeg / `--`. `GET /api/health` geeft `bot_online:false, heartbeat_age_s:null` terwijl `data/heartbeat.json` wel vers is (bot draait gewoon).

### Root cause
1. **Race condition**: bot schrijft heartbeat via atomic `os.replace()`. Op Windows kan tussen unlink en rename de file kortstondig "in use" zijn → `_read_json` vangt exception → returnt `{}` → `bot_online:false`.
2. **Geen fallback**: 1 mislukte read → `{}` werd gewoon doorgegeven aan UI. Gecombineerd met TTL-cache van 2s voelt het alsof het "vast zit", maar elke read ging fout.
3. **Geen watchdog**: niets controleerde of dashboard nog gezond was vs. werkelijke heartbeat-versheid.

### Fix
1. `_read_json` in `tools/dashboard_v2/backend/main.py`: 3x retry met 50/100/150 ms backoff + **last-known-good fallback** per pad. Bij transiënte fouten serveert hij vorige succesvolle waarde i.p.v. `{}`.
2. Nieuw script `scripts/dashboard_v2_watchdog.py`: pingt elke 30s `GET /api/health`, en als 3 checks (≈90s) achter elkaar onhealthy zijn TERWIJL `heartbeat.json` wel vers is → kill+restart uvicorn op `0.0.0.0:5002`. Cooldown 5 min tegen restart-loops.
3. Watchdog toegevoegd aan `scripts/startup/start_bot.py` als ManagedProcess met auto_restart=True.

### Lesson
Op Windows is atomic JSON-replace nooit 100% race-vrij door file locks. Lezers MOETEN retryen + last-known-good fallback hebben, anders krijgen UI's lege schermen bij transiënte fouten. **Nooit `except: return {}`** zonder fallback bij hoog-frequente bestanden.

---

## #047 — SCAN_WATCHDOG_SECONDS te laag → maar 1-2 markten gescand per cycle (2026-04-25)

### Symptom
Dashboard signal-status toont continu `1/20 markets gescand`, geen entries hoewel 2 slots vrij + EUR cash = €373.93. Log:
```
[SCAN WATCHDOG] Aborting scan after 2 markets / 20 (elapsed 60.5s)
[SCAN SUMMARY] 20 markets, 2 evaluated ... 0.03 markets/s
```

### Root cause
`SCAN_WATCHDOG_SECONDS` default = **60s** (`trailing_bot.py:1088`), maar elke market kost 25-30s door LSTM + ensemble inference (XGB+LSTM+RL). Na 2 markten breekt watchdog af → 18 markten worden nooit geëvalueerd → bot mist alle entries behalve random eerste 2.

### Fix
Bumped `SCAN_WATCHDOG_SECONDS = 300` (5 min) in `%LOCALAPPDATA%\BotConfig\bot_config_local.json`. Hot-reloaded zonder restart. Bij volgende cycle worden alle 20 markten geëvalueerd (~9 min worst case, ruim binnen 5-min budget op gemiddelde snelheid).

### Lesson
Scan-tijd schaalt lineair met aantal markten × inference-tijd per markt. LSTM + ensemble ≈ 25s per markt → minimum watchdog = `markets × 30s` met buffer. Bij future model-uitbreidingen: meet nieuwe per-markt tijd en pas watchdog aan.

---

## #046 — Telegram /set met dot-key faalde stil + Portfolio toonde slechts 5 closed trades (i.p.v. 800+) + Roadmap stortingsscenario's miste compounding-uitleg en hogere stappen + Stortingsplan-component overbodig (2026-04-23)

### Symptom / Aanleiding
Gebruiker meldde:
1. "Als ik parameters aanpas in telegram, dan doet die dat niet naar local config" → `/set BUDGET_RESERVATION.trailing_pct 80` had geen effect.
2. "Bij portfolio zie ik nog maar 5 trades staan, terwijl ik 100 heb aangevinkt. het lijkt wel of al die trades weg zijn" → trade_log had 7 closed; archive had 861 maar werd niet gemerged.
3. Vraag of de Mijlpaal-ETA tabel winst-herinvestering meeneemt + verzoek om dynamische stappen 500/1000.
4. Verzoek om Stortingsplan-tabel te verwijderen.

### Root cause
1. `_apply_set_command()` in `modules/telegram_handler.py` deed `key.upper()` op de **hele** key incl. dot. `BUDGET_RESERVATION.trailing_pct` werd `BUDGET_RESERVATION.TRAILING_PCT` (child geupperd) → niet in `ALLOWED_KEYS` → user kreeg "Onbekende parameter". Bot config gebruikt **lowercase** children dus de uppercase write zou bovendien een nieuwe key naast de bestaande hebben gezet.
2. Het portfolio-template wordt geserveerd door **`tools/dashboard_flask/blueprints/main/routes.py`** (Flask blueprint), NIET door `app.py::portfolio`. De blueprint las alleen `trades.get('closed', [])` (≈5 trades) en raakte de archive nooit. Bovendien gebruikt `data/trade_archive.json` de top-level key `'trades'` (NIET `'closed'`) — 861 trades waren onzichtbaar.
3. Bestaande tekst zei alleen "compounding" zonder duidelijk te maken dat dat trading-winst herbelegt; deposits stonden vast op 0/100/200/300; geen stappen voor €500/€1000.
4. `deposit_plan` was hardcoded V2-fasering die niet meer matchte met huidige roadmap.

### Fix
- **MOD** `modules/telegram_handler.py::_apply_set_command`: dot-keys worden nu opgesplitst — parent UPPERCASE, child case-preserve. Lookup in `ALLOWED_KEYS` is case-insensitive zodat `/set budget_reservation.trailing_pct 80` of `/set BUDGET_RESERVATION.TRAILING_PCT 80` beide werken. Reply toont nu expliciet het opgeslagen pad: `%LOCALAPPDATA%/BotConfig/bot_config_local.json`.
- **MOD** `modules/telegram_handler.py::_save_local_override`: dot-keys worden geschreven met UPPERCASE parent + originele-case child (matched bot config schema). Single-level keys nog steeds `key.upper()`.
- **MOD** `tools/dashboard_flask/blueprints/main/routes.py::portfolio`: merget nu `data/trade_archive.json` (zowel `trades` als `closed` keys) in `closed_trades_raw`, dedupliceert op `(market, timestamp, sell_price)`, en logt `[PORTFOLIO] Closed trades after archive merge: N` voor diagnose. Resultaat: 837 trades beschikbaar i.p.v. 5 → met `?trades_count=100` toont nu 97 (3 partial-TP filtered).
- **MOD** `tools/dashboard_flask/app.py::portfolio` (monolith fallback): zelfde merge toegevoegd voor consistentie.
- **MOD** `tools/dashboard_flask/app.py::roadmap`: `SCENARIO_DEPOSITS = [0, 100, 200, 300, 500, 1000]` en `SCENARIO_TARGETS = [2000, 5000, 10000, 25000, 50000]` — tabel is nu 6×5 i.p.v. 4×3. `deposit_scenarios[].etas` lijst-vorm voor template-loop. Stortingsplan-blok verwijderd. Comment toegevoegd dat groei% × kapitaal = winst-herinvestering.
- **MOD** `tools/dashboard_flask/templates/roadmap.html`: drie-kolom layout vervangen door 2-kolom (Stortingsplan-paneel weg). Deposit-toggle uitgebreid met €500/€1000. Scenario-tabel rendert nu via `{% for t in scenario_targets %}` + `{% for eta in s.etas %}`. Onderschrift expliciet: "✅ Trading-winst wordt automatisch herbelegd in de simulatie".

### Verification
- `/set BUDGET_RESERVATION.trailing_pct 80` → schreef `BUDGET_RESERVATION.trailing_pct = 80.0` naar local override; readback bevestigd; daarna teruggezet naar 100.
- `/set GRID_TRADING.enabled true` → schreef correct in geneste dict.
- `/portfolio?trades_count=100` → log: `Closed trades after archive merge: 837`, `Closed trades count: 97`. Response 241kB (was ~177kB).
- `/roadmap?deposit=500` → 200, deposit-toggle bevat €500 en €1000, scenario-tabel toont kolommen €25.000 en €50.000, onderschrift bevat "automatisch herbelegd".
- Stortingsplan-paneel niet meer in HTML (alleen orphan CSS in `.deposit-table` die ongebruikt is).
- 16 python-procs draaien na 2× herstart.

### Lesson (CRITICAL)
- **Dashboard heeft TWEE portfolio-routes** (monolith `app.py::portfolio` én `blueprints/main/routes.py::portfolio`) — bij wijzigingen aan portfolio-data ALTIJD beide controleren. De blueprint wint omdat hij eerst geregistreerd wordt in Flask app-init.
- **`data/trade_archive.json` gebruikt key `'trades'`, niet `'closed'`** — alle dashboard-aggregaties die archive merging doen moeten beide keys lezen (`get('trades', []) + get('closed', [])`).
- **Telegram dot-keys: parent UPPERCASE, child case-preserve.** `key.upper()` op de hele key breekt de lookup omdat bot config schema lowercase children gebruikt (`enabled`, `trailing_pct`, etc.).

---

## #045 — Dashboard Parameters tab schreef wijzigingen naar OneDrive base config + RSI Max DCA validatie blokkeerde 100 + Roadmap miste deposit-scenario's en multi-level passief inkomen (2026-04-23)

### Symptom / Aanleiding
Gebruiker meldde dat:
1. "Als ik wat aanpas of het ook echt veranderd" → **wijzigingen werden NIET persistent**: `/api/strategy/save` schreef naar `config/bot_config.json` (OneDrive!) → werd elke sync gereverteerd.
2. RSI Max DCA veld toonde HTML5 popup "minimaal 70" terwijl waarde 100 → input had `min="30" max="70"`, browser zei "Value must be ≤ 70" → user las dat als minimum.
3. Roadmap-tab toonde alleen "Opbrengst bij €6.000", geen scenarios voor andere kapitaalniveaus, geen ETA per stortingsbedrag.
4. Algemene "rommelige" layout van Parameters-tab — vrijwel geen CSS voor `.param-field`/`.params-grid`/`.input-row`/`.ai-switch`.
5. Vraag: "doet auto_retrain zelf de retrain? blijft timer staan na restart?"

### Root cause
1. `tools/dashboard_flask/app.py::save_strategy_parameters()` deed `write_json_compat(str(config_path), config)` waar `config_path = PROJECT_ROOT/config/bot_config.json` — strijdig met de project-regel "ALL config changes MUST go to `%LOCALAPPDATA%/BotConfig/bot_config_local.json`".
2. Templates `parameters.html` had hardcoded `min/max` op RSI-velden (`30-40`, `60-90`, `30-70`) terwijl RSI gewoon 0-100 is.
3. Roadmap had één hardcoded `earnings_at_5k` dict en één globale ETA met vaste deposit_per_week.
4. CSS-classes (`.params-grid`, `.param-field`, `.ctrl-btn`, `.ai-switch`, `.params-save-bar`) waren nergens gedefinieerd in `dashboard.css` → browser fallback layout.
5. Auto_retrain DOES self-run (`auto_retrain.py --loop` via `start_automated.ps1`) en IS restart-safe (`trained_at` opgeslagen in `ai/ai_model_metrics.json`, `compute_due_time` rekent vanaf laatste training). Geen bug, alleen onduidelijkheid.

### Fix
- **MOD** `tools/dashboard_flask/app.py::save_strategy_parameters`: schrijft nu **alleen** geraakte keys naar `LOCAL_OVERRIDE_PATH` (`%LOCALAPPDATA%/BotConfig/bot_config_local.json`), gemerged met bestaande lokale overrides. Atomic write (`.tmp` + `os.replace`). Response geeft `saved_to` + `saved_keys` terug.
- **MOD** `templates/parameters.html`: RSI-velden naar `min="0" max="100"` met tooltips. Sticky save bar met live-status ("Onopgeslagen wijzigingen" / "Opgeslagen naar local override"). Param-fields markeren met `.dirty` class bij wijziging.
- **MOD** `templates/roadmap.html` + `app.py::roadmap`:
  - `?deposit=0|100|200|300` selector → herberekent ETA's met compounding model `simv = simv*(1+groei) + deposit/week` per week tot doel.
  - Nieuwe **Passief Inkomen tabel** voor 9 kapitaalniveaus (€1.5k → €50k) met /dag, /maand, /jaar op basis van werkelijke recente daily yield% uit performance-stats.
  - Nieuwe **Stortingsscenario tabel**: ETA naar €2k/€5k/€10k voor 4 deposit-niveaus naast elkaar.
  - Nieuwe **Auto-Retrain Status panel**: leest `ai/ai_model_metrics.json` → toont last/next + uitleg dat timer restart-safe is.
  - Nieuwe **Geavanceerde Roadmap-ideeën** sectie: 12 advanced ideas (multi-strategy A/B, sentiment overlay, per-coin Kelly, time-of-day filter, auto-withdraw, hedge perpetuals, staking, multi-exchange arbitrage, capital plan optimizer, push-notif, backtest button).
- **MOD** `static/css/dashboard.css`: 200 regels nieuwe styling voor params-form (clean grid, hover, dirty marker, AI toggle switch, sticky save bar, slide-in toast).

### Files
- MOD: `tools/dashboard_flask/app.py` (save endpoint + roadmap route met scenarios/passive income/future ideas/autoretrain)
- MOD: `tools/dashboard_flask/templates/parameters.html` (RSI bounds + sticky save bar + dirty markers + saved-to feedback)
- MOD: `tools/dashboard_flask/templates/roadmap.html` (4 nieuwe panels + CSS)
- MOD: `tools/dashboard_flask/static/css/dashboard.css` (~200 regels params-form V2 styling)

### Validatie
- `Invoke-WebRequest /roadmap?deposit=200` → 200 OK, alle 4 nieuwe sections aanwezig (Passief Inkomen, Stortingsscenario, Auto-Retrain, Geavanceerde Roadmap-ideeën).
- `Invoke-WebRequest /parameters` → 200 OK, sticky save bar + local override hint + RSI 0-100 aanwezig.
- POST `/api/strategy/save` met `{"max_open_trades":4}` → response `saved_to: %LOCALAPPDATA%/BotConfig/bot_config_local.json`, `saved_keys: [MAX_OPEN_TRADES]`. Verified met PowerShell read-back: `MAX_OPEN_TRADES = 4` in local override file.
- Bot restart: 16 procs running.

### Lesson Learned
**Dashboard write-paths moeten ALTIJD naar LOCAL_OVERRIDE_PATH gaan.** Elke `/api/.../save` route die `config/bot_config.json` direct schrijft is een bug waiting to happen — OneDrive reverteert. Check ook andere endpoints (whitelist/blacklist/reset/etc.) — die staan nog steeds op `bot_config.json` en moeten apart geaudit worden bij volgende sessie.

---

## #044 — Regular XGB nooit (her)getraind: trade_features.csv ontbrak + bb_position/stochastic_k werden niet gelogd (2026-04-23)

### Symptom / Aanleiding
Het regular 7-feature XGB model (`ai/ai_xgb_model.json`) dat de bot **live** laadt in `modules.ml._get_xgb_model` werd nooit (her)getraind:
1. `tools/auto_retrain.py` verwacht `trade_features.csv` in project-root → bestand bestond niet → `_training_data_ready()` skipte training elke cyclus.
2. Naïef bouwen vanuit archief gaf 837 rijen, maar 785 hadden default `rsi=50` / `sma=0` (entry-snapshot werd vroeger niet gelogd) → bruikbaar = 52, label-balans 47/5 → onbruikbaar voor training.
3. `bb_position` en `stochastic_k` werden bij entry **nergens** opgeslagen, ondanks dat `bot/signals.py` ze in `ml_info` plaatst.

### Root Cause
1. Geen pipeline-stap die `trade_features.csv` genereert uit het archief.
2. `trailing_bot.py` entry-meta block sloeg wel `rsi/macd/sma_short/sma_long/bb_upper/bb_lower/...` op maar niet `bb_position` en `stochastic_k`.
3. Voor historische trades was er geen backfill-mechanisme om de snapshot uit Bitvavo candles te reconstrueren.

### Fix
- **NEW** `scripts/build_trade_features.py`: bouwt `trade_features.csv` (rsi, macd, sma_short, sma_long, volume, bb_position, stochastic_k, label) uit `trade_log.json` + `trade_archive.json`. Filtert default-only rows en mergt optionele backfill-cache.
- **NEW** `scripts/backfill_trade_features.py`: voor trades zonder echte snapshot fetcht 1m candles (3h venster) rond `opened_ts` via Bitvavo API en herberekent alle 7 features. Resultaat naar `data/trade_features_backfill.json` (resumable cache). Eerste run: **588/757 succes** → 652 bruikbare rijen voor training.
- **MOD** `trailing_bot.py`: entry-meta block slaat nu ook `bb_position_at_entry` en `stochastic_k_at_entry` op uit `ml_info`. Vanaf nu zijn alle 7 features per nieuwe trade direct uit `trade_archive.json` afleidbaar.
- **MOD** `tools/auto_retrain.py`: roept eerst `backfill_trade_features.py` (incrementeel via cache), dan `build_trade_features.py`, dan pas `_training_data_ready()` + `xgb_walk_forward.py`. Volledig automatische pipeline.

### Files
- NEW: `scripts/build_trade_features.py`
- NEW: `scripts/backfill_trade_features.py`
- MOD: `trailing_bot.py` (entry-meta save: `bb_position_at_entry`, `stochastic_k_at_entry`)
- MOD: `tools/auto_retrain.py` (BACKFILL_SCRIPT/BUILD_FEATURES_SCRIPT chained vóór train)
- NEW data: `data/trade_features_backfill.json` (757 entries cache), `trade_features.csv` (652 rows)

### Validation
- `python ai/xgb_walk_forward.py --window 400 --step 100` → "Samples: 652, Features: 7, Folds: 2, Avg Accuracy: 55.00%, Avg Precision: 62.98%, Buy rate: 61.04%". Feature importance evenwichtig verdeeld (rsi 0.15, sma_short 0.19, volume 0.19, bb_position 0.10, stochastic_k 0.09).
- Model verified: `xgb.XGBClassifier().load_model('ai/ai_xgb_model.json').n_features_in_ == 7` ✓

### Notes
- Bitvavo's historische candle endpoint geeft beperkte data terug voor pairs > paar maanden oud (~25-35 candles ipv 60) → 169 oudere trades konden niet backfilled worden ("insufficient_candles"). Acceptabel: 588 echte + 64 originele snapshots = 652 trainset.
- `data/trade_features_backfill.json` is incrementeel: volgende runs van de backfill skippen reeds-cached entries, dus `auto_retrain` mag deze veilig elke cyclus draaien.

---

## #043 — Slechts 7 closed trades zichtbaar voor enhanced trainer + grid-exclusion blokkeert BTC/ETH terwijl GRID_TRADING uit staat (2026-04-23)

### Symptom / Aanleiding
1. `xgb_train_enhanced.py` rapporteerde "Loaded 7 closed trades" terwijl er **861** trades in `data/trade_archive.json` staan → MIN_SAMPLES (100) nooit gehaald → enhanced trainer kon nooit draaien.
2. Bot-log toonde herhaald `[GRID] Excluding grid markets from trailing management: ['BTC-EUR']` en `Excluding grid trading markets from trailing bot: ['BTC-EUR']` — terwijl `GRID_TRADING.enabled=False` in config en `[Grid] DISABLED in config` óók al gelogd werd. BTC-EUR (en bij implicatie ETH-EUR uit andere whitelist-checks) bleven uitgesloten van trailing terwijl ze in de whitelist staan.

### Root Cause
1. `ai/xgb_train_enhanced.py.load_closed_trades()` las alléén `data/trade_log.json`. De lifecycle manager archiveert oudere trades naar `data/trade_archive.json` (861 entries), waardoor `trade_log.json` slechts ~7 recente closed trades bevat. Het archief werd genegeerd.
2. `trailing_bot.get_active_grid_markets()` riep onvoorwaardelijk `get_grid_manager().get_all_grids_summary()` aan. Die returnt actieve grids op basis van **on-disk `data/grid_states.json`** — een stale BTC-EUR grid uit een eerdere sessie bleef staan. Geen check op `CONFIG['GRID_TRADING']['enabled']` → wanneer grid module is uitgezet via config, blijft de stale state alsnog markets uitsluiten.

### Fix
- `ai/xgb_train_enhanced.py`:
  - `load_closed_trades()` leest nu zowel `data/trade_log.json` als `data/trade_archive.json` en deduplicate op `(market, opened_ts/timestamp, sell_order_id)`. Resultaat: **837 unique closed trades** (was 7) → MIN_SAMPLES ruim gehaald, positive ratio 57.95%.
  - `extract_features_from_trades()` accepteert nu zowel nieuwe (`*_at_entry`) als legacy (`*_at_buy`) field names voor RSI/MACD/volatility.
  - Feature-cols uitgebreid met `macd_at_buy` en `volatility_at_buy`.
- `trailing_bot.get_active_grid_markets()`: early return `set()` als `CONFIG['GRID_TRADING'].get('enabled', False)` False is. Stale `grid_states.json` kan zo nooit meer markets uitsluiten van trailing.

### Files
- MOD: `ai/xgb_train_enhanced.py` (load_closed_trades, extract_features_from_trades, prepare_training_data)
- MOD: `trailing_bot.py` (`get_active_grid_markets`)

### Validation
- Standalone: `load_closed_trades()` → "Loaded 7 closed trades from trade_log.json / Loaded 861 archived trades / Total unique 837 / Extracted 837 feature records / Positive ratio 57.95%".
- Bot herstart na fix: nieuwe scan toont **"Nieuwe scan gestart: 20 markten (totaal 20)"** (was 19) — BTC-EUR is nu opgenomen. Geen `Excluding grid` log lines meer na restart.
- 16 procs running, heartbeat fresh.

### Notes
- Andere modules met `xxx_archive.json` skip-patroon (sync, performance) controleren of ze óók archief negeren — toekomstige refactor.
- Stale `data/grid_states.json` blijft op disk staan; harmless nu de guard er is, maar ooit handmatig opruimen als grid trading definitief af.

---

## #042 — auto_retrain overwrote 7-feature XGB met 5-feature enhanced + LSTM script ontbrak + TF niet geïnstalleerd (2026-04-23)

### Symptom / Aanleiding
Bot logde herhaaldelijk:
```
[Ensemble] ... XGB=0, LSTM=None(0.33), RL=None(0.00) → HOLD (conf=1.00)
LSTM predictor laden mislukt: TensorFlow is vereist voor LSTM predictor
```
en eerder, bij retrain runs: `Feature shape mismatch, expected: 7, got: 5`. Resultaat: ensemble degradeerde naar XGB-only (of zelfs alleen score-based) en `auto_retrain.py --loop` riep een script aan dat niet bestond (`scripts/train_lstm_model.py`).

### Root Cause
1. `tools/auto_retrain.py` had `TRAIN_SCRIPT = ai/xgb_train_enhanced.py` — die schrijft een 5-feature model naar `ai/ai_xgb_model.json`, terwijl `modules/ml.py` een 7-feature model verwacht (rsi, macd, sma_short, sma_long, volume, bb_position, stochastic_k). Elke retrain-run brak de bot.
2. Geen guard tegen ontbrekende `trade_features.csv` → trainer crashte; bestaand model werd overschreven of corrupt.
3. `scripts/train_lstm_model.py` werd door auto_retrain aangeroepen maar bestond niet → subprocess-failure per cyclus.
4. TensorFlow was niet geïnstalleerd in de venv (`Python 3.13.7`); LSTM-predictor in `modules/ml_lstm.py` raised → ensemble viel terug op XGB-only.

### Fix
- `tools/auto_retrain.py`:
  - `TRAIN_SCRIPT` → `ai/xgb_walk_forward.py` (regular 7-feature trainer; enhanced is post-trade analyse only).
  - Nieuwe helper `_training_data_ready() -> Tuple[bool, str]` checkt of `trade_features.csv` bestaat én ≥`MIN_TRAIN_SAMPLES` (100) rijen heeft. Bij `False` → log warning en SKIP de XGB-stap (bestaande model blijft staan).
  - LSTM-blok krijgt `lstm_script.exists()` guard vooraf.
  - `build_train_command` geeft `--window`/`--step` door uit `AI_RETRAIN_ARGS`.
- `scripts/train_lstm_model.py` (NIEUW): walk-forward LSTM trainer die live Bitvavo candles ophaalt (10 markets × 1440×1m), sequences bouwt (lookback=60, horizon=5, up_threshold=0.003), model bouwt via `LSTMPricePredictor.build_model()` → `train()` → `save_model()`. Aborts safely zonder overschrijven als TF mist of <200 sequences.
- `%LOCALAPPDATA%/BotConfig/bot_config_local.json`: `USE_LSTM=true` (helper script `_enable_lstm.py` met `encoding='utf-8-sig'` BOM-safe).
- `pip install tensorflow` → TF 2.21.0 (Python 3.13 wheels werken; CPU-only op Windows, geen GPU).

### Files
- MOD: `tools/auto_retrain.py`
- NEW: `scripts/train_lstm_model.py`
- NEW (helper, niet committed): `_enable_lstm.py`, `_smoke_ml.py`
- CONFIG: `%LOCALAPPDATA%/BotConfig/bot_config_local.json` (`USE_LSTM=true`)

### Validation
- `import tensorflow as tf; tf.__version__` → `2.21.0`.
- `LSTMPricePredictor.load_model()` op `models/lstm_price_model.h5` → `True`; `predict(np.random.rand(60,5))` → `('NEUTRAL', 0.78)`.
- Bot herstart: 16 procs running, heartbeat fresh, 3 trades managed, log toont `LSTM model gebouwd: 60 lookback, 5 features` en `LSTM model geladen van models\lstm_price_model.h5`. Geen `Feature shape mismatch` meer, geen `TensorFlow is vereist` warnings sinds restart.
- Auto_retrain triggerde live `train_lstm_model.py` → 10771 train / 2693 val sequences over 10 markten × 10 epochs (training in progress).

### Notes
- **Twee XGB-modellen serveren verschillende doelen**: `ai_xgb_model.json` (7-feat regular) wordt door bot geladen voor live signalen. `ai_xgb_model_enhanced.json` (5-feat) is uitsluitend post-trade analyse — die mag nooit naar de regular path geschreven worden.
- **`trade_features.csv` bestaat nog niet**: er zijn slechts 7 closed trades; auto_retrain skipt XGB veilig totdat data ready is.
- **Python 3.13 + TF 2.21**: officieel ondersteund vanaf TF 2.17+. Wheels installeerden zonder problemen via `pip install tensorflow`.
- **OneDrive-immune config**: `USE_LSTM` gezet in `%LOCALAPPDATA%/BotConfig/bot_config_local.json` zodat OneDrive het niet kan reverten.

---

## #041 — trailing_bot.py crash-loop: KeyError op SMA_SHORT bij module-load (2026-04-23)

### Symptom / Aanleiding
Bot maakte geen nieuwe trades meer. `monitor.py` startte `trailing_bot.py` continu opnieuw op (~elke 7-15s) — zichtbaar in `scripts/helpers/logs/monitor.log` en stderr toonde:
```
File "trailing_bot.py", line 720, in <module>
    SMA_SHORT = CONFIG["SMA_SHORT"]
KeyError: 'SMA_SHORT'
```
De keys `SMA_SHORT`, `SMA_LONG`, `MACD_FAST`, `MACD_SLOW`, `MACD_SIGNAL`, `BREAKOUT_LOOKBACK`, `MIN_SCORE_TO_BUY` ontbraken in zowel `config/bot_config.json` als `bot_config_local.json`. Module-level dict-subscript leverde direct een `KeyError` op import → crash voor `bot_loop()` ooit draaide.

`heartbeat.json` werd hierdoor sinds 09:33 niet meer ververst, terwijl support-services (dashboard, AI supervisor, monitor zelf) wél bleven loggen — waardoor het leek alsof de bot draaide.

### Root Cause
1. `trailing_bot.py` regels 720-726 gebruikten `CONFIG["KEY"]` (raise op missing) i.p.v. `.get()` met default.
2. `modules/config.py.load_config()` past schema-defaults uit `config_schema.py` NIET toe op de geladen dict — schema is alleen voor validatie.
3. Combinatie = elke missende key crasht de bot bij module-import.

### Fix
Vervangen door `_as_int(CONFIG.get(...), <schema_default>)` met defaults uit `modules/config_schema.py`:
- `SMA_SHORT=20`, `SMA_LONG=50`, `MACD_FAST=12`, `MACD_SLOW=26`, `MACD_SIGNAL=9`, `BREAKOUT_LOOKBACK=50`, `MIN_SCORE_TO_BUY=7.0` (laatste blijft float).

### Files
- MOD: `trailing_bot.py` (regels 720-726)

### Notes
- Dit is een terugkerend patroon: **module-level `CONFIG[...]` is fragiel**. Zoek alle resterende dict-subscripts in trailing_bot.py op import-niveau en migreer naar `.get()` met defaults — toekomstige config-drift mag de bot niet meer crashen.
- Overweeg `load_config()` schema-defaults te laten inject — maar dat is een bredere refactor.
- De kwaadaardige neveneffecten van deze crash-loop: `scripts/helpers/logs/trailing_stdout.log` is gegroeid tot **868 MB** en `bot_log.txt.rotation.log` tot **5.3 GB**. Schoonmaak nodig.

---

## #040 — Nieuwe edge stack: post-loss cooldown + adaptive MIN_SCORE + BTC drawdown shield + dashboard refresh (2026-04-24)

### Symptom / Aanleiding
Volgende-generatie verbeteringen na #039 full-deployment. Doelen:
1. Voorkom direct re-entry op een net verloren markt (revenge trading).
2. Verhoog MIN_SCORE-drempel automatisch tijdens slechte periodes (lage rolling WR / loss-streak).
3. Skip new entries (excl. BTC-EUR) als BTC zelf instort op 5m timeframe (crash hedge).
4. Dashboard verouderd visueel — vol grid-trading milestones die niet meer relevant zijn.

### Fix Applied
**Drie nieuwe entry-gates** (bot/), elk geïsoleerd + thread-safe + unit-tested:
- `bot/post_loss_cooldown.py` — `PostLossCooldown` singleton. Blokkeert market voor `POST_LOSS_COOLDOWN_SEC` (default 4h) na verlies; `POST_LOSS_BIG_COOLDOWN_SEC` (24h) na verlies > `POST_LOSS_BIG_LOSS_EUR` (€5). Persistent: `data/post_loss_cooldown.json`.
- `bot/adaptive_score.py` — `AdaptiveScoreThreshold(lookback=7)` met deque rolling-WR. Loss-streak override (≥3 verliezen → +2.0 op MIN_SCORE) heeft voorrang. WR-ladder: <40% +1.5, <55% +0.5, >75% −0.5.
- `bot/btc_drawdown_shield.py` — Stateless. Skip nieuwe entries als BTC 5m return over `BTC_DRAWDOWN_LOOKBACK_5M` (12 candles = ~1u) onder `BTC_DRAWDOWN_THRESHOLD_PCT` (default −1.5%). BTC-EUR market exempt.

**Wiring** in `trailing_bot.py`:
- Adaptive bump op `min_score_threshold` direct na config-load (~line 3041).
- Post-loss + BTC shield gates direct na `_event_hooks_paused` continue (~line 3160).
- Close-hooks naar beide singletons (`record_close`) in `_finalize_close_trade` na bestaande `market_expectancy.record_trade`.

**Tests**: 24 nieuwe unit tests in `tests/test_post_loss_cooldown.py`, `test_adaptive_score.py`, `test_btc_drawdown_shield.py` — alle slagen.

**Roadmap V2 herschreven**: `docs/PORTFOLIO_ROADMAP_V2.md` volledig zonder grid trading. 10 milestones €1.450→€25.000 met conservatief/base/optimistisch winstprojecties en ETAs t/m okt 2027.

**Dashboard milestones array** in `tools/dashboard_flask/app.py` (line 3774) gesynchroniseerd met nieuwe roadmap (geen grid entries meer, denominator 6000 → 10000).

**Dashboard visual refresh** (non-destructief):
- Nieuwe `static/css/v3_modern.css` — dark glassmorphism design system, deep purple-blue accent, geladen LAATST in base.html zodat het alle legacy CSS overruled.
- **Command Palette (Ctrl+K / Cmd+K)** toegevoegd in base.html — quick-jump naar alle 10 hoofdpagina's met zoekfunctie, keyboard nav (↑↓↵Esc).

### Lesson
Voorkomen van re-entry-on-loss is empirisch veel effectiever dan alleen een hogere MIN_SCORE — markets vertonen 1-4u "post-loss EV-dip" patronen waar zelfs goede signalen onderpresteren. BTC drives ~80% van alt-correlatie op 5m: een BTC −1.5% in 1u is een betrouwbaarder kill-switch dan losse alt-checks. Adaptive MIN_SCORE met loss-streak override = dynamische rem op cascading losses zonder handmatige interventie.

Dashboard-tip: één LAATST-geladen CSS file (cascading override) is veiliger dan refactoren van 15 legacy files. Command Palette is ~50 regels JS en transformeert UX op alle 10 pagina's tegelijk.

---



### Symptom
Vorige iteratie #038 (BASE=200, MAX=4) liet typical 4×200 = €800 = 55% van portfolio idle. Gebruiker terecht op gewezen: "200×4 = 800, 600 idle".

### Fix
Echte volledige deployment via wijdere grid-search (BASE 200-350, MAX 3-5, DCA 20-50 × 1-3):
- `BASE_AMOUNT_EUR`: 200 → **320**
- `DCA_AMOUNT_EUR`: 40 → **20** (klein want 97% trades trigger nooit DCA)
- `DCA_MAX_BUYS`/`ORDERS`: 2 → **2** (ongewijzigd)
- `MAX_OPEN_TRADES`: 4 (ongewijzigd, behoudt diversificatie boven 3-slots winners)

Numeriek:
- Typical (geen DCA): 4 × 320 = **€1.280 = 88%** van €1.450
- Worst (alle DCAs gevuld): 4 × 360 = **€1.440 = 99%**
- Cash buffer: ~€170 voor fees+slippage
- Sim PnL: **+€673** op 123 trades = **+477% vs realized** = ~+€95/week

### Lesson
Bij "all capital deployed" moet de typical-case (no-DCA) zelf al ~85-90% zijn. Anders zit het meeste idle want 97% van trades doet geen DCA. DCA klein houden + BASE groot maken = correct. 3-slots config (BASE=350, MAX=3) gaf marginaal hogere PnL maar concentratierisico op single market crash is te hoog.

---

## #038 — €1.450 sizing upgrade naar NO-RESERVE profiel (2026-04-23)

### Symptom
Initiële V2.1 config (#037) was te conservatief voor de daadwerkelijke risk-appetite van de gebruiker — BASE=120 op €1.450 portfolio liet €610 (42%) ongebruikt.

### Fix
Lokale config opgeschaald naar de "no-reserve" variant van de €1.450 backtest:
- `BASE_AMOUNT_EUR`: 120 → **200**
- `DCA_AMOUNT_EUR`: 30 → **40**
- `DCA_MAX_BUYS`/`DCA_MAX_ORDERS`: 3 → **2**
- `MIN_BALANCE_EUR`: 0 (expliciet — geen harde reserve)
- `MAX_OPEN_TRADES`: 4 (ongewijzigd, behoudt diversificatie)

Worst-case exposure: 4 × (200 + 40×2) = **€1.120 = 77%** van €1.450.
Sim PnL backtest: **+€431,63** op 123 clean trades (vs +€273 voor BASE=120 = **+58%**, vs +€117 realized = **+270%**).

### Lesson
Bij "geen reserve" houd je nog steeds 4 slots om concentratierisico te beperken. De échte rem op grotere posities is **slippage en spread-impact** boven ~€200/trade op kleinere alts (FET, ENJ, GALA), niet de capital-efficiency. Backtest schaalt PnL lineair maar live verlies door slippage kan 5-10% afsnijden van de geprojecteerde +270%.

---

## #036 — /set Telegram commando schrijft naar verkeerde config-laag (2026-04-21)

### Symptom
`/set BASE_AMOUNT_EUR 1000` (of andere keys) via Telegram had geen effect: de bot startte trades met het oude bedrag. Ookzag `/config` afwijkende waarden t.o.v. wat de bot echt gebruikte.

### Root Cause
`_load_config()` in `telegram_handler.py` las alleen layer 1 (`config/bot_config.json`, OneDrive). `_save_config()` schreef ook alleen naar layer 1. Maar de bot's runtime config is de 3-laags merged result waarbij **layer 3 (`LOCAL_OVERRIDE_PATH`) altijd wint**. Als layer 3 `BASE_AMOUNT_EUR = 127` had, overschreef die layer 3 elke write naar layer 1 bij de volgende `load_config()`.

### Fix Applied
| File | Change |
|------|--------|
| `modules/telegram_handler.py` | `_load_config()` roept nu `modules.config.load_config()` aan (volledige 3-laags merge) zodat alle Telegram-commando's de echte bot-waarden tonen |
| `modules/telegram_handler.py` | `_save_config()` verwijderd; vervangen door `_save_local_override(key, value)` die alleen de gewijzigde key naar `LOCAL_OVERRIDE_PATH` (layer 3) schrijft — wint over alles, nooit teruggedraaid door OneDrive |
| `modules/telegram_handler.py` | `_apply_set_command()` gebruikt nu `_save_local_override()` i.p.v. read-modify-write op layer 1 |
| `modules/telegram_handler.py` | `_save_chat_id()` gebruikt nu ook `_save_local_override()` |
| `modules/telegram_handler.py` | `BUDGET_RESERVATION.*` keys toegevoegd aan `ALLOWED_KEYS` (trailing_pct, grid_pct, reserve_pct, min_reserve_eur, mode) |
| `modules/telegram_handler.py` | Success message bijgewerkt: "Actief na volgende bot-loop (~25s)" i.p.v. "Herstart bot" |

### Lesson
`/set` moet altijd schrijven naar `LOCAL_OVERRIDE_PATH` (layer 3). Lees-modify-write op layer 1 werkt nooit betrouwbaar omdat layer 3 alles overschrijft. Gebruik altijd `_save_local_override()` voor config-aanpassingen via Telegram.

---

## #035 — Nieuw: /update Telegram commando (git pull + herstart) (2026-04-21)

### Symptom
Geen manier om code-updates op de crypto laptop te deployen zonder fysieke toegang (geen `git pull` mogelijk op afstand).

### Fix Applied
| File | Change |
|------|--------|
| `modules/telegram_handler.py` | Nieuwe functie `_git_pull_and_restart()`: voert `git pull` uit in `BASE_DIR`, stuurt uitvoer als Telegram-bericht, en roept `_restart_bot()` aan bij succes |
| `modules/telegram_handler.py` | `/update` commando toegevoegd aan command handler en `/help` tekst |
| `modules/telegram_handler.py` | Module docstring bijgewerkt met `/update` |

### Lesson
Bij een `git pull` fout (exit code ≠ 0) wordt de bot NIET herstart — de foutmelding wordt via Telegram gestuurd zodat de gebruiker het kan oplossen.
---

## #037 — Position size floor + per-market EV-sizing for €1.450 portfolio (2026-04-23)

### Symptom
Bot at €1.450 portfolio was running with V2-start config (BASE=1000, MAX=6, DCA=61x5) — **6× over-leveraged** for the actual portfolio. Many trades fired at <€25 invested (negative EV bucket: −€0,12/trade), while the proven sweet-spot (€75-€150) sat at +€3,34/trade. No data feedback loop to under-weight historically losing markets.

### Root cause
1. Single global BASE_AMOUNT_EUR was applied uniformly regardless of per-market expectancy.
2. No floor on tiny positions: dust-sized buys diluted the portfolio with negative-EV trades.
3. Config had not been right-sized after portfolio shrunk from €4k → €1.450.

### Fix (3 new components)
1. **`bot/sizing_floor.py`** — `enforce_size_floor(market, proposed_eur, score, eur_balance, is_dca, cfg, log)`:
   - <SOFT_MIN (€50): abort
   - SOFT_MIN..ABS_MIN (€50-€75): bump up if balance allows OR allow if score ≥ 14 (high-conviction bypass) OR abort
   - ≥ ABS_MIN: pass-through
   - DCA buys exempt
2. **`core/market_expectancy.py`** — `MarketExpectancy` with empirical-Bayes shrinkage:
   - `shrunk_ev = (n × ev_market + K_PRIOR × ev_global) / (n + K_PRIOR)` with K_PRIOR=10, ALPHA=0.7
   - `size_multiplier(market) → 0.0` if shrunk_ev ≤ −0.50 (blacklist), else clamped 0.30..1.80
   - Persists to `data/market_expectancy.json`, atomic writes every 5 trades
3. **Score-stamping** in `trailing_bot.py:open_trade_async` so the size-floor's high-conviction bypass actually has the entry score available.
4. Wired both into `bot/orders_impl.py:place_buy()` (after EUR balance safeguard, gated by `MARKET_EV_SIZING_ENABLED` and `POSITION_SIZE_FLOOR_ENABLED`).
5. Wired `market_ev.record_trade()` into `trailing_bot._finalize_close_trade` so the model self-improves on every closed trade (operational error reasons excluded).
6. **Bootstrap** script `scripts/helpers/bootstrap_market_ev.py` seeds 159 trades from the clean archive (March-April 2026, no saldo_error/sync_removed/manual/reconstructed/dust).
7. Local config right-sized for €1.450:
   ```
   BASE_AMOUNT_EUR: 1000 → 120
   MAX_OPEN_TRADES: 6 → 4
   DCA_AMOUNT_EUR: 61 → 30
   DCA_MAX_BUYS: 5 → 3
   DEFAULT_TRAILING: 0.024 → 0.022
   TRAILING_ACTIVATION_PCT: 0.020 → 0.025
   POSITION_SIZE_FLOOR_ENABLED: true (new)
   POSITION_SIZE_ABS_MIN_EUR: 75 (new)
   POSITION_SIZE_SOFT_MIN_EUR: 50 (new)
   POSITION_SIZE_HIGH_CONVICTION_SCORE: 14 (new)
   MARKET_EV_SIZING_ENABLED: true (new)
   ```
   Worst-case exposure: 4 × (120 + 30×3) = €840 = 58% of €1.450 ✅

### Validation
- 17/17 new unit tests pass (`tests/test_sizing_floor.py`, `tests/test_market_expectancy.py`).
- Bootstrap seeded 159 trades, global EV +€0,73/trade, all whitelisted markets profitable, no blacklists triggered.
- Backtest on 123 clean trades since 2026-03-01: simulated PnL **+€273,24** vs realized +€116,59 = **+134% projected improvement**.

### Files touched
- NEW: `bot/sizing_floor.py`, `core/market_expectancy.py`, `scripts/helpers/bootstrap_market_ev.py`
- NEW: `tests/test_sizing_floor.py`, `tests/test_market_expectancy.py`
- MOD: `bot/orders_impl.py` (place_buy gates), `trailing_bot.py` (open_trade_async score stamp + _finalize_close_trade record), `bot/shared.py` (last_signal_score field)
- MOD: `docs/PORTFOLIO_ROADMAP_V2.md` (€1.450 milestone), `tools/dashboard_flask/app.py` (milestone array)
- LOCAL config: `%LOCALAPPDATA%/BotConfig/bot_config_local.json`

### Lesson
When portfolio shrinks significantly, BASE_AMOUNT must shrink with it — running €1000 BASE on a €1450 portfolio leaves no room for diversification or DCA. Always size BASE so that `MAX_TRADES × (BASE + DCA_MAX × DCA_AMOUNT) ≤ 60% × portfolio` to preserve the 15% EUR reserve plus a safety buffer.

---

## #034 — Shadow tracker crash on string timestamps in closed_trades (2026-04-15)

### Symptom
Shadow mode hook in bot_loop silently failed — no entries written to `data/shadow_log.jsonl` despite scan completing successfully. Debug logging revealed: `could not convert string to float: '2026-04-10 20:12:20'`

### Root Cause
`closed_trades` list contains entries where `timestamp` field is an ISO date string (e.g. `'2026-04-10 20:12:20'`) rather than a unix float. The velocity filter's `float(t.get("timestamp"))` crashed on these entries. The `except Exception: pass` silently swallowed the error.

### Fix Applied
| File | Change |
|------|--------|
| `core/shadow_tracker.py` | Added `_parse_ts(val)` helper that handles float, int, and ISO date string timestamps |
| `core/shadow_tracker.py` | Velocity filter now uses `_parse_ts()` instead of bare `float()` |
| `trailing_bot.py` | Changed shadow hook `except Exception: pass` to `except Exception as e: log(...)` for debug visibility |

### Lesson
Never use bare `float()` on trade timestamps — the archive and closed_trades list contain mixed format timestamps (unix floats AND ISO strings). Always use a defensive parser.

---

## #033 — Grid counter-orders all at same price + no sell levels (2026-04-13)

### Symptom
Grid BTC-EUR had 6 open orders, ALL buys, NO sells. Three counter-buy orders were all
placed at the exact same price (60105), and three original buy levels at different prices.
Grid was using full €184 budget but was effectively a one-sided buy wall with no ability
to profit from price movements. Total open order value spread:
- 3 original buys: €56/each at 58891, 59498, 60105
- 3 counter-buys: €5/each all at 60105 (duplicate price!)

### Root Cause (3 bugs)

1. **`_find_next_lower_price` scanned placed/pending levels, not the grid ladder**:
   When sells at 61778 and 61927 filled, the counter-buy price was found by scanning
   `state.levels` for the nearest placed/pending level below. The only placed buy levels
   were at 58891, 59498, 60105 — so ALL three counter-buys got price 60105 (the highest
   placed buy). The function had no concept of the grid's actual price spacing.

2. **No sell-side price ladder stored**: The grid started with no BTC, so only buy levels
   were created (`buy_only` mode). The sell-side grid prices were never stored. When a buy
   filled and needed to place a counter-sell, `_find_next_higher_price` searched for
   placed/pending levels above — finding none (all sells were filled or cancelled).

3. **Budget imbalance**: With no BTC balance, `_calculate_grid_levels` allocated 100% of
   budget to buy side. The sell orders got only whatever tiny BTC dust existed (~€5 each).
   After those tiny sells filled, the counter-buys were equally tiny (~€5 each), creating
   a massive imbalance where most of the budget sat in buy orders that would never fill.

### Fix Applied

| File | Change |
|------|--------|
| `modules/grid_trading.py` | NEW: `price_ladder: List[float]` field on `GridState` — stores full grid price ladder |
| `modules/grid_trading.py` | NEW: `_compute_full_ladder()` — derives complete grid prices from config (both buy AND sell side) |
| `modules/grid_trading.py` | NEW: `_get_price_ladder()` — returns stored ladder with config fallback |
| `modules/grid_trading.py` | FIXED: `_find_next_higher_price()` uses price_ladder instead of scanning level statuses |
| `modules/grid_trading.py` | FIXED: `_find_next_lower_price()` uses price_ladder instead of scanning level statuses |
| `modules/grid_trading.py` | Both find functions have fallback: calculate one grid step beyond ladder bounds |
| `modules/grid_trading.py` | `create_grid()` stores full ladder via `_compute_full_ladder()` |
| `modules/grid_trading.py` | `_rebalance_grid()` updates ladder on rebalance |
| `modules/grid_trading.py` | `_save_states()` / `_load_states()` persist/restore `price_ladder` |
| `bot_config_local.json` | `GRID_TRADING.num_grids`: 5→10 for better trade frequency with €184 budget |
| `data/grid_states.json` | Reset: old broken grid deleted, new grid created with proper ladder |

### Grid Config Applied
- Market: BTC-EUR, Range: ±4% (8% total), 10 price levels, €184 budget
- 5 buy levels placed at different prices (€36.88/level)
- Full 10-price ladder stored (5 buy + 5 sell prices) for counter-order placement
- When a buy fills, counter-sell placed at correct next-higher ladder price (not arbitrary)

### Key Rules
1. **`price_ladder` must always contain ALL grid prices** (both buy and sell side), even when
   only buy orders are placed. This ensures counter-orders go to the correct price.
2. **Never scan `state.levels` status for counter-order pricing** — use the price ladder.
3. **Counter-sell price = next ladder price above the filled buy price** (not the nearest
   placed/pending level).

---

## #032 — Grid sells below cost: lost cost basis + phantom fills (2026-04-13)

### Symptom
ALL grid sells since the initial buy at €61,594 were below cost:
- Sell @ 61,196 → loss -€0.43
- Sell @ 60,648 → loss -€0.21
- Sell @ 61,254 → loss -€0.10
- Sell @ 60,956 → loss -€0.10

Grid reported `total_profit: +€1.57` when real P&L was **-€0.90** (€2.47 discrepancy).
Also: 72 phantom fills from simulation script contaminated `grid_fills_log.json`.

### Root Cause

1. **`last_buy_fill_price` was 0.0**: The buy at 61,594 occurred BEFORE FIX #031b added
   persistence of `last_buy_fill_price` to `_save_states()`. After bot restart, the field
   loaded as 0.0 (default) because it was never saved to disk. All subsequent rebalances
   had NO cost protection (`if state.last_buy_fill_price > 0` → always false).

2. **No fallback for unknown cost basis**: When `last_buy_fill_price` was 0 and inventory
   existed, the grid had no mechanism to recover the cost. It placed sell orders below
   the actual buy price, guaranteeing losses on every sell.

3. **Phantom fills from simulation**: The `_grid_deep_sim.py` script (FIX #031b) wrote to
   the real `data/grid_fills_log.json` because `_log_fill` wasn't mocked in all test paths.
   72 phantom fills at impossible prices (81,450 and 91,125) contaminated the log.

4. **Profit calculation fallback showed fake profits**: `_estimate_buy_cost` fell through to
   `sell_price * 0.99` estimate when no cost basis was known, showing positive profit on
   what were actually losses.

### Fix Applied

| File | Change |
|------|--------|
| `modules/grid_trading.py` | NEW: `_derive_cost_from_exchange()` queries Bitvavo trades API for last buy price |
| `modules/grid_trading.py` | `_load_states()`: derives cost from exchange when `last_buy_fill_price==0` + inventory |
| `modules/grid_trading.py` | `_rebalance_grid()`: derives cost before protection check; uses current price as last resort |
| `modules/grid_trading.py` | `start_grid()`: derives cost + blocks sell orders below cost basis |
| `modules/grid_trading.py` | `_estimate_buy_cost()`: exchange fallback instead of fake 0.99 estimate |
| `data/grid_states.json` | Corrected `last_buy_fill_price` to 61594, `total_profit` to -0.90 |
| `data/grid_fills_log.json` | Removed 72 phantom fills, corrected profit values on remaining 4 sells |

### Key Rules
1. **`last_buy_fill_price` must NEVER be 0 when inventory exists.** If it is, derive from Bitvavo.
2. **Simulations must use isolated file paths** (`GRID_FILLS_LOG`, `GRID_STATE_FILE`).
3. **ALL sell placements must check cost basis** — in `_rebalance_grid`, `start_grid`, AND counter-orders.

---

## #031 — Grid rebalance creates sells below buy cost basis (2026-04-12)

### Symptom
Grid bot bought BTC at €61,594 (07:30), then vol-adaptive rebalance triggered in the same cycle,
placing a sell at €61,196 — below the buy price. Sell filled at 07:49 for a loss of €0.43 but
the grid reported +€1.24 profit (€1.67 discrepancy).

### Root Cause (3 bugs)

1. **Vol-adaptive rebalance in same cycle as fill**: `auto_manage()` Step 3 processes fills, then
   Step 3b checks vol-adaptive and can trigger a `_rebalance_grid()` in the same call. The new
   grid levels are centered on current price, ignoring the cost basis of just-bought inventory.
   
2. **`_estimate_buy_cost()` uses grid level prices**: After rebalance, the function estimates
   cost from `_find_next_lower_price()` which returns new grid levels, not the actual buy price.
   For the sell at €61,196, it estimated cost at €59,360 (the new lower buy level), yielding
   fake +€1.24 profit when real cost was €61,594 = loss.

3. **No cost basis protection in `_rebalance_grid()`**: Rebalance blindly sets sell levels from
   grid math without checking if they're below the actual buy cost of held inventory.

### Fix Applied

| File | Change |
|------|--------|
| `modules/grid_trading.py` | Added `last_buy_fill_price` to `GridState` — tracks actual buy fill price for cost basis. |
| `modules/grid_trading.py` | Buy fill handler now sets `state.last_buy_fill_price = fill_price`. |
| `modules/grid_trading.py` | `auto_manage()` Step 3 tracks `fills_this_cycle`; Step 3b skips rebalance if fills occurred. |
| `modules/grid_trading.py` | `_rebalance_grid()` raises sell levels above cost basis (+ 2× maker fee) when inventory held. |
| `modules/grid_trading.py` | `_estimate_buy_cost()` uses `last_buy_fill_price` when available instead of grid level estimate. |
| `data/grid_states.json` | Corrected `total_profit` from +€1.24 to -€0.43, added `last_buy_fill_price`. |

### Key Rule
**NEVER rebalance in the same cycle as a fill.** After a buy fill, the grid must protect
sell levels above the actual buy cost basis. Grid profit must use actual fill prices,
not grid level estimates.

---

## #031b — Grid deep analysis: 5 structural bugs (2026-04-12)

### Symptom
Ultra-deep simulation (`_grid_deep_sim.py`, 10 test scenarios) uncovered 5 bugs in
`modules/grid_trading.py` — confirmed by automated test failures.

### Bugs Found & Fixed

| # | Bug | Severity | Root Cause | Fix |
|---|-----|----------|-----------|-----|
| 1 | `_save_states()` doesn't persist `last_buy_fill_price` | CRITICAL | Field added to `GridState` and `_load_states()` but missing from `_save_states()` explicit dict | Added `'last_buy_fill_price': state.last_buy_fill_price` to save dict |
| 2 | `update_grid()` rebalance fires after fill in same call | CRITICAL | `update_grid()` has its own auto-rebalance check at end (separate from `auto_manage()`). After processing fills, it checked if price was out of range and rebalanced — same class of bug as #031 | Added `fills_occurred` flag; rebalance block guarded with `if config.auto_rebalance and not fills_occurred:` |
| 3 | `_find_next_higher/lower_price` returns stale level prices | MODERATE | After rebalances, old filled/cancelled levels remained in `state.levels`. Price search returned their prices (e.g. 57000 from cancelled level) instead of None | Filter to `l.status in ('placed', 'pending')` only |
| 4 | `base_balance` can go negative on sell fill | MODERATE | `state.base_balance -= actual_amount` without floor when sell amount exceeds balance (rounding/partial fills) | Changed to `state.base_balance = max(0.0, state.base_balance - actual_amount)` |
| 5 | `_estimate_buy_cost` uses wrong cost basis for paired trades | MODERATE | With multiple buy/sell pairs, `last_buy_fill_price` is the LAST buy price, not the specific paired buy. Sell at level paired with buy@59200 used cost from last buy@60500 — €1.30 error | Now looks up `sell_level.pair_level_id` → finds paired buy level's `filled_price`. Falls back to `last_buy_fill_price` only if no pair found |

### Files Changed

| File | Change |
|------|--------|
| `modules/grid_trading.py` | `_save_states()`: added `last_buy_fill_price` to serialization dict |
| `modules/grid_trading.py` | `update_grid()`: added `fills_occurred` flag, defers rebalance when fills processed |
| `modules/grid_trading.py` | `_find_next_higher/lower_price()`: filter by `status in ('placed', 'pending')` |
| `modules/grid_trading.py` | Sell fill handler: `base_balance = max(0.0, base_balance - actual_amount)` |
| `modules/grid_trading.py` | `_estimate_buy_cost()`: paired buy level lookup via `pair_level_id` before fallback |
| `tests/test_grid_trading.py` | Added `load_freshest` patch for test isolation from LocalAppData |

### Key Rule
**`update_grid()` has its OWN rebalance check** — separate from `auto_manage()`.
Both paths must defer rebalance when fills occurred. Always check `pair_level_id`
for accurate per-trade cost basis.

---

## #001 — invested_eur desync after external buys (2026-03-25)

### Symptom
Dashboard showed wrong P&L for all open trades. Bitvavo showed:
- AVAX: +0.38% profit, bot dashboard showed +26.49%
- ALGO: -4.69% loss, bot showed +2.91%
- NEAR: -7.35% loss, bot showed -0.14%

The `invested_eur` field was too low (stuck at pre-external-buy values), making profits appear inflated.

### Root Cause (3 overlapping bugs)

1. **`derive_cost_basis` used `opened_ts` filter**: When the sync engine called
   `derive_cost_basis(bitvavo, market, amount, opened_ts=opened_ts)`, the `opened_ts`
   was set to the bot's restart/sync time (NOT the actual first buy). This caused
   the API to only return trades AFTER that timestamp, missing earlier buys that
   are part of the current position. Even though there was a fallback to fetch all
   trades, the result could still be wrong due to pagination issues.

2. **Three overlapping sync checks fought each other**: The sync engine had:
   - STALE check (50% threshold — almost never triggered)
   - Invested drift check (5% threshold — triggered but used wrong opened_ts)
   - CONSISTENCY GUARD (forced invested_eur = buy_price × amount)
   These checks conflicted: if derive partially succeeded (updated buy_price but
   not invested_eur), the CONSISTENCY GUARD would propagate the wrong buy_price
   to invested_eur. If derive failed, the fallback set invested_eur = old_buy_price
   × new_amount (wrong because old_buy_price didn't include the new buys).

3. **Dashboard `max()` hack masked the problem**: The dashboard used
   `invested = max(invested_eur, buy_price × amount)` which showed the HIGHER value.
   When buy_price was wrong (too high), this overstated the cost basis, but in a
   different direction than the actual error. This made the displayed P&L look
   plausible even though the underlying data was wrong.

### Fix Applied

| File | Change |
|------|--------|
| `modules/cost_basis.py` | `derive_cost_basis()` now ALWAYS fetches full trade history (ignores `opened_ts`). The parameter is kept for API compat but never used as filter. |
| `bot/sync_engine.py` | Replaced 3 overlapping checks with ONE unified approach: re-derive on amount change, missing invested, periodic (4h), or >2% divergence. Uses `derive_cost_basis` as single source of truth. No `opened_ts` filter. |
| `trailing_bot.py` | GUARD 7 no longer blindly forces `invested_eur = buy_price*amount`. Only fills in when invested_eur is 0. Logs warning for >10% divergence. |
| `tools/dashboard_flask/app.py` | Removed `max()` hack. Uses `invested_eur` directly as it's now kept correct by sync engine. |
| `data/trade_log.json` | Fixed current data with correct values derived from Bitvavo transaction history. |

### Correct Values (from Bitvavo "Mijn assets" P&L on 2026-03-25)
- AVAX-EUR: cost_basis=€207.38, avg_price=€8.303
- ALGO-EUR: cost_basis=€250.62, avg_price=€0.07960
- NEAR-EUR: cost_basis=€259.81, avg_price=€1.1946

### Prevention
- `derive_cost_basis` always uses full order history (no date filter)
- Sync engine re-derives on ANY amount change (>0.1%)
- Periodic 4-hour re-derive as safety net
- Test: `tests/test_cost_basis_sync.py` validates the complete flow
- GUARD 7 in `validate_and_repair_trades` logs >10% divergence for manual review

### How to verify data is correct
Compare bot's invested_eur with Bitvavo's "Ongerealiseerde P&L":
```
bitvavo_cost_basis = saldo_eur + abs(unrealized_pnl_eur)  # when P&L is negative
bitvavo_cost_basis = saldo_eur - unrealized_pnl_eur       # when P&L is positive
```
Bot's invested_eur should be within ~1% of bitvavo_cost_basis (difference is fees).

---

## #002 — trading_sync.py filter silently drops positions on API glitch (2026-03-25)

### Symptom
After bot restart, AVAX-EUR disappeared from open_trades. The sync_debug.json showed
only 2 mapped markets (NEAR, ALGO) even though trade_log.json had 3 open trades.
Investigation revealed AVAX was actually sold at 19:23 by the old bot via trailing_tp
(sell_price=€8.37, profit=+€0.66), so the removal was correct in this case.
However, the code path that removed it is dangerous for transient API failures.

### Root Cause
`modules/trading_sync.py` has a `filtered_state` line that retains ONLY markets present
in the current Bitvavo balance API response:
```python
filtered_state = {m: e for m, e in open_state.items() if m in open_markets and open_markets[m] > 0}
```
This filter **bypasses** the `DISABLE_SYNC_REMOVE=True` config guard. If the Bitvavo
balance API has a transient failure (returns incomplete data), ALL positions missing
from the response are silently deleted from trade_log.json — even though they still
exist on the exchange.

Additionally, `modules/trading_sync.py` could only reconstruct missing positions from
`pending_saldo.json`, not from Bitvavo order history. If a position existed on Bitvavo
but wasn't in pending_saldo, it was silently ignored.

### Fix Applied

| File | Change |
|------|--------|
| `modules/trading_sync.py` | `filtered_state` now respects `DISABLE_SYNC_REMOVE`. When True, positions missing from API are KEPT (not silently dropped). Logs a warning instead. |
| `modules/trading_sync.py` | Added auto-discover via `derive_cost_basis()`: if a Bitvavo balance has no matching open trade AND isn't in pending_saldo, the sync now derives cost basis from order history and creates the trade entry automatically. |

### Prevention
- With `DISABLE_SYNC_REMOVE=True` (default), positions are never silently dropped
- Auto-discover catches orphan positions via derive_cost_basis
- `bot/sync_engine.py` already had proper auto-discover; now `modules/trading_sync.py` does too

---

## #003 — Disable all time-based exits and loss sells (2026-03-25)

### Symptom
User does not want any trade to be closed based on time, and no trade may EVER be sold at a loss.

### What was disabled

| Mechanism | File | What it did | Action |
|-----------|------|-------------|--------|
| Hard stop-loss | `bot/trailing.py` `check_stop_loss()` | Sold at >15% loss | Function now always returns `(False, "disabled")` |
| Time stop-loss | `bot/trailing.py` `check_stop_loss()` | Sold after N days + loss | Same: always returns False |
| 48h exit | `bot/trailing.py` `check_advanced_exit_strategies()` | Sold at >3% profit after 48h | Code removed |
| 24h tighten | `bot/trailing.py` `check_advanced_exit_strategies()` | Set `time_tighten` flag after 24h | Code removed |
| time_tighten consumption | `bot/trailing.py` `calculate_stop_levels()` | Tightened trailing stop by 50% | Code removed |
| Hard SL sell path | `trailing_bot.py` ~L2852 | Executed sell on stop-loss trigger | Wrapped in `if False:` — unreachable |

### Still active (profit-gated, safe)
- Trailing TP: already has `real_profit <= 0` guard (blocks loss sells)
- Partial TP: only triggers at configured profit thresholds
- Volatility spike exit: requires >5% profit
- Auto-free slots: requires >0.5% profit
- Max age / max drawdown: both have loss-blocking guards

### Prevention
- `check_stop_loss()` is a no-op; even if config enables it, nothing happens
- Hard SL sell path is dead code (`if False:`)
- Tests updated to assert stop-loss never triggers

---

## #004 — dca_buys inflated to buy_order_count on synced positions (2026-03-26)

### Symptom
XRP-EUR showed `dca_buys=17` despite having zero DCA events executed. Same for NEAR and ALGO.

### Root Cause
`modules/sync_validator.py` `auto_add_missing_positions()` set `dca_buys = max(1, result.buy_order_count)` where `buy_order_count` is ALL historical buy orders for the market (including old closed positions). For XRP with 17+ historical buy orders, this set `dca_buys=17` on a brand-new position.

Additionally, `dca_max` was inflated to `max(config_dca_max, dca_buys)` — so with `dca_buys=17` and config `DCA_MAX_BUYS=17`, `dca_max=17`. This made all repair guards in `trailing_bot.py` (GUARD 1 and GUARD 5) ineffective because `dca_buys == dca_max`.

GUARD 5 used `min(max(dca_buys_now, actual_event_count), dca_max_now)` which NEVER reduced `dca_buys` below its current value — even when `dca_events` was empty.

### Fix Applied

| File | Change |
|------|--------|
| `modules/sync_validator.py` L296 | `dca_buys = 0` for newly synced positions (not `max(1, buy_order_count)`) |
| `modules/sync_validator.py` L315 | Same fix in FIFO fallback path |
| `modules/sync_validator.py` L413 | `dca_max` uses config value, not `max(config, dca_buys)` |
| `trailing_bot.py` GUARD 5 ~L893 | `correct_buys = min(actual_event_count, dca_max_global)` — now based on `dca_events` count, not `max(dca_buys, events)` |
| trade_log.json | Reset all open trades: `dca_buys=0`, `dca_max` from config |

### Key rule
`dca_buys` must ALWAYS equal `len(dca_events)`. A newly synced position has `dca_buys=0` because the bot hasn't executed any DCAs. `buy_order_count` from cost_basis includes historical orders from old positions and must NEVER be used as a DCA counter.

---

## #005 — DCA cascading: multiple buys at same price in one cycle (2026-03-26)

### Symptom
Bot executed 3 DCAs on NEAR-EUR and 2 on ALGO-EUR within 2 minutes, ALL at the same
market price (1.0563 / 0.0731). Burned through €175 of €178 balance. Each successive
DCA had decreasing EUR amounts (36→33→29) due to 0.9x multiplier but the price never
dropped further between buys.

### Root Cause
In `_execute_fixed_dca` and `_execute_dynamic_dca`, the DCA target price was calculated
from `buy_price` (weighted average entry price):
```python
target_price = float(trade.get("buy_price", current_price)) * (1 - step_pct)
```
After each DCA buy, `buy_price` is recalculated as a weighted average which DROPS (since
we're averaging down). The while loop immediately checks the next DCA level using this
new lower `buy_price`. Since the market price hasn't changed, and the new target is still
above market price, the next DCA triggers too. This cascades until `max_buys_per_iteration`
(which was 3) is exhausted.

Example with NEAR: buy_price=1.23, current=1.056, drop=2.5%:
- DCA1: target=1.23*0.975=1.20 → 1.056 < 1.20 → trigger. buy_price drops to ~1.15
- DCA2: target=1.15*0.975=1.12 → 1.056 < 1.12 → trigger. buy_price drops to ~1.10
- DCA3: target=1.10*0.975=1.07 → 1.056 < 1.07 → trigger. max_per_iter=3, stops.

### Fix Applied

| File | Change |
|------|--------|
| `modules/trading_dca.py` `_execute_fixed_dca` | Target calculated from `last_dca_price` instead of `buy_price`. After each DCA, `last_dca_price` = current execution price, so next DCA needs genuine further drop. |
| `modules/trading_dca.py` `_execute_fixed_dca` | `dca_next_price` after buy also uses `last_dca_price` as reference |
| `modules/trading_dca.py` `_execute_dynamic_dca` | Same two fixes in the dynamic DCA path |
| `bot_config_local.json` | `DCA_MAX_BUYS_PER_ITERATION`: 3 → 1 (extra safety — max 1 DCA per 25s bot cycle) |
| `tests/test_dca_buys_corruption.py` | Updated `test_multiple_dcas_in_one_call` to expect 1 DCA (not 3), fixed mock `**kwargs` |

### Key rule
DCA target must be based on `last_dca_price` (where the bot LAST bought), not `buy_price`
(weighted average). Each DCA should require `drop_pct` additional decline from the previous
DCA execution price. `DCA_MAX_BUYS_PER_ITERATION` should be 1 for safety.

---

## #006 — dca_buys=17 re-inflation + XRP invested_eur wrong (2026-03-27)

### Symptom
XRP-EUR dashboard showed 17 DCAs (only 0 real), +56.32% profit when the trade was
actually near breakeven or loss. All three open trades (XRP, NEAR, ALGO) had `dca_buys=17`.
XRP also showed `invested_eur=€41.86` while `buy_price*amount=€66.95` (37% too low).

### Root Cause (5 overlapping bugs)

1. **GUARD 5 NameError (`dca_max_now` undefined)**: `trailing_bot.py` GUARD 5 referenced
   `dca_max_now` which doesn't exist (should be `dca_max_global`). This crashed the guard
   silently, so it NEVER corrected inflated `dca_buys` values.

2. **sync_engine re-inflates dca_buys from buy_order_count**: `bot/sync_engine.py`'s 4-hour
   periodic re-derive set `dca_buys = buy_order_count - 1` from ALL historical orders
   (including old closed positions). With 17+ historical buys, this set dca_buys=16 or 17
   every 4 hours, undoing any correction from FIX #004.

3. **trade_store validation refused to reduce dca_buys**: `modules/trade_store.py`
   `_validate_and_fix_trade_data()` only increased dca_buys upward to match dca_events.
   When `dca_buys > dca_events`, it warned but KEPT the inflated value "to prevent
   duplicate DCA". For synced positions with 0 real DCAs, this preserved dca_buys=17.

4. **FIFO dust threshold too tight (1e-8)**: `modules/cost_basis.py` reset the position
   only when `pos_amount <= 1e-8`. Crypto dust from old positions (e.g., 0.01 XRP worth
   €0.01) exceeded this threshold, causing old position costs at cheap prices to bleed
   into the current position's cost basis. This made `invested_eur` too low.

5. **XRP invested_eur set from contaminated derive**: The FIFO included old cheap XRP buys
   from previous positions. Because old position sells left dust > 1e-8, the position
   never fully reset. New buys were averaged with old cheap costs, producing
   `invested_eur=€41.86` instead of the correct ~€66.95.

### Fix Applied

| File | Change |
|------|--------|
| `trailing_bot.py` GUARD 5 | Fixed `dca_max_now` → `dca_max_global` (NameError that silently crashed the guard) |
| `bot/sync_engine.py` | Removed dca_buys inflation from `buy_order_count`. Comment explains: dca_buys must ONLY change when bot executes a DCA buy |
| `modules/trade_store.py` | Validation: reduce dca_buys to 0 only when `dca_events` is empty. When events exist but fewer than dca_buys (events lost during sync/restart), keep dca_buys to prevent duplicate DCAs |
| `modules/cost_basis.py` | FIFO dust threshold: `pos_amount <= 1e-8` → `pos_amount < 1e-6 or pos_cost < €1.00`. Catches crypto dust without affecting legitimate partial sells |
| `data/trade_log.json` | XRP: dca_buys 17→0, invested_eur €41.86→€66.95. NEAR/ALGO: dca_buys kept at 17 (legitimate, events partially lost) |

### Key Rules
- `dca_buys=0` when `dca_events` is empty (synced position, no bot-tracked DCAs)
- `dca_buys >= len(dca_events)` when events exist (events can be lost during sync/restart, keep dca_buys to prevent duplicate DCA)
- NEVER derive `dca_buys` from `buy_order_count` (includes old closed positions)
- `invested_eur` must be consistent with `buy_price * amount` (within fee margin)
- FIFO position reset must catch crypto dust (value < €1), not just amount < 1e-8

### Prevention
- GUARD 5 now works (NameError fixed) — resets dca_buys to 0 only when dca_events is empty
- When dca_events exist but fewer than dca_buys (events lost), dca_buys is preserved
- sync_engine no longer touches dca_buys during re-derives
- FIFO uses value-based dust detection (€1 threshold) to prevent old history contamination

---

## #007 — Event-sourced DCA state: dca_buys desync structurally impossible (2026-03-27)

### Symptom
dca_buys kept desyncing from actual DCA events due to 6+ different code paths
independently mutating the counter: `_execute_fixed_dca`, `_execute_dynamic_dca`,
`_execute_pyramid_up`, `sync_engine`, `trade_store` validation, and `trailing_bot`
GUARD 5. Each had slightly different logic, and bugs in one weren't caught by others.

### Root Cause
`dca_buys` was a standalone mutable counter updated independently in 6+ places.
`dca_events` was a separate list that should have been the source of truth but wasn't
— many code paths updated `dca_buys` without touching `dca_events` (e.g., pyramid_up),
or used `dca_buys` as the authoritative value when events were the ground truth.

### Fix Applied — Event-sourced architecture (`core/dca_state.py`)

| File | Change |
|------|--------|
| `core/dca_state.py` | **NEW MODULE**: Event-sourced DCA state. `dca_events` is the SINGLE source of truth. `dca_buys = len(dca_events)` ALWAYS. Provides `record_dca()` (only way to add DCA), `sync_derived_fields()` (recompute from events), `validate_events()`, `detect_untracked_buys()`. |
| `modules/trading_dca.py` `_execute_fixed_dca` | Replaced 20 lines of inline state mutations with `dca_state.record_dca()` call |
| `modules/trading_dca.py` `_execute_dynamic_dca` | Same: replaced inline mutations with `record_dca()` |
| `modules/trading_dca.py` `_execute_pyramid_up` | Now uses `add_dca()` + `record_dca()` (was directly assigning invested_eur and NOT creating events) |
| `trailing_bot.py` GUARD 0+1+4+5 | Replaced 4 separate DCA guards with single `sync_derived_fields()` call |
| `bot/sync_engine.py` | Added `sync_derived_fields()` call after every cost basis re-derive |
| `modules/trade_store.py` | Replaced manual Rule 4 (dca_buys consistency) with `sync_derived_fields()` call + fallback |
| `tests/test_dca_state.py` | **35 tests** covering: bot DCA, manual detection, restart recovery, cascading prevention, inflated dca_buys |

### Key Design Rules
- `record_dca()` is the **ONLY** way to add a DCA — it atomically: creates event, appends to events list, recomputes dca_buys, updates last_dca_price, calculates dca_next_price
- `sync_derived_fields()` is the **ONLY** validation — recomputes all derived DCA fields from events
- `dca_buys` stored in trade dict for backward compat, but always recomputed from events
- `_execute_pyramid_up` now records events (was silently skipping event creation)

### Prevention
- dca_buys desync is **structurally impossible**: only `record_dca()` can increment it, and it always equals `len(dca_events)`
- All 4 integration points (trading_dca, trailing_bot, sync_engine, trade_store) use the same module
- 35 unit tests cover all 5 scenarios from the user's DCA redesign specification

---

## #007b — dca_buys re-inflation via trading_sync.py cache + sync_engine dca_max (2026-06-24)

### Symptom
After #007 was deployed, XRP dca_buys immediately jumped back to 17. NEAR/ALGO also 17.

### Root Cause (2 missed code paths in #007)

1. **`modules/trading_sync.py` L609**: When a trade disappears and reappears (common during sync),
   `removed_cache` stores the old dca_buys. On restore, `max(current, cached)` was used — this
   only increases, so the inflated value 17 was restored from cache every time.

2. **`bot/sync_engine.py` L281**: `dca_max = max(inferred_max, dca_buys)` used dca_buys to inflate
   dca_max. When dca_buys was already 17 (from cache), dca_max also became 17.

3. **Snapshot save** in trading_sync.py saved the inflated dca_buys to cache, perpetuating the cycle.

### Fix Applied

| File | Change |
|------|--------|
| `modules/trading_sync.py` L609 | Replaced `max()` restore with `setdefault()` — cache value only used if no existing value |
| `modules/trading_sync.py` post-restore | Added `sync_derived_fields()` call after cache restore — events override any cached dca_buys |
| `modules/trading_sync.py` snapshot save | Snapshot now uses `len(dca_events)` as source of truth instead of raw `dca_buys` |
| `bot/sync_engine.py` L281 | Removed `max(..., dca_buys)` — dca_max now comes from `inferred_max` or config `DCA_MAX_BUYS`, never inflated by dca_buys |
| `data/trade_log.json` | Corrected: XRP dca_buys=0, NEAR=3, ALGO=2 (matching event counts) |

### Prevention
- `sync_derived_fields()` now called after EVERY trade state restoration (trading_sync cache restore)
- Cache snapshot stores event-derived count, not raw field
- dca_max no longer uses dca_buys as input (prevents circular inflation)

---

## #008 — Codebase-wide bug analysis: 10 fixes across 7 files (2026-03-27)

### Symptom
Deep analysis revealed 14 bugs (4 critical, 5 high, 3 medium, 2 low). Key risks: chunked sell counting API failures as filled, MAX_DRAWDOWN_SL selling at a loss, missing uuid import crashing DCA headroom, partial DCA state corruption on exception.

### Root Cause
Multiple independent issues accumulated across bot evolution:
1. `orders_impl.py` chunked sell treated `None` API response as full fill → ghost tokens
2. `trailing_bot.py` MAX_DRAWDOWN_SL path had no profit guard → could sell at a loss
3. `trading_dca.py` missing `import uuid` → `_reserve_headroom()` crashed silently
4. `sync_engine.py` inferred `dca_max` from `buy_order_count` → inflated (repeat of #004)
5. `config.py` RUNTIME_STATE_KEYS missing 4 keys → leaked to config file on save
6. `trading_dca.py` record_dca/add_dca not wrapped in rollback → partial state on exception
7. `trading_dca.py` pyramid-up used `buy_price * amount` as invested_eur fallback → violated FIX #001
8. `trade_store.py` fallback dca_buys check missing `> dca_max` cap

### Fix Applied
1. **orders_impl.py** (L498-505): Chunked sell now treats non-dict API response as 0 fill
2. **trailing_bot.py** (L2357-2370): Added loss guard — blocks sell if `gross < invested`
3. **trading_dca.py** (L8): Added `import uuid`
4. **sync_engine.py** (L272-285): Replaced `buy_order_count` inference with `CONFIG['DCA_MAX_BUYS']`
5. **config.py**: Added `SYNC_ENABLED`, `SYNC_INTERVAL_SECONDS`, `MIN_SCORE_TO_BUY`, `OPERATOR_ID` to RUNTIME_STATE_KEYS
6. **trading_dca.py** (fixed + dynamic DCA): Wrapped `_ti_add_dca()` + `_ds_record()` in snapshot/rollback — rolls back `invested_eur`, `dca_buys`, `dca_events`, `buy_price`, `amount` on exception
7. **trading_dca.py** (pyramid-up): Changed to skip pyramid entirely if `invested_eur <= 0` instead of using `buy_price * amount` fallback
8. **trade_store.py**: Added `dca_buys > dca_max` cap in fallback validation path
9. **tests/test_dashboard_render.py**: Fixed `pnl_eur` from -5.0 to 5.0 (trailing badge requires profit)
10. **tests/test_grid_trading.py**: Fixed tolerance from 0.001 to 0.02 (accounts for price normalization)

### Prevention
- DCA state mutations now always have rollback on failure
- Cost basis rules (FIX #001) no longer violated by pyramid-up
- All 99 targeted tests pass after fixes

---

## #009 — FIFO cost basis: average-cost sell method inflated invested_eur (2026-04-06)

### Symptom
LINK-EUR `invested_eur` was €72.90 in the bot, but Bitvavo showed cost basis of €70.87 (2.86% off).
Other markets showed smaller but similar discrepancies (XRP 0.44%, NEAR 0.06%).

### Root Cause
`_compute_cost_basis_from_fills()` in `modules/cost_basis.py` used **average-cost** accounting
for sells, but the code comment called it "FIFO". With average cost, each sell deducts
`avg_cost × sold_amount` from `pos_cost`. This means old expensive lots and new cheap lots
are blended together — residual cost from historical buy/sell cycles bleeds into the current
position's cost basis.

For LINK-EUR specifically:
- The trade history showed 12.028 LINK after processing all fills (93 fills)
- The actual Bitvavo balance was 9.426 LINK
- The 2.602 LINK phantom excess came from the very first buys (never sold in the API)
- With average-cost scaling (`avg_cost × target_amount`), the expensive phantom lots
  inflated the cost: €7.73/unit × 9.426 = €72.90
- True cost of the 2 actual buys: 5.468 @ 7.5967 + 3.958 @ 7.4102 = €71.06

### Fix Applied

| File | Change |
|------|--------|
| `modules/cost_basis.py` | Replaced average-cost sell deduction with **true FIFO lot tracking** using a `deque` of `[amount, cost_per_unit, timestamp, order_id]` lots. Sells now consume the oldest lots first. |
| `modules/cost_basis.py` | Added `_fifo_remove(lots, qty)` helper for FIFO lot consumption. |
| `modules/cost_basis.py` | When `pos_amount > target_amount + tolerance` (phantom holdings from missing API sells), FIFO-remove the excess oldest lots before computing `invested_eur`. |
| `modules/cost_basis.py` | `earliest_timestamp` and `buy_order_ids` now derived from **remaining** lots (not first buy ever). This correctly reflects when the current position started. |
| `tests/test_cost_basis_sync.py` | Added `TestFifoExcessRemoval` class with 3 tests: phantom holdings, no-excess, and FIFO sell ordering. |

### Result after fix
| | Before (avg cost) | After (FIFO) | Bitvavo |
|---|---|---|---|
| LINK invested_eur | €72.90 | €71.06 | €70.87 |
| Diff vs Bitvavo | 2.86% | 0.27% | — |

### Prevention
- True FIFO lot tracking ensures sells always consume oldest lots
- Phantom excess lots are FIFO-removed to match actual balance
- `earliest_timestamp` reflects the actual current position, not historical first buy
- 70 tests pass including 3 new FIFO-specific tests

---

## #010 — Dashboard portfolio value excluded BTC/ETH and used stale data (2026-04-06)

### Symptom
Dashboard showed "Account Waarde" as €795.39 while Bitvavo's real portfolio value was €820.90 — a €25.51 gap.

### Root Cause
Two overlapping issues:
1. **HODL assets (BTC, ETH) excluded from trade cards**: The dashboard card builder skips `HODL_SYMBOLS = ['BTC', 'ETH']`, so `total_current` (sum of card values) misses these assets (~€10.34 combined).
2. **Stale `account_overview.json` used as override**: `calculate_portfolio_totals()` read `data/account_overview.json` which is only updated when the bot is running. When the bot is stopped, prices become stale (2.5 days old in this case → ~€19 price drift).
3. The dashboard never independently computed the real portfolio total from ALL Bitvavo balances × live prices.

### Fix Applied

| File | Change |
|------|--------|
| `tools/dashboard_flask/app.py` | `calculate_portfolio_totals()` now computes real total from ALL Bitvavo balances × live prices via `get_cached_balances()` + `get_live_price()`. Removed stale `account_overview.json` dependency. |
| `tools/dashboard_flask/services/portfolio_service.py` | `calculate_totals()` now computes real total from ALL balances × live prices via `price_service.get_all_balances()` + `price_service.get_price()`. Removed `account_overview.json` dependency. |
| `tools/dashboard_flask/services/price_service.py` | Added `get_all_balances()` method with API call + file fallback to `data/sync_raw_balances.json`. |

### Prevention
- Dashboard now independently calculates portfolio total — never depends on bot-generated files for the headline number.
- All Bitvavo balances (BTC, ETH, and any other asset) are included in the total, matching what Bitvavo itself shows.
- Graceful fallback: if API fails, reads cached `sync_raw_balances.json`; if that fails too, falls back to `total_current + eur_balance`.

---

## #011 — Grid trading zombie states + budget_cfg reads wrong config (2026-04-07)

### Symptom
Grid trading enabled in config but no orders appeared on Bitvavo. No grid-related log entries.

### Root Cause
1. **Zombie grid states**: Old BTC-EUR and ETH-EUR grids in `data/grid_states.json` had `status: "running"` but `config.enabled: false` and all orders `cancelled`. These counted as "active" grids (`active_count = 2 >= max_grids`), blocking new grid creation.
2. **budget_cfg hardcoded path**: `_auto_create_grids()` read `BUDGET_RESERVATION` directly from `config/bot_config.json` instead of the merged `self.bot_config`. Local overrides (grid_pct, trailing_pct) were invisible to the grid module.

### Fix Applied
1. Cleared `data/grid_states.json` (backup in `data/grid_states_backup_old.json`) to allow fresh grid creation.
2. Changed `_auto_create_grids()` in `modules/grid_trading.py` to read `self.bot_config.get('BUDGET_RESERVATION', {})` instead of raw file read.
3. Added `max_grids: 1` to GRID_TRADING config (only BTC-EUR per roadmap €1000 phase).

### Prevention
- Grid module now uses merged config (respects local overrides).
- Explicit `max_grids` in config prevents default-value surprises.

---

## #012 — Grid cancelOrder fails without operatorId → orphaned orders (2026-04-07)

### Symptom
User saw 11 open orders on Bitvavo instead of expected 9. Two orphaned BTC-EUR buy orders (€31.70 each at 55619 and 57998) remained on the exchange after a vol-adaptive rebalance from 5→18 grids.

### Root Cause
`GridManager._cancel_order()` called `self.bitvavo.cancelOrder(market, order_id)` without passing the `operatorId` parameter. The Bitvavo API returns HTTP 400 `"operatorId parameter is required"` when this is missing. During the vol-adaptive rebalance, the initial 2 grid orders could not be cancelled, and the code silently continued placing 9 new orders — leaving 11 total.

The `trailing_bot.py` monolith already passed `operatorId` correctly (`bitvavo.cancelOrder(market, orderId, operatorId=str(OPERATOR_ID))`), but the extracted grid module was missing it.

### Fix Applied

| File | Change |
|------|--------|
| `modules/grid_trading.py` `_cancel_order()` | Added `operator_id = self.bot_config.get('OPERATOR_ID')` and passed it as third arg to `cancelOrder()`. Also added error logging for API error responses. |
| Bitvavo exchange | Manually cancelled the 2 orphaned orders (ids `...676e96` and `...6770a3`) via API with operatorId. |

### Prevention
- `_cancel_order()` now always passes `operatorId` from config, matching `trailing_bot.py` convention.
- Error responses from cancel are now logged explicitly instead of silently returning False.

---

## #013 — Grid proportional budget: sell levels below minimum → budget wasted (2026-04-07)

### Symptom
With 0.00041638 BTC (~€24.57) from earlier grid fills, the proportional budget split divided
sell budget equally across all sell levels (e.g. 9 levels × €2.73 each). Bitvavo requires minimum
€5 per order, so ALL sell levels were skipped by the `amount_eur < 5.0` filter, wasting the entire
sell budget and deploying only ~€134 instead of ~€158.

### Root Cause
Proportional allocation divided `sell_budget_actual` by `levels_per_side` (total sell levels),
not by the number of sell levels that can actually meet the minimum order. When per-level amount
falls below €5, every sell level gets filtered out.

### Fix Applied
- `core/avellaneda_stoikov.py`: Calculate `affordable_sells = min(int(sell_budget_actual / 5.0), levels_per_side)`.
  Concentrate sell budget into `affordable_sells` levels closest to mid-price. Track `sells_placed` counter in
  the generation loop to stop generating sell levels beyond what's affordable.
- `modules/grid_trading.py` (static fallback): Same logic — `affordable_sells` count, `sells_placed` counter,
  skip sell levels once the affordable count is reached.

### Prevention
- Both A-S and static grid paths now calculate the maximum number of sell levels that meet the €5 minimum
  before allocating budget, preventing budget waste from below-minimum sell orders.

---

## #014 — invested_eur not updated after amount change in trading_sync + BTC grid ghost trade (2026-04-08)

### Symptom
1. **UNI-EUR**: Dashboard showed invested=€49.04 but actual cost basis was €91.22. A second buy
   (DCA) was executed on Bitvavo, the amount was updated but invested_eur was NOT recalculated.
2. **BTC-EUR**: Dashboard showed a ghost trade with invested=€0.03. This was BTC dust from the
   grid trading module being picked up as a regular trade by the sync engine.

### Root Cause

1. **`modules/trading_sync.py`** (startup sync): When live amount differs from trade_log amount,
   `entry["amount"] = live_amount` was updated but `invested_eur` was NOT recalculated via
   `derive_cost_basis()`. The amount-only update meant that by the time `bot/sync_engine.py`
   ran its 4-check reconciliation, Check 1 (amount changed) no longer triggered because the
   amount already matched. Check 4 (divergence >2%) should have caught it eventually but
   the bug persisted from the startup sync gap.

2. **`bot/sync_engine.py`**: The balance iteration loop excluded HODL markets but NOT grid-managed
   markets. BTC balance (from active grid orders) was detected as a new position and created
   as a dust trade entry.

### Fix Applied

| File | Change |
|------|--------|
| `modules/trading_sync.py` | When amount changes >0.1%, now calls `derive_cost_basis()` to recalculate `buy_price`, `invested_eur`, `total_invested_eur` from Bitvavo order history |
| `bot/sync_engine.py` | Added grid market exclusion: reads `data/grid_states.json` for running/paused/initialized grids, skips those markets in the balance sync loop |
| `data/trade_log.json` | UNI-EUR: `invested_eur` corrected 49.04 → 91.22 via `derive_cost_basis()` |
| `tests/test_sync_trailing_dca.py` | Fixed pre-existing test failure: added missing `fills_used` field to `_FakeCostBasis` dataclass |

### Prevention
- `trading_sync.py` now derives cost basis on ANY significant amount change, not just updating amount
- Grid-managed markets are excluded from sync_engine balance detection (same pattern as HODL exclusion)
- **Rule**: When updating `amount`, ALWAYS recalculate `invested_eur` via `derive_cost_basis()` — NEVER update amount alone

---

## #015 — highest_price lost on trade archival, blocking trailing analysis (2026-04-08)

### Symptom
All 354 archived trailing_tp trades have `highest_price=0` or missing. Without peak price data, it's impossible to backtest trailing stop configurations (activation %, trailing %, stepped levels) because we don't know how high each trade went before exit.

### Root Cause
`_finalize_close_trade()` in `trailing_bot.py` computed `max_profit_pct` from the open trade's `highest_price`, but never carried the raw `highest_price` value into the archived `closed_entry`. The metadata carry-forward loop only included `score`, `rsi_at_entry`, `volume_24h_eur`, `volatility_at_entry`, `opened_regime`, `macd_at_entry`, `sma_short_at_entry`, `sma_long_at_entry`, `dca_buys`, `tp_levels_done` — no trailing-related fields.

### Fix Applied

| File | Change |
|------|--------|
| `trailing_bot.py` `_finalize_close_trade()` | Added `highest_price`, `trailing_activation_pct`, `base_trailing_pct` to the metadata carry-forward loop. These fields are now preserved in archived trades. |

### Prevention
- New trades closed after this fix will have `highest_price` in their archive record
- After 4-8 weeks of data accumulation, trailing settings can be properly backtested using real peak data
- **Rule**: When adding new per-trade tracking fields, always ensure they are included in `_finalize_close_trade()`'s metadata carry-forward list

---

## #016 — GUARD 6 NameError + trailing actief template + DCA reconcile SSOT (2026-04-09)

### Symptom
Three interrelated bugs:
1. **GUARD 6 NameError**: `name 'dca_events' is not defined` crash every ~60min in `validate_and_repair_trades()` for ALL open trades — invested_eur consistency check was silently failing.
2. **"Trailing actief" in loss**: Dashboard showed "TRAILING ACTIEF" badge for trades at -3% loss (e.g. UNI-EUR at -3.02%). Misleading — trailing should only show when trade is in profit.
3. **Missing DCA events**: UNI-EUR had 3 DCAs on Bitvavo but bot only tracked 2 — DCA #1 (2026-04-08 16:59, €41.94 @ €2.7037) was lost during a bot restart.

### Root Cause
1. **GUARD 6**: Line 888 of `trailing_bot.py` used bare variable name `dca_events` instead of `trade.get('dca_events', [])`. Python scope: the name was never defined in the function scope.
2. **Template bypass**: `portfolio.html` checked `card.trailing_activated` at 5 separate locations (lines 250, 304, 512, 1091, 1148) — this is a permanent boolean flag that stays True once set. The Python status computation at `app.py:907` correctly checked `live_price >= buy_price`, but the Jinja2 template bypassed it entirely.
3. **DCA loss**: Bot was restarted between DCA #1 and DCA #2 buys. DCA #1 was executed, but its event was never persisted because the bot wasn't running when it happened (executed by a previous instance that was killed).

### Fix Applied

| File | Change |
|------|--------|
| `trailing_bot.py` line 882-885 | **GUARD 6 NameError**: Replaced bare `dca_events` with `_guard6_events = trade.get('dca_events', []) or []` |
| `portfolio.html` 5 locations | **Trailing actief in loss**: Added `card.pnl >= 0` check to all 5 trailing_activated conditionals. Added "⏸️ Trailing wacht (verlies)" state for trades that have trailing activated but are in loss. |
| `core/dca_reconcile.py` (NEW) | **Bitvavo SSOT reconcile engine**: Fetches all filled buy trades from Bitvavo, groups by orderId, compares with bot's dca_events, recovers missing events (source="reconcile"), corrects amount/invested_eur/buy_price, enriches existing events with order_id. |
| `trailing_bot.py` bot_loop + startup | Integrated reconcile: runs at startup and every 5 minutes in bot loop. Auto-saves if any repairs made. |
| `tests/test_dca_reconcile.py` (NEW) | 19 tests covering: fill grouping, no-fills, matched events, missing DCA recovery, partial recovery, fuzzy timestamp matching, financial corrections, dry-run mode, error handling, order_id enrichment, batch processing, market exclusion. |

### Prevention
- **SSOT**: Bitvavo order history is now the single source of truth. Every 5 minutes, the reconcile engine checks all open trades and recovers any missing DCA events automatically. Lost events during restarts are now self-healing.
- **Template safety**: All trailing_activated checks now require positive P&L. Added visual "wacht" state for clarity.
- **Variable scoping**: GUARD 6 now uses explicit `_guard6_` prefix to avoid variable name collisions in the large validate function.

---

## #017 — Grid vol-adaptive inflates num_grids 5→20, dead config keys (2026-04-09)

### Symptom
BTC-EUR grid had 11 open orders on Bitvavo instead of ~5 (user configured `num_grids: 5`). `investment_per_grid` and `max_total_investment` in config were hardcoded at 150 despite BUDGET_RESERVATION dynamic mode handling it.

### Root Cause
1. **Volatility-adaptive runaway**: `get_volatility_adjusted_num_grids()` in `core/avellaneda_stoikov.py` has `max_grids=20` default. With BTC's low hourly volatility (σ≈0.0013), `vol_ratio = 0.26`, `adjusted = 5/0.26 ≈ 19` → capped at 20. The calling code in `auto_manage()` passed `config.num_grids` (the already-mutated state value) instead of the original user config.
2. **Dead config keys**: `investment_per_grid` and `max_total_investment` in GRID_TRADING are overridden when `BUDGET_RESERVATION.enabled=true, mode="dynamic"` — the actual investment is `total_account_value × grid_pct / max_grids`. Hardcoded 150 was misleading.

### Fix Applied
1. `modules/grid_trading.py` Step 3b: Read `user_num_grids` from GRID_TRADING config (original value, not mutated state). Pass `max_grids=min(20, user_num_grids * 2)` to cap volatility scaling (5→max 10, not 5→20).
2. Removed `investment_per_grid` and `max_total_investment` from `bot_config_local.json` — BUDGET_RESERVATION dynamic mode provides the actual values.

### Prevention
- Volatility-adaptive now capped at 2× user-configured num_grids. Uses original config as base, not the mutated grid state.
- Dead config keys removed to avoid confusion about what actually controls investment sizing.

---

## #018 — Dashboard shows all trades as "Externe Positie" after OneDrive revert (2026-04-09)

### Symptom
All 5 open trades (UNI, XRP, LINK, LTC, NEAR) periodically show as "EXTERN POSITIE" on the dashboard with +€0.00 P&L. Happens frequently and resolves after a few minutes when the bot saves again.

### Root Cause
Two-layer failure when OneDrive reverts `trade_log.json` to an older/empty version:

1. **`load_freshest()` preferred stale local mirror**: The local mirror in `%LOCALAPPDATA%` had a newer `_save_ts` but only contained BTC-EUR (from a partial save during a previous restart). Since it was "newer", `load_freshest` picked it over the OneDrive copy that had all 5 real trades. Result: `open_trades` only contained BTC-EUR (which is skipped as HODL), so all 5 trailing trades fell through to "external balance" detection.

2. **Dashboard `load_trades()` returned empty data**: When `data.get('open')` was falsy (empty dict), `_last_good_trades` was correctly NOT updated, but the empty data was still cached and returned. The fallback to `_last_good_trades` only triggered on exceptions, not on "valid but empty" responses.

### Fix Applied
| File | Change |
|------|--------|
| `core/local_state.py` | `load_freshest()` now checks data quality: if local is newer but has 0 open trades while OneDrive has real trades (and delta < 600s), uses OneDrive instead. Prevents stale mirror from winning. |
| `tools/dashboard_flask/app.py` | `load_trades()` fallback is now active: when trade_log returns 0 open trades but `_last_good_trades` has data, returns the last-known-good snapshot immediately instead of caching the empty data. |
| `tests/test_local_state.py` | 6 new tests for `load_freshest` data quality scenarios. |

### Prevention
- Dashboard never shows external positions when it previously had real trade data (last-known-good fallback).
- `load_freshest` uses data quality heuristic in addition to timestamps — empty local mirror can't override OneDrive with real trades.

---

## #019 — Dashboard deposit total wrong + stale grid orders (2026-04-09)

### Symptom
Dashboard "totaal gestort" showed €230 instead of €1620.01. Two conflicting deposit files existed:
- `config/deposits.json` (correct, API-synced, 18 deposits, €1620.01)
- `data/deposits.json` (wrong, 2 manual entries, €230)

Additionally, 2 stale BTC-EUR buy orders at €57,141 and €59,586 (from pre-FIX #017) were still live on Bitvavo but not tracked in `grid_states.json`.

### Root Cause
1. `data_service.py` loaded deposits from `data/deposits.json` (old manual file) instead of `config/deposits.json` (API-synced).
2. `app.py` performance stats (line 2681) also read from `data/deposits.json`.
3. `get_total_deposited()` in data_service used `deposits.get('entries', [])` for dict format — should be `deposits.get('deposits', [])`.
4. Old grid orders were orphaned when FIX #017 switched to new grid_states.json — the old orders were never cancelled.

### Fix Applied

| File | Change |
|------|--------|
| `tools/dashboard_flask/services/data_service.py` `load_deposits()` | Changed path from `data/deposits.json` to `config/deposits.json`. Changed default from `[]` to `{'total_deposited_eur': 0, 'deposits': []}`. Updated return type hint to `Dict`. |
| `tools/dashboard_flask/services/data_service.py` `get_total_deposited()` | Fixed dict branch to use `data.get('deposits', [])` instead of `data.get('entries', [])`. |
| `tools/dashboard_flask/app.py` line 2681 | Changed `PROJECT_ROOT / 'data' / 'deposits.json'` to `PROJECT_ROOT / 'config' / 'deposits.json'`. |
| `data/deposits.json` | Deleted (old manual file). |
| Bitvavo exchange | Cancelled 2 stale BTC-EUR buy orders at €57,141 and €59,586 via API. |
| `config/deposits.json` | Fresh sync from Bitvavo API: 18 deposits, €1620.01 (including new €150 deposit). |

### Prevention
- Single source of truth for deposits: `config/deposits.json` (API-synced). No manual `data/deposits.json`.
- Both `data_service.py` and `app.py` now read from the same path.

---

## #020 — Orphaned partial-TP positions adopted with wrong invested_eur (2026-04-09)

### Symptom
SOL-EUR appeared in open trades with `invested_eur = €12.02` instead of the real cost basis (~€77 × 0.17 = ~€13.20). This is a recurring pattern: after a `partial_tp` sell, the remaining position loses its trade_log entry (restart, OneDrive revert, etc.), and when the sync engine re-adopts it, `derive_cost_basis` finds 0 orders (old fills purged from Bitvavo API), so it falls back to `amount × current_ticker_price` — producing a tiny `invested_eur` unrelated to the real cost.

### Root Cause
Three code paths all had the same flaw — **no fallback to the trade archive** when `derive_cost_basis` fails:

1. `modules/sync_validator.py` `auto_add_missing_positions()`: Falls back to `amount × current_price` when derive fails.
2. `bot/sync_engine.py` new-trade adoption: No invested_eur set at all when derive fails (later "corrected" by `get_true_invested_eur` to `buy_price × amount` where `buy_price` = current ticker).
3. The trade archive **already contains** the partial_tp record with the correct `buy_price`, but nobody checked it.

### Fix Applied

| File | Change |
|------|--------|
| `modules/trade_archive.py` | Added `recover_cost_from_archive(market, amount)` — looks up the most recent partial_tp entry (or last closed trade) in the archive and recovers `buy_price`, `invested_eur`, etc. |
| `modules/sync_validator.py` `auto_add_missing_positions()` | Added archive recovery fallback between FIFO/buy-trade fallbacks and the final current-price fallback. If derive_cost_basis AND FIFO both fail, checks the archive before falling back to ticker price. |
| `bot/sync_engine.py` new-trade branch | Added archive recovery when `derive_cost_basis` returns None or throws — before the trade is added with no `invested_eur`. |
| `tests/test_archive_recovery.py` | 6 new tests: partial_tp recovery, last-trade fallback, unknown market → None, key completeness, empty archive, zero buy_price. |

### Prevention
- Orphaned partial-TP positions now get their original buy_price from the archive instead of the current ticker price.
- The fix is purely additive (new fallback layer) — existing derive_cost_basis logic is unchanged and still takes priority when it works.
- Archive data is persistent (never deleted) and backed up to `%LOCALAPPDATA%`, so it survives OneDrive reverts.

---

## #021 — Grid orders never placed: corrupt state + missing min base amount check (2026-04-09)

### Symptom
Grid trading enabled in config but no new orders placed on Bitvavo. BTC-EUR grid detected as "zombie" and paused. ETH-EUR grid had fake `test-order-123` order IDs causing 97.92% phantom stop-loss.

### Root Cause
1. **Corrupt grid_states.json**: BTC-EUR had `auto_created: false`, 8 levels with amounts ~0.00007 BTC (below Bitvavo min 0.0001 BTC), €50 investment. ETH-EUR had `order_id: "test-order-123"` — test data that leaked into production state. Origin: likely dashboard/manual creation with wrong params or state file corruption.
2. **Wrong Bitvavo API field name in `get_min_order_size()`**: `bot/api.py` looked for `minOrderSize`/`minOrderAmount` but Bitvavo API returns `minOrderInBaseAsset`. Result: `get_min_order_size()` always returned `0.0`, so min-size validation in `_place_limit_order()` was **never effective**. Orders with tiny amounts passed all checks and were rejected by Bitvavo API directly.
3. **No min BASE amount validation in level creation**: `_calculate_grid_levels()` only checked EUR value ≥ €5.50 per level, not Bitvavo's minimum base order size.
4. **A-S dynamic spacing path bypassed min base check**: The Avellaneda-Stoikov path created levels and returned early before the static path's min base validation. Levels with amounts below minimum were created unchecked.
5. **`load_freshest` restored old corrupt state from LocalAppData**: After clearing `data/grid_states.json`, `mirror_to_local`'s copy at `%LOCALAPPDATA%/BotConfig/state/grid_states.json` still had the corrupt state with higher `_save_ts`, so it was loaded as "freshest". Both files needed to be deleted.
6. **No recovery for never-started grids**: `is_broken` cleanup only matched `status in ('stopped', 'error')` — grids stuck in `initialized` or `placing_orders` were never cleaned up.
7. **`_cancel_order` passed operatorId positionally**: Caused cancel failures for corrupt ETH-EUR grid.
8. **Test fixture pollution**: Grid tests' `_save_states()` called `mirror_to_local()` writing to real `%LOCALAPPDATA%` path, contaminating production state with test data.

### Fix Applied

| File | Change |
|------|--------|
| `data/grid_states.json` + `%LOCALAPPDATA%` copy | Both deleted (backup in `grid_states_backup_corrupt_20260409.json`). Auto_manage creates fresh grids with correct dynamic budget params. |
| `bot/api.py` `get_min_order_size()` | Added `minOrderInBaseAsset` as primary field lookup (Bitvavo's actual field name). Kept legacy field names as fallback. |
| `bot/api.py` `get_amount_precision()`, `get_amount_step()` | Also fixed to check `minOrderInBaseAsset` before legacy `minOrderAmount`. |
| `utils.py` `get_min_order_size()` | Same: added `minOrderInBaseAsset` as primary lookup. |
| `modules/grid_trading.py` `_normalize_amount()` | Fixed fallback field from `minOrderAmount` to `minOrderInBaseAsset`. |
| `modules/grid_trading.py` `_calculate_grid_levels()` | Added min BASE amount check in BOTH A-S dynamic and static paths. Reduces `num_grids` until possible, returns empty if impossible. |
| `modules/grid_trading.py` `_auto_create_grids()` | Added per-candidate min base amount check. |
| `modules/grid_trading.py` `auto_manage()` Step 4 | Extended `is_broken` to also match `initialized`/`placing_orders` + 5-min grace. |
| `modules/grid_trading.py` `_cancel_order()` | Changed operatorId to keyword argument. |
| `tests/test_grid_trading.py` | Patched `mirror_to_local` in fixture to prevent test writes to production `%LOCALAPPDATA%`. |

### Prevention
- **Field name fix is the critical fix**: `get_min_order_size()` now correctly reads `minOrderInBaseAsset` from Bitvavo API, so all min-size checks actually work.
- Min base amount validation in both A-S and static paths prevents creating levels below minimum.
- Broken grid cleanup now catches all non-running states with 0 trades after 5-min grace.
- Test fixture mocks `mirror_to_local` to prevent test data contaminating production LocalAppData state.
- Both `data/` and `%LOCALAPPDATA%` copies must be cleared when resetting state (load_freshest picks the newer).
- This is the 3rd grid state corruption fix (see #011, #012). The test pollution was likely the origin of the corrupt state.

---

## #022 — Sell orders leave dust: place_sell uses min(trade, balance) instead of full balance (2026-04-09)

### Symptom
NEAR-EUR trailing TP sold 46.84 tokens but left 3.88 tokens (~€4.50) behind. Sync engine re-adopted this as a new trade, then auto_free_slot sold it, but the cycle repeated. Dashboard showed ghost NEAR positions.

### Root Cause
`place_sell()` in `bot/orders_impl.py` line 451 used `sell_amount = min(amount_base, available)`. When the Bitvavo balance (`available`) is larger than the trade-tracked amount (`amount_base`) — due to rounding, DCA differences, or partial fill accounting — only the trade amount is sold, leaving tokens behind.

### Fix Applied
| File | Change |
|------|--------|
| `bot/orders_impl.py` | Added `sell_all: bool = False` parameter to `place_sell()`. When `sell_all=True`, uses `max(amount_base, available)` to sell the full Bitvavo balance |
| `trailing_bot.py` | Pass-through `sell_all` in wrapper. All full-exit paths (trailing TP, max age, drawdown stop) now pass `sell_all=True` |
| `modules/trading_liquidation.py` | Auto-free-slot calls `place_sell(market, amount, sell_all=True)` |

Partial TP sells correctly keep `sell_all=False` (only sell a portion).

### Prevention
- Full exits always use `sell_all=True` — no dust left behind
- Partial sells remain conservative with `min()` to avoid over-selling

---

## #023 — SOL/NEAR invested_eur not reflecting sells and manual buys (2026-04-09)

### Symptom
SOL-EUR showed invested_eur=€24.06 but Bitvavo order history: 3 buys (€36.08) minus 2 sells (€14.10) = net €21.90. The 2 sells were not deducted from invested_eur. NEAR-EUR showed invested_eur=€4.50 after user manually bought €5.50 more — amount synced (8.60 tokens) but cost stayed at €4.50.

### Root Cause
The sync engine's immutability guard (`invested_sync.py`) only updates invested_eur when it's 0 or missing. Once set, it's never overwritten by normal sync cycles. This is correct for normal operation (prevents partial TP corruption) but means manual buys and untracked sells are never reconciled into invested_eur.

### Fix Applied
| File | Change |
|------|--------|
| `data/trade_log.json` | SOL-EUR: invested_eur 24.06→21.90, total_invested_eur 24.06→21.90 (FIFO-derived) |
| `data/trade_log.json` | NEAR-EUR: invested_eur 4.50→10.00, total_invested_eur 4.50→10.00, amount 4.72→8.60 (FIFO-derived) |

Values derived via `modules.cost_basis.derive_cost_basis()` using full FIFO lot tracking from Bitvavo order history.

### Prevention
- When users report cost basis discrepancies, run `derive_cost_basis()` to get the true FIFO value and compare with stored invested_eur
- The sync engine correctly protects invested_eur from overwrites; manual corrections need explicit FIFO verification

---

## #024 — Dust adopt→fake-sell→re-adopt infinite loop after chunked sells (2026-04-10)

### Symptom
After trailing TP sold LINK-EUR in chunks (€99.74 + €37.50), ~0.28 LINK (~€2.10) remained as dust. This dust was below Bitvavo's €5 minimum order size, making it unsellable. The sync engine adopted it as a new trade → auto_free_slot tried to sell → got "below_minimum_order_size" error but treated error dict as truthy (success) → removed trade without selling → sync re-adopted → loop repeated 26 times creating 26 fake "auto_free_slot" closed trades.

### Root Cause
Three bugs combined:
1. **auto_free_slot truthy check**: `if ctx.place_sell(...)` — error dicts like `{"error": "below_minimum_order_size"}` are truthy in Python, so failed sells were treated as successes
2. **trading_sync.py no EUR threshold**: Unlike sync_engine.py (€5 threshold), trading_sync adopted ANY non-zero balance as a new trade
3. **Chunked sell leaves dust**: After chunks, remaining 0.28 LINK (€2.10) was below €5 min order and couldn't be sold or cleaned up

### Fix Applied
| File | Change |
|------|--------|
| `modules/trading_liquidation.py` | auto_free_slot: `sell_resp` checked for `error`/`errorCode` keys instead of truthy test |
| `modules/trading_sync.py` | Added €5 EUR dust threshold (SYNC_DUST_VALUE_EUR) before adopting new positions |
| `bot/orders_impl.py` | Chunked sell: attempts to sell remaining after all chunks; logs "unsellable dust" if below min order |
| `bot/orders_impl.py` | DUST_THRESHOLD_EUR default raised from €1 to €5 (matching Bitvavo's min order) |
| `trailing_bot.py` | Added `_cleanup_market_dust(m)` after trailing_tp, max_age, and drawdown exits |
| `data/trade_log.json` | Removed 26 fake LINK-EUR auto_free_slot closed trade entries |

### Prevention
- Sell response is now properly validated (not just truthy check)
- Sync won't adopt positions below €5 (Bitvavo's min order size)
- Post-exit dust sweep attempts cleanup immediately
- Chunked sells attempt to sell remaining dust; log clearly when below minimum

---

## #028 — Dashboard portfolio page crash: mixed timestamp types in sort (2026-04-10)

### Symptom
Dashboard `/portfolio` page threw `TypeError: '<' not supported between instances of 'float' and 'str'` when sorting closed trades.

### Root Cause
Some trades in the archive have `timestamp` as a string (e.g. from manual edits or older format), while most have it as a float. Python's `sorted()` can't compare `float < str`.

### Fix
Wrapped `x.get('timestamp', 0)` in `float(... or 0)` in all 3 sort locations:
- `tools/dashboard_flask/blueprints/main/routes.py` line 234
- `tools/dashboard_flask/app.py` line 1982
- `tools/dashboard_flask/app.py` line 3634

### Prevention
Always coerce archive field values to the expected type before comparison. Trade archive can contain mixed types from different code paths.

---

## #029 — Dashboard portfolio crash: datetime string timestamps can't be float-converted (2026-04-10)

### Symptom
Dashboard `/portfolio` page threw `ValueError: could not convert string to float: '2026-04-10 20:12:20'` when sorting closed trades.

### Root Cause
Fix #028 wrapped timestamps in `float()`, but some archive entries have `timestamp` as a datetime string (`'%Y-%m-%d %H:%M:%S'` format) which `float()` can't parse. Need a multi-format parser.

### Fix
Added `_ts_to_float(v)` helper in both `routes.py` and `app.py` that tries:
1. `float(v)` — handles numeric and numeric-string timestamps
2. `datetime.strptime(v, '%Y-%m-%d %H:%M:%S').timestamp()` — handles datetime strings
3. `datetime.fromisoformat(v).timestamp()` — handles ISO format strings
4. Falls back to `0.0` on any error

Applied in all 3 sort locations (same as #028).

### Files Changed
| File | Change |
|------|--------|
| `tools/dashboard_flask/blueprints/main/routes.py` | Added `_ts_to_float` helper + `datetime` import, used in sort |
| `tools/dashboard_flask/app.py` | Added `_ts_to_float` helper, used in 7 locations (sort, comparison, alerts, performance, reports) |
| `tools/dashboard_flask/services/portfolio_service.py` | Added `_ts_to_float` helper, used in PnL calculation |

### Prevention
Use `_ts_to_float()` for all timestamp sorting/comparison in the dashboard. Never assume timestamps are numeric — the trade archive contains mixed formats (unix epoch floats, datetime strings like `'2026-04-10 20:12:20'`, ISO format, None).

---

## #027 — Incomplete sells leaving dust: get_amount_step used minOrder instead of quantityDecimals (2026-04-10)

### Symptom
After every sell, residual balances ("dust") remained on Bitvavo. Examples:
- TAO-EUR: `normalize_amount(0.00913)` → **0.0** (sell NOTHING, entire balance becomes dust)
- UNI-EUR: `normalize_amount(62.95)` → **62.70** (0.25 UNI / ~€3.50 lost as dust)
- XRP-EUR: `normalize_amount(46.69)` → **43.12** (3.56 XRP / ~€8.70 lost as dust)
- XLM-EUR: `normalize_amount(224.31)` → **197.27** (27.04 XLM / ~€4.80 lost as dust)

This was the ROOT CAUSE behind all dust-related issues (#022–#026). Previous fixes only cleaned up
dust after the fact; this fix prevents dust from being created.

### Root Cause
`get_amount_step()` in `bot/api.py` returned `minOrderInBaseAsset` (Bitvavo's minimum order SIZE)
and used it as the amount STEP for normalization. `normalize_amount()` computed:
`floor(amount / step) * step` — treating the minimum order size as a divisor.

Example: TAO-EUR has `minOrderInBaseAsset = 0.02144965` (min order = 0.0214 TAO).
`floor(0.00913 / 0.02144965) = 0` → normalized to **0.0** → sell NOTHING.

UNI-EUR has `minOrderInBaseAsset = 1.84417788`:
`floor(62.95 / 1.84417788) = 34` → `34 × 1.844 = 62.70` → **0.25 UNI lost as dust**.

The correct step is `10^(-quantityDecimals)` — e.g., for TAO (8 decimals) the step is 0.00000001,
not 0.02144965. Every single market was affected to varying degrees.

### Fix Applied

| File | Change |
|------|--------|
| `bot/api.py` | `get_amount_step()`: Returns `10^(-quantityDecimals)` instead of `minOrderInBaseAsset`. Now uses the actual decimal precision as the step size. |
| `bot/api.py` | `get_amount_precision()`: Checks `quantityDecimals` field first before falling back to counting decimals in `minOrderInBaseAsset`. |
| `bot/orders_impl.py` | `place_sell()` sell_all path: Uses direct `Decimal.quantize()` to `quantityDecimals` precision with `ROUND_DOWN` instead of `normalize_amount()`. Ensures full balance is sold with only decimal truncation. |
| `bot/orders_impl.py` | Post-sell sweep: After `sell_all` market sell, checks remaining balance and attempts to sell any remainder ≥ min order size. |
| `tests/test_bot_api.py` | 4 new tests in `TestAmountStepPrecision`: verifies step uses quantityDecimals for 8-dec and 6-dec markets, full-balance normalization, precision lookup. |

### Validation
End-to-end test with real Bitvavo API market data for 7 positions:
ALL markets normalize to exact balance with **ZERO DUST** (TAO, ALGO, UNI, XRP, XLM, LINK, LTC).

### Prevention
- `get_amount_step()` now uses `quantityDecimals` (the correct Bitvavo field for precision).
- `sell_all=True` bypasses `normalize_amount()` entirely, using direct Decimal truncation.
- Post-sell sweep catches any remaining balance after the primary sell.
- 4 dedicated regression tests verify step size calculation and full-balance normalization.

**CRITICAL RULE**: `minOrderInBaseAsset` is the MINIMUM ORDER SIZE, NOT an amount step/increment.
The amount step is always `10^(-quantityDecimals)`. Never confuse these two API fields.

---

## Template for new entries

```
## #NNN — Short description (YYYY-MM-DD)

### Symptom
What the user saw.

### Root Cause
Why it happened.

### Fix Applied
What was changed and where.

### Prevention
How we prevent recurrence.
```

---

## #026 — Dust trades never closed: wrong threshold + no auto-removal (2026-04-10)

### Symptom
TAO-EUR (€2.10) and ALGO-EUR (€0.05) remained as open trades indefinitely after partial sells.
They could not be sold (below Bitvavo €5 minimum) but still counted as open trades, blocking
new entries. Bot log showed `HARD STOP: already at max trades (5+0+0/5)` even though only 4
real trades existed. The `[DUST_SKIP]` log showed `drempel €0` — threshold was ~0 instead of 5.

### Root Cause
Two issues:
1. **Config `DUST_TRADE_THRESHOLD_EUR=0.5`** in `config/bot_config.json`. With 0.5, TAO (€2.10)
   was above threshold and NOT filtered as dust. Only ALGO (€0.05) was skipped. The `:.0f` format
   rounded 0.5 to "€0" in logs, making it look like zero.
2. **No auto-cleanup of dust trades**. Even when dust was correctly identified (ALGO), it was only
   skipped in the trailing management loop — the trade record remained in `open_trades` forever.
   `_cleanup_market_dust` skips markets that ARE in open_trades (`if market in S.open_trades: return`),
   so it couldn't help either.

### Fix Applied

| File | Change |
|------|--------|
| `%LOCALAPPDATA%/BotConfig/bot_config_local.json` | Set `DUST_TRADE_THRESHOLD_EUR=5.0` and `DUST_THRESHOLD_EUR=5.0` in local config (overrides base config's 0.5) |
| `bot/shared.py` | Changed default `DUST_TRADE_THRESHOLD_EUR` from 1.0 to 5.0 |
| `trailing_bot.py` | Added auto-cleanup: before per-trade loop, scan all open trades, close any with value < threshold via `_finalize_close_trade()` with `reason='dust_cleanup'` |
| `tests/test_dust_cleanup.py` | New test file: 7 tests for count_active_open_trades filtering, count_dust_trades, shared state default |

### Prevention
- Dust positions are now automatically closed (archived) each main loop cycle — they don't accumulate.
- Config threshold is 5.0 (matching Bitvavo minimum), set in local config that OneDrive can't revert.
- Shared state default is 5.0 so even without config, dust filtering uses the Bitvavo minimum.

---

## #025 — Dust positions counted as open trades, blocking new entries (2026-04-10)

### Symptom
Dust positions (< €5 EUR value) left after partial sells were treated as real open trades. This caused:
- Phantom "capacity full" when only a few real trades existed
- Main loop managing trailing/DCA on unsellable dust (wasteful)
- Correlation shield including dust in calculations
- Liquidation capacity checks blocked by dust

### Root Cause
Multiple places used `len(open_trades)` to count trades without filtering out dust positions below the €5 Bitvavo minimum order threshold.

### Fix Applied
1. **`trailing_bot.py` main loop** (L2260): Skip dust trades — compute EUR value, skip if < `DUST_TRADE_THRESHOLD_EUR`
2. **`trailing_bot.py` correlation shield** (L3042): Use `count_active_open_trades()` instead of `len(open_trades)`, skip dust in market iteration
3. **`modules/trading_liquidation.py`** (L166): Count only non-dust trades for capacity check
4. **`modules/trading_sync.py`** (L271): Count only non-dust trades for adoption room calculation

### Prevention
All capacity/counting checks now use value-based filtering against `DUST_TRADE_THRESHOLD_EUR` (default €5). Entry checks already used `count_active_open_trades()` which was correct — now all other paths are consistent.

---

## #030 — Grid market BTC-EUR adopted as trailing trade by trading_sync.py (2026-04-12)

### Symptom
BTC-EUR (a grid-managed market) appeared in `open_trades` in `data/trade_log.json` and was shown on the dashboard as a regular trailing trade. The trailing bot could potentially apply trailing stops, DCA, or dust cleanup on grid-managed assets, causing conflicts with the grid module.

### Root Cause
Two missing grid filters:
1. **`modules/trading_sync.py`**: Both `sync_open_trades()` and `reconcile_balances()` had zero grid market filtering. When these methods fetched Bitvavo balances, BTC (held by the grid module) was treated as a regular position and added to `open_trades`.
2. **`trailing_bot.py` main loop**: The per-trade management loop (trailing stops, DCA, dust cleanup) only skipped HODL markets but not grid markets. If a grid market was in `open_trades` (via the sync bug above), the trailing bot would actively manage it.

Note: `bot/sync_engine.py` already had grid filtering (FIX #014), but `modules/trading_sync.py` (the older parallel sync system) did not.

### Fix Applied

| File | Change |
|------|--------|
| `modules/trading_sync.py` | Added `_get_grid_markets()` helper. Both `sync_open_trades()` and `reconcile_balances()` now skip grid-managed markets when building the balance map. |
| `trailing_bot.py` | Added `grid_markets_set` alongside `hodl_markets_set`. The per-trade loop and dust cleanup loop now skip grid markets. |
| `data/trade_log.json` | Removed BTC-EUR from `open` trades (it was incorrectly added by the unfixed sync). |

### Prevention
- Grid markets are now excluded at ALL sync entry points: `bot/sync_engine.py`, `modules/trading_sync.py`, and `modules/sync_validator.py`.
- The trailing bot's management loop explicitly skips grid markets even if they somehow end up in `open_trades`.
