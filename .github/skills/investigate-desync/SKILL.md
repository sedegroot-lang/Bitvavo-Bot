---
name: investigate-desync
description: Investigate why a market's bot state (open_trades) is out of sync with Bitvavo reality (balance, order history). Use when the user reports a market with wrong amount, wrong invested_eur, missing DCAs, or "ghost" trades.
---

# Investigate-desync skill

Diagnose desync between bot trade state and Bitvavo exchange reality for a single market.

## Inputs needed
- Market symbol (e.g. `ENJ-EUR`).
- Symptom (e.g. "shows 0 DCA but I see 5 buys", "amount mismatch", "not selling").

## Investigation steps

### 1. Snapshot the bot view
Read `data/trade_log.json` — find the entry for the market. Note:
- `amount`, `buy_price`, `invested_eur`, `initial_invested_eur`
- `dca_buys`, `dca_events`, `pending_dca_order_id`
- `opened_ts`, `last_dca_ts`
- `partial_tp_returned_eur`

### 2. Snapshot the exchange view
Run a Python REPL command (or short script) to fetch:
```python
from modules.config import load_config
from python_bitvavo_api.bitvavo import Bitvavo
cfg = load_config()
bv = Bitvavo({'APIKEY': cfg['BITVAVO_API_KEY'], 'APISECRET': cfg['BITVAVO_API_SECRET']})
print(bv.balance({'symbol': '<COIN>'}))                # actual balance
print(bv.orders('<MARKET>', {}))                       # open orders
hist = bv.trades('<MARKET>', {})                       # trade history
print(len(hist), hist[:3])
```

### 3. Compare
| Field | Bot view | Exchange | Delta |
|-------|----------|----------|-------|
| amount | … | … | … |
| invested EUR (sum of fills × price + fees) | … | … | … |
| number of buy fills | … | … | … |

### 4. Categorize the desync
- **Ghost trade**: bot has it, exchange doesn't (no balance, no history).
- **Missing DCA**: exchange shows N buys, bot shows fewer.
- **Cost-basis drift**: amount matches but `invested_eur` is wrong (likely `buy_price * amount` was used somewhere instead of `derive_cost_basis`).
- **Stale pending order**: `pending_dca_order_id` set but exchange order is filled or canceled.
- **Partial-TP mismatch**: `partial_tp_returned_eur` doesn't match sells in history.

### 5. Decide remediation
- **Ghost trade** → archive it via `bot.trade_lifecycle.archive_trade(market, reason='ghost')`.
- **Missing DCA / cost-basis drift** → re-reconcile via the canonical reconcile path (call `derive_cost_basis(trade)` and merge results — see `bot/sync.py` and `modules/sync_validator.py`).
- **Stale pending** → clear `pending_dca_order_id` and let the next sync cycle reconcile.

### 6. Apply remediation safely
- Stop the bot first (kill running pythons) so it doesn't write over your changes.
- Apply the fix via a one-shot Python script (do NOT edit `data/trade_log.json` by hand — write through the lifecycle helpers so backups are created).
- Restart the bot.
- Verify next cycle sync log shows no desync warning.

### 7. Log the investigation
If a NEW class of desync was found (not in FIX_LOG), open a FIX entry — even if the remediation was data-only, document the root cause for future prevention.

## Output to user
```
Market <SYMBOL> — desync investigation
Bot view:    amount=<X>  invested=€<Y>  dca_buys=<N>
Exchange:    amount=<X>  invested=€<Y>  buy_fills=<M>
Diagnosis:   <category + one-line cause>
Action:      <what was done>
Verified:    <yes/no — next cycle clean>
```
