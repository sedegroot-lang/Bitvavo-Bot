"""Mean-Reversion Scalper — aggressive reversal entry signal.

Conditions for a BUY signal:
  1. Z-score ≤ -2.0 on 15-bar VWAP (computed from 1m candles)
  2. RSI(14) < 35 (oversold)
  3. Price below lower Bollinger Band (20, 2σ)
  4. Volume surge: current volume > 1.5× 20-bar average

This signal fires in aggressive sell-offs where a bounce is statistically
likely.  It scores higher the more extreme the deviation.

Config keys:
  SIGNALS_MR_SCALPER_ENABLED     (bool, default True)
  SIGNALS_MR_SCALPER_Z_ENTRY     (float, default -2.0)
  SIGNALS_MR_SCALPER_RSI_MAX     (float, default 35.0)
  SIGNALS_MR_SCALPER_WINDOW      (int,   default 30)  — zscore lookback
  SIGNALS_MR_SCALPER_VWAP_WINDOW (int,   default 15)  — VWAP period
"""

from __future__ import annotations

from .base import (
    SignalContext,
    SignalResult,
    _safe_cfg_bool,
    _safe_cfg_float,
    _safe_cfg_int,
)
from .indicators import rsi, zscore


def _vwap(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    window: int,
) -> float | None:
    """Volume Weighted Average Price over the last *window* bars."""
    if len(closes) < window or len(volumes) < window:
        return None
    # Typical price = (H + L + C) / 3
    tp_vol_sum = 0.0
    vol_sum = 0.0
    for i in range(-window, 0):
        tp = (highs[i] + lows[i] + closes[i]) / 3
        v = volumes[i]
        tp_vol_sum += tp * v
        vol_sum += v
    return tp_vol_sum / vol_sum if vol_sum > 0 else None


def _vwap_zscore(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    vwap_window: int,
    z_window: int,
) -> float | None:
    """Z-score of price deviation from rolling VWAP."""
    if len(closes) < max(vwap_window, z_window) + 5:
        return None

    # Build series of (price - VWAP) for the last z_window bars
    devs = []
    for j in range(z_window):
        idx = len(closes) - z_window + j
        end = idx + 1
        start = max(0, end - vwap_window)
        if end - start < 3:
            continue
        seg_c = closes[start:end]
        seg_h = highs[start:end]
        seg_l = lows[start:end]
        seg_v = volumes[start:end]
        vw = _vwap(seg_c, seg_h, seg_l, seg_v, len(seg_c))
        if vw and vw > 0:
            devs.append(closes[idx] - vw)

    if len(devs) < 5:
        return None

    mean = sum(devs) / len(devs)
    var = sum((d - mean) ** 2 for d in devs) / len(devs)
    std = var ** 0.5
    return (devs[-1] - mean) / std if std > 0 else 0.0


def mean_reversion_scalper_signal(ctx: SignalContext) -> SignalResult:
    """Aggressive mean-reversion entry when price deviates far below VWAP."""
    cfg = ctx.config
    if not _safe_cfg_bool(cfg, "SIGNALS_MR_SCALPER_ENABLED", True):
        return SignalResult(name="mr_scalper", active=False, reason="disabled")

    z_entry = _safe_cfg_float(cfg, "SIGNALS_MR_SCALPER_Z_ENTRY", -2.0)
    rsi_cap = _safe_cfg_float(cfg, "SIGNALS_MR_SCALPER_RSI_MAX", 35.0)
    z_window = _safe_cfg_int(cfg, "SIGNALS_MR_SCALPER_WINDOW", 30)
    vwap_window = _safe_cfg_int(cfg, "SIGNALS_MR_SCALPER_VWAP_WINDOW", 15)

    closes = list(ctx.closes_1m)
    h = list(ctx.highs_1m)
    l = list(ctx.lows_1m)
    v = list(ctx.volumes_1m)

    # 1. VWAP Z-score
    z_val = _vwap_zscore(closes, h, l, v, vwap_window, z_window)
    if z_val is None:
        return SignalResult(name="mr_scalper", active=False, reason="no_data")

    # 2. RSI gate
    rsi_val = rsi(closes, 14)
    rsi_gate = 100.0 if rsi_val is None else float(rsi_val)

    # 3. Volume surge check
    if len(v) >= 21:
        avg_vol = sum(v[-21:-1]) / 20 if sum(v[-21:-1]) > 0 else 1
        vol_ratio = v[-1] / avg_vol if avg_vol > 0 else 0
    else:
        vol_ratio = 0

    # 4. Bollinger Band position
    from .indicators import sma as _sma
    import numpy as np
    price = closes[-1] if closes else 0
    bb_window = 20
    below_bb = False
    if len(closes) >= bb_window:
        ma = sum(closes[-bb_window:]) / bb_window
        std = (sum((c - ma) ** 2 for c in closes[-bb_window:]) / bb_window) ** 0.5
        lower_bb = ma - 2 * std
        below_bb = price < lower_bb

    # Check all conditions
    if z_val > z_entry:
        return SignalResult(
            name="mr_scalper", active=False, reason="zscore_not_extreme",
            details={"zscore": round(z_val, 3), "rsi": rsi_val, "vol_ratio": round(vol_ratio, 2)},
        )

    if rsi_gate > rsi_cap:
        return SignalResult(
            name="mr_scalper", active=False, reason="rsi_too_high",
            details={"zscore": round(z_val, 3), "rsi": rsi_val},
        )

    # Score: more extreme = higher score
    # Base score from zscore deviation beyond entry threshold
    score = abs(z_val - z_entry) * 2.0

    # Bonus for volume surge (confirms panic selling)
    if vol_ratio > 1.5:
        score += min(vol_ratio - 1.0, 3.0)

    # Bonus for being below BB
    if below_bb:
        score += 1.5

    # Bonus for very low RSI
    if rsi_gate < 25:
        score += 1.0

    return SignalResult(
        name="mr_scalper",
        active=True,
        score=round(score, 2),
        reason="vwap_reversion",
        details={
            "zscore": round(z_val, 3),
            "rsi": rsi_val,
            "vol_ratio": round(vol_ratio, 2),
            "below_bb": below_bb,
            "price": price,
        },
    )
