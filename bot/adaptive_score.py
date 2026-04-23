# -*- coding: utf-8 -*-
"""Adaptive MIN_SCORE_TO_BUY based on rolling 7-trade win-rate.

Empirical data (759 clean trades since 2026-03-01):
- Rolling 7-trade WR < 50% → next-trade EV -0.28, WR 34%  (n=263)
- Rolling 7-trade WR 50-65% → next-trade EV -0.46, WR 49% (n= 79)
- Rolling 7-trade WR 65-80% → next-trade EV +2.75, WR 61% (n= 80)
- Rolling 7-trade WR >= 80% → next-trade EV +3.03, WR 92% (n=330)
- After 3+ consecutive losses: WR 27%, EV -0.52 (n=78)

Conclusion: When the bot is in a slump, the next trade is heavily negative-EV.
Bumping the entry threshold (MIN_SCORE_TO_BUY) lets only the highest-conviction
signals through, dramatically improving WR during slumps.

The adjustment is *additive* on top of the configured base MIN_SCORE_TO_BUY.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Mapping, Optional, Tuple


class AdaptiveScoreThreshold:
    def __init__(self, lookback: int = 7):
        self._lock = threading.RLock()
        self._lookback = max(3, lookback)
        # store tuples (ts, profit_eur)
        self._closes: Deque[Tuple[float, float]] = deque(maxlen=self._lookback)

    def record_close(self, profit: float, ts: Optional[float] = None) -> None:
        with self._lock:
            self._closes.append((float(ts if ts is not None else time.time()),
                                 float(profit)))

    def _compute_state_locked(self) -> Tuple[int, float, int]:
        """Return (n, win_rate, current_loss_streak)."""
        n = len(self._closes)
        if n == 0:
            return 0, 1.0, 0
        wins = sum(1 for _, p in self._closes if p > 0)
        wr = wins / n
        # Current loss streak (from the right)
        streak = 0
        for _, p in reversed(self._closes):
            if p < 0:
                streak += 1
            else:
                break
        return n, wr, streak

    def adjustment(self, *, cfg: Mapping | None = None) -> Tuple[float, str]:
        """Return (score_delta, reason). Positive delta = harder to enter."""
        cfg = cfg or {}
        if not bool(cfg.get('ADAPTIVE_SCORE_ENABLED', True)):
            return 0.0, 'disabled'

        with self._lock:
            n, wr, streak = self._compute_state_locked()

        # Need at least N trades to act
        min_n = int(cfg.get('ADAPTIVE_SCORE_MIN_HISTORY', 5))
        if n < min_n:
            return 0.0, f'warmup ({n}/{min_n})'

        # Loss-streak override (strongest signal)
        streak_thr = int(cfg.get('ADAPTIVE_SCORE_LOSS_STREAK', 3))
        streak_bump = float(cfg.get('ADAPTIVE_SCORE_STREAK_BUMP', 2.0))
        if streak >= streak_thr:
            return streak_bump, f'loss_streak={streak}'

        # WR-based ladder
        bump_low = float(cfg.get('ADAPTIVE_SCORE_BUMP_LOW_WR', 1.5))    # WR < 50%
        bump_mid = float(cfg.get('ADAPTIVE_SCORE_BUMP_MID_WR', 0.5))    # WR 50-65%
        relax_high = float(cfg.get('ADAPTIVE_SCORE_RELAX_HIGH_WR', -0.5))  # WR >= 80%

        if wr < 0.50:
            return bump_low, f'rolling_wr={wr:.0%} (low)'
        if wr < 0.65:
            return bump_mid, f'rolling_wr={wr:.0%} (mid)'
        if wr >= 0.80:
            return relax_high, f'rolling_wr={wr:.0%} (high)'
        return 0.0, f'rolling_wr={wr:.0%} (normal)'

    def stats(self) -> dict:
        with self._lock:
            n, wr, streak = self._compute_state_locked()
            return {'lookback': self._lookback, 'n': n,
                    'rolling_wr': wr, 'loss_streak': streak,
                    'recent_pnl': sum(p for _, p in self._closes)}


_instance: Optional[AdaptiveScoreThreshold] = None


def get_instance(lookback: int = 7) -> AdaptiveScoreThreshold:
    global _instance
    if _instance is None:
        _instance = AdaptiveScoreThreshold(lookback=lookback)
    return _instance


def reset_instance() -> None:  # for tests
    global _instance
    _instance = None
