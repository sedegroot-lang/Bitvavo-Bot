"""Spread Regime Detector — uses bid-ask spread (high-low proxy) as information signal.

Simulation showed +€23 improvement by avoiding trades when spread z-score is abnormally high.
Wide spread = market maker uncertainty = higher reversal/crash risk.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Sequence

from .base import SignalContext, SignalResult, _safe_cfg_float, _safe_cfg_int


def spread_regime_signal(ctx: SignalContext) -> SignalResult:
    """Penalizes entries when the high-low range (spread proxy) is abnormally wide.

    Config keys:
        SPREAD_LOOKBACK (int): candles for z-score calculation (default 50)
        SPREAD_Z_THRESHOLD (float): z-score above which to penalize (default 1.0)
        SPREAD_PENALTY (float): score penalty on wide spread (default -0.7)
        SPREAD_TIGHT_BONUS (float): bonus on tight spread (default 0.3)
    """
    lookback = _safe_cfg_int(ctx.config, "SPREAD_LOOKBACK", 50)
    z_threshold = _safe_cfg_float(ctx.config, "SPREAD_Z_THRESHOLD", 1.0)
    penalty = _safe_cfg_float(ctx.config, "SPREAD_PENALTY", 0.7)
    tight_bonus = _safe_cfg_float(ctx.config, "SPREAD_TIGHT_BONUS", 0.3)

    closes = list(ctx.closes_1m)
    highs = list(ctx.highs_1m)
    lows = list(ctx.lows_1m)

    if len(closes) < lookback + 1 or len(highs) < lookback + 1:
        return SignalResult(name="spread_regime", score=0.0, reason="insufficient data")

    # Compute normalized spread (high-low range / close)
    spreads = []
    start = max(0, len(closes) - lookback - 1)
    for i in range(start, len(closes)):
        if closes[i] > 0:
            spreads.append((highs[i] - lows[i]) / closes[i])
        else:
            spreads.append(0.0)

    if len(spreads) < 10:
        return SignalResult(name="spread_regime", score=0.0, reason="insufficient spread data")

    # Z-score of current spread vs historical
    current_spread = spreads[-1]
    mean_s = sum(spreads[:-1]) / len(spreads[:-1]) if len(spreads) > 1 else 0
    std_s = (sum((s - mean_s) ** 2 for s in spreads[:-1]) / max(len(spreads) - 1, 1)) ** 0.5

    if std_s < 1e-12:
        return SignalResult(name="spread_regime", score=0.0, reason="zero spread variance")

    z_score = (current_spread - mean_s) / std_s

    if z_score > z_threshold:
        return SignalResult(
            name="spread_regime",
            score=-penalty,
            active=True,
            reason=f"wide spread (z={z_score:.2f} > {z_threshold})",
            details={"z_score": round(z_score, 4), "current_spread": round(current_spread, 6), "mean": round(mean_s, 6)},
        )
    elif z_score < -0.5:
        return SignalResult(
            name="spread_regime",
            score=tight_bonus,
            active=True,
            reason=f"tight spread (z={z_score:.2f})",
            details={"z_score": round(z_score, 4), "current_spread": round(current_spread, 6), "mean": round(mean_s, 6)},
        )
    else:
        return SignalResult(
            name="spread_regime",
            score=0.0,
            active=False,
            reason=f"normal spread (z={z_score:.2f})",
            details={"z_score": round(z_score, 4)},
        )
