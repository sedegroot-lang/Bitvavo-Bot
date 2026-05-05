"""Circuit breaker check (extracted from trailing_bot.py — road-to-10 #066 batch 5).

Pauses new entries on poor recent performance. Uses a grace period after cooldown
expires so the same bad recent stats don't immediately re-trigger a new cooldown.

Public API:
    is_active() -> tuple[bool, str]
"""

from __future__ import annotations

import json
import time
from typing import Tuple

from bot.shared import state


def is_active() -> Tuple[bool, str]:
    """Return (active, reason). Active=True blocks new entries.

    All thresholds + cooldown + grace are read from state.CONFIG.
    Mutates CONFIG keys: '_circuit_breaker_until_ts', '_cb_trades_since_reset'.
    """
    log = state.log
    cfg = state.CONFIG
    try:
        min_wr = float(cfg.get("CIRCUIT_BREAKER_MIN_WIN_RATE", 0) or 0)
        min_pf = float(cfg.get("CIRCUIT_BREAKER_MIN_PROFIT_FACTOR", 0) or 0)
        cooldown_min = int(cfg.get("CIRCUIT_BREAKER_COOLDOWN_MINUTES", 0) or 0)
        grace_trades = int(cfg.get("CIRCUIT_BREAKER_GRACE_TRADES", 5) or 5)
        if min_wr <= 0 and min_pf <= 0:
            return False, ""
        now = time.time()
        until = cfg.get("_circuit_breaker_until_ts", 0)
        if until and now < until:
            return True, f"cooldown_until={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(until))}"
        # Cooldown just expired — enter grace period
        if until and now >= until:
            trades_since = cfg.get("_cb_trades_since_reset", 0)
            if trades_since < grace_trades:
                if trades_since == 0:
                    try:
                        log(
                            f"[CIRCUIT BREAKER] Cooldown expired, grace period: {grace_trades} trades allowed before re-check",
                            level="info",
                        )
                    except Exception:
                        pass
                return False, ""
            cfg.pop("_circuit_breaker_until_ts", None)
            cfg.pop("_cb_trades_since_reset", None)
        trade_log_path = getattr(state, "TRADE_LOG", "data/trade_log.json")
        # Allow tests (and runtime hot-patches) to override TRADE_LOG on the
        # trailing_bot module without re-initialising shared state.
        try:
            import trailing_bot as _tb  # noqa: WPS433 (lazy to avoid circular)

            _tb_path = getattr(_tb, "TRADE_LOG", None)
            if _tb_path:
                trade_log_path = _tb_path
        except Exception:
            pass
        try:
            with open(trade_log_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            closed = data.get("closed", []) if isinstance(data, dict) else []
            recent = closed[-20:] if len(closed) > 20 else closed
            if not recent:
                return False, ""
            min_trades_for_cb = max(5, grace_trades)
            if len(recent) < min_trades_for_cb:
                return False, ""
            wins = [t for t in recent if t.get("profit", 0) > 0]
            losses = [t for t in recent if t.get("profit", 0) < 0]
            win_rate = len(wins) / len(recent)
            total_win = sum(t.get("profit", 0) for t in wins)
            total_loss = abs(sum(t.get("profit", 0) for t in losses))
            if total_loss > 0:
                profit_factor = total_win / total_loss
            elif total_win > 0:
                profit_factor = float("inf")
            else:
                profit_factor = 0.0
            if (min_wr > 0 and win_rate < min_wr) or (min_pf > 0 and profit_factor < min_pf):
                if cooldown_min > 0:
                    cfg["_circuit_breaker_until_ts"] = now + cooldown_min * 60
                    cfg["_cb_trades_since_reset"] = 0
                try:
                    log(
                        f"[CIRCUIT BREAKER] Active: win_rate={win_rate:.2%} (min {min_wr:.2%}), pf={profit_factor:.2f} (min {min_pf:.2f})",
                        level="warning",
                    )
                except Exception:
                    pass
                return True, f"win_rate={win_rate:.2f}, pf={profit_factor:.2f}"
        except Exception:
            return False, ""
    except Exception:
        return False, ""
    return False, ""
