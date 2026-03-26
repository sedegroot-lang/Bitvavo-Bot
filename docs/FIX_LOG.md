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
