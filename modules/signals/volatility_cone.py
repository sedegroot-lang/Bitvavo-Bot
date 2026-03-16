"""Realized Volatility Cone Signal — detects abnormal volatility regimes.

Builds a "volatility cone" from historical data across multiple time horizons.
When realized vol falls outside the expected cone:
- Below cone → vol expansion imminent → reduce entries  
- Above cone → vol contraction expected → increase entries

Based on: Natenberg, "Option Volatility" — volatility cone concept adapted to crypto spot trading.
"""

from __future__ import annotations

import math
from typing import Any, MutableMapping, Sequence

from .base import SignalContext, SignalResult


def _realized_vol(returns: Sequence[float], window: int) -> float:
    """Compute annualized realized volatility from returns."""
    if len(returns) < window:
        return 0.0
    w = list(returns[-window:])
    mean = sum(w) / window
    var = sum((r - mean) ** 2 for r in w) / window
    # Annualize: ~525,600 minutes in a year, using sqrt scaling
    return math.sqrt(var) * math.sqrt(1440)  # daily-scaled for 1m candles


def _vol_percentile(current: float, historical: Sequence[float]) -> float:
    """Compute where current vol sits in the historical distribution (0-1)."""
    if not historical or current <= 0:
        return 0.5
    below = sum(1 for v in historical if v <= current)
    return below / len(historical)


def _safe_cfg(cfg: MutableMapping[str, Any], key: str, default: float) -> float:
    try:
        return float(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def volatility_cone_signal(ctx: SignalContext) -> SignalResult:
    """Volatility cone signal provider.

    Computes realized vol at short (10) and medium (30) windows,
    then checks if they're abnormally high or low compared to a longer baseline.

    - Vol percentile < 15%: vol is abnormally low → expansion likely → penalty
    - Vol percentile > 85%: vol is abnormally high → contraction likely → bonus (buying the vol crush)
    - Vol percentile 30-70%: normal → neutral
    """
    lookback = int(_safe_cfg(ctx.config, 'VOLCONE_LOOKBACK', 120))
    short_window = int(_safe_cfg(ctx.config, 'VOLCONE_SHORT_WIN', 10))
    medium_window = int(_safe_cfg(ctx.config, 'VOLCONE_MED_WIN', 30))
    low_pct_threshold = _safe_cfg(ctx.config, 'VOLCONE_LOW_PCT', 0.15)
    high_pct_threshold = _safe_cfg(ctx.config, 'VOLCONE_HIGH_PCT', 0.85)
    low_penalty = _safe_cfg(ctx.config, 'VOLCONE_LOW_PENALTY', 0.5)
    high_bonus = _safe_cfg(ctx.config, 'VOLCONE_HIGH_BONUS', 0.4)

    closes = ctx.closes_1m
    if len(closes) < lookback:
        return SignalResult(name='vol_cone', reason='insufficient data')

    # Compute log returns
    returns = []
    for i in range(1, len(closes)):
        if closes[i] > 0 and closes[i - 1] > 0:
            returns.append(math.log(closes[i] / closes[i - 1]))

    if len(returns) < lookback - 1:
        return SignalResult(name='vol_cone', reason='insufficient returns')

    # Current realized vol at short window
    current_short = _realized_vol(returns, short_window)
    current_med = _realized_vol(returns, medium_window)

    # Build historical vol distribution using rolling windows
    hist_vols = []
    step = max(1, short_window // 2)
    for i in range(short_window, len(returns) - short_window, step):
        hv = _realized_vol(returns[i - short_window:i], short_window)
        if hv > 0:
            hist_vols.append(hv)

    if len(hist_vols) < 10:
        return SignalResult(name='vol_cone', reason='insufficient history for cone')

    pct = _vol_percentile(current_short, hist_vols)

    details = {
        'vol_short': round(current_short, 6),
        'vol_medium': round(current_med, 6),
        'vol_percentile': round(pct, 4),
        'hist_samples': len(hist_vols),
    }

    if pct < low_pct_threshold:
        # Vol is abnormally low — expansion expected, risky entry
        return SignalResult(
            name='vol_cone', score=-low_penalty, active=True,
            reason=f'vol abnormally low (pct={pct:.2f}, expecting expansion)',
            details=details,
        )
    elif pct > high_pct_threshold:
        # Vol is abnormally high — contraction expected, good entry (vol crush)
        return SignalResult(
            name='vol_cone', score=high_bonus, active=True,
            reason=f'vol abnormally high (pct={pct:.2f}, expecting contraction)',
            details=details,
        )
    else:
        return SignalResult(
            name='vol_cone', score=0.0, active=False,
            reason=f'vol normal (pct={pct:.2f})',
            details=details,
        )
