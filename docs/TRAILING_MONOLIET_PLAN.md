# 🧱 Trailing Monoliet — Refactor Plan

> **Status:** Living document — opgesteld 2026-04-30 als onderdeel van Fase 2 van [COPILOT_ROAD_TO_10.md](COPILOT_ROAD_TO_10.md).
> **Scope:** alle code rondom trailing stops, exit-logica en partial take-profit consolideren tot één heldere, getestbare module — en ze uit `trailing_bot.py` weghalen.
> **Eigenaar:** Copilot — leest dit aan begin van élke trailing-gerelateerde sessie.

---

## 0. Waarom dit plan?

Op dit moment is de trailing-logica versnipperd over minimaal 4 plekken:

| Bestand | Regels | Verantwoordelijkheid |
|---|---|---|
| [`bot/trailing.py`](../bot/trailing.py) | **753** | `calculate_stop_levels()` — stepped + ATR + DCA-mult + trend-mult, partial TP levels |
| [`bot/per_market_trailing.py`](../bot/per_market_trailing.py) | 63 | per-market overrides voor BTC/ETH/SOL |
| [`trailing_bot.py`](../trailing_bot.py) | **3758** | main loop calls `calculate_stop_levels`, hard-SL evaluatie, sell-trigger, partial-TP execution, no-loss bypass, "trailing wacht onder buy" status — verspreid over meerdere blokken |
| [`tools/dashboard_v2/backend/main.py`](../tools/dashboard_v2/backend/main.py) (`_compute_trailing_stop`) | ~30 | **dupliceert** de bot-logica voor weergave — afwijkingen mogelijk |

**Pijnpunten vandaag:**
1. **Duplicaat in dashboard.** Backend heeft eigen `_compute_trailing_stop()` die alleen STEPPED kent — geen ATR, geen DCA-mult, geen per-market override. Dashboard toont dus *andere* trailing-stop dan wat de bot intern gebruikt. Bewijs: huidige config heeft `ATR_MULTIPLIER=1.5` actief in bot, maar dashboard cijfer komt van een pct-formule.
2. **Veilig refactoren is duur.** `bot/trailing.py` heeft 0% directe unit tests (alleen integratie-tests via main loop). Elke wijziging vraagt full-bot test-run.
3. **Onleesbaar `calculate_stop_levels`.** Eén functie van ~560 regels met 12+ verantwoordelijkheden (regime adj, hard SL, activation, hw-mark, stepped levels, ATR, trend-mult, dca-mult, cost buffer, sell slippage, profit velocity, override-merging).
4. **trailing_bot.py heeft nog ~250 regels exit/sell-logica** verstrengeld met DCA-checks en order-exec. Niet apart testbaar.

---

## 1. Doel-architectuur

```
core/
  trailing_math.py        ← PURE math: ATR, stepped reduction, distance compute. 0 deps.
                            Vervangt het reken-deel van calculate_stop_levels.

bot/
  trailing/
    __init__.py           ← re-export van publieke API
    engine.py             ← dunne orchestrator: input=trade_dict+candles, output=Decision
    activation.py         ← activation rule (1.5%-boven-buy + hw bookkeeping)
    stops.py              ← hard SL + cost buffer + sell-slippage floor
    overrides.py          ← per-market + regime + DCA-mult + trend-mult merger
    decision.py           ← @dataclass TrailingDecision { trailing_stop, hard_stop, reason, debug }
    partial_tp.py         ← partial-TP levels + execute helpers (uit huidige trailing.py 281-298)
    sell_trigger.py       ← evalueert decision tegen current price → SellSignal of None
                            (verhuist uit trailing_bot.py main loop)

modules/dashboard/
  trailing_view.py        ← één plek waar dashboard EXACT hetzelfde rekent als bot
                            via core.trailing_math. Dashboard backend importeert dit.
```

**Kern-invariant:** zowel bot als dashboard roepen `core.trailing_math.compute(...)` aan. Geen duplicate logica meer.

---

## 2. Publieke API (immutable contract)

```python
# core/trailing_math.py
from dataclasses import dataclass
from typing import Optional, Sequence

@dataclass(frozen=True, slots=True)
class TrailingInput:
    buy_price: float
    highest_price: float            # high-water sinds entry (of since-activation indien actief)
    current_price: float
    trailing_active: bool
    atr_value: Optional[float]      # None → falt back op pct-only
    base_pct: float                 # bv. 0.014
    activation_pct: float           # bv. 0.015
    cost_buffer_pct: float = 0.006
    atr_multiplier: float = 1.5
    stepped_levels: Sequence[tuple[float, float]] = ()  # [(profit_pct, trail_pct), ...]
    trend_strength: float = 0.0     # ema_short - ema_long / ema_long
    dca_buys: int = 0
    market_override: Optional[dict] = None  # per-market merge

@dataclass(frozen=True, slots=True)
class TrailingDecision:
    trailing_stop: Optional[float]  # None als trailing nog niet actief
    hard_stop: float
    activation_price: float
    distance_used: Optional[float]  # debug: welke afstand werd gekozen
    source: str                     # "atr" | "pct_floor" | "stepped" | "inactive"

def compute(inp: TrailingInput, hard_sl_pct: float) -> TrailingDecision:
    """Pure functie. Geen I/O, geen state, geen logging. 100% testbaar."""
    ...
```

Alle bestaande call-sites (bot loop + dashboard) gebruiken hierna **alleen** deze functie.

---

## 3. Migratie-plan (incrementeel, tests-eerst)

### Stap 1 — Unit tests vóór refactor (1u) ✋ PIN BEHAVIOR
Schrijf `tests/test_trailing_pin.py` die de **huidige** `calculate_stop_levels()` aanroept met fixed inputs en de output snapshot. ~25 cases:
- pct-only modus (atr=None)
- ATR-only modus (atr=0.012)
- DCA-mult actief (dca_buys=2)
- per-market override aanwezig
- regime adjusted (sl_mult=0.8)
- stepped triggered (profit_pct=0.05)
- onder activation_pct (trailing inactive)
- highest_price < buy (geen trailing)

**Doel:** elke regression direct zichtbaar. Deze tests blijven groen tot eind van refactor.

### Stap 2 — Extract `core/trailing_math.py` (2u)
- Kopieer **alleen het rekenwerk** (geen I/O, geen `_open_trades` mutaties) naar nieuwe pure module
- Schrijf 30+ unit tests direct op deze pure functie
- Voeg `# noqa: imported-but-not-used` toe in `bot/trailing.py` — nog niet wisselen

### Stap 3 — Switch `bot/trailing.py` over op `core.trailing_math` (1u)
- Vervang de math-blokken in `calculate_stop_levels` door één call: `decision = core.trailing_math.compute(input)`
- Behoud de wrapping (state-mutaties zoals `trade["trailing_activated"]=True`)
- **Pin-tests uit Stap 1 moeten groen blijven** — anders rollback

### Stap 4 — Extract activation + stops + overrides (2u)
- Verplaats per-stuk: `activation.py`, `stops.py`, `overrides.py`
- Elk in eigen file met tests
- `bot/trailing.py` krimpt tot ~150 regels (alleen orchestratie)

### Stap 5 — Extract sell-trigger uit `trailing_bot.py` (2u)
- Identificeer alle blokken in main loop die zeggen "if cur ≤ trailing_stop: sell"
- Verhuis naar `bot/trailing/sell_trigger.py` als pure functie `evaluate_sell(trade, decision, cur_price) -> SellSignal | None`
- Main loop houdt alleen: `signal = sell_trigger.evaluate(...); if signal: orders.execute_sell(signal)`
- Reduceert `trailing_bot.py` met ~150-250 regels

### Stap 6 — Partial TP eruit (1u)
- `bot/trailing/partial_tp.py` krijgt `levels()` + `should_take(trade, cur)` + `execute(trade, level)`
- Main loop callsite vervangt door 3 regels

### Stap 7 — Dashboard de-duplicate (30min)
- Verwijder `_compute_trailing_stop` in `tools/dashboard_v2/backend/main.py`
- Vervang door `from core.trailing_math import compute`
- **Bewijs:** dashboard cijfer = bot cijfer (snapshot-test in `tests/test_dashboard_trailing_parity.py`)

### Stap 8 — Cleanup + docs (30min)
- Verwijder dode code in oude `bot/trailing.py`
- Update [docs/COPILOT_ROAD_TO_10.md](COPILOT_ROAD_TO_10.md) Fase 2 ✓
- FIX_LOG entry
- Commit + push per stap (8 commits totaal voor reviewability)

---

## 4. Test-strategie

| Test-type | Locatie | Waarvoor |
|---|---|---|
| **Pin tests** (snapshot) | `tests/test_trailing_pin.py` | Stap 1 — alarm bij elk gedragsverschil |
| **Pure unit tests** | `tests/test_trailing_math.py` | Stap 2 — alle math edge-cases (negatieve buy, atr=0, override leeg) |
| **Activation/stops** | `tests/test_trailing_activation.py`, `_stops.py` | Stap 4 |
| **Sell-trigger** | `tests/test_sell_trigger.py` | Stap 5 — geen orders bij None decision; sell bij price ≤ trailing |
| **Dashboard parity** | `tests/test_dashboard_trailing_parity.py` | Stap 7 — bot decision == dashboard decision voor 10 trade-fixtures |
| **Backtest regressie** | hergebruik `_backtest_atr_trailing.py` | Voor en na refactor: aggregate PnL identiek (±0.1%) |

**Acceptance:**
- Alle 806+ bestaande tests blijven groen
- 50+ nieuwe unit tests
- Backtest aggregate PnL identiek pre/post (binnen rounding)

---

## 5. Risico's & mitigaties

| Risico | Kans | Impact | Mitigatie |
|---|---|---|---|
| Pin-tests vangen niet alle paden | Medium | Hoog | Voor Stap 1: zet bot 1u in shadow-mode en log alle `(input, output)` paren naar JSONL. Gebruik die als pin-test data. |
| `_open_trades` state-mutaties stiekem afwijken | Medium | Hoog | Behoud mutaties exact in `bot/trailing/engine.py`; pure module raakt geen state aan |
| Per-market overrides werken anders na merge | Laag | Medium | Aparte test per override-pad in Stap 4 |
| Dashboard breekt (parity test) | Laag | Laag | Stap 7 is laatste stap; dashboard heeft fallback-pad in `_trades()` |
| Refactor in production tijdens open trades | Medium | Hoog | Deploy alleen na markt-rust (geen open trades) of via feature-flag `USE_NEW_TRAILING=true` |

---

## 6. Definition of Done

- [ ] `bot/trailing.py` ≤ 200 regels (was 753)
- [ ] `trailing_bot.py` minus ~300 regels (sell-trigger + partial-TP eruit)
- [ ] `core/trailing_math.py` is pure, side-effect-free, 100% test-coverage
- [ ] Dashboard `_trades()` gebruikt `core.trailing_math.compute` (geen duplicate)
- [ ] 50+ nieuwe unit tests, alle 806+ oude tests groen
- [ ] Backtest pre/post identiek binnen 0.1%
- [ ] FIX_LOG entry + COPILOT_ROAD_TO_10 update
- [ ] 1 commit per stap (8 totaal), allemaal gepushed

---

## 7. Volgorde van uitvoering (concreet)

| Sprint | Duur | Stap | Commit-msg |
|---|---|---|---|
| T1 | 1u | Pin-tests | `test(trailing): pin current behavior with 25 snapshot cases` |
| T2 | 2u | Extract `core/trailing_math.py` (no switch) | `feat(core): pure trailing_math module + 30 unit tests` |
| T3 | 1u | Switch `bot/trailing.py` over | `refactor(trailing): use core.trailing_math, pin tests green` |
| T4 | 2u | Extract activation/stops/overrides | `refactor(trailing): split into activation/stops/overrides modules` |
| T5 | 2u | Extract sell-trigger | `refactor(trailing): move sell-trigger out of monolith (-200 lines)` |
| T6 | 1u | Extract partial-TP | `refactor(trailing): extract partial_tp module (-100 lines)` |
| T7 | 30min | Dashboard de-dupe | `fix(dashboard): use core.trailing_math (no more duplicate logic)` |
| T8 | 30min | Cleanup + docs | `docs(trailing): refactor complete, COPILOT_ROAD_TO_10 fase 2 closer` |

**Totaal:** ~10u over 4-5 sessies. Geen big-bang.

---

## 8. Open vragen (voor user)

1. **Feature-flag of harde switch?** Wil je `USE_NEW_TRAILING=true` als opt-in, of vertrouwen we op de pin-tests? *(Mijn advies: pin-tests + één-commit-per-stap = veilig genoeg, geen flag nodig.)*
2. **Live shadow-log voor pin-data?** Mag ik 1-2u shadow-mode aanzetten om real-world `(input, output)` te loggen vóór Stap 1? Maakt pin-tests veel sterker.
3. **Wanneer beginnen?** Niet tijdens open RENDER positie — of juist wel (geen risico bij correct refactor)?
