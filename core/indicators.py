"""Technical indicators — pure functions, no bot state dependency.

All functions accept plain lists/arrays and return scalars or tuples.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Candle helpers
# ---------------------------------------------------------------------------

def close_prices(candles: Sequence) -> List[float]:
    """Extract close prices from candle arrays (index 4)."""
    prices: List[float] = []
    for x in (candles or []):
        try:
            if len(x) > 4:
                prices.append(float(x[4]))
        except Exception:
            pass
    return prices


def highs(candles: Sequence) -> List[float]:
    return [float(x[2]) for x in candles if len(x) > 2]


def lows(candles: Sequence) -> List[float]:
    return [float(x[3]) for x in candles if len(x) > 3]


def volumes(candles: Sequence) -> List[float]:
    return [float(x[5]) for x in candles if len(x) > 5]


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------

def sma(vals: Sequence[float], window: int) -> Optional[float]:
    """Simple moving average over the last *window* values."""
    if len(vals) >= window:
        return float(np.mean(vals[-window:]))
    return None


def ema(vals: Sequence[float], window: int) -> Optional[float]:
    """Exponential moving average — returns the *last* value."""
    if len(vals) < window:
        return None
    k = 2 / (window + 1)
    e = [vals[0]]
    for x in vals[1:]:
        e.append(x * k + e[-1] * (1 - k))
    return float(e[-1])


def ema_series(vals: Sequence[float], window: int) -> List[float]:
    """Full EMA series — used internally by :func:`macd`."""
    k = 2 / (window + 1)
    e = [vals[0]]
    for x in vals[1:]:
        e.append(x * k + e[-1] * (1 - k))
    return e


# ---------------------------------------------------------------------------
# Oscillators
# ---------------------------------------------------------------------------

def rsi(vals: Sequence[float], period: int = 14) -> Optional[float]:
    """Relative Strength Index."""
    if len(vals) < period + 1:
        return None
    deltas = np.diff(vals)
    gains = deltas[deltas > 0].sum() / period
    losses = -deltas[deltas < 0].sum() / period
    if losses == 0:
        return 100.0
    rs = gains / losses
    return float(100 - (100 / (1 + rs)))


def stochastic(vals: Sequence[float], window: int = 14) -> Optional[float]:
    """Stochastic %K."""
    if len(vals) < window:
        return None
    high = max(vals[-window:])
    low = min(vals[-window:])
    close = vals[-1]
    return 100.0 * (close - low) / (high - low) if high != low else None


def macd(
    vals: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """MACD line, signal line, histogram."""
    if len(vals) < slow + signal:
        return None, None, None
    ef = ema_series(vals, fast)
    es = ema_series(vals, slow)
    macd_line = [f - s for f, s in zip(ef[-len(es):], es)]
    sig = ema_series(macd_line, signal)
    return macd_line[-1], sig[-1], macd_line[-1] - sig[-1]


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

def bollinger_bands(
    vals: Sequence[float],
    window: int = 20,
    num_std: int = 2,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Upper band, middle band, lower band."""
    if len(vals) < window:
        return None, None, None
    ma = float(np.mean(vals[-window:]))
    std = float(np.std(vals[-window:]))
    return ma + num_std * std, ma, ma - num_std * std


def atr(
    h: Sequence[float],
    l: Sequence[float],
    c: Sequence[float],
    window: int = 14,
) -> Optional[float]:
    """Average True Range."""
    if len(h) < window + 1:
        return None
    trs = [
        max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        for i in range(1, len(c))
    ]
    return float(np.mean(trs[-window:]))


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

def calculate_momentum_score(
    candles: Sequence,
    *,
    _close_prices=None,
    _volumes=None,
) -> int:
    """Short-term momentum score (-7 to +7).

    Positive → bullish, negative → bearish.
    """
    try:
        if len(candles) < 20:
            return 0
        prices = _close_prices if _close_prices is not None else close_prices(candles)
        if len(prices) < 20:
            return 0

        roc_1 = (prices[-1] - prices[-2]) / prices[-2] if prices[-2] != 0 else 0
        roc_5 = (
            (prices[-1] - prices[-6]) / prices[-6]
            if len(prices) >= 6 and prices[-6] != 0
            else 0
        )

        vols = _volumes if _volumes is not None else volumes(candles)
        if len(vols) >= 20:
            avg_vol = float(np.mean(vols[:-1]))
            current_vol = vols[-1]
            vol_surge = current_vol / avg_vol if avg_vol > 0 else 1
        else:
            vol_surge = 1

        score = 0
        if roc_1 > 0.01:
            score += 2
        if roc_5 > 0.03:
            score += 3
        if vol_surge > 1.5:
            score += 2
        if roc_1 < -0.01:
            score -= 3
        if roc_5 < -0.03:
            score -= 4

        return score
    except Exception:
        return 0
