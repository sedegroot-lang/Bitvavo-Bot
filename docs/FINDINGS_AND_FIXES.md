# Bitvavo Trading Bot — Analyse & Fixes

> **Doel**: Dit bestand bevat alle bevindingen uit de diepte-analyse van de codebase.
> Elke fix is concreet, met exacte bestandspaden, regelnummers en code-snippets.
> Claude Sonnet kan dit bestand gebruiken om alle fixes direct uit te voeren.

---

## Uitvoeringsstatus (bijgewerkt 2026-03-13)

| # | Status | Bestand | Probleem |
|---|--------|---------|----------|
| 1 | ✅ GEDAAN | `modules/ml.py` + `core/indicators.py` | Feature engineering mismatch opgelost (5→7 features) |
| 2 | ✅ GEDAAN | `modules/config.py` | 4 runtime state keys toegevoegd aan `RUNTIME_STATE_KEYS` |
| 3 | ✅ GEDAAN | `.env` + `config/bot_config.json` | Telegram token verplaatst naar `.env` |
| 4 | ✅ GEDAAN | `trailing_bot.py` | `force_refresh=True` verwijderd uit trade loop |
| 5 | ✅ GEDAAN | `modules/trading_risk.py` | Negatieve Kelly → 0.0 |
| 6 | ✅ GEDAAN | `bot/api.py` | `_CB_STATE` nu thread-safe via `_CB_LOCK` |
| 7 | ✅ GEDAAN | `bot/trailing.py` | HTF candle cache toegevoegd (`_get_htf_candles`) |
| 8 | ✅ GEDAAN | `bot/trailing.py` | Lock-ownership noten toegevoegd aan muterende functies |
| 9 | ✅ GEDAAN | `modules/config_schema.py` | `RSI_DCA_THRESHOLD` + `DCA_SYNC_COOLDOWN_SEC` toegevoegd |
| 10 | ✅ GEDAAN | `core/indicators.py` | `bb_position()` toegevoegd (fix 1 afhankelijkheid) |
| 11 | ✅ GEDAAN | `config/bot_config.json` + overrides | Dode key `ENABLE_STOP_LOSS` verwijderd |
| 12 | ⏭️ SKIP | `trailing_bot.py` | `optimize_parameters()` lege placeholder — bewust gelaten |
| 13 | ✅ GEDAAN | `modules/ml.py` | `model_explainability()` bijgewerkt naar 7 feature-namen |

---

## Overzicht Prioriteiten

| # | Severity | Bestand | Probleem | Complexiteit |
|---|----------|---------|----------|--------------|
| 1 | 🔴 CRITICAL | `modules/ml.py` | Feature engineering mismatch (5 vs 7 features) — ML is effectief uitgeschakeld | Laag |
| 2 | 🔴 CRITICAL | `modules/config.py` | 4 runtime state keys ontbreken in `RUNTIME_STATE_KEYS` — worden per ongeluk naar config geschreven | Laag |
| 3 | 🔴 CRITICAL | `config/bot_config.json` | Telegram Bot Token in plaintext (security) | Laag |
| 4 | 🔴 CRITICAL | `trailing_bot.py` | `force_refresh=True` in trade loop veroorzaakt ~40 API calls/sec | Middel |
| 5 | 🟠 HIGH | `modules/trading_risk.py` | Negatieve Kelly retourneert min-bedrag i.p.v. 0 (handelt bij verliesstrategie) | Laag |
| 6 | 🟠 HIGH | `bot/api.py` | Circuit breaker `_CB_STATE` dict niet thread-safe | Laag |
| 7 | 🟠 HIGH | `bot/trailing.py` | HTF candles (5m/15m/1h) elke 25s opnieuw opgehaald zonder cache | Middel |
| 8 | 🟠 HIGH | `bot/trailing.py` | Trade dict mutaties zonder `trades_lock` | Middel |
| 9 | 🟡 MEDIUM | `modules/config_schema.py` | `RSI_DCA_THRESHOLD` en `DCA_SYNC_COOLDOWN_SEC` ontbreken in schema | Laag |
| 10 | 🟡 MEDIUM | `core/indicators.py` | `bb_position()` functie ontbreekt (nodig voor ML fix) | Laag |
| 11 | 🟡 MEDIUM | `config/bot_config.json` + overrides | Dode key `ENABLE_STOP_LOSS` (live key = `STOP_LOSS_ENABLED`) | Laag |
| 12 | 🟢 LOW | `trailing_bot.py` | `optimize_parameters()` is een lege placeholder | Laag |
| 13 | 🟢 LOW | `modules/ml.py` | `model_explainability()` kent maar 5 feature-namen (moet 7 zijn na fix #1) | Laag |

---

## Fix 1 — ML Feature Engineering Mismatch (CRITICAL)

### Probleem
`modules/ml.py` regel 69: `feature_engineering()` produceert **5 features**, maar het XGBoost-model verwacht **7 features** (standaard `_xgb_num_features = 7`). Hierdoor faalt `validate_features()` altijd en is het ML-systeem effectief uitgeschakeld.

### Ontbrekende features
- `bb_position` — Bollinger Bands positie (0.0 = onder lower band, 1.0 = boven upper band)
- `stochastic_k` — Stochastic oscillator %K

### Stap 1: Voeg `bb_position()` toe aan `core/indicators.py`

**Bestand**: `core/indicators.py`
**Locatie**: Na de bestaande `bollinger_bands()` functie

```python
def bb_position(vals: Sequence[float], window: int = 20, num_std: float = 2.0) -> Optional[float]:
    """Bollinger Bands positie: (prijs - lower) / (upper - lower). Retourneert 0.0-1.0."""
    result = bollinger_bands(vals, window, num_std)
    if result is None:
        return None
    upper, mid, lower = result
    if upper == lower:
        return 0.5
    return (vals[-1] - lower) / (upper - lower)
```

### Stap 2: Fix `feature_engineering()` in `modules/ml.py`

**Bestand**: `modules/ml.py`
**Regel**: 62-69

**Huidige code**:
```python
def feature_engineering(raw: dict):
    """
    Zet ruwe indicatoren om naar ML feature array.
    """
    # raw: dict met indicatoren
    # Voorbeeld: {'rsi':..., 'macd':..., 'sma_short':..., 'sma_long':..., 'volume':...}
    features = [raw.get('rsi',0), raw.get('macd',0), raw.get('sma_short',0), raw.get('sma_long',0), raw.get('volume',0)]
    return features
```

**Nieuwe code**:
```python
def feature_engineering(raw: dict):
    """
    Zet ruwe indicatoren om naar ML feature array (7 features).
    Volgorde: rsi, macd, sma_short, sma_long, volume, bb_position, stochastic_k
    """
    features = [
        raw.get('rsi', 0),
        raw.get('macd', 0),
        raw.get('sma_short', 0),
        raw.get('sma_long', 0),
        raw.get('volume', 0),
        raw.get('bb_position', 0.5),
        raw.get('stochastic_k', 50.0),
    ]
    return features
```

### Stap 3: Fix `model_explainability()` in `modules/ml.py`

**Bestand**: `modules/ml.py`
**Regel**: ~77 (in `model_explainability`)

**Huidige code**:
```python
        return dict(zip(['rsi','macd','sma_short','sma_long','volume'], importances))
```

**Nieuwe code**:
```python
        return dict(zip(['rsi','macd','sma_short','sma_long','volume','bb_position','stochastic_k'], importances))
```

### Stap 4: Zorg dat callers ook `bb_position` en `stochastic_k` meegeven

Zoek in de codebase naar alle plekken waar `feature_engineering()` wordt aangeroepen en zorg dat de `raw` dict ook de keys `bb_position` en `stochastic_k` bevat. Typisch in `bot/signals.py` of `trailing_bot.py` waar indicatoren worden berekend:

```python
from core.indicators import bb_position, stochastic

# Bij het samenstellen van de raw dict:
raw['bb_position'] = bb_position(closes, window=20) or 0.5
raw['stochastic_k'] = stochastic(closes, window=14) or 50.0
```

### Verificatie
```python
# Na de fix:
raw = {'rsi': 45, 'macd': 0.5, 'sma_short': 100, 'sma_long': 98, 'volume': 50000, 'bb_position': 0.6, 'stochastic_k': 35}
features = feature_engineering(raw)
assert len(features) == 7  # Moet slagen
assert validate_features(features) == True  # Moet slagen
```

---

## Fix 2 — Ontbrekende RUNTIME_STATE_KEYS (CRITICAL)

### Probleem
`modules/config.py` regel 15-20: De `RUNTIME_STATE_KEYS` frozenset mist 4 keys die wél als runtime state in CONFIG worden opgeslagen. Hierdoor worden ze per ongeluk naar `config/bot_config.json` geschreven bij elke `save_config()`, wat stale data veroorzaakt na herstarts.

### Ontbrekende keys
- `_SALDO_COOLDOWN_UNTIL` — saldo-cooldown timestamp
- `_REGIME_ADJ` — regime adjustment dict
- `_REGIME_RESULT` — regime detection result
- `_cb_trades_since_reset` — circuit breaker trade counter

### Fix

**Bestand**: `modules/config.py`
**Regel**: 15-20

**Huidige code**:
```python
RUNTIME_STATE_KEYS = frozenset({
    'LAST_REINVEST_TS',
    'LAST_HEARTBEAT_TS',
    '_circuit_breaker_until_ts',
    'LAST_SCAN_STATS',
})
```

**Nieuwe code**:
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
})
```

### Opruiming: Verwijder stale keys uit config bestanden

**Bestand**: `config/bot_config.json`
Verwijder deze regels:
```json
  "_SALDO_COOLDOWN_UNTIL": 1773403839.9883974,
  "_cb_trades_since_reset": 0,
  "_REGIME_ADJ": { ... },
  "_REGIME_RESULT": { ... },
```

De waarden worden na herstart automatisch opnieuw berekend en opgeslagen in `data/bot_state.json`.

### Verificatie
```python
from modules.config import RUNTIME_STATE_KEYS
assert '_SALDO_COOLDOWN_UNTIL' in RUNTIME_STATE_KEYS
assert '_REGIME_ADJ' in RUNTIME_STATE_KEYS
assert '_REGIME_RESULT' in RUNTIME_STATE_KEYS
assert '_cb_trades_since_reset' in RUNTIME_STATE_KEYS
```

---

## Fix 3 — Telegram Bot Token uit Config (CRITICAL / Security)

### Probleem
`config/bot_config.json` regel 303: De Telegram Bot Token staat in plaintext in een bestand dat via OneDrive wordt gesynchroniseerd en mogelijk in git-history staat. Iedereen met toegang kan berichten sturen namens de bot.

### Fix

**Stap 1**: Maak een `.env` bestand aan in de project root (als dat nog niet bestaat):

**Bestand**: `.env` (project root)
```
TELEGRAM_BOT_TOKEN=8397921391:AAGYxTWiK6HFlvXUnEg989v0Vb_JTO_7ccc
TELEGRAM_CHAT_ID=8337751679
```

**Stap 2**: Zorg dat `.env` in `.gitignore` staat:
```
.env
```

**Stap 3**: Pas `modules/config.py` aan om env vars te laden

In de `load_config()` functie, na het laden van de JSON config, overschrijf gevoelige waarden met env vars:

```python
import os
from dotenv import load_dotenv

load_dotenv()

def load_config() -> dict:
    # ... bestaande load logica ...
    
    # Override sensitive keys from environment variables
    env_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if env_token:
        config['TELEGRAM_BOT_TOKEN'] = env_token
    env_chat = os.environ.get('TELEGRAM_CHAT_ID')
    if env_chat:
        config['TELEGRAM_CHAT_ID'] = env_chat
    
    return config
```

**Stap 4**: Vervang token in config bestanden door placeholder:

**`config/bot_config.json`**:
```json
  "TELEGRAM_BOT_TOKEN": "",
  "TELEGRAM_CHAT_ID": "",
```

**Stap 5**: **Regenereer de Telegram Bot Token** via @BotFather op Telegram (de huidige token is gecompromitteerd als het in git stond).

### Verificatie
```python
import os
assert os.environ.get('TELEGRAM_BOT_TOKEN') is not None
assert len(os.environ.get('TELEGRAM_BOT_TOKEN', '')) > 10
```

---

## Fix 4 — force_refresh=True in Trade Loop (CRITICAL)

### Probleem
`trailing_bot.py` regel ~2095: In de trade management loop wordt `get_current_price(m, force_refresh=True)` aangeroepen voor **elke open trade** per iteratie. Bij 3+ trades = 3+ onnodige API calls per 25s loop. Waarde is al gecached vanuit de market scan.

### Fix

**Bestand**: `trailing_bot.py`
**Zoek naar**: `get_current_price(m, force_refresh=True)` binnen de trade management sectie (rond regel 2095)

**Vervang**:
```python
cp = get_current_price(m, force_refresh=True)
```

**Door**:
```python
cp = get_current_price(m)
```

**Let op**: Behoud `force_refresh=True` ALLEEN bij:
- Balance checks na een order (`get_eur_balance(force_refresh=True)`) — dit is correct
- Initiële sync bij startup

Zoek in `trailing_bot.py` naar alle `force_refresh=True` calls en evalueer per case:
- `get_current_price(m, force_refresh=True)` in trade loop → **verwijder** `force_refresh=True`
- `get_eur_balance(force_refresh=True)` na orders → **behoud** (correct gebruik)

---

## Fix 5 — Negatieve Kelly Retourneert Min-bedrag (HIGH)

### Probleem
`modules/trading_risk.py` regel ~477: Als de Kelly-fractie negatief is (= verliesstrategie), retourneert de code een minimumbedrag (€5) in plaats van €0. Dit betekent dat de bot blijft handelen met verlies.

### Fix

**Bestand**: `modules/trading_risk.py`
**Regel**: ~477

**Huidige code**:
```python
			if kelly_fraction <= 0:
				# Negative Kelly = losing strategy → use minimum
				min_amount = float(self.ctx.config.get("RISK_KELLY_MIN_AMOUNT", 5.0))
				self.ctx.log(
					f"Kelly negative ({kelly_fraction:.3f}) — using min amount €{min_amount}",
					level="warning",
				)
				return min_amount
```

**Nieuwe code**:
```python
			if kelly_fraction <= 0:
				# Negative Kelly = losing strategy → don't trade
				self.ctx.log(
					f"Kelly negative ({kelly_fraction:.3f}) — skip trade, win rate too low",
					level="warning",
				)
				return 0.0
```

### Impact
Na deze fix blokkeert een negatieve Kelly nieuwe trades totdat de win rate verbetert. Dit voorkomt verliesrisico bij slechte marktomstandigheden.

### Verificatie
```python
# Test: Kelly negatief → moet 0.0 retourneren, niet min_amount
# Win rate 20%, avg_win 10, avg_loss 20 → Kelly = 0.2 - 0.8/0.5 = -1.4
assert kelly_sizing_result == 0.0
```

---

## Fix 6 — Circuit Breaker State Thread-Safety (HIGH)

### Probleem
`bot/api.py` regel 247: `_CB_STATE` is een module-level dict die door meerdere threads wordt gelezen/geschreven zonder lock. Dit kan race conditions veroorzaken.

### Fix

**Bestand**: `bot/api.py`

**Stap 1**: Voeg een lock toe (bovenaan bij de imports/globals):

Zoek naar de regel `_CB_STATE: Dict[str, dict] = {}` en voeg erboven toe:
```python
_CB_LOCK = threading.Lock()
```

**Stap 2**: Wrap alle reads/writes van `_CB_STATE` in de `safe_call()` functie:

Elke `_CB_STATE.get(...)` en `_CB_STATE[key] = ...` moet binnen `with _CB_LOCK:` staan.

Voorbeeld patroon:
```python
# VOOR:
st = _CB_STATE.get(key, {'failures': 0, 'state': 'closed', 'opened_ts': 0})

# NA:
with _CB_LOCK:
    st = _CB_STATE.get(key, {'failures': 0, 'state': 'closed', 'opened_ts': 0}).copy()

# ...logica...

# VOOR:
_CB_STATE[key] = st

# NA:
with _CB_LOCK:
    _CB_STATE[key] = st
```

**Let op**: Gebruik `.copy()` bij het lezen zodat je niet buiten de lock een shared dict muteert.

---

## Fix 7 — HTF Candle Cache in Trailing (HIGH)

### Probleem
`bot/trailing.py` regel 647-665: Bij elke loop-iteratie (25s) worden 5m/15m/1h candles opgehaald voor elke open trade via `_api.get_candles()`. Deze data verandert langzaam (5m candle pas elke 5 min) maar wordt elke 25s opnieuw opgehaald.

### Fix

**Bestand**: `bot/trailing.py`

**Stap 1**: Voeg een module-level HTF cache toe:

```python
import time
import threading

_HTF_CACHE: dict = {}  # key: (market, interval) → {'data': candles, 'ts': time.time()}
_HTF_CACHE_LOCK = threading.Lock()
_HTF_CACHE_TTL = {
    '5m': 120,    # Cache 5m candles voor 2 minuten
    '15m': 300,   # Cache 15m candles voor 5 minuten
    '1h': 600,    # Cache 1h candles voor 10 minuten
}

def _get_htf_candles(market: str, interval: str, limit: int = 20):
    """Haal HTF candles op met caching."""
    key = (market, interval)
    ttl = _HTF_CACHE_TTL.get(interval, 120)
    now = time.time()
    
    with _HTF_CACHE_LOCK:
        cached = _HTF_CACHE.get(key)
        if cached and (now - cached['ts']) < ttl:
            return cached['data']
    
    data = _api.get_candles(market, interval, limit)
    
    with _HTF_CACHE_LOCK:
        _HTF_CACHE[key] = {'data': data, 'ts': now}
    
    return data
```

**Stap 2**: Vervang in de multi-timeframe consensus sectie:

```python
# VOOR:
c5m = _api.get_candles(m, "5m", 20)
c15m = _api.get_candles(m, "15m", 20)
c1h = _api.get_candles(m, "1h", 20)

# NA:
c5m = _get_htf_candles(m, "5m", 20)
c15m = _get_htf_candles(m, "15m", 20)
c1h = _get_htf_candles(m, "1h", 20)
```

### Impact
Reduceert API calls drastisch: van 3 calls per trade per 25s → 3 calls per trade per 2-10 minuten.

---

## Fix 8 — Trade Dict Mutaties Zonder Lock (HIGH)

### Probleem
`bot/trailing.py` muteert trade dicts op meerdere plekken (regels 134, 142, 175, 370, 428-431, 455-459) zonder `state.trades_lock` te acquiren. Dit kan race conditions veroorzaken met andere threads.

### Fix

**Optie A** (aanbevolen): Documenteer dat callers de lock moeten vasthouden. Voeg assertion toe aan het begin van de publieke functies:

```python
def manage_trailing_stop(trade: dict, market: str, ...):
    """Manage trailing stop voor een trade. Caller MOET state.trades_lock vasthouden."""
    assert state.trades_lock._is_owned(), "trades_lock must be held by caller"
    # ... bestaande code ...
```

**Optie B**: Wrap de hele functie in de lock:

```python
def manage_trailing_stop(trade: dict, market: str, ...):
    with state.trades_lock:
        # ... alle bestaande code ...
```

**Let op**: Kies één optie consistent door het hele `bot/trailing.py` bestand. Optie A is beter als de caller al de lock vasthoudt (voorkomt deadlock bij RLock).

### Betreffende functies in `bot/trailing.py`:
- `manage_trailing_stop()`
- `_apply_partial_tp()`
- `_check_time_based_tighten()`
- Elke functie die `trade[...]= ...` doet

---

## Fix 9 — Schema Validatie Ontbrekende Keys (MEDIUM)

### Probleem
`modules/config_schema.py`: De keys `RSI_DCA_THRESHOLD` en `DCA_SYNC_COOLDOWN_SEC` worden in code gebruikt maar staan niet in het validatie-schema.

### Fix

**Bestand**: `modules/config_schema.py`

Voeg toe aan de `_SCHEMA` dict (na de RSI_MAX_BUY entry):

```python
    "RSI_DCA_THRESHOLD":        {"type": "float", "default": 100.0, "min": 50.0,  "max": 100.0, "desc": "RSI drempel voor DCA (100=altijd DCA)"},
    "DCA_SYNC_COOLDOWN_SEC":    {"type": "float", "default": 300.0, "min": 0.0,   "max": 1800.0, "desc": "Seconden DCA-pauze na sync"},
```

---

## Fix 10 — `bb_position()` Toevoegen aan Indicators (MEDIUM)

### Probleem
`core/indicators.py` heeft wel `bollinger_bands()` en `stochastic()` maar geen `bb_position()` helper. Die is nodig voor Fix 1.

### Fix
Zie **Fix 1, Stap 1** hierboven.

---

## Fix 11 — Dode Config Key `ENABLE_STOP_LOSS` (MEDIUM)

### Probleem
`config/bot_config.json` en `config/bot_config_overrides.json` bevatten de key `ENABLE_STOP_LOSS`, maar de code leest alleen `STOP_LOSS_ENABLED`. De key heeft geen effect.

### Fix

**Bestand**: `config/bot_config.json`
**Verwijder**: de regel `"ENABLE_STOP_LOSS": false,`

**Bestand**: `config/bot_config_overrides.json`
**Verwijder**: de regel `"ENABLE_STOP_LOSS": false,`

---

## Fix 12 — Lege `optimize_parameters()` Placeholder (LOW)

### Probleem
`trailing_bot.py` regel 1218-1229: `optimize_parameters()` is een no-op functie die nooit iets doet.

### Fix
**Optie A**: Verwijder de functie en alle aanroepen.
**Optie B**: Implementeer basis-functionaliteit (bijv. dynamische MIN_SCORE_TO_BUY aanpassing op basis van recente trade performance).

Aanbeveling: Optie A tenzij er concrete plannen zijn voor parameter-optimalisatie.

---

## Fix 13 — Explainability Feature Namen (LOW)

### Probleem
Na Fix 1 klopt `model_explainability()` niet meer — het kent 5 feature-namen maar er zijn nu 7.

### Fix
Zie **Fix 1, Stap 3** hierboven.

---

## Aanvullende Aanbevelingen

### Test Cases om toe te voegen

**1. ML Feature Count Test**
```python
# tests/test_ml_features.py
def test_feature_engineering_count():
    raw = {'rsi': 45, 'macd': 0.5, 'sma_short': 100, 'sma_long': 98,
           'volume': 50000, 'bb_position': 0.6, 'stochastic_k': 35}
    features = feature_engineering(raw)
    assert len(features) == 7
    assert validate_features(features) is True

def test_feature_engineering_defaults():
    """Zonder bb_position/stochastic_k moeten defaults worden gebruikt."""
    raw = {'rsi': 45, 'macd': 0.5, 'sma_short': 100, 'sma_long': 98, 'volume': 50000}
    features = feature_engineering(raw)
    assert len(features) == 7
    assert features[5] == 0.5   # bb_position default
    assert features[6] == 50.0  # stochastic_k default
```

**2. Runtime State Keys Test**
```python
# tests/test_config_runtime_keys.py
def test_runtime_keys_not_saved_to_config():
    """Alle underscore-prefixed runtime keys moeten in RUNTIME_STATE_KEYS staan."""
    from modules.config import RUNTIME_STATE_KEYS
    assert '_SALDO_COOLDOWN_UNTIL' in RUNTIME_STATE_KEYS
    assert '_REGIME_ADJ' in RUNTIME_STATE_KEYS
    assert '_REGIME_RESULT' in RUNTIME_STATE_KEYS
    assert '_cb_trades_since_reset' in RUNTIME_STATE_KEYS
```

**3. Kelly Negative Test**
```python
# tests/test_kelly_negative.py
def test_kelly_negative_returns_zero():
    """Negatieve Kelly moet 0 retourneren, niet minimum bedrag."""
    # Setup: win_rate=0.2, avg_win=10, avg_loss=20
    # Kelly = 0.2 - 0.8/0.5 = -1.4
    result = risk_manager.kelly_size(base_amount_eur=38.0)
    assert result == 0.0
```

**4. bb_position Test**
```python
# tests/test_indicators.py
def test_bb_position():
    from core.indicators import bb_position
    vals = [100.0] * 20  # Flat → positie = 0.5
    assert bb_position(vals) == pytest.approx(0.5, abs=0.01)
    
    # Te kort → None
    assert bb_position([1.0, 2.0]) is None
```

---

## Refactoring Roadmap (Volgorde)

1. **Week 1**: Fix 1 (ML features) + Fix 2 (runtime keys) + Fix 5 (Kelly) — hoogste impact op trading performance
2. **Week 1**: Fix 3 (Telegram token) — security, doe dit direct
3. **Week 2**: Fix 6 (CB lock) + Fix 7 (HTF cache) + Fix 4 (force_refresh) — API stabiliteit en rate limits
4. **Week 3**: Fix 8 (trade lock) + Fix 9 (schema) — robustheid
5. **Week 4**: Fix 11 (dead key) + Fix 12 (placeholder) + Fix 13 (explainability) — opschoning

---

## Score Dashboard (uit analyse)

| Component | Score | Status |
|-----------|-------|--------|
| bot/api.py | 8/10 | ✅ Beste module |
| core/indicators.py | 7.5/10 | ✅ Solide |
| bot/signals.py | 7/10 | ✅ Goed |
| modules/config.py | 6.5/10 | ⚠️ Runtime keys |
| bot/trailing.py | 6/10 | ⚠️ Lock + cache |
| modules/trading_risk.py | 6/10 | ⚠️ Kelly bug |
| bot/trade_lifecycle.py | 6.5/10 | ⚠️ Okee |
| modules/trading_dca.py | 5.5/10 | ⚠️ Dead code |
| modules/ml.py | 4/10 | 🔴 Feature mismatch |
| trailing_bot.py | 5/10 | 🔴 Monolith |
| Config/Security | 4/10 | 🔴 Token exposed |
| Tests | 6/10 | ⚠️ Coverage gaps |
| **Gemiddeld** | **6.0/10** | |
