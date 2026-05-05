"""BTC Momentum Cascade — predict alt-coin moves from BTC momentum.

When BTC shows strong short-term momentum, alts typically follow with a
1-5 minute lag.  This module:

1. Tracks BTC 5-minute rate of change (ROC)
2. Detects momentum bursts (>0.3% in 5m)
3. Calculates per-alt beta (how much each alt follows BTC)
4. Returns a score bonus for alts that haven't yet reacted

Usage
-----
    from core.momentum_cascade import cascade_score_bonus, update_btc_momentum
    update_btc_momentum(btc_candles_5m)
    bonus, details = cascade_score_bonus(market, alt_candles_5m, btc_candles_5m)
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module state — BTC momentum tracking
# ---------------------------------------------------------------------------

_btc_roc_history: deque = deque(maxlen=60)  # 60 × 5m = 5 hours
_last_btc_update: float = 0.0
_btc_momentum_state: Dict[str, Any] = {
    "roc_5m": 0.0,
    "roc_15m": 0.0,
    "roc_1h": 0.0,
    "burst_active": False,
    "burst_direction": 0,  # +1 = pump, -1 = dump
    "burst_magnitude": 0.0,
    "burst_start_ts": 0.0,
}


# ---------------------------------------------------------------------------
# BTC Momentum Tracking
# ---------------------------------------------------------------------------


def _rate_of_change(values: Sequence[float], periods: int) -> Optional[float]:
    """Calculate percentage rate of change."""
    if len(values) < periods + 1:
        return None
    old = values[-(periods + 1)]
    new = values[-1]
    if old == 0:
        return None
    return (new - old) / old * 100


def update_btc_momentum(btc_candles_5m: List) -> Dict[str, Any]:
    """Update BTC momentum state from 5m candles.

    Call this once per scan cycle with fresh BTC 5m data.
    """
    global _last_btc_update, _btc_momentum_state

    if not btc_candles_5m or len(btc_candles_5m) < 13:
        return _btc_momentum_state

    try:
        closes = [float(c[4]) for c in btc_candles_5m]
    except (IndexError, TypeError, ValueError):
        return _btc_momentum_state

    # Calculate ROC at multiple windows
    roc_1 = _rate_of_change(closes, 1)  # 5m ROC
    roc_3 = _rate_of_change(closes, 3)  # 15m ROC
    roc_12 = _rate_of_change(closes, 12)  # 1h ROC

    if roc_1 is not None:
        _btc_roc_history.append(roc_1)

    # Detect momentum burst
    burst_active = False
    burst_direction = 0
    burst_magnitude = 0.0

    if roc_1 is not None:
        # Strong 5m move
        if abs(roc_1) > 0.30:
            burst_active = True
            burst_direction = 1 if roc_1 > 0 else -1
            burst_magnitude = abs(roc_1)

        # Sustained 15m momentum
        if roc_3 is not None and abs(roc_3) > 0.50:
            burst_active = True
            burst_direction = 1 if roc_3 > 0 else -1
            burst_magnitude = max(burst_magnitude, abs(roc_3))

    # Calculate volatility regime of BTC
    btc_vol = float(np.std(_btc_roc_history)) if len(_btc_roc_history) >= 10 else 0.3

    _btc_momentum_state = {
        "roc_5m": round(roc_1, 4) if roc_1 is not None else 0.0,
        "roc_15m": round(roc_3, 4) if roc_3 is not None else 0.0,
        "roc_1h": round(roc_12, 4) if roc_12 is not None else 0.0,
        "burst_active": burst_active,
        "burst_direction": burst_direction,
        "burst_magnitude": round(burst_magnitude, 4),
        "btc_volatility": round(btc_vol, 4),
        "btc_price": closes[-1],
        "ts": time.time(),
    }

    _last_btc_update = time.time()

    if burst_active:
        direction = "PUMP" if burst_direction > 0 else "DUMP"
        logger.info(
            f"[BTC-CASCADE] BTC {direction} detected: ROC_5m={roc_1:+.3f}%, "
            f"ROC_15m={roc_3:+.3f}%, magnitude={burst_magnitude:.3f}%"
        )

    return _btc_momentum_state


# ---------------------------------------------------------------------------
# Per-alt beta calculation
# ---------------------------------------------------------------------------


def _calculate_beta(
    alt_returns: Sequence[float],
    btc_returns: Sequence[float],
) -> Tuple[float, float]:
    """Calculate beta (alt sensitivity to BTC) and correlation.

    Beta = Cov(alt, btc) / Var(btc)
    """
    n = min(len(alt_returns), len(btc_returns))
    if n < 10:
        return 1.0, 0.0  # default beta = 1, no correlation measured

    try:
        alt = np.array(alt_returns[-n:], dtype=np.float64)
        btc = np.array(btc_returns[-n:], dtype=np.float64)

        cov = float(np.cov(alt, btc)[0, 1])
        var_btc = float(np.var(btc))

        if var_btc < 1e-12:
            return 1.0, 0.0

        beta = cov / var_btc

        # Correlation
        std_alt = float(np.std(alt))
        std_btc = float(np.std(btc))
        if std_alt < 1e-12 or std_btc < 1e-12:
            corr = 0.0
        else:
            corr = cov / (std_alt * std_btc)

        return float(np.clip(beta, -3.0, 5.0)), float(np.clip(corr, -1.0, 1.0))
    except Exception:
        return 1.0, 0.0


def _candle_returns(candles: List) -> List[float]:
    """Calculate period-over-period returns from candles."""
    try:
        closes = [float(c[4]) for c in candles]
        if len(closes) < 2:
            return []
        return [(closes[i] - closes[i - 1]) / closes[i - 1] * 100 for i in range(1, len(closes))]
    except (IndexError, TypeError, ValueError):
        return []


# ---------------------------------------------------------------------------
# Score Bonus
# ---------------------------------------------------------------------------


def cascade_score_bonus(
    market: str,
    alt_candles_5m: List,
    btc_candles_5m: List,
) -> Tuple[float, Dict[str, Any]]:
    """Calculate cascade score bonus for an alt based on BTC momentum.

    Logic:
    - If BTC is pumping and alt hasn't moved yet → bonus (front-run opportunity)
    - If BTC is dumping → penalty (risk of cascade sell-off)
    - If BTC is flat → no bonus
    - Beta-weighted: high-beta alts get stronger signals

    Returns
    -------
    (bonus, details) : tuple
        bonus in range [-2.0, +3.0]
    """
    if not alt_candles_5m or not btc_candles_5m:
        return 0.0, {"reason": "no_data"}

    if len(alt_candles_5m) < 13 or len(btc_candles_5m) < 13:
        return 0.0, {"reason": "insufficient_data"}

    state = _btc_momentum_state
    if time.time() - state.get("ts", 0) > 600:
        # Stale data — update first
        update_btc_momentum(btc_candles_5m)
        state = _btc_momentum_state

    btc_roc_5m = state.get("roc_5m", 0.0)
    btc_roc_15m = state.get("roc_15m", 0.0)
    burst_active = state.get("burst_active", False)
    burst_dir = state.get("burst_direction", 0)
    burst_mag = state.get("burst_magnitude", 0.0)

    # Calculate alt's own recent ROC
    try:
        alt_closes = [float(c[4]) for c in alt_candles_5m]
    except (IndexError, TypeError, ValueError):
        return 0.0, {"reason": "bad_candle_data"}

    alt_roc_5m = _rate_of_change(alt_closes, 1)
    alt_roc_15m = _rate_of_change(alt_closes, 3)

    if alt_roc_5m is None:
        return 0.0, {"reason": "cannot_compute_alt_roc"}

    # Calculate beta
    alt_returns = _candle_returns(alt_candles_5m)
    btc_returns = _candle_returns(btc_candles_5m)
    beta, correlation = _calculate_beta(alt_returns, btc_returns)

    bonus = 0.0
    reasons = []

    if burst_active and burst_dir > 0:
        # BTC is PUMPING
        expected_alt_move = btc_roc_5m * beta
        actual_alt_move = alt_roc_5m

        lag = expected_alt_move - actual_alt_move

        if lag > 0.15 and correlation > 0.3:
            # Alt hasn't reacted yet — front-run opportunity
            bonus = min(3.0, lag * beta * correlation * 2.0)
            reasons.append(
                f"btc_pump_lag (expected={expected_alt_move:+.3f}%, actual={actual_alt_move:+.3f}%, lag={lag:.3f}%)"
            )
        elif lag > 0.05:
            bonus = min(1.5, lag * beta * 1.0)
            reasons.append(f"btc_pump_minor_lag (lag={lag:.3f}%)")

    elif burst_active and burst_dir < 0:
        # BTC is DUMPING — penalty
        if correlation > 0.3:
            bonus = max(-2.0, -burst_mag * beta * correlation * 0.5)
            reasons.append(f"btc_dump_risk (mag={burst_mag:.3f}%, beta={beta:.2f})")

    elif abs(btc_roc_15m) > 0.30:
        # Moderate sustained BTC momentum (not burst-level but noteworthy)
        if btc_roc_15m > 0 and alt_roc_15m is not None:
            if alt_roc_15m < btc_roc_15m * 0.3:
                bonus = min(1.0, (btc_roc_15m - alt_roc_15m) * 0.5)
                reasons.append(f"btc_sustained_momentum_lag (btc={btc_roc_15m:+.3f}%, alt={alt_roc_15m:+.3f}%)")

    bonus = max(-2.0, min(3.0, bonus))

    details = {
        "btc_roc_5m": btc_roc_5m,
        "btc_roc_15m": btc_roc_15m,
        "alt_roc_5m": round(alt_roc_5m, 4),
        "alt_roc_15m": round(alt_roc_15m, 4) if alt_roc_15m is not None else None,
        "beta": round(beta, 3),
        "correlation": round(correlation, 3),
        "burst_active": burst_active,
        "burst_direction": burst_dir,
        "bonus": round(bonus, 2),
        "reasons": reasons,
    }

    if bonus != 0:
        logger.debug(
            f"[BTC-CASCADE] {market}: bonus={bonus:+.2f} "
            f"(beta={beta:.2f}, corr={correlation:.2f}, {', '.join(reasons)})"
        )

    return round(bonus, 2), details


def get_btc_state() -> Dict[str, Any]:
    """Return current BTC momentum state (read-only)."""
    return dict(_btc_momentum_state)
