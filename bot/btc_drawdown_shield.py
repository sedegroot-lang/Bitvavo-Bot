# -*- coding: utf-8 -*-
"""BTC drawdown shield: block alt entries when BTC is in fast-fall mode.

Rationale: When BTC drops sharply, alts almost always follow with amplified
losses. This module computes BTC's recent return over a configurable window
and blocks new alt entries if BTC has fallen below a threshold.

Stateless — caller provides BTC candles. Cheap to evaluate (last-N closes).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(slots=True)
class BTCShieldResult:
    blocked: bool
    btc_return_pct: float
    reason: str


def evaluate(btc_candles_5m: Sequence[Sequence] | None,
             *, cfg: Mapping | None = None,
             market: str = "") -> BTCShieldResult:
    """Block alt entries when BTC has dropped below threshold.

    Args:
        btc_candles_5m: List of 5m candles, OHLCV (Bitvavo format:
                       [timestamp, open, high, low, close, volume]).
        cfg: Config mapping with keys:
             BTC_DRAWDOWN_SHIELD_ENABLED (bool, default True)
             BTC_DRAWDOWN_LOOKBACK_5M (int, default 12 = 1 hour)
             BTC_DRAWDOWN_THRESHOLD_PCT (float, default -1.5)
                 If BTC return over the lookback is below this, block.
        market: Market being evaluated (for logging). BTC itself is exempt.
    """
    cfg = cfg or {}
    if not bool(cfg.get('BTC_DRAWDOWN_SHIELD_ENABLED', True)):
        return BTCShieldResult(False, 0.0, 'disabled')

    if market.upper().startswith('BTC-'):
        return BTCShieldResult(False, 0.0, 'is_btc')

    if not btc_candles_5m or len(btc_candles_5m) < 3:
        return BTCShieldResult(False, 0.0, 'no_data')

    lookback = int(cfg.get('BTC_DRAWDOWN_LOOKBACK_5M', 12))
    threshold = float(cfg.get('BTC_DRAWDOWN_THRESHOLD_PCT', -1.5))

    candles = btc_candles_5m[-(lookback + 1):]
    try:
        # Bitvavo format: index 4 = close
        first_close = float(candles[0][4])
        last_close = float(candles[-1][4])
    except (IndexError, ValueError, TypeError):
        return BTCShieldResult(False, 0.0, 'parse_error')

    if first_close <= 0:
        return BTCShieldResult(False, 0.0, 'invalid_price')

    ret_pct = (last_close - first_close) / first_close * 100.0
    if ret_pct <= threshold:
        return BTCShieldResult(
            True, ret_pct,
            f'BTC {ret_pct:+.2f}% over last {lookback*5}m <= {threshold:+.2f}%'
        )
    return BTCShieldResult(False, ret_pct, f'BTC {ret_pct:+.2f}% (ok)')
