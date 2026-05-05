"""Markov Regime Transition Model — anticipates regime changes using transition probability matrix.

Simulation showed +€123 combined improvement by pre-positioning for favorable regime transitions.
Tracks historical regime→regime transitions and predicts upcoming regime shifts.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class MarkovRegimePredictor:
    """Builds and uses a regime transition matrix for anticipatory positioning."""

    def __init__(self):
        self.transitions: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.regime_history: List[Tuple[str, float]] = []  # (regime, timestamp)
        self._prob_cache: Dict[str, Dict[str, float]] = {}
        self._cache_dirty = True

    def record_regime(self, regime: str, ts: Optional[float] = None) -> None:
        """Record a regime observation. Call this every bot loop iteration."""
        ts = ts or time.time()
        if self.regime_history and self.regime_history[-1][0] == regime:
            return  # same regime, skip

        if self.regime_history:
            prev = self.regime_history[-1][0]
            self.transitions[prev][regime] += 1
            self._cache_dirty = True

        self.regime_history.append((regime, ts))

        # Trim history to last 500 transitions
        if len(self.regime_history) > 500:
            self.regime_history = self.regime_history[-500:]

    def _compute_probs(self) -> Dict[str, Dict[str, float]]:
        """Compute transition probability matrix."""
        if not self._cache_dirty and self._prob_cache:
            return self._prob_cache

        probs: Dict[str, Dict[str, float]] = {}
        for from_r, to_dict in self.transitions.items():
            total = sum(to_dict.values())
            if total > 0:
                probs[from_r] = {to_r: count / total for to_r, count in to_dict.items()}
        self._prob_cache = probs
        self._cache_dirty = False
        return probs

    def transition_probability(self, from_regime: str, to_regime: str) -> float:
        """Get P(to_regime | from_regime)."""
        probs = self._compute_probs()
        return probs.get(from_regime, {}).get(to_regime, 0.0)

    def most_likely_next(self, current_regime: str) -> Tuple[str, float]:
        """Get most likely next regime and its probability."""
        probs = self._compute_probs()
        regime_probs = probs.get(current_regime, {})
        if not regime_probs:
            return current_regime, 0.5  # no data → assume staying
        best = max(regime_probs, key=lambda k: regime_probs[k])
        return best, regime_probs[best]

    def should_anticipate_trend(self, current_regime: str, threshold: float = 0.15) -> bool:
        """Check if transitioning to trending_up is likely enough to pre-position."""
        return self.transition_probability(current_regime, "trending_up") > threshold

    def should_reduce_exposure(self, current_regime: str, threshold: float = 0.20) -> bool:
        """Check if transitioning to bearish or high_vol is likely."""
        p_bear = self.transition_probability(current_regime, "bearish")
        p_hvol = self.transition_probability(current_regime, "high_volatility")
        return (p_bear + p_hvol) > threshold

    def get_score_adjustment(self, current_regime: str) -> float:
        """Get MIN_SCORE adjustment based on anticipated regime.

        Positive = raise threshold (more selective).
        Negative = lower threshold (more trades, anticipate trend).
        """
        probs = self._compute_probs()
        regime_probs = probs.get(current_regime, {})

        if not regime_probs:
            return 0.0

        p_trend = regime_probs.get("trending_up", 0)
        p_bear = regime_probs.get("bearish", 0)
        p_hvol = regime_probs.get("high_volatility", 0)

        # If transitioning to good regime → lower min score
        if p_trend > 0.25:
            return -0.5

        # If transitioning to bad regime → raise min score
        if p_bear > 0.25 or p_hvol > 0.25:
            return 1.0

        return 0.0

    def get_matrix(self) -> Dict[str, Dict[str, float]]:
        """Return the full transition probability matrix."""
        return {k: {k2: round(v2, 3) for k2, v2 in v.items()} for k, v in self._compute_probs().items()}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transitions": {k: dict(v) for k, v in self.transitions.items()},
            "history_len": len(self.regime_history),
            "matrix": self.get_matrix(),
            "updated_at": time.time(),
        }

    def save(self, path: Optional[str] = None) -> None:
        p = Path(path) if path else Path(__file__).resolve().parent.parent / "data" / "markov_regime.json"
        try:
            tmp = p.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
            import os

            os.replace(str(tmp), str(p))
        except Exception:
            pass

    @classmethod
    def load(cls, path: Optional[str] = None) -> "MarkovRegimePredictor":
        p = Path(path) if path else Path(__file__).resolve().parent.parent / "data" / "markov_regime.json"
        instance = cls()
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                for from_r, to_dict in data.get("transitions", {}).items():
                    for to_r, count in to_dict.items():
                        instance.transitions[from_r][to_r] = count
                instance._cache_dirty = True
            except Exception:
                pass
        return instance
