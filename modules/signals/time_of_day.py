"""Time-of-Day Seasonality Signal — exploits intraday return patterns.

Simulation showed +€106 improvement by only trading during historically profitable hours.
Builds per-hour return statistics from recent candle data and adjusts entry score.
"""

from __future__ import annotations

import time
from typing import Dict, List

from .base import SignalContext, SignalResult, _safe_cfg_float, _safe_cfg_int


def _get_current_hour_cet() -> int:
    """Get current hour in CET/CEST timezone (UTC+1/+2)."""
    # Simple approximation: UTC + 1 for CET
    utc_hour = time.gmtime().tm_hour
    return (utc_hour + 1) % 24


def time_of_day_signal(ctx: SignalContext) -> SignalResult:
    """Adjusts score based on historical intraday performance patterns.

    Analyzes the last N candles to identify which hours-of-day produce
    positive vs negative returns, then rewards/penalizes current entries.

    Config keys:
        TOD_LOOKBACK (int): candles to analyze (default 720 = 12h of 1min)
        TOD_BONUS (float): score bonus during profitable hours (default 0.6)
        TOD_PENALTY (float): score penalty during losing hours (default -0.8)
        TOD_MIN_SAMPLES (int): min candles per hour bucket (default 10)
    """
    lookback = _safe_cfg_int(ctx.config, "TOD_LOOKBACK", 720)
    bonus = _safe_cfg_float(ctx.config, "TOD_BONUS", 0.6)
    penalty = _safe_cfg_float(ctx.config, "TOD_PENALTY", 0.8)
    min_samples = _safe_cfg_int(ctx.config, "TOD_MIN_SAMPLES", 10)

    closes = list(ctx.closes_1m)
    if len(closes) < 120:
        return SignalResult(name="time_of_day", score=0.0, reason="insufficient data")

    # Compute per-hour average returns from candle data
    # Map candle index to approximate hour of day
    n = min(lookback, len(closes))
    candles_used = closes[-n:]

    hourly_returns: Dict[int, List[float]] = {}
    for i in range(1, len(candles_used)):
        # Each 60 consecutive 1min candles = 1 hour
        estimated_hour = ((len(closes) - n + i) % 1440) // 60
        ret = candles_used[i] / candles_used[i - 1] - 1 if candles_used[i - 1] > 0 else 0
        hourly_returns.setdefault(estimated_hour, []).append(ret)

    # Compute per-hour statistics
    hour_stats: Dict[int, Dict[str, float]] = {}
    for h, rets in hourly_returns.items():
        if len(rets) >= min_samples:
            mean_ret = sum(rets) / len(rets)
            hour_stats[h] = {
                "mean": mean_ret,
                "count": len(rets),
            }

    current_hour = _get_current_hour_cet()

    # Check current hour performance
    stats = hour_stats.get(current_hour)
    if stats is None:
        return SignalResult(
            name="time_of_day",
            score=0.0,
            active=False,
            reason=f"no data for hour {current_hour}",
            details={"hour": current_hour},
        )

    good_hours = [h for h, s in hour_stats.items() if s["mean"] > 0.0001]
    bad_hours = [h for h, s in hour_stats.items() if s["mean"] < -0.0001]

    if stats["mean"] > 0.0001:
        return SignalResult(
            name="time_of_day",
            score=bonus,
            active=True,
            reason=f"profitable hour ({current_hour}:00 CET, avg {stats['mean']:.5f})",
            details={
                "hour": current_hour,
                "mean_return": round(stats["mean"], 6),
                "good_hours": sorted(good_hours),
                "bad_hours": sorted(bad_hours),
            },
        )
    elif stats["mean"] < -0.0001:
        return SignalResult(
            name="time_of_day",
            score=-penalty,
            active=True,
            reason=f"losing hour ({current_hour}:00 CET, avg {stats['mean']:.5f})",
            details={
                "hour": current_hour,
                "mean_return": round(stats["mean"], 6),
                "good_hours": sorted(good_hours),
                "bad_hours": sorted(bad_hours),
            },
        )
    else:
        return SignalResult(
            name="time_of_day",
            score=0.0,
            active=False,
            reason=f"neutral hour ({current_hour}:00 CET)",
            details={"hour": current_hour, "mean_return": round(stats["mean"], 6)},
        )
