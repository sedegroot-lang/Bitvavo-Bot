"""Detect intraday ranges and see if price sits near support for bounce entries."""

from __future__ import annotations

from typing import Any

from .base import (
    SignalContext,
    SignalResult,
    _safe_cfg_bool,
    _safe_cfg_float,
    _safe_cfg_int,
)
from .indicators import detect_range, rsi


def range_signal(ctx: SignalContext) -> SignalResult:
    cfg = ctx.config
    cfg = ctx.config
    if not _safe_cfg_bool(cfg, "SIGNALS_RANGE_ENABLED", True):
        return SignalResult(name="range", score=0.0, active=False, reason="disabled")

    lookback = _safe_cfg_int(cfg, "SIGNALS_RANGE_LOOKBACK", 90)
    threshold = _safe_cfg_float(cfg, "SIGNALS_RANGE_THRESHOLD", 0.25)
    rsi_period = _safe_cfg_int(cfg, "SIGNALS_RANGE_RSI_PERIOD", 14)
    rsi_max = _safe_cfg_float(cfg, "SIGNALS_RANGE_RSI_MAX", 48.0)

    detected = detect_range(ctx.closes_1m, lookback)
    if detected is None:
        return SignalResult(name="range", active=False, reason="insufficient_data")

    support, resistance = detected
    price = ctx.closes_1m[-1]
    range_span = resistance - support
    if range_span <= 0:
        return SignalResult(name="range", active=False, reason="flat_range")

    normalized = (price - support) / range_span
    current_rsi = rsi(ctx.closes_1m, rsi_period)

    if current_rsi is None:
        return SignalResult(name="range", active=False, reason="no_rsi")

    near_support = normalized <= threshold and current_rsi <= rsi_max
    score = max(0.0, (threshold - normalized) * 4.0)
    return SignalResult(
        name="range",
        score=score if near_support else 0.0,
        active=near_support,
        reason="near_support" if near_support else "range_neutral",
        details={
            "normalized": round(normalized, 4),
            "support": support,
            "resistance": resistance,
            "rsi": current_rsi,
        },
    )
