# Prompt voor Claude Opus — Grondige Bug Analyse Hele Codebase

---

## Context & Opdracht

Ik heb een Python-based cryptocurrency trailing-stop trading bot voor de Bitvavo exchange.
De bot draait 24/7 op Windows, beheert echt geld, en heeft de afgelopen maanden een stroom
van bugs gehad — van kritieke crashes tot sluipende data-corruptie die pas weken later zichtbaar werd.

**Ik wil dat jij een grondige bug-analyse uitvoert van de hele codebase.**

Geen oppervlakkige code-review. Geen "overweeg om...". Ik wil:
1. Alle echte bugs gevonden — zeker de niet-voor-de-hand-liggende
2. Prioritering: wat kan geld kosten of de bot laten crashen?
3. Concrete fixes met werkende code
4. Een oordeel over welke delen architectureel kapot zijn vs. gewoon slecht geïmplementeerd

---

## Wat er al is gevonden (sla dit niet opnieuw): al gedocumenteerd in `docs/FIX_LOG.md`

De volgende bugs zijn al gefixed (analyseer ze niet opnieuw, maar gebruik ze wel als patroon
om te begrijpen hoe bugs hier ontstaan):

| # | Bug | Kern |
|---|-----|------|
| #001 | `invested_eur` desync door `opened_ts` filter in FIFO | Gefilterde order history → verkeerde cost basis |
| #002 | `trading_sync.py` dropte posities bij API glitch | `filtered_state` bypass van DISABLE_SYNC_REMOVE guard |
| #003 | Alle stop-loss en time-exits uitgeschakeld | Geen bug, bewuste wijziging |
| #004 | `dca_buys=17` op XRP terwijl 0 DCAs gedaan | `buy_order_count` bevat historische orders van ANDERE posities |
| #005 | Cascading DCAs — 3× kopen op zelfde prijs in 2 min | `buy_price` (gewogen gemiddelde) als referentie i.p.v. `last_dca_price` |
| #006 | GUARD 5 NameError (`dca_max_now`), dca_buys herinflateerd elke 4u | 5 overlappende bugs, FIFO dust threshold te streng |

**Patroon**: Bugs hier ontstaan doordat (a) meerdere systemen hetzelfde state-veld muteren,
(b) stilzwijgende fouten swallowed worden, (c) guards zichzelf kapotmaken door typos.

---

## Architectuur & Grote Lijnen

```
Bitvavo REST API
  → bot/api.py          (rate limiter, cache, circuit breaker — thread-safe via _CB_LOCK)
  → core/indicators.py  (SMA, RSI, MACD, ATR, Bollinger — pure functies)
  → bot/signals.py      (entry signal scoring, per-market evaluatie)
  → modules/ml.py       (XGBoost + LSTM ensemble, optioneel RL gating)
  → core/regime_engine.py  (4 regimes: TRENDING_UP, RANGING, HIGH_VOLATILITY, BEARISH)
  → bot/orders_impl.py  (buy/sell uitvoering)
  → bot/trailing.py     (7-level stepped trailing stops, partial TP, adaptive exit)
  → modules/trading_dca.py  (DCA logic — het probleem-kind)
  → bot/trade_lifecycle.py  (open/close trades, persistence)
  → bot/sync_engine.py  (periodieke reconciliatie met Bitvavo balances)
  → modules/trading_sync.py  (achtergrond-thread sync)
```

**De bot is een ~4300-regel monoliet `trailing_bot.py`** die progressief uitgesplitst wordt
naar `bot/`, `core/`, `modules/`. De twee systemen bestaan naast elkaar en botsen soms.

**Threading model**: Multi-threaded met Python threads. `state.trades_lock` (RLock) beschermt
`open_trades`. Achtergrondthreads voor WebSocket, scheduling, health checks.

**Config**: 3-laags JSON (`bot_config.json` → `bot_config_overrides.json` → `LOCAL/bot_config_local.json`).
Laag 3 wint altijd. Config is een mutable shared dict.

**Trade state**: Plain Python dict, geserialiseerd naar `data/trade_log.json`. ~30 velden per trade.
Wordt gelezen/geschreven door minstens 6 verschillende modules.

---

## Bestanden om te analyseren (volgorde van prioriteit)

### Tier 1 — Kritiek (direct geld-impact)
```
trailing_bot.py                    # ~4300 regels, main loop, alle guards
modules/trading_dca.py             # ~830 regels, DCA uitvoering
bot/sync_engine.py                 # Reconciliatie met exchange
modules/trading_sync.py            # Achtergrond-thread sync
modules/cost_basis.py              # FIFO cost basis (fouten = verkeerde P&L)
bot/orders_impl.py                 # Buy/sell uitvoering
```

### Tier 2 — Hoog risico (crashes/data-corruptie)
```
bot/trailing.py                    # Trailing stops, partial TP
bot/trade_lifecycle.py             # Open/close trade flow
modules/trade_store.py             # Trade validatie en opslag
modules/sync_validator.py          # Positie-herstel na restart
modules/invested_sync.py           # invested_eur synchronisatie
modules/trading_risk.py            # Kelly sizing, risico-checks
core/dca_state.py                  # DCA state management (nieuw)
```

### Tier 3 — Infrastructuur (langetermijnproblemen)
```
bot/api.py                         # API wrapper, circuit breaker
modules/config.py                  # Config loading, state management
modules/ml.py                      # ML predictions
modules/ml_lstm.py                 # LSTM model
core/regime_engine.py              # Marktregime detectie
core/kelly_sizing.py               # Position sizing
bot/shared.py                      # Singleton state
```

### Tier 4 — Dashboard & Monitoring
```
tools/dashboard_flask/app.py       # Flask dashboard (~3000 regels)
modules/metrics.py                 # Metrics emissie
modules/telegram_handler.py        # Telegram alerts
```

---

## Bekende problemen uit eerdere analyses die nog niet gefixed zijn

### ⚠️ Reeds gedocumenteerd in `docs/FINDINGS_AND_FIXES.md` (status per maart 2026):

**Al gefixed (16 items):**
- ML feature mismatch (5 vs 7 features) → GEDAAN
- 4 runtime state keys ontbraken in RUNTIME_STATE_KEYS → GEDAAN
- Circuit breaker `_CB_STATE` niet thread-safe → GEDAAN (Lock toegevoegd)
- `force_refresh=True` in trade loop → GEDAAN
- Negatieve Kelly → min bedrag i.p.v. 0 → GEDAAN
- HTF candle cache in trailing → GEDAAN
- DCAManager._log() methode ontbrak → GEDAAN
- total_invested_eur dubbel-telling in validatie → GEDAAN

**Actieve test failures (nu, run `pytest tests/`):**
- `test_determine_status_badge_affirms_trailing` — FAILED
- `test_geometric_mode` (grid trading) — FAILED
- 2 import errors (`flask` en `psutil` niet geïnstalleerd in test-env)

---

## Specifieke verdachte patronen — focus hierop

### 1. Stille exception swallowing
Vrijwel elke module heeft `except Exception: pass` of `except Exception as e: log(e)`.
Dit maskeert bugs die zichzelf terugkeren. Catalogiseer alle gevallen waarbij een exception
iets still laat falen dat daarna geld kost.

### 2. Meerdere schrijvers op hetzelfde veld
De volgende velden worden geschreven door meerdere onafhankelijke modules:
- `invested_eur`: `trading_dca.py`, `sync_engine.py`, `trading_sync.py`, `trade_lifecycle.py`, `trailing_bot.py` GUARD 7
- `dca_buys`: `trading_dca.py`, `sync_validator.py`, `trade_store.py`, `trailing_bot.py` GUARD 1/4/5
- `buy_price`: `trading_dca.py`, `sync_engine.py`, `orders_impl.py`, `trailing_bot.py`
- `amount`: `trading_dca.py`, `sync_engine.py`, `trading_sync.py`, `orders_impl.py`

Zoek naar write-write conflicten waarbij de volgorde niet gegarandeerd is.

### 3. Bot restart recovery
Na een crash of herstart moet de bot de volledige trade state herstellen vanuit:
- `data/trade_log.json` (primair)
- `data/pending_saldo.json` (legacy fallback)
- Bitvavo order history (via `derive_cost_basis`)

Wat kan er misgaan als de bot crasht **midden in** een DCA-uitvoering?
- Order is al geplaatst op Bitvavo maar trade state is nog niet opgeslagen
- `amount` is al bijgewerkt maar `invested_eur` niet
- `dca_buys` is verhoogd maar `dca_events` nog niet

### 4. Locking gaps
`state.trades_lock` (RLock) is aanwezig maar wordt niet overal gebruikt.
Zoek functies die `open_trades` of individuele trade-dicts muteren zonder de lock te houden.
Let speciaal op:
- `bot/trailing.py` (benoemd in eerdere analyse als problematisch)
- `modules/trading_dca.py` (muteert trade dict meteen na API call, lock?)
- Callbackfuncties die vanuit WebSocket thread worden aangeroepen

### 5. Config mutation bugs
`CONFIG` is een mutable shared dict. Sommige modules slaan runtime state op in CONFIG
(bijv. `LAST_REINVEST_TS`). Dit kan naar disk geschreven worden en andere config-waarden
overschrijven of de 3-layer merge verstoren.

Zoek alle `CONFIG[key] = value` assignments buiten `save_config()`.

### 6. API response None-safety
`safe_call()` retourneert `None` bij failure. Maar callers controleren dit niet altijd.
Zoek alle patronen zoals:
```python
result = safe_call(...)
value = result['key']  # KeyError/TypeError als result is None
```

### 7. Getaltype-problemen in trade dicts
Trade dicts komen van JSON (alles is float/int/str) maar worden ook direct geschreven
vanuit Python-berekeningen (soms Decimal, numpy.float64, etc.).
Zoek naar plaatsen waar:
- `numpy.float64` in een trade dict terechtkomt (JSON-serizalisatie faalt)
- Integer-divisie waar float verwacht wordt (`amount / price` met integers)
- `None` arithmetic (`trade.get('dca_buys', None) + 1`)

### 8. Timing bugs
De bot draait elke ~25s. Sommige operaties hebben eigen cooldowns/debounces.
Zoek naar:
- Cooldown checks met `time.time()` die bij herstart/timezone-issues falen
- Debounce timestamps die naar 0 worden gereset bij fouten (waardoor direct opnieuw triggeren)
- `synced_at` timestamp die na handmatige correctie niet bijgewerkt wordt

### 9. File I/O corruptie
Trade log wordt geschreven via atomisch tmp+replace pattern. Maar:
- Wordt ook gelezen zonder lock in sommige background threads?
- Wat als de write faalt halverwege?
- Zijn er race conditions tussen de twee sync-systemen die allebei schrijven?

### 10. DCA next price inconsistentie
`dca_next_price` wordt op meerdere plekken berekend:
- In `trading_dca.py` bij elke check (recalculeert altijd)
- In `trade_store.py` bij validatie
- In `trailing_bot.py` in de guards

Als de referentieprijzen (buy_price, last_dca_price) ergens anders bijgewerkt worden,
kan `dca_next_price` stale worden → bot triggert DCA op verkeerd niveau.

---

## Wat ik wil als output

### Sectie 1: Executive Summary
- Hoeveel kritieke bugs gevonden?
- Welke kunnen direct geld kosten?
- Is de architectuur fundamenteel gezond of zijn er structurele problemen?

### Sectie 2: Bug Catalogue (per bug)
Voor elke bevinding:
```
## Bug #N — [Korte naam]
Severity: CRITICAL / HIGH / MEDIUM / LOW
Bestand(en): [exact pad + regelnummer(s)]
Symptoom: Wat de gebruiker ziet
Root Cause: Waarom het fout gaat (technisch)
Reproduceerstappen: Hoe je het triggert
Impact: Wat er mis kan gaan (verlies, crash, corruptie?)
Fix: Concrete Python code om het op te lossen
Test: Hoe je verifieert dat de fix werkt
```

### Sectie 3: Architectuurproblemen
Problemen die niet met een quick fix oplosbaar zijn maar structureel aangepakt moeten worden.
Geef per probleem een aanbeveling: refactor, vervangen, of accepteren als technical debt.

### Sectie 4: Aanbevolen prioriteitsvolgorde
Sorteer alle gevonden bugs op: (impact × kans) — wat moet eerst?

### Sectie 5: Ontbrekende tests
Welke test-cases ontbreken die de gevonden bugs zouden hebben gevonden?
Schrijf de test-stubs (met `pytest`-stijl).

---

## Aanvullende context die je moet weten

### Kritieke invarianten (mogen NOOIT geschonden worden)
1. `dca_buys == len(dca_events)` — altijd, na elke operatie
2. Bot verkoopt NOOIT met verlies (alle sell-paths hebben `real_profit > 0` guard of zijn uitgeschakeld)
3. `initial_invested_eur` is IMMUTABLE na aanmaken — wordt nooit bijgewerkt
4. `derive_cost_basis()` haalt ALTIJD volledige order history op (geen datum-filter)
5. `MAX_OPEN_TRADES >= 3` altijd (enforcement in ai_supervisor + suggest_rules)

### Bewuste keuzes (niet als bug rapporteren)
- Stop-loss is **volledig uitgeschakeld** (`check_stop_loss()` returnt altijd False) — dit is gewild
- Time-based exits zijn **uitgeschakeld** — gewild
- `if False:` op regel ~2826 in `trailing_bot.py` — bewuste dead code (FIX #003)
- Nederlandse log-berichten — intentioneel (developer is Nederlands)
- DCA_MAX_BUYS=17 — hoog getal maar configureerbaar, geen bug

### Omgeving
- Python 3.13, Windows 11
- Bot draait als set van ~7 Python-processen via `scripts/startup/start_bot.py`
- Bestanden staan op OneDrive (sync-latency soms relevant voor file I/O)
- Geen asyncio — alles threading

### Actuele test failures (reproduce ze en begrijp ze)
```
FAILED tests/test_dashboard_render.py::test_determine_status_badge_affirms_trailing
FAILED tests/test_grid_trading.py::TestGridCreation::test_geometric_mode
```

### Actuele test-omgeving problemen (negeer deze)
```
ERROR tests/test_dashboard_flask_app.py  — flask niet geïnstalleerd in test-venv
ERROR tests/test_load.py               — psutil niet geïnstalleerd in test-venv
```

---

## Specifieke vragen die ik beantwoord wil hebben

1. **Bot crash mid-DCA**: Als de bot crasht nadat een DCA order is geplaatst op Bitvavo maar VÓÓR
   `save_trades()` wordt aangeroepen, wat gebeurt er dan bij restart? Verliest de bot geld?
   Koopt hij opnieuw op hetzelfde niveau?

2. **Threading in DCA**: `DCAManager.handle_trade()` muteert het trade-dict direct. Wordt dit
   aangeroepen binnen `state.trades_lock` of buiten? Kan een concurrent write (bijv. van
   `sync_engine.py`) de DCA-teller corrupt maken?

3. **Dashboard P&L accuracy**: Onder welke omstandigheden toont het dashboard een fout P&L-getal?
   (De `max()` hack is weg, maar zijn er andere plekken waar derived values verkeerd berekend worden?)

4. **config.py 3-layer merge**: Is er een scenario waarbij laag 3 (`bot_config_local.json`) per
   ongeluk wordt overschreven door `save_config()`? Of waarbij RUNTIME_STATE_KEYS per ongeluk
   naar laag 1/2 worden geschreven?

5. **ML pipeline**: Zijn de XGBoost features en het getrainde model in sync? Kan het model
   stale zijn (getraind op andere features dan wat nu gegenereerd wordt)?

6. **Grid trading**: Er zijn 2 test failures in grid trading. Is dit een echte bug in de
   grid-trading logica of een test-implementatiefout?

7. **Rate limiting**: Als Bitvavo een 429 Too Many Requests teruggeeft, hoe gedraagt de bot
   zich? Blijft hij retrying? Kan dit leiden tot een ban/block?

8. **Memory leaks**: Zijn er module-level caches of lijsten die onbeperkt groeien?
   (`_HTF_CACHE`, `PARTIAL_TP_HISTORY`, `dca_audit.log`, etc.)

---

## Instructie voor analyse-methode

Analyseer de code op de volgende manier:

1. **Lees eerst de kritieke bestanden volledig** (trailing_bot.py, trading_dca.py, sync_engine.py)
   voordat je conclusions trekt — de context is verspreid over het hele bestand.

2. **Volg data-flows**: trace elk veld (`dca_buys`, `invested_eur`, `amount`, `buy_price`)
   van schrijven naar lezen en terug. Identificeer alle schrijvers en de volgorde.

3. **Denk als een failure-mode ingenieur**: voor elke functie, wat is de slechtst
   denkbare invoer? Wat als een API call None terugstuurt? Wat als de thread halverwege
   onderbroken wordt? Wat als dit de 1000e keer is dat de functie wordt aangeroepen?

4. **Wees specifiek**: geen "overweeg logging toe te voegen". Geef exact rules en code.

5. **Prioriteer over volledigheid**: liever 10 gevonden bugs diepgaand dan 50 snel gescand.
   Focus op wat geld kost of de bot lamlegt.

Neem alle tijd die je nodig hebt. Dit is een productiesysteem met echt geld.
