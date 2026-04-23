# ULTRA-DEEP PROFIT MAXIMIZATION PROMPT — BITVAVO TRADING BOT
> **Voor: Claude Opus (meest recente versie)** | Gemaakt: 23 april 2026
> **Vorige prompt**: `docs/claude_opus_analysis_prompt.md` (basis architectuuranalyse, maart 2026)
> **Focus van DEZE prompt**: WINSTMAXIMALISATIE — draai -€26/week om naar +€50/week

---

## KRITISCHE CONTEXT: DE BOT VERLIEST GELD

Dit is het centrale probleem dat je moet oplossen:

| Metric | Waarde | Probleem |
|--------|--------|---------|
| **Netto resultaat** | **-€26/week** | Ondanks 194 dagen data en 1.130+ trades |
| **Winrate** | 57.1% | Lijkt goed, maar… |
| **Gem. winst per trade** | **€2.91** | Te laag |
| **Gem. verlies per trade** | **-€5.61** | **Bijna 2× de winst** |
| **Verwachte waarde per trade** | **-€0.75** | 0.57×2.91 + 0.43×(-5.61) = NEGATIEF |
| **Beschikbare markten** | 429 EUR-paren | Bitvavo |
| **Gescande markten** | ~15 | **3.5% dekking** |
| **DCA gebruik** | 3.6% | 96.4% trades krijgt 0 DCA |

### Kerndiagnose
De bot heeft een **fundamenteel negatieve expected value per trade**. Meer trades maken het erger, niet beter. Het probleem zit in één van deze drie oorzaken (of alle drie):
1. **Verkeerde entries** — te vroeg instappen, slechte marktomstandigheden
2. **Verkeerde exits** — stops te strak of stops te ruim (en de prijs daalt door)  
3. **Verkeerde markten** — scant de 15 meest bekende/liquide markten in plaats van kansen

---

## JOUW TAAK ALS EXPERT

Je bent een **quantitative trading systems architect** met expertise in:
- Python crypto-trading bots op Bitvavo
- Trailing stop optimalisatie voor mean-reverting & trending markten
- ML-gedreven signaalsystemen (XGBoost, LSTM, RL)
- Statistisch winstanalyse van echte trade-archives
- Productie-grade codebase refactoring

**Voer een meedogenloze, analytische deep-dive uit** op de volledige codebase. Lees ALLE bestanden die hieronder staan. Jouw doel is NIET architectuur verbeteren — jouw doel is elke euro meer winst per week.

**Deliverable**: Een geprioriteerde lijst van concrete implementaties, van hoogste naar laagste winstimpact, met werkende Python code die Claude Sonnet 4.6 direct kan implementeren.

---

## BESTANDEN OM TE LEZEN

### Prioriteit 1 — Winst-kritieke bestanden (lees deze EERST)
```
docs/STRATEGY_IDEAS_COMPLETE.md      (8 ideeën met backtests en P&L projecties — BELANGRIJK)
docs/PORTFOLIO_ROADMAP_V2.md         (huidige config, mijlpalen, portfolio toestand)
docs/FIX_LOG.md                      (34 bekende bugs — vermijd re-introductie)
data/trade_archive.json              (echte historische trades — voor eigen analyse)
data/trade_pnl_history.jsonl         (P&L tijdlijn — voor trend analyse)
```

### Prioriteit 2 — Kernlogica
```
trailing_bot.py                      (~4300 regels — de hoofdmonoliet, scan op TODO/FIXME/hacks)
bot/trailing.py                      (7-level stepped trailing, partial TP)
bot/signals.py                       (signal scoring + ML gate)
modules/trading_dca.py               (DCA manager — 96.4% ongebruikt, waarom?)
modules/ml.py                        (XGBoost + LSTM + RL ensemble)
core/regime_engine.py                (4 regimes, parameter aanpassing)
core/kelly_sizing.py                 (half-Kelly + volatility parity)
modules/trading_risk.py              (risk management, circuit breakers)
```

### Prioriteit 3 — Signaalgevers
```
modules/signals/__init__.py          (plugin registratie)
modules/signals/base.py              (SignalContext, SignalResult protocol)
modules/signals/range_signal.py
modules/signals/volatility_breakout_signal.py
modules/signals/mean_reversion_signal.py
modules/signals/mean_reversion_scalper_signal.py
modules/signals/ta_confirmation_signal.py
```

### Prioriteit 4 — Infrastructure
```
bot/api.py                           (rate limiting, circuit breaker, safe_call)
bot/orders_impl.py                   (buy/sell executie)
modules/grid_trading.py              (grid trading — BTC-EUR, recent 3 bugs gefixd)
core/shadow_tracker.py               (shadow mode — velocity filter tracking)
modules/trading_monitoring.py
modules/config.py                    (3-laags config merge)
config/bot_config.json               (actuele bot config)
```

### Prioriteit 5 — Tests & AI
```
tests/test_bot_trailing.py
tests/test_signal_providers.py
tests/test_trading_behaviors.py
ai/ai_supervisor.py
ai/suggest_rules.py
ai/xgb_auto_train.py
```

---

## HUIDIGE CONFIG (23 april 2026 — V2 €1.450 phase)

```json
{
  "MAX_OPEN_TRADES": 4,
  "BASE_AMOUNT_EUR": 320,
  "DCA_MAX_BUYS": 2,
  "DCA_AMOUNT_EUR": 20,
  "DCA_SIZE_MULTIPLIER": 0.9,
  "DCA_DROP_PCT": 0.025,
  "MIN_SCORE_TO_BUY": 8.0,
  "DEFAULT_TRAILING": 0.022,
  "TRAILING_ACTIVATION_PCT": 0.025,
  "TAKE_PROFIT_ENABLED": false,
  "HARD_SL_ALT_PCT": 0.25,
  "GRID_TRADING": {
    "enabled": false
  }
}
```

**Portfolio snapshot (23 april 2026)**:
- Totale portfolio: ~€1.450
- Vrij EUR: ~€144
- Grid trading: UITGESCHAKELD (V2 strategie = pure trailing+DCA)
- Open trailing trades: 2 stuks (~€1.117 geïnvesteerd)

---

## BEKENDE PROBLEMEN (uit 34 fix log entries — VERMIJD DEZE TE RE-INTRODUCEREN)

### Kritieke bugs die al zijn gefixd (verander ze NIET terug):
- **#001**: `derive_cost_basis` moet ALTIJD volledige order history ophalen — nooit filteren op `opened_ts`
- **#006**: `dca_buys` inflatie via `buy_order_count` — fix was `dca_buys = len(events)`
- **#007**: Event-sourced DCA state via `core/dca_state.py` — `dca_buys` altijd via events
- **#021**: Bitvavo API gebruikt `minOrderInBaseAsset` — NIET `minOrderSize`/`minOrderAmount`
- **#033**: Grid counter-orders op dezelfde prijs geplaatst (3 bugs, opgelost)
- **#034**: ISO timestamp strings in `closed_trades` kunnen niet worden omgezet met `float()`

### Architectuurregels (nooit schenden):
- `invested_eur` altijd via `derive_cost_basis()` — NOOIT `buy_price * amount`
- Config wijzigingen ALLEEN naar `%LOCALAPPDATA%/BotConfig/bot_config_local.json`
- `MAX_OPEN_TRADES` minimum is 3 (enforced in ai_supervisor + suggest_rules)
- `MIN_SCORE_TO_BUY` stays at 7.0 — alleen verlagen als user dit expliciet vraagt

---

## ANALYSE-OPDRACHTEN — IN DEZE VOLGORDE

### FASE A: DIAGNOSE VAN HET VERLIES (-€26/week)

**A1. Trade outcome analyse**
Lees `data/trade_archive.json` en voer zelf een statistische analyse uit:
- Verdeel trades in buckets: winst < €0, €0-€5, €5-€10, €10+
- Verdeel verlies-trades: stop_loss vs trailing_stop vs saldo_error vs sync_removed
- Per markt: welke markten hebben stelselmatig negatieve P&L?
- Tijdsverdeling: welke uren van de dag hebben de meeste verlies-trades?
- Verlies-trades: gemiddelde houdduur vs winst-trades?

**A2. Expected value berekening**
Bereken de exacte EV per signaal-provider afzonderlijk (als die data beschikbaar is in trades):
- `score` field in trade dict → correleer met uitkomst
- Zijn trades met score ≥ 8 winstgevender dan score 7.0-7.9?
- Zijn er specifieke `opened_regime` waarden die consistent verliezen?

**A3. DCA paradox**
DCA gebruik is 3.6% — 96.4% trades krijgt nul DCA. Dit kan twee dingen betekenen:
1. De DCA drempel (2.5% dip) wordt bijna nooit bereikt → price-action is vlakker dan gedacht
2. Trades worden gesloten (stop-loss) VOORDAT DCA kan triggeren

Analyseer: welk percentage van verliezende trades had een maximale daling KLEINER DAN 2.5% voor sluiting? Als dit > 50% is, zijn de stops te strak ingesteld.

**A4. Trailing stop calibratie**
Analyseer de trailing stop logica in `bot/trailing.py`:
- Wat is de gemiddelde daling van `highest_price` tot `sell_price` bij trailing_stop exits?
- Wat is de gemiddelde daling van `buy_price` tot `sell_price` bij stop_loss exits?
- Vergelijk TRAILING_ACTIVATION_PCT (2.0%) met de daadwerkelijk behaalde activatie
- Hoeveel trades activeren de trailing maar worden alsnog verliezend gesloten?

---

### FASE B: QUICK WIN ANALYSE (Strategie-ideeën uit docs/STRATEGY_IDEAS_COMPLETE.md)

**B1. Timing Filter (Idee #3 — 30 minuten implementatie)**
Data toont: 13:00-17:00 heeft 40% winrate, avg -7.1% vs 00:00-06:00 met 80% winrate.
- Verifieer deze data in het trade archive
- Ontwerp de implementatie: waar in `trailing_bot.py` of `bot/signals.py` wordt de entry geblokkeerd?
- Schrijf de volledige implementatie inclusief tests
- Zorg voor config key (`DISABLE_ENTRY_HOURS = [[13, 17]]`) in het 3-laags systeem

**B2. Velocity Filter (Idee #1 — 2 uur implementatie)**
Blokkeer markten met negatief 30-daags P&L.
- Is `core/shadow_tracker.py` al de basis hiervoor? Zo ja, wat ontbreekt er nog?
- Ontwerp een `market_velocity_score(market, trade_archive, window_days=30)` functie
- Schrijf de vollledige implementatie met correcte timestamp handling (zie bug #034: gebruik `_parse_ts()`)
- Integreer in het entry-filter systeem

**B3. Dynamic Market Scanner (Idee #4 — 1 dag implementatie)**
Bot scant 15 van 429 markten. De kansen zitten elders.
- Schrijf een `scan_universe()` functie die `ticker24h` voor alle markten ophaalt (1 API call)
- Bereken opportunity score = `volume_24h × (high - low) / low` (% beweegruimte × volume)
- Sla top-50 op als roterend watchlist
- Integreer met `MARKET_WHITELIST` config mechanisme

---

### FASE C: ML PIPELINE EVALUATIE

**C1. Is het ML-model werkelijk nuttig?**
- Lees `modules/ml.py` volledig — wat voorspelt het model precies?
- Welke features worden gebruikt? Matchen deze met wat live gecomputed wordt?
- Controleer: kan het model silent failures hebben (feature mismatch, stale model)?
- Bereken: wat was de winrate van trades waarbij ML de score verhoogde vs. verlaagde?

**C2. XGBoost feature importance**
- Lees `ai/xgb_auto_train.py` en `ai/xgb_train_enhanced.py`
- Welke features zijn de top-5 voorspellers? Zijn dit zinvolle features?
- Is er overfitting? (Vergelijk train accuracy vs. trade resultaten in productie)
- Is er een `feature_names.pkl` of vergelijkbare opslag? Zo niet — dit is een bug.

**C3. RL Agent**
- Wat leert de RL-agent precies? Wat zijn de states, acties en rewards?
- Wordt de RL-agent correct gereset bij herstart?
- Is de reward function op winst gebaseerd of op iets anders?

---

### FASE D: GRID TRADING ANALYSE

**D1. Grid profitabiliteit**
- Is de grid trading winstgevend? Bereken grid P&L uit `data/grid_states.json`
- Met €184 geïnvesteerd in BTC grid: wat is de gerealiseerde P&L? (fee-gecorrigeerd)
- BTC heeft veel hoge fees bij kleine orders. Zijn de grid spreads breed genoeg?
- Na fix #033 (counter-orders bug): zijn er legacy-states die nog steeds het probleem hebben?

**D2. Grid vs Trailing trade budget**
- Budget RESERVATION: grid_pct 15%, trailing 85%
- Met 5 trails × (€62 + 2× €30 DCA) = €610 typisch + €150 grid = €760 van €1.228
- Is er budget voor DCA als alle 5 slots actief zijn EN grid actief is?

---

### FASE E: SYSTEEM-BREDE RISICO'S

**E1. Saldo fouten kosten geld**
In de PORTFOLIO_ROADMAP_V2 staat: "Bug-gerelateerd verlies: −€1.713 uit 336 trades (saldo_flood_guard, sync_removed, saldo_error)".
- Zijn deze bugs volledig gefixd? Kunnen ze nog steeds voorkomen?
- Wat triggert `saldo_error` trades? Zijn er recent (laatste 2 weken) saldo_error trades?
- Wat is de exacte trigger voor `sync_removed`? Is DISABLE_SYNC_REMOVE=True effectief?

**E2. Race conditions**
- Kunnen trailing_check en DCA_check concurrent hetzelfde trade-object muteren?
- Worden `state.trades_lock` (RLock) correct gebruikt bij alle trade-mutaties?
- Zijn er unlocked reads van `state.open_trades` buiten de lock?

**E3. API timeouts**
- `bot/api.py`: 10-seconde timeout per API call — correct voor Windows
- Worden circuit breaker opens correct gelogd? Hoeveel circuit-breaker opens zijn er de afgelopen week?
- Wordt `None` return van `safe_call` overal correct afgehandeld?

---

### FASE F: CONCRETE IMPLEMENTATIEPLAN

Na je analyse, lever het volgende:

#### F1. Winstimpact ranking
Maak een tabel van ALLE gevonden problemen en ideeën, gesorteerd op geschatte winstimpact:

```
| # | Probleem/Idee | Winstimpact/week | Implementatietijd | Prioriteit |
|---|--------------|-----------------|-------------------|------------|
| 1 | ...          | +€X tot +€Y     | X uur             | KRITIEK    |
```

#### F2. Top-3 implementaties (volledig uitgewerkt)
Kies de 3 verbeteringen met de hoogste verwachte winstimpact en schrijf de **volledige implementatie**:

Voor elke implementatie:
```python
# Exacte bestandsnaam: modules/timing_filter.py (of waar ook past)
# Exacte functienaam en signature
# Volledige werkende code
# Integratiepunt: regel ~XXXX in trailing_bot.py
# Config key: TIMING_FILTER_HOURS = [[13, 17]]
# Test: tests/test_timing_filter.py
```

#### F3. Config aanpassingen
Stel de optimale config voor (als wijzigingen gerechtvaardigd zijn door je analyse):
```json
{
  "MIN_SCORE_TO_BUY": X,          // verander alleen als statistisch onderbouwd
  "DEFAULT_TRAILING": X,           // verander alleen als trailing analyse aantoont dat het beter kan
  "TRAILING_ACTIVATION_PCT": X,    // id.
  "DCA_DROP_PCT": X,               // id.
  "HARD_SL_ALT_PCT": X             // dit is 25% — erg ruim, is dit juist?
}
```

#### F4. Stap-voor-stap roadmap
Een weekplanning van 4 weken om van -€26/week naar +€30/week te komen:

```
Week 1 (dag 1-2): Quick Wins — Timing Filter + Velocity Filter
  - Verwacht: -€26 → +€0 tot +€10/week
  - Metric om te meten: winrate 57% → 65%+

Week 2 (dag 3-7): Market Expansion — Dynamic Market Scanner
  - Verwacht: +€0-10 → +€15-25/week
  - Metric: trades/week van ~15 naar ~30

Week 3: ML Optimalisatie / Signal Decay
Week 4: Grid optimalisatie / Kapitaalefficiëntie
```

---

## EVALUATIECRITERIA

Beoordeel elk onderdeel op:

1. **Winstimpact** (0-10): Hoeveel €/week verbetert dit direct?
2. **Veiligheid** (0-10): Kan dit bestaande wins kapotmaken?
3. **Complexiteit** (0-10): Hoe moeilijk te implementeren zonder nieuwe bugs?
4. **Urgentie** (KRITIEK / HOOG / MEDIUM / LAAG)

---

## TECHNISCHE RICHTLIJNEN VOOR IMPLEMENTATIES

### Code kwaliteitsregels (verplicht)
- Lijnlengte: max 120 tekens (Black formatter)
- Type hints overal (`from __future__ import annotations`)
- Atomic writes: altijd `tmp + os.replace()` voor JSON
- Thread-safe: `state.trades_lock` bij trade mutaties
- `safe_call()` voor alle Bitvavo API calls — None-check na elke call
- Logging in Dutch (bestaande modules) of Engels (nieuwe modules)

### Config-toegang (verplicht patroon)
```python
from bot.helpers import as_float, as_int, as_bool
from modules.config import CONFIG

# Correct:
threshold = as_float(CONFIG.get('MY_NEW_KEY', 0.025))

# FOUT (nooit doen):
threshold = CONFIG['MY_NEW_KEY']  # kan KeyError geven
threshold = float(CONFIG.get('MY_NEW_KEY'))  # kan None zijn
```

### Timestamp-veilig (verplicht — zie Bug #034)
```python
def _parse_ts(val) -> float:
    """Verwerk zowel unix float als ISO string timestamps."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        from datetime import datetime
        try:
            return datetime.fromisoformat(val).timestamp()
        except ValueError:
            return 0.0
    return 0.0
```

### Import conventies
```python
# Absolute imports vanaf project root
from modules.config import load_config, CONFIG
from bot.helpers import as_float
from core.indicators import rsi, macd

# Binnen een package: relatieve imports
from .base import SignalContext, SignalResult
```

### Signal providers (nieuw patroon)
```python
# modules/signals/mijn_signal.py
from __future__ import annotations
from .base import SignalContext, SignalResult, _safe_cfg_float

def mijn_signal(ctx: SignalContext) -> SignalResult:
    threshold = _safe_cfg_float(ctx.config, 'MIJN_DREMPEL', 0.5)
    # ... logica ...
    return SignalResult(name="mijn_signal", score=score, active=active, reason=reason)
```

---

## OUTPUT FORMAT

Structureer je volledige antwoord als volgt:

```
## EXECUTIVE SUMMARY
[3-5 zinnen: wat is het hoofdprobleem en wat is de oplossing?]

## DIAGNOSE: WAAROM -€26/WEEK
[Statistische analyse op basis van trade archive + code analyse]

## GEVONDEN PROBLEMEN (gesorteerd op winstimpact)
[Tabel met alle problemen en verwachte impact]

## IMPLEMENTATIE 1: [Naam]
[Volledige code + tests + integratie + config keys]

## IMPLEMENTATIE 2: [Naam]
[Volledige code + tests + integratie + config keys]

## IMPLEMENTATIE 3: [Naam]
[Volledige code + tests + integratie + config keys]

## CONFIG AANPASSINGEN
[JSON met aanbevolen wijzigingen en statistisch onderbouwing]

## 4-WEKEN ROADMAP
[Week-voor-week plan met meetbare doelen]

## WAT NIET TE DOEN
[Anti-patterns en waarschuwingen op basis van de 34 bekende bugs]
```

---

## AANVULLENDE CONTEXT

### Architectuur samenvatting
- **Python 3.13, Windows-first** (OneDrive paden, thread-based timeouts)
- **Monoliet**: `trailing_bot.py` (~4300 regels) + extracted `bot/`, `core/`, `modules/`, `ai/` packages
- **State**: `bot/shared.py` singleton — alle modules via `state.open_trades`, `state.CONFIG`
- **Config**: 3-laags: `bot_config.json` < `bot_config_overrides.json` < `%LOCALAPPDATA%/BotConfig/bot_config_local.json`
- **Persistence**: `data/trade_log.json`, `data/trade_archive.json`, `data/grid_states.json`

### Wat NIET te doen
- Geen `MIN_SCORE_TO_BUY` verlagen zonder statistisch bewijs (staat op 7.0 LOCKED)
- Geen `MAX_OPEN_TRADES` onder 3 (minimum enforcement in codebase)
- Geen config wijzigingen in `bot_config.json` (OneDrive reverts dat bestand)
- Geen `invested_eur = buy_price * amount` — altijd `derive_cost_basis()`
- Geen bare `float()` op timestamps — altijd `_parse_ts()`

### Reeds geïmplementeerd (hoeft niet opnieuw)
- Shadow tracker (`core/shadow_tracker.py`) — velocity filter basis, maar incompleet
- Regime engine (`core/regime_engine.py`) — 4 regimes, al actief
- Kelly sizing (`core/kelly_sizing.py`) — al geïntegreerd
- 7-level stepped trailing (`bot/trailing.py`) — al werkend
- Event-sourced DCA state (`core/dca_state.py`) — al werkend na Fix #007

---

*Prompt versie: 2.0 | Gemaakt door: GitHub Copilot (Claude Sonnet 4.6) | 23 april 2026*
*Gebaseerd op: 1.130+ echte trades, 194 dagen data, 34 bekende bugs, 8 strategie-analyses*
