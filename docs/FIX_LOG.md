# Fix Log — Bitvavo Trading Bot

> **IMPORTANT**: Every Copilot session MUST read this file before making any fix.
> Check if the issue has been addressed here before. After fixing a bug, log it below.

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
