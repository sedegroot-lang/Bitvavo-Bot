# -*- coding: utf-8 -*-
"""Per-market post-loss cooldown.

Empirical data (159 clean trades March-April 2026):
- Re-entry within  1h after a loss: WR  0%, EV -0.79 EUR  (n=11)
- Re-entry within 1-4h after loss : WR 25%, EV -1.13 EUR  (n= 8)
- Re-entry within 4-24h after loss: WR 46%, EV -0.45 EUR  (n=26)
- Re-entry  >24h after loss      : WR 63%, EV -0.78 EUR  (n=102)
- Re-entry within 1h overall     : WR 81%, EV +2.12 EUR  (n=177)

Conclusion: Re-entering a market shortly after a LOSS is a proven money-loser.
Re-entering after a WIN is fine. Hence a *conditional* cooldown.

This module records every closed trade and gates entries on the same market
during the cooldown window if the previous outcome was negative.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Mapping, Optional

# Defaults — overridable via config
DEFAULT_COOLDOWN_AFTER_LOSS_SEC = 4 * 3600  # 4 hours
DEFAULT_COOLDOWN_AFTER_BIG_LOSS_SEC = 24 * 3600  # 24h after >5 EUR loss
DEFAULT_BIG_LOSS_THRESHOLD_EUR = 5.0


class PostLossCooldown:
    def __init__(self, persistence_path: Optional[Path] = None):
        self._lock = threading.RLock()
        self._last_close: Dict[str, Dict[str, float]] = {}
        self._path = Path(persistence_path) if persistence_path else None
        self._dirty_count = 0
        self._load()

    # ── persistence ──
    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                with self._lock:
                    self._last_close = {
                        str(k): {"ts": float(v.get("ts", 0)), "profit": float(v.get("profit", 0))}
                        for k, v in raw.items()
                        if isinstance(v, dict)
                    }
        except Exception:
            pass

    def _save_locked(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._last_close, f, indent=2)
            os.replace(tmp, self._path)
        except Exception:
            pass

    # ── public API ──
    def record_close(self, market: str, profit: float, ts: Optional[float] = None) -> None:
        ts = float(ts if ts is not None else time.time())
        with self._lock:
            self._last_close[market] = {"ts": ts, "profit": float(profit)}
            self._dirty_count += 1
            if self._dirty_count >= 5:
                self._save_locked()
                self._dirty_count = 0

    def is_blocked(self, market: str, *, cfg: Mapping | None = None, now: Optional[float] = None) -> tuple[bool, str]:
        """Return (blocked, reason). Only blocks after a LOSS."""
        cfg = cfg or {}
        if not bool(cfg.get("POST_LOSS_COOLDOWN_ENABLED", True)):
            return False, "disabled"

        with self._lock:
            entry = self._last_close.get(market)
        if not entry:
            return False, "no_history"

        last_profit = float(entry.get("profit", 0))
        if last_profit >= 0:
            return False, "last_was_win"

        now = float(now if now is not None else time.time())
        elapsed = now - float(entry.get("ts", 0))

        big_thr = float(cfg.get("POST_LOSS_BIG_LOSS_EUR", DEFAULT_BIG_LOSS_THRESHOLD_EUR))
        if abs(last_profit) >= big_thr:
            cooldown = float(cfg.get("POST_LOSS_BIG_COOLDOWN_SEC", DEFAULT_COOLDOWN_AFTER_BIG_LOSS_SEC))
            label = "big_loss"
        else:
            cooldown = float(cfg.get("POST_LOSS_COOLDOWN_SEC", DEFAULT_COOLDOWN_AFTER_LOSS_SEC))
            label = "loss"

        if elapsed < cooldown:
            remaining_min = (cooldown - elapsed) / 60.0
            return True, f"{label} {last_profit:+.2f}E, {remaining_min:.0f}min remaining"
        return False, "cooldown_elapsed"

    def stats(self) -> dict:
        with self._lock:
            return {"tracked_markets": len(self._last_close)}

    def force_save(self) -> None:
        with self._lock:
            self._save_locked()
            self._dirty_count = 0


# Module singleton — initialized lazily by the bot
_instance: Optional[PostLossCooldown] = None


def get_instance(persistence_path: Optional[Path] = None) -> PostLossCooldown:
    global _instance
    if _instance is None:
        _instance = PostLossCooldown(persistence_path)
    return _instance


def reset_instance() -> None:  # for tests
    global _instance
    _instance = None
