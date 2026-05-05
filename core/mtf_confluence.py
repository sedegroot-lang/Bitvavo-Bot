"""Multi-Timeframe Confluence Engine — score bonus based on higher-timeframe alignment.

Analyses 15m, 1h, and 4h candle data for each market.  Returns a score bonus
(−2 to +5) reflecting how strongly the higher time-frames confirm the 1m entry.

Usage
-----
    from core.mtf_confluence import mtf_score_bonus
    bonus, details = mtf_score_bonus(market, api_get_candles)
"""

from __future__ import annotations

import logging
import time as _time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MTF result cache: {market: (bonus, details, timestamp)}
# ---------------------------------------------------------------------------
_mtf_cache: Dict[str, Tuple[float, Dict[str, Any], float]] = {}
_MTF_CACHE_TTL_SECS = 120  # 2 minutes — 15m candles change slowly

# ---------------------------------------------------------------------------
# Lightweight TA helpers (avoid heavy deps; works on plain float sequences)
# ---------------------------------------------------------------------------


def _sma(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return float(np.mean(values[-period:]))


def _ema(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    arr = np.array(values, dtype=np.float64)
    alpha = 2.0 / (period + 1)
    ema_val = arr[0]
    for v in arr[1:]:
        ema_val = alpha * v + (1 - alpha) * ema_val
    return float(ema_val)


def _rsi(values: Sequence[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1:
        return None
    deltas = np.diff(values[-period - 1 :])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains)) if len(gains) else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) else 1e-9
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def _macd_histogram(values: Sequence[float], fast: int = 12, slow: int = 26, sig: int = 9) -> Optional[float]:
    if len(values) < slow + sig:
        return None
    ema_fast = _ema(values, fast)
    ema_slow = _ema(values, slow)
    if ema_fast is None or ema_slow is None:
        return None
    # Simplified: histogram = fast EMA - slow EMA (positive = bullish momentum)
    return ema_fast - ema_slow


def _adx(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> Optional[float]:
    """Simplified ADX — measures trend strength (0-100)."""
    n = len(closes)
    if n < period + 1:
        return None
    try:
        h = np.array(highs[-period - 1 :], dtype=np.float64)
        l = np.array(lows[-period - 1 :], dtype=np.float64)
        c = np.array(closes[-period - 1 :], dtype=np.float64)
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        up_move = h[1:] - h[:-1]
        dn_move = l[:-1] - l[1:]
        plus_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
        atr = float(np.mean(tr))
        if atr < 1e-12:
            return None
        plus_di = 100 * float(np.mean(plus_dm)) / atr
        minus_di = 100 * float(np.mean(minus_dm)) / atr
        denom = plus_di + minus_di
        if denom < 1e-12:
            return 0.0
        dx = 100.0 * abs(plus_di - minus_di) / denom
        return dx
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Timeframe analysis
# ---------------------------------------------------------------------------


def _analyse_timeframe(
    closes: Sequence[float],
    highs: Optional[Sequence[float]] = None,
    lows: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Analyse a single timeframe and return trend metrics."""
    result: Dict[str, Any] = {
        "trend": "neutral",
        "strength": 0.0,
        "rsi": None,
        "macd_hist": None,
        "adx": None,
        "sma_cross": False,
        "price_above_ema": False,
    }
    if not closes or len(closes) < 26:
        return result

    price = closes[-1]
    sma_fast = _sma(closes, 9)
    sma_slow = _sma(closes, 21)
    ema_21 = _ema(closes, 21)
    r = _rsi(closes, 14)
    mh = _macd_histogram(closes)

    result["rsi"] = r
    result["macd_hist"] = mh

    if highs and lows and len(highs) >= 15 and len(lows) >= 15:
        result["adx"] = _adx(highs, lows, closes)

    # Trend classification
    bullish_signals = 0
    bearish_signals = 0

    if sma_fast is not None and sma_slow is not None:
        result["sma_cross"] = sma_fast > sma_slow
        if sma_fast > sma_slow:
            bullish_signals += 1
        else:
            bearish_signals += 1

    if ema_21 is not None:
        result["price_above_ema"] = price > ema_21
        if price > ema_21:
            bullish_signals += 1
        else:
            bearish_signals += 1

    if r is not None:
        if r > 55:
            bullish_signals += 1
        elif r < 45:
            bearish_signals += 1

    if mh is not None:
        if mh > 0:
            bullish_signals += 1
        else:
            bearish_signals += 1

    adx_val = result.get("adx")
    strong_trend = adx_val is not None and adx_val > 25

    if bullish_signals >= 3:
        result["trend"] = "bullish"
        result["strength"] = min(1.0, bullish_signals / 4.0)
        if strong_trend:
            result["strength"] = min(1.0, result["strength"] + 0.2)
    elif bearish_signals >= 3:
        result["trend"] = "bearish"
        result["strength"] = min(1.0, bearish_signals / 4.0)
        if strong_trend:
            result["strength"] = min(1.0, result["strength"] + 0.2)
    else:
        result["trend"] = "neutral"
        result["strength"] = 0.3

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

GetCandlesFn = Callable[[str, str, int], Optional[List]]


def _extract_closes(candles: List) -> List[float]:
    """Extract close prices from candle list."""
    try:
        return [float(c[4]) if hasattr(c, "__getitem__") else float(c) for c in candles]
    except (IndexError, TypeError, ValueError):
        return []


def _extract_highs(candles: List) -> List[float]:
    try:
        return [float(c[2]) for c in candles]
    except (IndexError, TypeError, ValueError):
        return []


def _extract_lows(candles: List) -> List[float]:
    try:
        return [float(c[3]) for c in candles]
    except (IndexError, TypeError, ValueError):
        return []


def mtf_score_bonus(
    market: str,
    get_candles: GetCandlesFn,
    *,
    timeframes: Optional[Dict[str, int]] = None,
) -> Tuple[float, Dict[str, Any]]:
    """Calculate score bonus from multi-timeframe trend alignment.

    Parameters
    ----------
    market : str
        e.g. ``"SOL-EUR"``
    get_candles : callable
        ``(market, interval, limit) -> list_of_candles``
    timeframes : dict, optional
        ``{interval: limit}`` override.  Defaults to ``{'15m': 60, '1h': 48, '4h': 30}``.

    Returns
    -------
    (bonus, details) : tuple
        *bonus* is in range [−2.0 .. +5.0].
        *details* is a dict with per-timeframe analysis.
    """
    # ── Cache: avoid redundant API calls (51/cycle → 0 when warm) ──
    _now = _time.time()
    _cached = _mtf_cache.get(market)
    if _cached is not None:
        _c_bonus, _c_details, _c_ts = _cached
        if (_now - _c_ts) < _MTF_CACHE_TTL_SECS:
            logger.debug(f"[MTF] {market}: cache hit (age={_now - _c_ts:.0f}s)")
            return _c_bonus, _c_details

    tfs = timeframes or {"15m": 60, "1h": 48, "4h": 30}

    analyses: Dict[str, Dict[str, Any]] = {}
    bullish_count = 0
    bearish_count = 0
    total_strength = 0.0

    # Weight higher timeframes more (4h > 1h > 15m)
    tf_weights = {"15m": 0.8, "1h": 1.2, "4h": 1.5}

    for interval, limit in tfs.items():
        try:
            candles = get_candles(market, interval, limit)
            if not candles or len(candles) < 26:
                analyses[interval] = {"status": "insufficient_data"}
                continue

            closes = _extract_closes(candles)
            highs = _extract_highs(candles)
            lows = _extract_lows(candles)

            if len(closes) < 26:
                analyses[interval] = {"status": "insufficient_data"}
                continue

            analysis = _analyse_timeframe(closes, highs, lows)
            analyses[interval] = analysis

            weight = tf_weights.get(interval, 1.0)

            if analysis["trend"] == "bullish":
                bullish_count += 1
                total_strength += analysis["strength"] * weight
            elif analysis["trend"] == "bearish":
                bearish_count += 1
                total_strength -= analysis["strength"] * weight

        except Exception as exc:
            analyses[interval] = {"status": f"error:{exc}"}
            logger.debug(f"[MTF] {market} {interval}: {exc}")

    # Calculate bonus
    n_tfs = len([a for a in analyses.values() if "status" not in a])
    bonus = 0.0

    if n_tfs == 0:
        return 0.0, {"analyses": analyses, "bonus": 0.0, "reason": "no_data"}

    if bullish_count == n_tfs and n_tfs >= 2:
        # All timeframes bullish = strong confluence
        bonus = min(5.0, 2.0 + total_strength * 2.0)
        reason = f"full_bullish_confluence ({n_tfs} TFs aligned)"
    elif bullish_count > bearish_count:
        # Majority bullish
        bonus = min(3.0, 0.5 + total_strength * 1.0)
        reason = f"partial_bullish ({bullish_count}/{n_tfs} bullish)"
    elif bearish_count == n_tfs and n_tfs >= 2:
        # All bearish = strong contra-signal
        bonus = max(-2.0, -1.0 - abs(total_strength) * 0.5)
        reason = f"full_bearish_confluence ({n_tfs} TFs bearish)"
    elif bearish_count > bullish_count:
        # Majority bearish
        bonus = max(-1.5, -0.5 - abs(total_strength) * 0.3)
        reason = f"partial_bearish ({bearish_count}/{n_tfs} bearish)"
    else:
        bonus = 0.0
        reason = "mixed_signals"

    details = {
        "analyses": {k: v for k, v in analyses.items()},
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "n_timeframes": n_tfs,
        "total_strength": round(total_strength, 3),
        "bonus": round(bonus, 2),
        "reason": reason,
    }

    logger.debug(f"[MTF] {market}: bonus={bonus:+.2f} ({reason})")

    # ── Store in cache ──
    _mtf_cache[market] = (round(bonus, 2), details, _time.time())

    return round(bonus, 2), details
