"""Lightweight indicator helpers used by advanced signal providers."""

from __future__ import annotations

from typing import Iterable, List, Sequence

import numpy as np


def _to_floats(values: Iterable[float]) -> List[float]:
    return [float(v) for v in values]


def sma(values: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return float(np.mean(values[-window:]))


def ema(values: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    k = 2 / (window + 1)
    ema_vals = [values[0]]
    for price in values[1:]:
        ema_vals.append(price * k + ema_vals[-1] * (1 - k))
    return float(ema_vals[-1])


def rsi(values: Sequence[float], period: int = 14) -> float | None:
    if period <= 0 or len(values) < period + 1:
        return None
    deltas = np.diff(values)
    gains = deltas[deltas > 0].sum() / period
    losses = -deltas[deltas < 0].sum() / period
    if losses == 0:
        return 100.0
    rs = gains / losses
    return float(100 - (100 / (1 + rs)))


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], window: int = 14) -> float | None:
    if window <= 0 or len(highs) < window + 1 or len(lows) < window + 1 or len(closes) < window + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        high = highs[i]
        low = lows[i]
        prev_close = closes[i - 1]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if len(trs) < window:
        return None
    return float(np.mean(trs[-window:]))


def zscore(values: Sequence[float], window: int = 30) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    slice_vals = values[-window:]
    mean = float(np.mean(slice_vals))
    std = float(np.std(slice_vals))
    if std == 0:
        return None
    return float((slice_vals[-1] - mean) / std)


def rolling_vwap(closes: Sequence[float], volumes: Sequence[float], window: int = 30) -> float | None:
    if window <= 0 or len(closes) < window or len(volumes) < window:
        return None
    closes_slice = closes[-window:]
    volumes_slice = volumes[-window:]
    vol_sum = float(np.sum(volumes_slice))
    if vol_sum == 0:
        return None
    weighted = np.sum(np.multiply(closes_slice, volumes_slice))
    return float(weighted / vol_sum)


def detect_bullish_engulfing(closes: Sequence[float]) -> bool:
    if len(closes) < 3:
        return False
    prev = closes[-2]
    cur = closes[-1]
    return cur > prev * 1.003 and prev < closes[-3]


def detect_hammer(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> bool:
    if len(closes) < 3:
        return False
    body = abs(closes[-1] - closes[-2])
    total = highs[-1] - lows[-1]
    if total <= 0:
        return False
    lower_shadow = min(closes[-1], closes[-2]) - lows[-1]
    return lower_shadow / total > 0.6 and body / total < 0.2


def detect_range(closes: Sequence[float], lookback: int) -> tuple[float, float] | None:
    if len(closes) < lookback:
        return None
    window = closes[-lookback:]
    return min(window), max(window)


__all__ = [
    "atr",
    "detect_bullish_engulfing",
    "detect_hammer",
    "detect_range",
    "ema",
    "rolling_vwap",
    "rsi",
    "sma",
    "zscore",
]
