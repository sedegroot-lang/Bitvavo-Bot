---
applyTo: "bot/**/*.py"
description: "bot/ package conventions — extracted bot logic"
---

# bot/ package conventions

## Imports
- Absolute imports from project root: `from modules.config import CONFIG`, `from core.indicators import sma`.
- Module aliases: `import bot.api as _api`, `import bot.signals as _signals`, `import bot.performance as _perf`, `import bot.trailing as _trail`.
- Use **deferred (lazy) imports inside functions** to break circular deps with `modules/` or `trailing_bot.py`:
  ```python
  def some_op():
      from bot.portfolio import analyse_trades  # avoid top-level circular
  ```

## Shared state
- All extracted modules access state via the singleton: `from bot.shared import state`.
- Never import globals from `trailing_bot.py` directly. The state singleton injects everything: `state.open_trades`, `state.CONFIG`, `state.bitvavo`, `state.log`, `state.trades_lock`, etc.
- Always acquire `state.trades_lock` (RLock) before reading/writing `state.open_trades`, `state.closed_trades`, or `state.market_profits`.

## API calls
- All Bitvavo calls go through `bot.api.safe_call(func, *args, **kwargs)`.
- Returns `None` on total failure — always check `if result is None: return`.
- Never call `state.bitvavo.<method>(...)` directly — bypasses retry, rate limit, circuit breaker, cache.

## Cost basis
- ALWAYS use `derive_cost_basis(trade)` from `bot.cost_basis` (or whichever module owns it) — never `buy_price * amount`.
- `initial_invested_eur` is immutable ground truth. `invested_eur` is mutable and derived from order history (includes fees).

## Error handling
- Wrap risky operations in `try/except Exception`. Never let an exception bubble up to crash the bot loop.
- Log via `state.log(msg, level='error')`. Use throttled logging for high-frequency paths.

## Concurrency
- Bot is multi-threaded (not async). Use `threading.RLock` for shared state.
- Debounce rapid duplicates with timestamps + locks.
