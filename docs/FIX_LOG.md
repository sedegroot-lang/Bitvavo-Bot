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
