"""Auto-sync thread starter (extracted from trailing_bot.py — road-to-10 #066 batch 5).

Owns its own module-level thread handle so the trailing_bot.py shim can be a
one-liner. Reads synchronizer/trades_lock/open_trades/closed_trades/market_profits
from `bot.shared.state`.
"""

from __future__ import annotations

from bot.shared import state

_auto_sync_thread = None  # type: Optional[object]


def start(*, interval: int = 60) -> None:
    """Start the auto-sync background thread (idempotent)."""
    global _auto_sync_thread
    log = state.log
    synchronizer = getattr(state, "synchronizer", None)
    if synchronizer is None:
        try:
            log("Auto-sync niet gestart: synchronizer ontbreekt.", level="debug")
        except Exception:
            pass
        return
    try:
        cfg_interval = int(state.CONFIG.get("SYNC_INTERVAL_SECONDS", 60) or 60)
    except Exception:
        cfg_interval = 60
    if interval <= 0:
        interval = max(5, cfg_interval)
    if interval <= 0:
        interval = 60
    if _auto_sync_thread is not None:
        try:
            if _auto_sync_thread.is_alive():  # type: ignore[attr-defined]
                return
        except Exception:
            pass

    trades_lock = state.trades_lock
    open_trades = state.open_trades
    closed_trades = state.closed_trades
    market_profits = state.market_profits

    def state_provider():
        with trades_lock:
            return dict(open_trades), list(closed_trades), dict(market_profits)

    def state_consumer(new_open, new_closed, new_profits):
        with trades_lock:
            open_trades.clear()
            open_trades.update(new_open)
            closed_trades[:] = list(new_closed)
            market_profits.clear()
            market_profits.update(new_profits)

    _auto_sync_thread = synchronizer.start_auto_sync(
        state_provider,
        state_consumer,
        interval=interval,
    )
    try:
        log(f"Auto-sync thread gestart (interval={interval}s).", level="info")
    except Exception:
        pass
