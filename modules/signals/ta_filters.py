"""Composite technical-analysis filters that return incremental scores."""

from __future__ import annotations

from .base import (
    SignalContext,
    SignalResult,
    _safe_cfg_bool,
    _safe_cfg_int,
)
from .indicators import (
    detect_bullish_engulfing,
    detect_hammer,
    ema,
    rsi,
    sma,
)


def ta_confirmation_signal(ctx: SignalContext) -> SignalResult:
    cfg = ctx.config
    if not _safe_cfg_bool(cfg, "SIGNALS_TA_ENABLED", True):
        return SignalResult(name="ta_filters", active=False, reason="disabled")

    short_ma = sma(ctx.closes_1m, _safe_cfg_int(cfg, "SIGNALS_TA_SHORT_MA", 9))
    long_ma = sma(ctx.closes_1m, _safe_cfg_int(cfg, "SIGNALS_TA_LONG_MA", 21))
    ema_trend = ema(ctx.closes_1m, _safe_cfg_int(cfg, "SIGNALS_TA_EMA", 34))
    rsi_period = _safe_cfg_int(cfg, "SIGNALS_TA_RSI_PERIOD", 14)
    rsi_val = rsi(ctx.closes_1m, rsi_period)

    price = ctx.closes_1m[-1]
    ma_cross = short_ma and long_ma and short_ma > long_ma
    price_above_ema = ema_trend and price > ema_trend
    candle_signal = detect_bullish_engulfing(ctx.closes_1m) or detect_hammer(ctx.highs_1m, ctx.lows_1m, ctx.closes_1m)

    confirmations = [
        (bool(ma_cross), 1.0),
        (bool(price_above_ema), 0.8),
        (bool(candle_signal), 0.7),
        (bool(rsi_val is not None and 35 <= rsi_val <= 65), 0.5),
    ]

    score = sum(weight for cond, weight in confirmations if cond)
    return SignalResult(
        name="ta_filters",
        active=score > 0,
        score=score,
        reason="confirmations" if score > 0 else "no_confirmation",
        details={
            "short_ma": short_ma,
            "long_ma": long_ma,
            "ema": ema_trend,
            "rsi": rsi_val,
            "candle_signal": candle_signal,
        },
    )
