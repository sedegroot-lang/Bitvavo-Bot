"""core.regime_engine – Bayesian Online Changepoint Detection (BOCPD) Regime Engine.

Detects market regime shifts in real-time using a simplified BOCPD approach
combined with multi-timeframe analysis. Classifies the market into 4 regimes:

  - TRENDING_UP:   Trailing bot max exposure, grid paused, pyramid-up DCA
  - RANGING:       Grid bot maximized, trailing minimal, tighter ranges
  - HIGH_VOLATILITY: All positions smaller, grids wider, tight trailing
  - BEARISH:       Circuit breaker, no new buys, DCA agressief

Academic basis: Adams & MacKay (2007) "Bayesian Online Changepoint Detection"
Simplified for production use without scipy dependency.

No external API needed — uses only Bitvavo candle data already available.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

from modules.logging_utils import log

# ── Regime Definitions ──
REGIME_TRENDING_UP = "trending_up"
REGIME_RANGING = "ranging"
REGIME_HIGH_VOL = "high_volatility"
REGIME_BEARISH = "bearish"

# ── Parameter Profiles per Regime ──
REGIME_PROFILES: Dict[str, Dict[str, Any]] = {
    REGIME_TRENDING_UP: {
        "trailing_pct_override": 0.03,       # Tighter trailing to ride trends
        "base_amount_mult": 1.3,             # Bigger positions in trend
        "max_trades_mult": 1.0,
        "dca_enabled": True,
        "dca_pyramid_up": True,              # Add on winners
        "grid_pause": False,                 # Grid also profits in strong trends
        "sl_mult": 1.2,                      # Wider SL to avoid stop-outs
        "min_score_adj": -1.0,               # Lower entry threshold in uptrend
        "description": "Strong uptrend: max trailing, pyramid DCA, grid active",
    },
    REGIME_RANGING: {
        "trailing_pct_override": None,       # Default trailing
        "base_amount_mult": 0.8,             # Smaller trailing positions
        "max_trades_mult": 0.7,
        "dca_enabled": True,
        "dca_pyramid_up": False,
        "grid_pause": False,                 # Grid thrives in range
        "sl_mult": 0.8,                      # Tighter SL in range
        "min_score_adj": 1.0,                # Higher threshold = pickier
        "description": "Ranging: grid maximized, trailing minimal",
    },
    REGIME_HIGH_VOL: {
        "trailing_pct_override": 0.025,      # Very tight trailing
        "base_amount_mult": 0.6,             # Smaller positions
        "max_trades_mult": 0.5,
        "dca_enabled": False,                # No DCA in chaos
        "dca_pyramid_up": False,
        "grid_pause": True,                  # Grid danger zone
        "sl_mult": 0.7,                      # Tight SL
        "min_score_adj": 3.0,                # Very picky entries
        "description": "High volatility: reduced exposure, tight stops",
    },
    REGIME_BEARISH: {
        "trailing_pct_override": None,
        "base_amount_mult": 0.0,             # NO new buys
        "max_trades_mult": 0.0,
        "dca_enabled": True,                 # DCA for averaging down existing
        "dca_pyramid_up": False,
        "grid_pause": True,
        "sl_mult": 0.6,                      # Very tight SL
        "min_score_adj": 99.0,               # Effectively blocks all buys
        "description": "Bearish: all buys blocked, only sells + DCA averaging",
    },
}

# ── BOCPD Parameters ──
_HAZARD_LAMBDA = 200         # Expected run length before changepoint (in candles)
_MIN_RUN_LENGTH = 10         # Min samples before considering a regime change
_CHANGEPOINT_THRESHOLD = 0.6 # Posterior probability threshold for regime shift

# Cache
_regime_cache: Dict[str, Any] = {}
_CACHE_TTL = 120  # seconds (re-evaluate every 2 minutes)


def _returns_from_candles(candles: List[List]) -> List[float]:
    """Extract log-returns from candle data [[ts,o,h,l,c,v], ...]."""
    closes = []
    for c in candles:
        try:
            closes.append(float(c[4]))  # close price
        except (IndexError, TypeError, ValueError):
            continue
    if len(closes) < 2:
        return []
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]


def _rolling_stats(returns: List[float], window: int = 20) -> Tuple[List[float], List[float]]:
    """Compute rolling mean and std of returns."""
    means = []
    stds = []
    for i in range(window, len(returns)):
        segment = returns[i - window:i]
        mu = sum(segment) / len(segment)
        var = sum((x - mu) ** 2 for x in segment) / len(segment)
        means.append(mu)
        stds.append(math.sqrt(var) if var > 0 else 1e-8)
    return means, stds


def _gaussian_logpdf(x: float, mu: float, sigma: float) -> float:
    """Log PDF of normal distribution."""
    if sigma <= 0:
        sigma = 1e-8
    return -0.5 * math.log(2 * math.pi * sigma ** 2) - (x - mu) ** 2 / (2 * sigma ** 2)


def _bocpd_changepoint_probability(returns: List[float]) -> List[float]:
    """Simplified BOCPD: compute changepoint posterior probabilities.

    Uses a Gaussian observation model with adaptive mean/variance.
    Returns list of changepoint probabilities for each time step.
    """
    n = len(returns)
    if n < 5:
        return [0.0] * n

    hazard = 1.0 / _HAZARD_LAMBDA  # Prior probability of changepoint at each step

    # Online sufficient statistics
    changepoint_prob = [0.0] * n
    # Running statistics for current segment
    seg_sum = 0.0
    seg_sq_sum = 0.0
    seg_count = 0
    # Prior statistics (from first few samples)
    prior_mu = sum(returns[:min(5, n)]) / min(5, n)
    prior_var = max(sum((r - prior_mu) ** 2 for r in returns[:min(5, n)]) / min(5, n), 1e-8)

    for t in range(n):
        x = returns[t]
        seg_count += 1
        seg_sum += x
        seg_sq_sum += x * x

        if seg_count >= _MIN_RUN_LENGTH:
            seg_mu = seg_sum / seg_count
            seg_var = max(seg_sq_sum / seg_count - seg_mu ** 2, 1e-8)

            # Predictive probability under current run
            logp_run = _gaussian_logpdf(x, seg_mu, math.sqrt(seg_var))
            # Predictive probability under new segment (prior)
            logp_new = _gaussian_logpdf(x, prior_mu, math.sqrt(prior_var))

            # Posterior changepoint probability (simplified)
            log_odds = logp_new - logp_run + math.log(hazard / (1 - hazard + 1e-12))
            # Sigmoid to get probability
            try:
                prob = 1.0 / (1.0 + math.exp(-log_odds))
            except OverflowError:
                prob = 0.0 if log_odds < 0 else 1.0

            changepoint_prob[t] = prob

            # If changepoint detected, reset segment
            if prob > _CHANGEPOINT_THRESHOLD:
                seg_sum = x
                seg_sq_sum = x * x
                seg_count = 1

    return changepoint_prob


def _classify_regime(
    returns_1m: List[float],
    returns_5m: List[float],
    returns_1h: List[float],
) -> Tuple[str, float, Dict[str, Any]]:
    """Classify market regime from multi-timeframe returns.

    Uses:
    - 1m returns: short-term volatility detection
    - 5m returns: medium-term trend detection
    - 1h returns: macro trend confirmation

    Returns (regime, confidence, details)
    """
    details: Dict[str, Any] = {}

    # ── 1. Volatility analysis (1m returns) ──
    if returns_1m and len(returns_1m) >= 20:
        recent_vol = math.sqrt(sum(r ** 2 for r in returns_1m[-20:]) / 20) * 100
        baseline_vol = math.sqrt(sum(r ** 2 for r in returns_1m) / len(returns_1m)) * 100 if returns_1m else recent_vol
        vol_ratio = recent_vol / baseline_vol if baseline_vol > 0 else 1.0
    else:
        recent_vol = 0.0
        vol_ratio = 1.0
    details["volatility_1m_pct"] = round(recent_vol, 4)
    details["vol_ratio"] = round(vol_ratio, 3)

    # ── 2. Trend analysis (5m returns) ──
    if returns_5m and len(returns_5m) >= 10:
        trend_5m = sum(returns_5m[-10:]) * 100  # Cumulative return last 10 candles
        trend_direction = 1 if trend_5m > 0.1 else (-1 if trend_5m < -0.1 else 0)
    else:
        trend_5m = 0.0
        trend_direction = 0
    details["trend_5m_pct"] = round(trend_5m, 4)

    # ── 3. Macro trend (1h returns) ──
    if returns_1h and len(returns_1h) >= 5:
        trend_1h = sum(returns_1h[-5:]) * 100  # Cumulative return last 5 hours
        macro_bullish = trend_1h > 0.5
        macro_bearish = trend_1h < -0.5
    else:
        trend_1h = 0.0
        macro_bullish = False
        macro_bearish = False
    details["trend_1h_pct"] = round(trend_1h, 4)

    # ── 4. BOCPD changepoint detection ──
    cp_probs = _bocpd_changepoint_probability(returns_1m[-100:] if len(returns_1m) > 100 else returns_1m)
    recent_cp = max(cp_probs[-10:]) if cp_probs and len(cp_probs) >= 10 else 0.0
    details["changepoint_prob"] = round(recent_cp, 3)

    # ── 5. Regime Classification ──
    # Priority: HIGH_VOL > BEARISH > TRENDING_UP > RANGING

    # High volatility: vol_ratio > 2x baseline AND recent changepoint
    if vol_ratio > 2.0 and recent_cp > 0.4:
        regime = REGIME_HIGH_VOL
        confidence = min(0.95, vol_ratio / 3.0)
        details["trigger"] = f"vol_ratio={vol_ratio:.2f}, cp={recent_cp:.2f}"

    # Bearish: macro downtrend + medium term downtrend
    elif macro_bearish and trend_direction == -1:
        regime = REGIME_BEARISH
        confidence = min(0.9, abs(trend_1h) / 2.0 + abs(trend_5m) / 1.0)
        details["trigger"] = f"1h={trend_1h:.2f}%, 5m={trend_5m:.2f}%"

    # Trending up: macro uptrend + medium term uptrend
    elif macro_bullish and trend_direction == 1:
        regime = REGIME_TRENDING_UP
        confidence = min(0.9, trend_1h / 2.0 + trend_5m / 1.0)
        details["trigger"] = f"1h={trend_1h:.2f}%, 5m={trend_5m:.2f}%"

    # Default: ranging
    else:
        regime = REGIME_RANGING
        confidence = 0.5 + 0.3 * (1.0 - vol_ratio / 2.0)  # More confident in calm markets
        confidence = max(0.3, min(0.8, confidence))
        details["trigger"] = f"no_clear_trend (vol_ratio={vol_ratio:.2f})"

    return regime, round(confidence, 3), details


def detect_regime(
    candles_1m: Optional[List[List]] = None,
    candles_5m: Optional[List[List]] = None,
    candles_1h: Optional[List[List]] = None,
    market: str = "BTC-EUR",
) -> Dict[str, Any]:
    """Detect current market regime using multi-timeframe BOCPD analysis.

    Args:
        candles_1m: 1-minute candles (at least 60, ideally 200+)
        candles_5m: 5-minute candles (at least 30, ideally 100+)
        candles_1h: 1-hour candles (at least 12, ideally 48+)
        market: Market identifier for caching

    Returns dict with:
        regime: str (trending_up|ranging|high_volatility|bearish)
        confidence: float (0-1)
        profile: dict (parameter adjustments for this regime)
        details: dict (diagnostic info)
    """
    now = time.time()

    # Check cache
    cached = _regime_cache.get(market)
    if cached and (now - cached.get("ts", 0)) < _CACHE_TTL:
        return cached["result"]

    # Extract returns from candle data
    returns_1m = _returns_from_candles(candles_1m or [])
    returns_5m = _returns_from_candles(candles_5m or [])
    returns_1h = _returns_from_candles(candles_1h or [])

    if not returns_1m and not returns_5m:
        # Insufficient data → default to ranging
        result = {
            "regime": REGIME_RANGING,
            "confidence": 0.3,
            "profile": REGIME_PROFILES[REGIME_RANGING],
            "details": {"error": "insufficient_data"},
            "market": market,
            "timestamp": now,
        }
        return result

    regime, confidence, details = _classify_regime(returns_1m, returns_5m, returns_1h)

    result = {
        "regime": regime,
        "confidence": confidence,
        "profile": REGIME_PROFILES[regime],
        "details": details,
        "market": market,
        "timestamp": now,
    }

    # Cache result
    _regime_cache[market] = {"result": result, "ts": now}

    log(
        f"[REGIME] {market}: {regime} (conf={confidence:.0%}) — {details.get('trigger', '')}",
        level="info" if regime != REGIME_RANGING else "debug",
    )

    return result


def get_regime_adjustments(regime_result: Dict[str, Any]) -> Dict[str, Any]:
    """Get parameter adjustments from a regime detection result.

    Returns a dict of config adjustments to apply.
    """
    profile = regime_result.get("profile", REGIME_PROFILES[REGIME_RANGING])
    regime = regime_result.get("regime", REGIME_RANGING)
    confidence = regime_result.get("confidence", 0.5)

    # Scale adjustments by confidence (less confident = less extreme changes)
    base_mult = profile.get("base_amount_mult", 1.0)
    # Blend toward 1.0 when confidence is low
    blended_mult = 1.0 + (base_mult - 1.0) * confidence

    return {
        "regime": regime,
        "confidence": confidence,
        "base_amount_mult": round(blended_mult, 3),
        "max_trades_mult": profile.get("max_trades_mult", 1.0),
        "trailing_pct_override": profile.get("trailing_pct_override"),
        "dca_enabled": profile.get("dca_enabled", True),
        "dca_pyramid_up": profile.get("dca_pyramid_up", False),
        "grid_pause": profile.get("grid_pause", False),
        "sl_mult": profile.get("sl_mult", 1.0),
        "min_score_adj": profile.get("min_score_adj", 0.0) * confidence,
        "description": profile.get("description", ""),
    }


def get_btc_regime(candles_1m=None, candles_5m=None, candles_1h=None) -> Dict[str, Any]:
    """Shortcut to get BTC regime (used as systemic market regime)."""
    return detect_regime(candles_1m, candles_5m, candles_1h, market="BTC-EUR")
