"""ATR/Bollinger-based breakout detector."""

from __future__ import annotations

from .base import (
    SignalContext,
    SignalResult,
    _safe_cfg_bool,
    _safe_cfg_float,
    _safe_cfg_int,
)
from .indicators import atr, rolling_vwap


def volatility_breakout_signal(ctx: SignalContext) -> SignalResult:
    cfg = ctx.config
    if not _safe_cfg_bool(cfg, "SIGNALS_VOL_BREAKOUT_ENABLED", True):
        return SignalResult(name="vol_breakout", active=False, reason="disabled")

    atr_window = _safe_cfg_int(cfg, "SIGNALS_VOL_ATR_WINDOW", 14)
    atr_mult = _safe_cfg_float(cfg, "SIGNALS_VOL_ATR_MULT", 1.8)
    volume_window = _safe_cfg_int(cfg, "SIGNALS_VOL_VOLUME_WINDOW", 60)
    volume_spike = _safe_cfg_float(cfg, "SIGNALS_VOL_VOLUME_SPIKE", 1.4)

    atr_val = atr(ctx.highs_1m, ctx.lows_1m, ctx.closes_1m, atr_window)
    if atr_val is None:
        return SignalResult(name="vol_breakout", active=False, reason="no_atr")

    vwap = rolling_vwap(ctx.closes_1m, ctx.volumes_1m, volume_window)
    if vwap is None:
        return SignalResult(name="vol_breakout", active=False, reason="no_vwap")

    price = ctx.closes_1m[-1]
    prior = ctx.closes_1m[-2] if len(ctx.closes_1m) >= 2 else price
    volume_slice = ctx.volumes_1m[-volume_window:]
    avg_volume = sum(volume_slice) / len(volume_slice) if volume_slice else 0.0
    latest_volume = ctx.volumes_1m[-1] if ctx.volumes_1m else 0.0

    breakout_level = vwap + atr_val * atr_mult
    breakout = price > breakout_level and price > prior
    volume_conf = latest_volume >= avg_volume * volume_spike

    if not breakout or not volume_conf:
        return SignalResult(
            name="vol_breakout",
            active=False,
            reason="no_breakout" if not breakout else "no_volume",
            details={
                "breakout_level": breakout_level,
                "price": price,
                "volume_ratio": (latest_volume / avg_volume) if avg_volume else 0.0,
            },
        )

    overshoot = price - breakout_level
    score = max(0.0, overshoot / breakout_level * 10.0)
    return SignalResult(
        name="vol_breakout",
        active=True,
        score=score,
        reason="breakout_confirmed",
        details={
            "breakout_level": breakout_level,
            "price": price,
            "atr": atr_val,
            "volume_ratio": (latest_volume / avg_volume) if avg_volume else 0.0,
        },
    )
