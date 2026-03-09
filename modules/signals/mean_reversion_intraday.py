"""Z-score based intraday mean reversion helper."""

from __future__ import annotations

from .base import (
    SignalContext,
    SignalResult,
    _safe_cfg_bool,
    _safe_cfg_float,
    _safe_cfg_int,
)
from .indicators import rsi, sma, zscore


def mean_reversion_signal(ctx: SignalContext) -> SignalResult:
    cfg = ctx.config
    if not _safe_cfg_bool(cfg, "SIGNALS_MEAN_REV_ENABLED", True):
        return SignalResult(name="mean_reversion", active=False, reason="disabled")

    window = _safe_cfg_int(cfg, "SIGNALS_MEAN_REV_WINDOW", 40)
    z_entry = _safe_cfg_float(cfg, "SIGNALS_MEAN_REV_Z", -1.2)
    rsi_cap = _safe_cfg_float(cfg, "SIGNALS_MEAN_REV_RSI_MAX", 50.0)
    ma_window = _safe_cfg_int(cfg, "SIGNALS_MEAN_REV_MA", 20)

    z_val = zscore(ctx.closes_1m, window)
    if z_val is None:
        return SignalResult(name="mean_reversion", active=False, reason="no_zscore")

    rsi_val = rsi(ctx.closes_1m, _safe_cfg_int(cfg, "SIGNALS_MEAN_REV_RSI_PERIOD", 14))
    ma_val = sma(ctx.closes_1m, ma_window)
    price = ctx.closes_1m[-1]

    rsi_gate = 100.0 if rsi_val is None else float(rsi_val)
    bearish_stretch = z_val <= z_entry and rsi_gate <= rsi_cap
    if not bearish_stretch:
        return SignalResult(
            name="mean_reversion",
            active=False,
            reason="zscore_not_extreme",
            details={"zscore": z_val, "rsi": rsi_val},
        )

    distance = 0.0
    if ma_val:
        distance = (ma_val - price) / ma_val if ma_val else 0.0

    score = abs(z_val - z_entry) * 2.0 + max(0.0, distance * 10)
    return SignalResult(
        name="mean_reversion",
        active=True,
        score=score,
        reason="zscore_rebound",
        details={
            "zscore": z_val,
            "rsi": rsi_val,
            "ma": ma_val,
            "price": price,
        },
    )
