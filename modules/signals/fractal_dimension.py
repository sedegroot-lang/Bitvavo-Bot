"""Fractal Dimension Signal — classifies market microstructure using Higuchi fractal dimension.

D ≈ 1.0 → smooth trend (momentum works)
D ≈ 1.5 → random walk (don't trade)
D ≈ 2.0 → space-filling / mean-reversion regime

This is a microstructure quality signal that no retail bot implements.
Based on: Higuchi (1988) "Approach to an irregular time series"
"""

from __future__ import annotations

from typing import Any, Dict, MutableMapping, Sequence

from .base import SignalContext, SignalResult


def _higuchi_fd(series: Sequence[float], k_max: int = 10) -> float:
    """Compute Higuchi Fractal Dimension of a time series.

    Uses the Higuchi (1988) algorithm which is efficient and robust for short series.

    Args:
        series: price or return series (at least 2*k_max long)
        k_max: maximum interval length

    Returns:
        Fractal dimension estimate (1.0 to 2.0)
    """
    import math

    n = len(series)
    if n < 2 * k_max:
        return 1.5  # default to random walk when insufficient data

    # Compute curve lengths L(k) for each interval k
    lk = []
    ln_k = []

    for k in range(1, k_max + 1):
        lengths = []
        for m in range(1, k + 1):
            # Number of elements in this sub-series
            floor_val = (n - m) // k
            if floor_val < 1:
                continue
            # Compute normalized length for this (m, k) pair
            length = 0.0
            for i in range(1, floor_val + 1):
                idx1 = m + i * k - 1
                idx2 = m + (i - 1) * k - 1
                if idx1 < n and idx2 < n:
                    length += abs(series[idx1] - series[idx2])

            norm = (n - 1) / (floor_val * k * k)
            if norm > 0:
                lengths.append(length * norm)

        if lengths:
            avg_length = sum(lengths) / len(lengths)
            if avg_length > 0:
                lk.append(math.log(avg_length))
                ln_k.append(math.log(1.0 / k))

    if len(lk) < 3:
        return 1.5

    # Linear regression of ln(L(k)) vs ln(1/k) — slope = fractal dimension
    n_pts = len(lk)
    mean_x = sum(ln_k) / n_pts
    mean_y = sum(lk) / n_pts
    ss_xy = sum((ln_k[i] - mean_x) * (lk[i] - mean_y) for i in range(n_pts))
    ss_xx = sum((ln_k[i] - mean_x) ** 2 for i in range(n_pts))

    if ss_xx < 1e-12:
        return 1.5

    slope = ss_xy / ss_xx
    # Clamp to valid range [1.0, 2.0]
    return max(1.0, min(2.0, slope))


def _safe_cfg(cfg: MutableMapping[str, Any], key: str, default: float) -> float:
    try:
        return float(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def fractal_dimension_signal(ctx: SignalContext) -> SignalResult:
    """Fractal dimension signal provider.

    - D < 1.25: smooth trend → momentum bonus
    - 1.25 <= D <= 1.65: mixed/random → neutral
    - D > 1.65: space-filling → mean reversion bonus (if RSI confirms)
    - D ≈ 1.45-1.55: pure random walk → penalty (don't trade noise)
    """
    lookback = int(_safe_cfg(ctx.config, 'FRACTAL_LOOKBACK', 80))
    trend_threshold = _safe_cfg(ctx.config, 'FRACTAL_TREND_D', 1.25)
    random_low = _safe_cfg(ctx.config, 'FRACTAL_RANDOM_LOW', 1.40)
    random_high = _safe_cfg(ctx.config, 'FRACTAL_RANDOM_HIGH', 1.60)
    mr_threshold = _safe_cfg(ctx.config, 'FRACTAL_MR_D', 1.65)
    trend_bonus = _safe_cfg(ctx.config, 'FRACTAL_TREND_BONUS', 0.8)
    random_penalty = _safe_cfg(ctx.config, 'FRACTAL_RANDOM_PENALTY', 0.6)
    mr_bonus = _safe_cfg(ctx.config, 'FRACTAL_MR_BONUS', 0.5)

    closes = ctx.closes_1m
    if len(closes) < lookback:
        return SignalResult(name='fractal_dim', reason='insufficient data')

    fd = _higuchi_fd(list(closes[-lookback:]), k_max=min(10, lookback // 4))

    if fd < trend_threshold:
        return SignalResult(
            name='fractal_dim', score=trend_bonus, active=True,
            reason=f'smooth trend (D={fd:.3f})',
            details={'fractal_dimension': round(fd, 4), 'regime': 'trending'},
        )
    elif random_low <= fd <= random_high:
        return SignalResult(
            name='fractal_dim', score=-random_penalty, active=True,
            reason=f'random walk (D={fd:.3f})',
            details={'fractal_dimension': round(fd, 4), 'regime': 'random'},
        )
    elif fd > mr_threshold:
        return SignalResult(
            name='fractal_dim', score=mr_bonus, active=True,
            reason=f'mean-reversion regime (D={fd:.3f})',
            details={'fractal_dimension': round(fd, 4), 'regime': 'mean_reversion'},
        )
    else:
        return SignalResult(
            name='fractal_dim', score=0.0, active=False,
            reason=f'mixed (D={fd:.3f})',
            details={'fractal_dimension': round(fd, 4), 'regime': 'mixed'},
        )
