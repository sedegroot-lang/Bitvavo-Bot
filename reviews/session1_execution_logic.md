# Opus Review - Session 1: Trade Execution Logic

**Date**: 2026-02-20  
**Reviewer**: GitHub Copilot (Claude Opus 4.6)  
**Focus**: Bugs, race conditions, edge cases, risk issues in order execution  
**Files analyzed**: `bot/trailing.py`, `bot/api.py`, `trailing_bot.py`

---

## TOP 5 CRITICAL ISSUES

---

### 🔴 CRITICAL #1: No Partial Fill Verification on Buy Orders — Ghost Trades

**File**: [trailing_bot.py](trailing_bot.py#L4357-L4373)  
**Severity**: 🔴 CRITICAL — Can cause capital loss

**Problem**: After `place_buy()` succeeds, the code checks for `filledAmount` and `filledAmountQuote` in the response. But Bitvavo limit orders may return `status: "new"` with `filledAmount: "0"` — meaning the order is placed but **not yet filled**. The bot immediately records it as a fully-opened trade with the *requested* amount as fallback.

```python
# Line 4361-4373
actual_invested_eur = amt_eur  # Fallback to requested amount
actual_tokens = amt_eur / entry_price  # Fallback calculation

try:
    if isinstance(buy_result, dict):
        if 'filledAmountQuote' in buy_result:
            actual_invested_eur = float(buy_result['filledAmountQuote'])
        if 'filledAmount' in buy_result:
            actual_tokens = float(buy_result['filledAmount'])
```

**What goes wrong**:  
1. Limit order placed → response has `filledAmount: "0"`, `status: "new"`  
2. `is_order_success()` returns `True` (no error key present)  
3. Trade is recorded with `amount = amt_eur / entry_price` (estimated) and `invested_eur = amt_eur` (requested — not filled)  
4. Bot now thinks it owns tokens it doesn't have  
5. Trailing/TP logic tries to sell tokens → Bitvavo returns saldo_error  
6. After N saldo retries, trade is force-closed as a 100% loss

**Impact**: Every unfilled or partially-filled limit order becomes a phantom trade that eventually registers as a full loss.

**Fix**:
```python
# After buy_result is received, verify actual fill status
if isinstance(buy_result, dict):
    status = str(buy_result.get('status', '')).lower()
    filled_amount = float(buy_result.get('filledAmount', 0) or 0)
    
    if status in ('new', 'awaitingtrigger') and filled_amount == 0:
        # Order placed but NOT filled — do not open trade yet
        log(f"⏳ Limit order placed for {m} but not yet filled (orderId={buy_result.get('orderId')}). "
            f"Will be picked up by sync.", level='warning')
        _release_market(m)
        return {'buy_executed': False, 'order_pending': True, 
                'orderId': buy_result.get('orderId')}
    
    if filled_amount > 0 and filled_amount < (amt_eur / entry_price) * 0.95:
        # Partial fill — use actual filled amount
        actual_tokens = filled_amount
        actual_invested_eur = float(buy_result.get('filledAmountQuote', 0) or 0)
        if actual_invested_eur <= 0:
            actual_invested_eur = filled_amount * entry_price
        log(f"⚠️ Partial fill for {m}: got {filled_amount:.8f} of "
            f"~{amt_eur/entry_price:.8f} requested", level='warning')
```

---

### 🔴 CRITICAL #2: Race Condition Between Sell Check and Trade State Update

**File**: [trailing_bot.py](trailing_bot.py#L3440-L3500)  
**Severity**: 🔴 CRITICAL — Can cause duplicate sells or sell-after-close

**Problem**: The main manage loop iterates over `open_trades.keys()` and multiple exit strategies can trigger for the same trade within the same iteration. The sell-then-close pattern is non-atomic:

```python
# Line ~3440 (advanced exit)
sell_response = place_sell(m, sell_amount)
# ... network call takes 1-5 seconds ...

# Line ~3490 (after sell)
if exit_portion >= 1.0:
    _finalize_close_trade(m, t, closed_entry, ...)
    continue
else:
    t['amount'] = amt - sell_amount  # ← NOT under trades_lock
    save_trades()
```

Meanwhile, the sync thread or another iteration can also enter `place_sell()` for the same market. There's also no early mark/flag to indicate "this trade is being sold right now."

**What goes wrong**:
1. Trailing TP triggers sell for market X at line ~3630 (sends API call)
2. Before the response returns, the `time_tighten` or `advanced_exit` path also evaluates market X
3. Since `t['amount']` hasn't been decremented yet, it triggers another sell
4. Double sell → saldo_error on the second one → potential force-close-as-loss

**Fix**: Add a per-trade "sell in progress" guard:
```python
# At the top of the manage loop, after getting trade t:
if t.get('_sell_in_progress'):
    log(f"[GUARD] Sell already in progress for {m}, skipping", level='debug')
    continue

# Before every place_sell call:
t['_sell_in_progress'] = True
sell_response = place_sell(m, amt)

# After sell completes (success or failure):
t.pop('_sell_in_progress', None)
```

Additionally, the `t['amount']` modification after partial sell at line ~3500 is done **outside** `trades_lock`:
```python
# CURRENT (unsafe):
t['amount'] = amt - sell_amount
save_trades()

# FIXED (safe):
with trades_lock:
    t['amount'] = amt - sell_amount
    save_trades()
```

---

### 🔴 CRITICAL #3: `place_sell()` Returns "Chunked" Dict But Callers Expect Single Order Response

**File**: [trailing_bot.py](trailing_bot.py#L2740-L2760)  
**Severity**: 🔴 HIGH — Silently treats failed chunked sells as success

**Problem**: When slippage is high, `place_sell()` chunks the sell into multiple smaller orders and returns `{'chunked': True, 'orders': [...], 'remaining': float}`. But **every caller** checks the response like this:

```python
# Line ~3294, ~3445, ~3630, etc.
if not sell_response or sell_response.get('error') or sell_response.get('errorCode'):
    log(f"❌ SELL FAILED for {m}: ...")
    continue

sell_order_id = sell_response.get('orderId')  # ← None for chunked!
```

**What goes wrong**:
1. `place_sell()` returns `{'chunked': True, 'orders': [...], 'remaining': 0.5}`
2. `sell_response.get('error')` → None (no 'error' key), so validation passes
3. `sell_response.get('orderId')` → None, so order tracking is broken
4. `remaining: 0.5` is silently ignored — 50% of the position is NOT sold
5. Trade is closed at full amount, but only half was actually sold
6. Remaining tokens become orphan dust that's never tracked

**Fix**:
```python
def _verify_sell_response(sell_response: dict, market: str, expected_amount: float) -> tuple:
    """Returns (success: bool, order_ids: list, remaining: float)."""
    if not sell_response:
        return False, [], expected_amount
    
    if sell_response.get('error') or sell_response.get('errorCode'):
        return False, [], expected_amount
    
    if sell_response.get('chunked'):
        order_ids = []
        for o in sell_response.get('orders', []):
            if isinstance(o, dict) and o.get('orderId'):
                order_ids.append(o['orderId'])
        remaining = float(sell_response.get('remaining', 0))
        if remaining > expected_amount * 0.05:  # >5% unsold
            return False, order_ids, remaining
        return True, order_ids, remaining
    
    # Single order
    order_id = sell_response.get('orderId')
    return True, [order_id] if order_id else [], 0.0
```

---

### 🟠 HIGH #4: `save_trades()` Called Excessively Without Lock — State Corruption Risk

**File**: [trailing_bot.py](trailing_bot.py#L1294-L1350)  
**Severity**: 🟠 HIGH — Can corrupt trade_log.json

**Problem**: `save_trades()` is called ~20+ times per manage loop iteration (for each trade: DCA price init, highest_price update, breakeven lock, trailing activation etc.). Each call does:

1. Read archive file from disk
2. Run `optimize_parameters()` on all trades
3. Write heartbeat JSON
4. Write trade_log.json
5. Write config changes
6. Run `cleanup_trades()`

The `save_trades()` function takes `trades_lock` only for the brief snapshot at line 1344:
```python
with trades_lock:
    data = {"open": dict(open_trades), "closed": list(closed_trades), "profits": dict(market_profits)}
```

But between the snapshot and the actual file write, another thread could:
- Modify `open_trades` (sync thread, DCA manager)
- Call `save_trades()` itself (heartbeat writer)

Both file writes could interleave, corrupting the JSON.

**Additional concern**: `save_trades()` also calls `optimize_parameters()` on **every** invocation. This is a heavy operation that should not run 20× per loop cycle.

**Fix**:
```python
_SAVE_TRADES_LOCK = threading.Lock()
_SAVE_TRADES_DEBOUNCE_TS = 0.0
_SAVE_TRADES_MIN_INTERVAL = 2.0  # seconds

def save_trades(force: bool = False):
    global _SAVE_TRADES_DEBOUNCE_TS
    now = time.time()
    
    if not force and (now - _SAVE_TRADES_DEBOUNCE_TS) < _SAVE_TRADES_MIN_INTERVAL:
        return  # Debounce rapid saves
    
    with _SAVE_TRADES_LOCK:
        _SAVE_TRADES_DEBOUNCE_TS = now
        # ... existing save logic ...
```

And move `optimize_parameters()` out of `save_trades()` into a periodic timer (every 5-10 minutes).

---

### 🟠 HIGH #5: Sell Uses Stale Price `cp` for Profit Calculation — Not Actual Execution Price

**File**: [trailing_bot.py](trailing_bot.py#L3600-L3650)  
**Severity**: 🟠 HIGH — Profit tracking can be significantly wrong

**Problem**: Throughout the manage loop, the sell price used for profit calculation is `cp` — the price fetched at the *start* of the trade evaluation. But the actual sell is a market order that executes at whatever the current bid is. Between `get_current_price()` and `place_sell()`, seconds pass (slippage calcs, exit strategy checks, etc).

```python
# Line ~3610-3640 (trailing TP exit)
cp = get_current_price(m, force_refresh=True)  # ← fetched BEFORE exit logic
# ... 20+ lines of calculations ...
sell_response = place_sell(m, amt)  # ← executes at CURRENT market price

# But profit is calculated with:
profit = realized_profit(t.get('buy_price', 0.0), cp, amt)  # ← uses STALE cp
closed_entry = {
    'sell_price': cp,  # ← not actual execution price!
}
```

For volatile crypto markets, the price can move 1-5% in those seconds, especially during the situations that trigger stop-loss exits (flash crashes).

**Fix**: Extract actual fill price from the sell response:
```python
sell_response = place_sell(m, amt)
if not sell_response or sell_response.get('error'):
    continue

# Use actual execution price if available
actual_sell_price = cp  # fallback
if isinstance(sell_response, dict):
    if sell_response.get('price'):
        actual_sell_price = float(sell_response['price'])
    elif sell_response.get('filledAmount') and sell_response.get('filledAmountQuote'):
        filled_base = float(sell_response['filledAmount'])
        filled_quote = float(sell_response['filledAmountQuote'])
        if filled_base > 0:
            actual_sell_price = filled_quote / filled_base

profit = realized_profit(t.get('buy_price', 0.0), actual_sell_price, amt)
closed_entry['sell_price'] = actual_sell_price
```

---

## ADDITIONAL ISSUES (Lower Priority)

### 🟡 #6: `is_order_success()` Is Too Permissive

**File**: [trailing_bot.py](trailing_bot.py#L2529-L2545)

```python
def is_order_success(resp):
    if not isinstance(resp, dict):
        return False
    if 'error' in resp or 'errorCode' in resp:
        return False
    return True  # ← ANY dict without 'error' is "success"
```

A Bitvavo response with `status: "rejected"` or `status: "expired"` would pass this check. Should verify `status` field explicitly.

### 🟡 #7: No Stuck Order Detection

There's no mechanism to detect orders that are placed on Bitvavo but never fill. `get_pending_bitvavo_orders()` fetches them for slot counting, but there's no timeout/cancellation logic for orders older than X minutes. Limit orders could sit indefinitely.

**Fix**: Add a periodic cleanup in `bot_loop()`:
```python
# Cancel limit orders older than MAX_ORDER_AGE_MINUTES
for order in get_pending_bitvavo_orders():
    age_min = order['age_seconds'] / 60
    if age_min > CONFIG.get('MAX_PENDING_ORDER_AGE_MINUTES', 30):
        safe_call(bitvavo.cancelOrder, order['market'], order['orderId'])
        log(f"Cancelled stale order for {order['market']} (age: {age_min:.0f}min)")
```

### 🟡 #8: `safety_buy()` Can Double-Buy At Worse Price

**File**: [trailing_bot.py](trailing_bot.py#L4494-L4510)

```python
async def safety_buy(m, amt_eur, entry_price):
    buy_result = place_buy(m, amt_eur, entry_price)
    if not is_order_success(buy_result):
        await asyncio.sleep(2)
        buy_result = place_buy(m, amt_eur, None, order_type='market')
```

If first buy fails due to transient error but actually executed on Bitvavo's side, the second buy causes a double position. The 2-second sleep is not enough to verify the first order's status.

### 🟡 #9: `_finalize_close_trade()` Deletes Trade Before Confirming File Write

**File**: [trailing_bot.py](trailing_bot.py#L156-L195)

```python
def _finalize_close_trade(...):
    archive_trade(**closed_entry)
    closed_trades.append(closed_entry)
    del open_trades[market]  # ← deleted from memory
    if do_save:
        save_trades()  # ← if this fails, trade is lost from both open AND closed
```

If `save_trades()` throws, the trade is gone from `open_trades` but never persisted to `closed_trades` on disk.

---

## ANSWERS TO THE 7 CRITICAL QUESTIONS

| # | Question | Answer | Risk Level |
|---|----------|--------|------------|
| 1 | **Partial fills** | Not properly handled. Limit orders with 0 fill are treated as full buys (Critical #1). Sell-side partial fills in chunked mode can leave orphan tokens (Critical #3). | 🔴 |
| 2 | **Network failures + state** | `safe_call()` has retry+circuit breaker. But trade state is updated in memory BEFORE file persistence, so a crash between sell and save loses the trade (Issue #9). | 🟠 |
| 3 | **Duplicate orders** | Yes, possible. `safety_buy()` retries without checking first order status (#8). Race condition in sell path can trigger double sells (#2). | 🔴 |
| 4 | **Rate limiting** | Well implemented in `bot/api.py` with per-endpoint buckets and sliding windows. No functional issues found. | ✅ |
| 5 | **Race condition sell↔buy** | Partially mitigated by `trades_lock` on atomic sections, but sell path operates without lock during API call, and amount updates are not always locked (#2). | 🟠 |
| 6 | **Slippage** | Pre-trade slippage check is good. But realized P&L uses stale `cp` price instead of actual execution price (#5). Chunked sell slippage accounting is broken (#3). | 🟠 |
| 7 | **Stuck orders** | No detection or cancellation for stuck limit orders (#7). Orphan orders count towards MAX_OPEN_TRADES forever. | 🟡 |

---

## IMPLEMENTATION PRIORITY

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| 1 | Critical #1: Partial fill verification | 2h | Prevents ghost trades / phantom losses |
| 2 | Critical #2: Sell race condition guard | 1h | Prevents double sells |
| 3 | Critical #3: Chunked sell response handling | 2h | Prevents orphan tokens |
| 4 | High #5: Use actual execution price | 1h | Fixes profit tracking accuracy |
| 5 | High #4: save_trades() debounce | 1h | Reduces corruption risk + CPU |
| 6 | Medium #7: Stuck order cleanup | 1h | Frees up trade slots |

---

*Generated by GitHub Copilot (Claude Opus 4.6) - Session 1 Review*
