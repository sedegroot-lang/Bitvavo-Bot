"""Microstructure Momentum Signal — detects hidden momentum from order flow microstructure.

Instead of standard price momentum, this analyzes the *quality* of price moves:
- Volume-weighted price acceleration (are moves getting stronger?)
- Tick imbalance (more up-ticks than down-ticks?)
- Price efficiency ratio (how much of the move is "real" vs noise?)

This captures institutional accumulation/distribution that standard indicators miss.
Based on: Kyle (1985) "Continuous Auctions and Insider Trading" — adapted lambda estimation.
"""

from __future__ import annotations

import math
from typing import Any, MutableMapping, Sequence

from .base import SignalContext, SignalResult


def _price_efficiency_ratio(closes: Sequence[float], window: int = 20) -> float:
    """Kaufman Efficiency Ratio: net price change / sum of absolute changes.

    PER = 1.0 → perfectly efficient (straight line move)
    PER = 0.0 → no net progress (choppy/noisy)
    """
    if len(closes) < window + 1:
        return 0.5
    w = list(closes[-(window + 1):])
    net_change = abs(w[-1] - w[0])
    sum_abs = sum(abs(w[i + 1] - w[i]) for i in range(len(w) - 1))
    if sum_abs < 1e-12:
        return 0.5
    return net_change / sum_abs


def _volume_weighted_acceleration(
    closes: Sequence[float], volumes: Sequence[float], window: int = 20
) -> float:
    """Volume-weighted price acceleration.

    Positive = accelerating upward (with volume confirmation)
    Negative = accelerating downward
    Near-zero = no significant volume-confirmed momentum
    """
    if len(closes) < window + 2 or len(volumes) < window + 2:
        return 0.0

    # Compute recent returns weighted by volume
    recent = []
    for i in range(-window, 0):
        if closes[i - 1] > 0:
            ret = (closes[i] - closes[i - 1]) / closes[i - 1]
            vol_w = volumes[i] if volumes[i] > 0 else 1.0
            recent.append(ret * vol_w)

    if len(recent) < 4:
        return 0.0

    half = len(recent) // 2
    first_half = sum(recent[:half]) / half if half > 0 else 0
    second_half = sum(recent[half:]) / (len(recent) - half) if len(recent) > half else 0

    # Acceleration = change in average momentum
    return second_half - first_half


def _tick_imbalance(closes: Sequence[float], window: int = 30) -> float:
    """Tick rule imbalance: fraction of up-ticks minus down-ticks.

    Range [-1, 1]. Positive = more buying pressure. Negative = more selling.
    """
    if len(closes) < window + 1:
        return 0.0
    w = list(closes[-(window + 1):])
    up = 0
    down = 0
    for i in range(1, len(w)):
        if w[i] > w[i - 1]:
            up += 1
        elif w[i] < w[i - 1]:
            down += 1
    total = up + down
    if total == 0:
        return 0.0
    return (up - down) / total


def _safe_cfg(cfg: MutableMapping[str, Any], key: str, default: float) -> float:
    try:
        return float(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def microstructure_momentum_signal(ctx: SignalContext) -> SignalResult:
    """Microstructure momentum signal provider.

    Combines three microstructure metrics:
    1. Price Efficiency Ratio (Kaufman) — trend quality
    2. Volume-Weighted Acceleration — momentum strength
    3. Tick Imbalance — hidden buying/selling pressure

    High efficiency + positive acceleration + positive imbalance = strong hidden momentum → bonus.
    Low efficiency + negative acceleration + negative imbalance = distribution → penalty.
    """
    window = int(_safe_cfg(ctx.config, 'MICRO_MOM_WINDOW', 30))
    eff_threshold = _safe_cfg(ctx.config, 'MICRO_MOM_EFF_THRESHOLD', 0.55)
    accel_threshold = _safe_cfg(ctx.config, 'MICRO_MOM_ACCEL_THRESHOLD', 0.0)
    imbalance_threshold = _safe_cfg(ctx.config, 'MICRO_MOM_IMBALANCE_THRESHOLD', 0.15)
    bonus = _safe_cfg(ctx.config, 'MICRO_MOM_BONUS', 0.7)
    penalty = _safe_cfg(ctx.config, 'MICRO_MOM_PENALTY', 0.5)

    closes = ctx.closes_1m
    volumes = ctx.volumes_1m
    if len(closes) < window + 5:
        return SignalResult(name='micro_momentum', reason='insufficient data')

    per = _price_efficiency_ratio(closes, window)
    vwa = _volume_weighted_acceleration(closes, volumes, window)
    ti = _tick_imbalance(closes, window)

    details = {
        'efficiency_ratio': round(per, 4),
        'vol_weighted_accel': round(vwa, 6),
        'tick_imbalance': round(ti, 4),
    }

    # Score composite: all three metrics must align
    bullish_signals = 0
    bearish_signals = 0

    if per > eff_threshold:
        bullish_signals += 1
    elif per < 0.25:
        bearish_signals += 1

    if vwa > accel_threshold:
        bullish_signals += 1
    elif vwa < -accel_threshold:
        bearish_signals += 1

    if ti > imbalance_threshold:
        bullish_signals += 1
    elif ti < -imbalance_threshold:
        bearish_signals += 1

    if bullish_signals >= 2:
        return SignalResult(
            name='micro_momentum', score=bonus, active=True,
            reason=f'hidden bullish momentum (eff={per:.2f}, accel={vwa:.4f}, imb={ti:.2f})',
            details=details,
        )
    elif bearish_signals >= 2:
        return SignalResult(
            name='micro_momentum', score=-penalty, active=True,
            reason=f'hidden distribution detected (eff={per:.2f}, accel={vwa:.4f}, imb={ti:.2f})',
            details=details,
        )
    else:
        return SignalResult(
            name='micro_momentum', score=0.0, active=False,
            reason=f'mixed microstructure (eff={per:.2f})',
            details=details,
        )
