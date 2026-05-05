"""bot.maintenance — Periodic config tweaks + saldo error log + optimize hook.

Extracted from `trailing_bot.py` (#066 batch 3). Self-contained utilities that
were previously module-level functions in the monolith. Access shared state via
`bot.shared.state` (CONFIG, log).
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from typing import Any, Dict, List, Optional

from bot.shared import state


def _log(msg: str, level: str = "info") -> None:
    try:
        state.log(msg, level=level)
    except Exception:
        pass


def apply_dynamic_performance_tweaks() -> None:
    """Adjust key config knobs (currently MIN_SCORE_TO_BUY) based on recent PnL."""
    cfg = state.CONFIG
    try:
        from modules.trade_store import load_snapshot

        trade_log = cfg.get("TRADE_LOG", "data/trade_log.json")
        data = load_snapshot(trade_log)
    except Exception as exc:
        _log(f"Dynamische analyse trade-log mislukt: {exc}", level="warning")
        return

    closed = data.get("closed", []) if isinstance(data, dict) else []
    if not closed:
        return

    pnl_list = [t.get("profit", 0) for t in closed if isinstance(t, dict)]
    if not pnl_list:
        return

    avg_pnl = statistics.mean(pnl_list)
    # win_rate calculation kept for future use; currently only avg_pnl drives logic

    min_score = float(cfg.get("MIN_SCORE_TO_BUY", 7))
    if avg_pnl < -0.5:
        new_score = min(min_score + 0.5, 9.0)
    elif avg_pnl > 0.5:
        new_score = max(min_score - 0.5, 5.0)
    else:
        new_score = min_score

    if abs(new_score - min_score) > 0.01:
        cfg["MIN_SCORE_TO_BUY"] = new_score
        _log(f"MIN_SCORE_TO_BUY aangepast naar {new_score:.1f} (gemiddelde winst {avg_pnl:.2f} EUR).")
        payload = {"MIN_SCORE_TO_BUY": cfg.get("MIN_SCORE_TO_BUY")}
        if "BASE_AMOUNT_EUR" in cfg:
            payload["BASE_AMOUNT_EUR"] = cfg["BASE_AMOUNT_EUR"]
        try:
            with open("param_log.txt", "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now()} | {json.dumps(payload)}\n")
        except Exception as e:
            _log(f"encoding failed: {e}", level="warning")


def register_saldo_error(market: str, bitvavo_balance: Optional[dict], trade_snapshot: Optional[dict]) -> None:
    """Persist saldo errors for later inspection / flood detection."""
    import time

    cfg = state.CONFIG
    entry: Dict[str, Any] = {
        "market": market,
        "timestamp": time.time(),
        "bitvavo_balance": bitvavo_balance,
        "trade_snapshot": trade_snapshot,
    }
    max_entries = int(cfg.get("SALDO_ERROR_MAX_LOG", 200))
    try:
        from modules.json_compat import write_json_compat
        from modules.logging_utils import file_lock

        with file_lock:
            try:
                with open("data/pending_saldo.json", "r", encoding="utf-8") as fh:
                    pending = json.load(fh)
                if not isinstance(pending, list):
                    pending = []
            except Exception:
                pending = []
            pending.append(entry)
            if max_entries > 0:
                pending = pending[-max_entries:]
            write_json_compat("data/pending_saldo.json", pending, indent=2)
    except Exception as exc:
        _log(f"Fout bij registreren saldo_error voor {market}: {exc}", level="error")


def optimize_parameters(trades: List[Dict[str, Any]]) -> None:
    """Hook for future parameter optimization based on trade history.

    Currently a no-op besides logging — `apply_dynamic_performance_tweaks()`
    handles the actual MIN_SCORE adjustments today.
    """
    try:
        if not trades or len(trades) < 5:
            return
        _log(f"[OPTIMIZE] Analyzed {len(trades)} trades for parameter optimization", level="debug")
    except Exception as e:
        _log(f"[ERROR] Parameter optimization failed: {e}", level="warning")
