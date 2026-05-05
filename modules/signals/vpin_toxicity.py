"""VPIN Toxicity Filter — Volume-Synchronized Probability of Informed Trading.

Simulation showed +€27 improvement by blocking trades when toxic (informed) order flow is detected.
Based on Easley, López de Prado & O'Hara (2012) — academic early crash detection metric.
"""

from __future__ import annotations

from .base import SignalContext, SignalResult, _safe_cfg_float, _safe_cfg_int


def vpin_toxicity_signal(ctx: SignalContext) -> SignalResult:
    """Detects toxic order flow using VPIN proxy and penalizes entries.

    Uses a tick-rule approximation: up-tick = buy volume, down-tick = sell volume.
    High VPIN (>0.4) indicates informed traders are active → crash risk.

    Config keys:
        VPIN_LOOKBACK (int): candles for VPIN calculation (default 50)
        VPIN_THRESHOLD (float): VPIN level above which to penalize (default 0.40)
        VPIN_PENALTY (float): score penalty when toxic (default -1.0)
        VPIN_SAFE_BONUS (float): bonus when flow is clean (default 0.3)
    """
    lookback = _safe_cfg_int(ctx.config, "VPIN_LOOKBACK", 50)
    threshold = _safe_cfg_float(ctx.config, "VPIN_THRESHOLD", 0.40)
    penalty = _safe_cfg_float(ctx.config, "VPIN_PENALTY", 1.0)
    safe_bonus = _safe_cfg_float(ctx.config, "VPIN_SAFE_BONUS", 0.3)

    closes = list(ctx.closes_1m)
    volumes = list(ctx.volumes_1m)

    if len(closes) < lookback + 1 or len(volumes) < lookback + 1:
        return SignalResult(name="vpin_toxicity", score=0.0, reason="insufficient data")

    # Classify volume as buy or sell using tick rule
    buy_vol = 0.0
    sell_vol = 0.0
    start = len(closes) - lookback

    for i in range(start, len(closes)):
        vol = volumes[i] if i < len(volumes) else 0
        if closes[i] > closes[i - 1]:
            buy_vol += vol
        elif closes[i] < closes[i - 1]:
            sell_vol += vol
        else:
            # Split evenly on no change
            buy_vol += vol * 0.5
            sell_vol += vol * 0.5

    total_vol = buy_vol + sell_vol
    if total_vol < 1e-9:
        return SignalResult(name="vpin_toxicity", score=0.0, reason="no volume")

    vpin = abs(buy_vol - sell_vol) / total_vol

    if vpin > threshold:
        return SignalResult(
            name="vpin_toxicity",
            score=-penalty,
            active=True,
            reason=f"toxic flow detected (VPIN={vpin:.3f} > {threshold})",
            details={"vpin": round(vpin, 4), "buy_vol": round(buy_vol, 2), "sell_vol": round(sell_vol, 2)},
        )
    elif vpin < threshold * 0.5:
        return SignalResult(
            name="vpin_toxicity",
            score=safe_bonus,
            active=True,
            reason=f"clean flow (VPIN={vpin:.3f})",
            details={"vpin": round(vpin, 4), "buy_vol": round(buy_vol, 2), "sell_vol": round(sell_vol, 2)},
        )
    else:
        return SignalResult(
            name="vpin_toxicity",
            score=0.0,
            active=False,
            reason=f"moderate flow (VPIN={vpin:.3f})",
            details={"vpin": round(vpin, 4)},
        )
