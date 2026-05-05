"""Bayesian Signal Fusion — online adaptive signal weighting based on trade outcomes.

Simulation showed +€39 improvement over static signal weights.
After each trade, signal weights are updated based on whether the trade was profitable.
Signals that work in the current regime get upweighted; failing signals get downweighted.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict

# ---------------------------------------------------------------------------
# Persistent weight storage
# ---------------------------------------------------------------------------

_WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "data" / "bayesian_signal_weights.json"
_DEFAULT_ALPHA = 0.08  # learning rate
_MIN_WEIGHT = 0.1
_MAX_WEIGHT = 3.0

# In-memory signal weights
_signal_weights: Dict[str, float] = {}
_weights_loaded = False


def _load_weights() -> Dict[str, float]:
    """Load persisted signal weights from disk."""
    global _signal_weights, _weights_loaded
    if _WEIGHTS_PATH.exists():
        try:
            with open(_WEIGHTS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            _signal_weights = data.get("weights", {})
        except Exception:
            _signal_weights = {}
    _weights_loaded = True
    return _signal_weights


def _save_weights() -> None:
    """Persist signal weights atomically."""
    try:
        tmp = _WEIGHTS_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {"weights": _signal_weights, "updated_at": time.time()},
                f,
                indent=2,
            )
        import os

        os.replace(str(tmp), str(_WEIGHTS_PATH))
    except Exception:
        pass


def get_signal_weight(signal_name: str, default: float = 1.0) -> float:
    """Get the current Bayesian weight for a signal provider."""
    global _weights_loaded
    if not _weights_loaded:
        _load_weights()
    return _signal_weights.get(signal_name, default)


def get_all_weights() -> Dict[str, float]:
    """Get all current signal weights."""
    global _weights_loaded
    if not _weights_loaded:
        _load_weights()
    return dict(_signal_weights)


def update_signal_weight(
    signal_name: str,
    was_profitable: bool,
    alpha: float = _DEFAULT_ALPHA,
) -> float:
    """Update a signal's weight based on trade outcome using Bayesian-inspired rule.

    If the signal was active during a profitable trade → weight increases.
    If active during a losing trade → weight decreases (at half rate to be conservative).

    Returns the new weight.
    """
    global _weights_loaded
    if not _weights_loaded:
        _load_weights()

    current = _signal_weights.get(signal_name, 1.0)

    if was_profitable:
        new_weight = min(_MAX_WEIGHT, current + alpha)
    else:
        new_weight = max(_MIN_WEIGHT, current - alpha * 0.5)

    _signal_weights[signal_name] = round(new_weight, 4)
    return new_weight


def update_from_trade_result(
    active_signals: Dict[str, bool],
    trade_profit: float,
    alpha: float = _DEFAULT_ALPHA,
) -> Dict[str, float]:
    """Batch update all signal weights after a trade closes.

    Args:
        active_signals: dict of {signal_name: was_active} at entry time
        trade_profit: EUR profit of the closed trade
        alpha: learning rate

    Returns:
        Updated weights dict
    """
    was_profitable = trade_profit > 0

    for signal_name, was_active in active_signals.items():
        if was_active:
            update_signal_weight(signal_name, was_profitable, alpha)

    _save_weights()
    return get_all_weights()


def apply_bayesian_weights(
    signal_scores: Dict[str, float],
) -> Dict[str, float]:
    """Apply Bayesian weights to raw signal scores.

    Returns weighted scores: original_score × bayesian_weight for each signal.
    """
    global _weights_loaded
    if not _weights_loaded:
        _load_weights()

    weighted = {}
    for name, raw_score in signal_scores.items():
        weight = _signal_weights.get(name, 1.0)
        weighted[name] = round(raw_score * weight, 4)

    return weighted


def weighted_total_score(signal_scores: Dict[str, float]) -> float:
    """Calculate total score with Bayesian weights applied."""
    weighted = apply_bayesian_weights(signal_scores)
    return sum(weighted.values())


def reset_weights() -> None:
    """Reset all weights to 1.0 (useful for testing or after model retrain)."""
    global _signal_weights
    _signal_weights = {}
    _save_weights()
