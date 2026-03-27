# Grondige Bug Analyse — 27 maart 2026

---

## Sectie 1: Executive Summary

**Totaal gevonden: 14 bugs** (4 critical, 5 high, 3 medium, 2 low)

### Wat kan direct geld kosten?
1. **Chunked sell bij API failure telt niet-gevulde orders als succesvol** → bot denkt dat hij verkocht heeft terwijl hij dat niet deed. Volgende stappen (close trade, P&L booking) gebaseerd op fictieve verkoopbedragen.
2. **MAX_DRAWDOWN_SL verkoopt zonder profit guard** → als `MAX_DRAWDOWN_SL_PCT > 0`, verkoopt de bot op verlies. Momenteel staat deze op 0 (uitgeschakeld), maar elke configuratiewijziging activeert een pad zonder de "nooit met verlies verkopen"-invariant.
3. **DCA mutaties zonder trades_lock** → race condition met sync_engine kan cost basis corrumperen (invested_eur ≠ werkelijkheid).
4. **uuid import ontbreekt in trading_dca.py** → multi-process headroom reservation crasht met NameError.

### Is de architectuur fundamenteel gezond?
Nee — er zijn **structurele problemen** die niet met quick-fixes oplosbaar zijn:
- **Trade state is een shared mutable dict** geschreven door 6+ modules zonder consistente locking
- **Twee parallelle sync-systemen** (sync_engine + trading_sync) die hetzelfde state muteren met verschillende locks
- **Config als runtime state store** — 10+ plaatsen schrijven voortdurend naar CONFIG dict, waarvan sommige per ongeluk naar disk worden opgeslagen

De bot werkt ondanks deze problemen doordat de main loop (~25s) serieel draait en de sync threads meestal niet concurrent muteren. Maar onder load of bij API latency zijn race conditions reëel.

---

## Sectie 2: Bug Catalogue

---

## Bug #1 — Chunked sell assumes fill on API failure
**Severity**: CRITICAL  
**Bestand(en)**: [bot/orders_impl.py](bot/orders_impl.py#L500-L505)

### Symptoom
Na een chunked sell met API failures, meldt de bot dat de positie gesloten is, maar er zitten nog tokens in de account.

### Root Cause
In de chunk-loop:
```python
resp = _place_sell_order(chunk)
orders.append(resp)
try:
    filled = float(resp.get('filledAmount', chunk)) if isinstance(resp, dict) else chunk
except Exception:
    filled = chunk
remaining = max(0.0, remaining - filled)
```
Wanneer `resp` is `None` (API failure): `isinstance(None, dict)` = False → `filled = chunk` → volledige chunk wordt als verkocht beschouwd. De `remaining` counter wordt bijgewerkt alsof de verkoop gelukt is.

### Impact
- Bot sluit de trade in memory en trade_log.json terwijl tokens nog op Bitvavo staan
- P&L wordt geboekt voor een fictieve verkoop
- Tokens worden ghost-assets — bot weet niet meer dat ze bestaan
- Bij meerdere chunks: als chunk 2 faalt maar chunk 3 slaagt, wordt `remaining` helemaal fout berekend

### Fix
```python
resp = _place_sell_order(chunk)
orders.append(resp)
try:
    if isinstance(resp, dict) and not resp.get('error') and not resp.get('errorCode'):
        filled = float(resp.get('filledAmount', 0) or 0)
    else:
        filled = 0.0  # API failure → nothing filled
except Exception:
    filled = 0.0
remaining = max(0.0, remaining - filled)
```

### Test
```python
def test_chunked_sell_api_failure_does_not_count_as_filled():
    """When a chunk's API call returns None, remaining should NOT decrease."""
    # Mock _place_sell_order to return None for 2nd chunk
    # Assert: remaining == original_amount - chunk1_filled (not - chunk2)
```

---

## Bug #2 — MAX_DRAWDOWN_SL sells at a loss (no profit guard)
**Severity**: CRITICAL  
**Bestand(en)**: [trailing_bot.py](trailing_bot.py#L2357-L2407)

### Symptoom
Als `MAX_DRAWDOWN_SL_PCT` wordt ingesteld (bijv. 0.15 = 15%), verkoopt de bot bij die drawdown ONGEACHT of de positie op verlies staat.

### Root Cause
Het `max_age` exit pad heeft wél een loss guard:
```python
if bp_check > 0 and cp_check < bp_check:
    log(f"🛑 Max age exit BLOCKED: position in loss")
    continue  # Skip this exit
```
Maar het `MAX_DRAWDOWN_SL` pad mist dit volledig. Het heeft alleen een "stale guard" (>40% loss skip, bedoeld voor corrupt buy_price), maar geen guard tegen normale verliezen.

### Impact
Schendt de invariant: "Bot verkoopt NOOIT met verlies". Momenteel is `MAX_DRAWDOWN_SL_PCT=0` (uitgeschakeld), maar een AI supervisor of handmatige config-wijziging kan dit activeren.

### Fix
Voeg een expliciete loss guard toe, identiek aan max_age:
```python
dd_pct = float(CONFIG.get('MAX_DRAWDOWN_SL_PCT', 0) or 0)
if dd_pct > 0:
    bp = float(t.get('buy_price', cp) or cp)
    if bp > 0 and cp <= bp * (1 - dd_pct):
        # ── Loss guard: never sell at loss ──
        invested = get_true_invested_eur(t, market=m)
        gross = cp * float(t.get('amount', 0) or 0)
        if gross < invested:
            log(f"🛑 MAX_DRAWDOWN exit BLOCKED for {m}: position in loss "
                f"(gross={gross:.2f} < invested={invested:.2f}). "
                f"Only manual intervention may sell at loss.", level='warning')
            continue
        # ... rest of drawdown logic
```

### Test
```python
def test_max_drawdown_sl_blocked_when_in_loss():
    CONFIG['MAX_DRAWDOWN_SL_PCT'] = 0.15
    trade = {'buy_price': 100, 'amount': 1.0, 'invested_eur': 100}
    current_price = 80  # 20% loss, > 15% drawdown threshold
    # Assert: sell is NOT called (position in loss)
```

---

## Bug #3 — Missing `uuid` import in trading_dca.py
**Severity**: CRITICAL  
**Bestand(en)**: [modules/trading_dca.py](modules/trading_dca.py#L854)

### Symptoom
`NameError: name 'uuid' is not defined` wanneer `_reserve_headroom()` wordt aangeroepen. Dit blokkeert DCA-uitvoering op multi-process setups.

### Root Cause
Lijn 854 gebruikt `uuid.uuid4().hex[:6]` maar `import uuid` staat niet in de imports bovenaan het bestand. De reguliere importlijst (regels 1-14) bevat `json, math, os, time, dataclasses, typing, numpy` maar geen `uuid`.

### Impact
- `_reserve_headroom()` crasht bij elke aanroep
- Exception wordt gevangen door `except Exception: return None, 0.0` → headroom check faalt silently
- Zonder headroom reservation kan de bot over MAX_TOTAL_EXPOSURE_EUR heengaan
- Op single-process setups is dit minder erg (headroom reservation is optioneel), maar op multi-process setups is de exposure-limiet niet meer gehandhaafd

### Fix
Voeg toe aan de imports bovenaan `modules/trading_dca.py`:
```python
import uuid
```

### Test
```python
def test_reserve_headroom_creates_valid_reservation():
    """_reserve_headroom should not crash — uuid must be importable."""
    manager = DCAManager(...)
    rid, amount = manager._reserve_headroom(50.0, 1000.0, ctx)
    assert rid is not None  # Should not be None from exception fallback
```

---

## Bug #4 — DCA + trailing mutations without trades_lock
**Severity**: CRITICAL  
**Bestand(en)**: [trailing_bot.py](trailing_bot.py#L2211-L2440), [modules/trading_dca.py](modules/trading_dca.py#L424-L577)

### Symptoom
Intermittente inconsistentie in trade velden (invested_eur ≠ buy_price × amount) die na uren verschijnt en moeilijk te reproduceren is.

### Root Cause
De per-trade management loop in `trailing_bot.py` (lijn 2211: `for m in list(open_trades.keys()):`) draait **buiten** `state.trades_lock`. Dit omvat:
- Trailing stop checks → schrijft `highest_price`, `trailing_activated`, `activation_price`
- DCA uitvoering → schrijft `buy_price`, `amount`, `invested_eur`, `dca_buys`, `dca_events`
- Partial TP uitvoering → schrijft `partial_tp_returned_eur`, `tp_levels_done`

Tegelijkertijd draait `modules/trading_sync.py` in een achtergrond-thread en schrijft:
- `amount` (lijn 373) — met alleen `file_lock`, niet `trades_lock`
- `buy_price` (lijn 613) — idem
- Kan `open_trades[m]` verwijderen (lijn 219) — idem

De `bot/sync_engine.py` draait WEL met `trades_lock` (lijn 149), maar `trading_sync.py` niet.

### Impact
- Race: DCA schrijft `amount += dca_tokens`, sync schrijft `amount = bitvavo_balance` → een van beide is verloren
- Race: DCA schrijft `buy_price = weighted_avg`, sync schrijft `buy_price = derive_result.avg_price` → inconsistentie
- Resultaat: cost basis systematisch verkeerd, trailing stops op verkeerde drempels

### Fix
Twee opties (kies één):

**Optie A (snel, defensief)**: Wrap de hele per-trade loop in `with trades_lock:`:
```python
with trades_lock:
    for m in list(open_trades.keys()):
        t = open_trades.get(m)
        if not isinstance(t, dict):
            continue
        # ... alle trailing/DCA/TP logica ...
```
**Nadeel**: Lock wordt lang gehouden (~25s per loop iteratie). Sync thread wordt geblokkeerd.

**Optie B (beter, gericht)**: Acquire lock rond elke individuele trade mutatie:
```python
for m in list(open_trades.keys()):
    with trades_lock:
        t = open_trades.get(m)
        if not isinstance(t, dict):
            continue
        t_copy = dict(t)  # snapshot for read-only calcs
    
    cp = get_current_price(m)  # buiten lock (API call)
    
    # ... berekeningen op t_copy ...
    
    with trades_lock:
        # mutaties terugschrijven
        t['highest_price'] = max(t.get('highest_price', 0), cp)
        # etc.
```

**Optie B+**: Laat `trading_sync.py` ook `trades_lock` gebruiken in plaats van alleen `file_lock`.

### Test
```python
def test_concurrent_dca_and_sync_dont_corrupt():
    """Run DCA and sync concurrently and verify trade state consistency."""
    # Start DCA in thread 1, sync in thread 2
    # After both complete: assert invested_eur consistent with buy_price * amount
```

---

## Bug #5 — dca_max set from buy_order_count in sync_engine
**Severity**: HIGH  
**Bestand(en)**: [bot/sync_engine.py](bot/sync_engine.py#L301-L311)

### Symptoom
Na een 4-uurs sync-cycle springt `dca_max` naar een onverwacht hoog getal (bijv. 42 voor XRP die 42 historische buys heeft).

### Root Cause
```python
if 'dca_max' not in local:
    inferred_max = None
    if 'basis' in dir() and basis and getattr(basis, 'buy_order_count', None):
        inferred_max = int(getattr(basis, 'buy_order_count') or 0)
    if inferred_max and inferred_max > 0:
        local['dca_max'] = inferred_max  # ← BUG: all historical orders!
```
`buy_order_count` bevat ALLE historische buy orders voor de markt, inclusief oude gesloten posities. Dit is exact het patroon van FIX #004.

De guard `'dca_max' not in local` beschermt alleen bij eerste keer. Maar na een trade dict reset of `dca_max` verwijdering (bijv. door een validator), wordt dit pad opnieuw getriggerd.

### Fix
```python
if 'dca_max' not in local:
    # dca_max comes from config, NEVER from historical order counts (FIX #004/#006)
    local['dca_max'] = int(CONFIG.get('DCA_MAX_BUYS', 5))
```

### Test
```python
def test_sync_engine_dca_max_from_config_not_orders():
    """dca_max should come from config, not from buy_order_count."""
    trade = {}  # no dca_max key
    basis = CostBasisResult(buy_order_count=42, ...)
    # After sync: assert trade['dca_max'] == CONFIG['DCA_MAX_BUYS']
```

---

## Bug #6 — trading_sync.py mutations without trades_lock
**Severity**: HIGH  
**Bestand(en)**: [modules/trading_sync.py](modules/trading_sync.py#L216-L621)

### Symptoom
Zie Bug #4. `trading_sync.py` is de andere kant van dezelfde race condition.

### Root Cause
5 locaties in `trading_sync.py` muteren `open_trades` of individuele trade dicts met alleen `file_lock` (filesystem lock), niet `trades_lock` (in-memory threading lock):
- Lijn 219: `open_state.pop(market, None)` — verwijdert trade
- Lijn 289: `open_state[market] = reconstructed` — voegt trade toe
- Lijn 319: `open_state[market] = new_entry` — auto-discover
- Lijn 373: `entry["amount"] = live_amount` — past amount aan
- Lijn 613-616: schrijft buy_price, tp_levels_done, tp_last_time

### Fix
Replace `with ctx.file_lock:` met `with ctx.trades_lock:` op alle relevante plekken. Of beter: acquire BEIDE locks (trades_lock outer, file_lock inner) wanneer zowel in-memory state als disk state moeten wijzigen.

---

## Bug #7 — CONFIG runtime state keys ontbreken
**Severity**: HIGH  
**Bestand(en)**: [modules/config.py](modules/config.py#L23-L31), [trailing_bot.py](trailing_bot.py) meerdere regels

### Symptoom
`SYNC_ENABLED`, `SYNC_INTERVAL_SECONDS`, `MIN_SCORE_TO_BUY`, `OPERATOR_ID` worden naar `config/bot_config.json` geschreven bij `save_config()`. Na OneDrive revert worden deze waarden dan weer oud.

### Root Cause
Deze keys worden runtime naar `CONFIG` geschreven maar staan NIET in `RUNTIME_STATE_KEYS`:
| Key | Geschreven op | Type |
|-----|---------------|------|
| `SYNC_ENABLED` | trailing_bot.py:2123 | Forced True elke loop |
| `SYNC_INTERVAL_SECONDS` | trailing_bot.py:2124 | Forced 300 elke loop |
| `MIN_SCORE_TO_BUY` | trailing_bot.py:1222 | Dynamische score drempel |
| `OPERATOR_ID` | trailing_bot.py:81 | Uit env var |
| `BASE_AMOUNT_EUR` | bot/trade_lifecycle.py:158 | Reinvest compound |

### Impact
- `SYNC_ENABLED=True` en `SYNC_INTERVAL_SECONDS=300` worden elke loop geforceerd in CONFIG. Als ze in `save_config()` naar disk gaan, overschrijven ze eventuele handmatige wijzigingen in bot_config.json.
- `MIN_SCORE_TO_BUY` fluctueert runtime. Als het op disk wordt geschreven, kan het na restart een stale waarde zijn.
- `BASE_AMOUNT_EUR` is intentioneel persistent, maar schrijft naar OneDrive-synced bestand → wordt gereverteerd.

### Fix
Voeg toe aan `RUNTIME_STATE_KEYS` in [modules/config.py](modules/config.py#L23):
```python
RUNTIME_STATE_KEYS = frozenset({
    'LAST_REINVEST_TS',
    'LAST_HEARTBEAT_TS',
    '_circuit_breaker_until_ts',
    'LAST_SCAN_STATS',
    '_SALDO_COOLDOWN_UNTIL',
    '_REGIME_ADJ',
    '_REGIME_RESULT',
    '_cb_trades_since_reset',
    # Nieuw: runtime-forced values die niet naar disk mogen
    'SYNC_ENABLED',
    'SYNC_INTERVAL_SECONDS',
    'MIN_SCORE_TO_BUY',
    'OPERATOR_ID',
})
```
**Opmerking over BASE_AMOUNT_EUR**: Dit IS intentioneel persistent (reinvest compound). De fix hiervoor is dat `save_config()` ook naar `LOCAL_OVERRIDE_PATH` schrijft, zodat OneDrive het niet revert. Of beter: de reinvest logica schrijft direct naar de local override.

---

## Bug #8 — Crash window: DCA order placed → save_trades() not yet called
**Severity**: HIGH  
**Bestand(en)**: [modules/trading_dca.py](modules/trading_dca.py#L534-L615)

### Symptoom
Na een bot crash tijdens DCA-uitvoering: trade state op disk heeft de oude buy_price/amount, maar Bitvavo toont extra tokens. Bij restart: cost basis verkeerd, dca_buys desynced.

### Root Cause
In `_execute_fixed_dca` (en vergelijkbaar in `_execute_dynamic_dca` en `_execute_pyramid_up`):
1. `place_buy()` → succesvol, order op Bitvavo ✅
2. `trade["buy_price"] = ...` → in-memory mutatie ✅
3. `trade["amount"] += tokens` → in-memory mutatie ✅
4. `_ti_add_dca(trade, eur)` → invested_eur bijgewerkt ✅
5. `record_dca(trade, ...)` → dca_events bijgewerkt ✅
6. `ctx.save_trades()` → **pas hier wordt naar disk geschreven**

Crash tussen stap 1 en stap 6: order IS op Bitvavo geplaatst (onherroepelijk), maar trade state niet opgeslagen. Bij restart leest bot oude trade_log.json en ziet de extra tokens niet.

### Impact
- Invested_eur te laag → P&L te optimistisch
- dca_buys te laag → bot koopt opnieuw op hetzelfde DCA-niveau (cascading)
- Wordt deels gecompenseerd door sync_engine (die amount verschil detecteert en re-derives)
- Maar: tot de volgende 4-uurlijkse sync is cost basis verkeerd

### Fix (defensief)
Sla trades op direct NA de order (stap 1), met een "partial" marker:
```python
buy_result = ctx.place_buy(market, eur_amount, current_price, is_dca=True)
if not ctx.is_order_success(buy_result):
    return

# Immediate checkpoint: mark that an order was placed but state incomplete
trade['_dca_pending'] = {
    'ts': time.time(),
    'market': market,
    'eur': eur_amount,
    'order_result': buy_result,
}
ctx.save_trades(force=True)  # Persist immediately

# Now update state
trade["buy_price"] = ...
trade["amount"] += ...
record_dca(trade, ...)
trade.pop('_dca_pending', None)  # Remove marker
ctx.save_trades(force=True)  # Final save
```
Bij restart: als `_dca_pending` bestaat → re-derive cost basis voor die markt.

---

## Bug #9 — Exception in record_dca/add_dca not wrapped → partial state
**Severity**: HIGH  
**Bestand(en)**: [modules/trading_dca.py](modules/trading_dca.py#L565-L580)

### Symptoom
invested_eur is bijgewerkt maar dca_buys niet (of omgekeerd) → desync.

### Root Cause
```python
# Stap 1: invested_eur bijwerken (SUCCEEDS)
_ti_add_dca(trade, float(actual_dca_eur), source="dca_market_buy")

# Stap 2: record DCA event (COULD FAIL)
_dca_state = _ds_record(trade, price=float(current_price), ...)
```
Als `_ti_add_dca()` slaagt maar `_ds_record()` faalt (bijv. door een bug in core/dca_state.py):
- invested_eur IS bijgewerkt
- dca_buys NIET geïncrementeerd
- dca_events NIET aangevuld
- save_trades() wordt WEL nog aangeroepen → corrupte staat wordt opgeslagen

### Fix
Wrap beide in een transactie-achtig patroon:
```python
# Snapshot before mutation
old_invested = float(trade.get('invested_eur', 0) or 0)
old_dca_buys = int(trade.get('dca_buys', 0))
old_events = list(trade.get('dca_events', []))

try:
    _ti_add_dca(trade, float(actual_dca_eur), source="dca_market_buy")
    _dca_state = _ds_record(trade, price=float(current_price), ...)
except Exception as e:
    # Rollback in-memory state
    trade['invested_eur'] = old_invested
    trade['dca_buys'] = old_dca_buys
    trade['dca_events'] = old_events
    self._log(f"DCA state mutation failed for {market}, rolled back: {e}", level='error')
    return
```

---

## Bug #10 — Unbounded module-level caches (memory leaks)
**Severity**: MEDIUM  
**Bestand(en)**: Meerdere

### Symptoom
Na weken draaien: langzaam toenemend geheugengebruik. Geen crash, maar vertraging.

### Root Cause
5 module-level dicts/lijsten groeien zonder limiet:

| Cache | Bestand | Groeipatroon |
|-------|---------|--------------|
| `_HTF_CACHE` | bot/trailing.py:41 | `{market}:{interval}:{limit}` → honderden keys |
| `_API_ERROR_LOG_SUPPRESS` | bot/api.py:59 | Eén key per unieke error signature |
| `_log_throttle_ts` | trailing_bot.py:280 | Throttle markers per log-site |
| `_MARKET_PERF_FILTER_LOG` | trailing_bot.py:419 | Per-market filter timestamps |
| `_EVENT_PAUSE_CACHE` | trailing_bot.py:459 | Per-market pause state |
| `_cache_store` | bot/api.py:54 | API response cache, TTL maar geen max size |

### Impact
Over weken: 10-100MB geheugengroei. Geen directe geldimpact, maar grotere GC pauses en langzamere dict lookups.

### Fix (per cache)
Voeg een simpele size cap toe:
```python
# Generic LRU-like cleanup for dict caches
def _cache_cleanup(cache: dict, max_size: int = 500):
    if len(cache) > max_size:
        # Remove oldest half
        keys = list(cache.keys())[:max_size // 2]
        for k in keys:
            cache.pop(k, None)
```
Voor `_HTF_CACHE` specifiek: voeg periodic cleanup toe na elke bot cycle die expired entries verwijdert.

---

## Bug #11 — FIX #001 violation in pyramid-up invested_eur fallback
**Severity**: MEDIUM  
**Bestand(en)**: [modules/trading_dca.py](modules/trading_dca.py#L420)

### Symptoom
Pyramid-up kosten worden berekend met `buy_price × amount` als invested_eur missing is, wat per FIX #001 niet de juiste cost basis is.

### Root Cause
```python
old_invested = float(trade.get("invested_eur", 0) or 0) or (buy_price * old_amount)
```
Wanneer `invested_eur` = 0 (ontbreekt of corrupt): fallback naar `buy_price * amount`. Maar `buy_price` is de gewogen gemiddelde entry prijs, niet de werkelijke cost basis (die includes fees en kan afwijken bij external buys).

### Impact
Bij een pyramid-up na een sync waar invested_eur tijdelijk 0 is: cost basis wordt verkeerd berekend. Volgende DCA/sell berekeningen gebaseerd op verkeerde invested_eur.

### Fix
Gebruik invest verifiëring via derive i.p.v. blind fallback:
```python
old_invested = float(trade.get("invested_eur", 0) or 0)
if old_invested <= 0:
    # Don't use buy_price fallback (FIX #001). Log warning and skip pyramid.
    self._log(f"Pyramid-up skipped for {market}: invested_eur is 0/missing. Sync engine will fix.", level='warning')
    return
```

---

## Bug #12 — trade_store fallback missing dca_buys > dca_max cap
**Severity**: MEDIUM  
**Bestand(en)**: [modules/trade_store.py](modules/trade_store.py#L116-L130)

### Symptoom
Als `core.dca_state` import faalt, kan dca_buys boven dca_max staan zonder correctie.

### Root Cause
De fallback in het `except` block corrigeert:
- dca_buys → 0 als dca_events leeg ✅
- dca_buys → len(events) als te laag ✅
- dca_buys > dca_max: **NIET gecorrigeerd** ❌

### Fix
Voeg toe aan het except block:
```python
if dca_buys > dca_max:
    trade['dca_buys'] = min(dca_buys, dca_max)
    needs_fix = True
```

---

## Bug #13 — Test: test_determine_status_badge_affirms_trailing passes wrong value
**Severity**: LOW (test-only bug)  
**Bestand(en)**: [tests/test_dashboard_render.py](tests/test_dashboard_render.py#L38-L40)

### Root Cause
Test verwacht trailing badge met `pnl_eur=-5.0`, maar productie-code geeft trailing badge alleen bij `pnl_eur > 0`. Productie-code is correct (trailing badge alleen tonen bij winst).

### Fix
```python
def test_determine_status_badge_affirms_trailing() -> None:
    label, css = determine_status_badge(pnl_eur=5.0, trailing_active=True)  # was -5.0
    assert label == "Trailing actief"
    assert css == "badge-trailing"
```

---

## Bug #14 — Test: test_geometric_mode tolerance too tight
**Severity**: LOW (test-only bug)  
**Bestand(en)**: [tests/test_grid_trading.py](tests/test_grid_trading.py#L183)

### Root Cause
Geometric mode berekent correcte ratio's, maar `_normalize_price()` rondt prijzen af op tick-size. Na normalisering wijken ratio's af:
- r1 = 1.0387, r2 = 1.0293 → verschil = 0.0094 > 0.001 tolerantie

Productie-code is correct. De test heeft een te strakke tolerantie.

### Fix
```python
assert abs(r1 - r2) < 0.02  # Was 0.001, account for _normalize_price() rounding
```

---

## Sectie 3: Architectuurproblemen

### A1. Trade state als shared mutable dict (STRUCTUREEL)

**Probleem**: Trade dicts zijn plain Python dicts die door 6+ modules direct gemuteerd worden zonder enige encapsulatie. Elke module kan elk veld lezen en schrijven wanneer het maar wil.

**Impact**: Onmogelijk om invarianten te handhaven (bijv. `dca_buys == len(dca_events)`) wanneer meerdere modules dezelfde velden schrijven. De event-sourced DCA state (FIX #007) is een goede stap, maar alleen voor DCA-velden.

**Aanbeveling**: Refactor (langetermijn). Vervang plain dicts door een `Trade` class met:
- Gecontroleerde setters voor financiële velden (invested_eur, amount, buy_price)
- Automatische invariant-checks bij elke mutatie
- Ingebouwde locking (per-trade lock)
- Type-safety (geen numpy.float64 of None in financiële velden)

**Accepteren als tech debt**: Op korte termijn (3-6 maanden). Mitigeer met betere locking discipline.

### A2. Twee parallelle sync-systemen

**Probleem**: `bot/sync_engine.py` (main thread, met trades_lock) en `modules/trading_sync.py` (background thread, zonder trades_lock) doen grotendeels hetzelfde maar op verschillende manieren. Ze gebruiken verschillende locks en kunnen elkaars wijzigingen overschrijven.

**Aanbeveling**: Vervangen. Consolideer naar één sync module die:
- Altijd `trades_lock` acquireert
- Eén duidelijke reconciliatie-cyclus heeft
- `derive_cost_basis()` als single source of truth gebruikt

### A3. CONFIG als runtime state store

**Probleem**: CONFIG is een mutable shared dict dat zowel configuratie (persistent) als runtime state (ephemeral) bevat. De RUNTIME_STATE_KEYS set is de enige scheiding, maar die is incompleet.

**Aanbeveling**: Refactor. Scheid CONFIG in twee objecten:
- `CONFIG` → immutable na laden (of copy-on-read)
- `RUNTIME_STATE` → apart dict voor runtime waarden
- config-wijzigingen → altijd via `update_config(key, value)` die naar LOCAL_OVERRIDE schrijft

---

## Sectie 4: Aanbevolen prioriteitsvolgorde

Gesorteerd op *impact × waarschijnlijkheid*:

| # | Bug | Impact | Kans | Score | Actie |
|---|-----|--------|------|-------|-------|
| 1 | **Bug #1** Chunked sell API failure | 🔴 Geld verlies (ghost tokens) | Middel (alleen bij API glitch + hoge slippage) | **9/10** | Fix vandaag |
| 2 | **Bug #2** MAX_DRAWDOWN_SL loss sell | 🔴 Geld verlies | Laag (uitgeschakeld, maar 1 config-change weg) | **8/10** | Fix vandaag |
| 3 | **Bug #3** uuid import | 🔴 Exposure limiet niet gehandhaafd | Hoog (elke DCA call op multi-process) | **8/10** | Fix vandaag (1 regel) |
| 4 | **Bug #4** + **Bug #6** Locking gaps | 🟠 Data corruptie | Middel (sync thread + main loop concurrent) | **7/10** | Plan voor komende week |
| 5 | **Bug #8** Crash window DCA | 🟠 Cost basis verkeerd na crash | Laag (crash timing = specifiek) | **6/10** | Mitigeer met checkpoint |
| 6 | **Bug #9** record_dca exception | 🟠 dca_buys desync | Laag (dca_state module is simpel) | **6/10** | Wrap in transactie |
| 7 | **Bug #5** dca_max from buy_order_count | 🟠 DCA limiet verkeerd | Middel (elke 4u bij 'dca_max' niet in trade) | **6/10** | Fix deze week |
| 8 | **Bug #7** RUNTIME_STATE_KEYS incompleet | 🟡 Config pollution | Hoog (elke save_config() call) | **5/10** | Fix deze week |
| 9 | **Bug #11** Pyramid-up invested_eur fallback | 🟡 Verkeerde cost basis | Laag (pyramid-up + missing invested_eur) | **4/10** | Fix deze week |
| 10 | **Bug #10** Memory leaks | 🟡 Langzame degradatie | Hoog (groeit continue) | **4/10** | Cleanup routine toevoegen |
| 11 | **Bug #12** trade_store dca_max cap | 🟢 Edge case | Laag (alleen als dca_state module faalt) | **3/10** | Fix mee met #5 |
| 12 | **Bug #13** Test dashboard_render | 🟢 Test-only | Hoog (faalt elke CI run) | **2/10** | 1-regel fix |
| 13 | **Bug #14** Test grid geometric | 🟢 Test-only | Hoog (faalt elke CI run) | **2/10** | Tolerance verhogen |

---

## Sectie 5: Ontbrekende tests

```python
# tests/test_chunked_sell_safety.py

import pytest
from unittest.mock import MagicMock, patch


class TestChunkedSellApiFailure:
    """Bug #1: Chunked sell should not count failed chunks as filled."""

    def test_none_response_does_not_reduce_remaining(self):
        """When API returns None, remaining tokens should NOT decrease."""
        pass  # TODO: Mock _place_sell_order to return None for chunk 2

    def test_error_response_does_not_reduce_remaining(self):
        """When API returns {'error': ...}, remaining should NOT decrease."""
        pass  # TODO: Mock _place_sell_order to return error dict

    def test_partial_fill_uses_actual_amount(self):
        """When filledAmount < requested, only actual fill is counted."""
        pass


class TestDrawdownSLLossGuard:
    """Bug #2: MAX_DRAWDOWN_SL must never sell at a loss."""

    def test_drawdown_sl_blocked_when_gross_lt_invested(self):
        """If gross_sell < invested_eur, drawdown SL must NOT trigger sell."""
        pass

    def test_drawdown_sl_allowed_when_in_profit(self):
        """If position is profitable AND drawdown threshold met, sell OK."""
        pass


class TestDcaReservationHeadroom:
    """Bug #3: _reserve_headroom must not crash on uuid usage."""

    def test_reservation_creates_valid_id(self):
        """uuid.uuid4() must succeed (import present)."""
        pass


class TestDcaLockSafety:
    """Bug #4: DCA mutations must be atomic w.r.t. sync thread."""

    def test_concurrent_dca_and_sync_dont_corrupt(self):
        """Stress test: DCA + sync in parallel → consistent state."""
        pass


class TestDcaCrashRecovery:
    """Bug #8: Bot crash after place_buy but before save_trades."""

    def test_pending_dca_marker_survives_crash(self):
        """A _dca_pending marker should trigger re-derive on restart."""
        pass


class TestDcaStateMutationRollback:
    """Bug #9: Exception in record_dca should rollback invested_eur."""

    def test_record_dca_failure_rolls_back_state(self):
        """If record_dca raises, invested_eur should not be updated."""
        pass


class TestSyncEngineDcaMax:
    """Bug #5: dca_max must come from config, not buy_order_count."""

    def test_dca_max_from_config_not_history(self):
        pass


class TestRuntimeStateKeys:
    """Bug #7: All runtime keys must be in RUNTIME_STATE_KEYS."""

    def test_no_runtime_keys_in_saved_config(self):
        """After save_config(), no runtime state keys in output file."""
        pass
```

---

## Antwoorden op specifieke vragen

### 1. Bot crash mid-DCA

**Antwoord**: Ja, er is een probleem. Als de bot crasht NA `place_buy()` maar VOOR `save_trades()`:
- **Order IS geplaatst op Bitvavo** — onherroepelijk
- **trade_log.json heeft oude state** — amount/invested_eur niet bijgewerkt
- **Bij restart**: bot leest oud bestand. Sync engine detecteert amount mismatch pas bij de volgende 4-uurlijkse reconciliatie of direct als `amount_diff > 0.1%`
- **In die tussentijd**: cost basis is te laag → P&L te optimistisch
- **Koopt hij opnieuw?**: Ja, als het DCA-niveau nog niet bereikt was → dubbele DCA op hetzelfde niveau mogelijk. De `dca_buys` counter is ook niet opgehoogd, dus het DCA-slot is "vrij".

Mitigatie: sync_engine's 4-uurlijkse re-derive vangt het uiteindelijk op, maar er is een window van uren met verkeerde cost basis.

### 2. Threading in DCA

**Antwoord**: `DCAManager.handle_trade()` wordt aangeroepen in de main loop (trailing_bot.py:2418) **BUITEN** `state.trades_lock`. De sync_engine background thread (trading_sync.py) kan concurrent schrijven. Er IS een race condition. In de praktijk is het risico beperkt doordat de main loop serieel draait en de sync thread om de 5 minuten actief is, maar het is een reële bug.

### 3. Dashboard P&L accuracy

**Antwoord**: Na FIX #001 (max() hack verwijderd) is het dashboard correct MITS invested_eur correct is. Scenario's met fout P&L:
1. **Na DCA crash (Bug #8)**: invested_eur te laag → winst overschat
2. **Na sync race (Bug #4)**: invested_eur kan intermittent verkeerd zijn
3. **Pyramid-up met missing invested_eur (Bug #11)**: cost basis via buy_price×amount i.p.v. derive

### 4. config.py 3-layer merge

**Antwoord**: `save_config()` schrijft NOOIT naar LOCAL_OVERRIDE_PATH — dat is veilig ✅. Het schrijft alleen naar `CONFIG_PATH` (bot_config.json). Maar:
- `RUNTIME_STATE_KEYS` is incompleet (Bug #7), waardoor runtime waarden WEL naar bot_config.json gaan
- OneDrive revert bot_config.json, maar dat is OK zolang de belangrijke wijzigingen in local override staan
- `BASE_AMOUNT_EUR` (reinvest compound) wordt naar bot_config.json geschreven en KAN door OneDrive gereverteerd worden → reinvest stap gaat verloren

### 5. ML pipeline

**Antwoord**: Er is een mismatch. Inference produceert 7 features (na FINDINGS Fix #1). Maar `xgb_train_enhanced.py` traint op 5 ANDERE features (`score, ml_score, rsi_at_buy, dca_buys, hold_duration_hours`). Als het enhanced model wordt geladen, faalt feature validatie en ML is effectief uitgeschakeld. `xgb_auto_train.py` traint WEL op de juiste 7 features. Welk model actief is hangt af van het pad in config.

### 6. Grid trading test failure

**Antwoord**: Dit is een TEST BUG, niet een productie-bug. De geometric mode berekening is correct (`ratio = (upper/lower) ** (1/(n-1))`), maar `_normalize_price()` rondt prijzen af op de tick-size van Bitvavo. Na normalisering wijken de ratio's af met ~0.009, wat meer is dan de test tolerantie van 0.001. Fix: verhoog tolerantie naar 0.02.

### 7. Rate limiting

**Antwoord**: Bij een 429 response:
1. Pattern match op "rate limit" → transient error → retry
2. Exponential backoff: 0.5s, 1s, 2s, 4s, 8s (max 10s), 5 retries max
3. Na 5+ opeenvolgende failures: circuit breaker opent → 30 seconden blokkade
4. **Ontbrekend**: `Retry-After` header wordt NIET gelezen → bot luistert niet naar Bitvavo's hints
5. Ban risico: beperkt door circuit breaker + backoff. Maar bij agressieve market scanning (50+ markets/cycle) kan de bot toch tegen limieten aanlopen. Geen harde garantie tegen ban.

### 8. Memory leaks

**Antwoord**: Ja, 6 unbounded caches gevonden (Bug #10). Grootste risico's:
- `_HTF_CACHE`: groeit met `markets × intervals × limits` — 100+ entries, elk met candle data (~50KB)
- `_cache_store` (API responses): TTL-based cleanup, maar alleen bij read. Stale keys (delisted markets) worden nooit verwijderd
- Praktische impact: 10-100MB na weken. Geen crash, maar langzamere GC en meer memory pressure.
