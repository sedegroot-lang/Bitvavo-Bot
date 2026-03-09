"""Adaptive Exit Manager — dynamic TP/SL based on regime, ATR, and volume profile.

Instead of static trailing percentages, this module calculates per-trade
exit parameters that adapt to:
1. Current market regime (trending → wide SL, ranging → tight TP)
2. ATR-based volatility (avoid getting stopped out by noise)
3. Volume profile resistance levels (set TP near key levels)

Usage
-----
    from core.adaptive_exit import calculate_adaptive_exits
    exits = calculate_adaptive_exits(market, entry_price, candles_1m, regime)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ATR Calculation
# ---------------------------------------------------------------------------

def _atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> Optional[float]:
    """Average True Range — measures price volatility."""
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return None
    
    try:
        h = np.array(highs[-(period + 1):], dtype=np.float64)
        l = np.array(lows[-(period + 1):], dtype=np.float64)
        c = np.array(closes[-(period + 1):], dtype=np.float64)
        
        tr = np.maximum(
            h[1:] - l[1:],
            np.maximum(
                np.abs(h[1:] - c[:-1]),
                np.abs(l[1:] - c[:-1]),
            ),
        )
        return float(np.mean(tr))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Support/Resistance Detection
# ---------------------------------------------------------------------------

def _find_resistance_levels(
    closes: Sequence[float],
    highs: Sequence[float],
    n_levels: int = 3,
) -> List[float]:
    """Find resistance levels from recent price action."""
    if len(closes) < 30 or len(highs) < 30:
        return []
    
    try:
        h = np.array(highs[-120:], dtype=np.float64)
        c = np.array(closes[-120:], dtype=np.float64)
        price = c[-1]
        
        # Find local maxima
        resistances = []
        for i in range(2, len(h) - 2):
            if h[i] > h[i-1] and h[i] > h[i-2] and h[i] > h[i+1] and h[i] > h[i+2]:
                if h[i] > price * 1.001:  # Above current price
                    resistances.append(float(h[i]))
        
        if not resistances:
            # Fallback: use recent high
            resistances = [float(np.max(h[-30:]))]
        
        # Cluster nearby levels and take the strongest
        resistances.sort()
        clustered = []
        for r in resistances:
            if not clustered or abs(r - clustered[-1]) / price > 0.003:
                clustered.append(r)
        
        return clustered[:n_levels]
    except Exception:
        return []


def _find_support_levels(
    closes: Sequence[float],
    lows: Sequence[float],
    n_levels: int = 3,
) -> List[float]:
    """Find support levels from recent price action."""
    if len(closes) < 30 or len(lows) < 30:
        return []
    
    try:
        l = np.array(lows[-120:], dtype=np.float64)
        c = np.array(closes[-120:], dtype=np.float64)
        price = c[-1]
        
        supports = []
        for i in range(2, len(l) - 2):
            if l[i] < l[i-1] and l[i] < l[i-2] and l[i] < l[i+1] and l[i] < l[i+2]:
                if l[i] < price * 0.999:  # Below current price
                    supports.append(float(l[i]))
        
        if not supports:
            supports = [float(np.min(l[-30:]))]
        
        supports.sort(reverse=True)
        clustered = []
        for s in supports:
            if not clustered or abs(s - clustered[-1]) / price > 0.003:
                clustered.append(s)
        
        return clustered[:n_levels]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Adaptive Exit Calculation
# ---------------------------------------------------------------------------

def calculate_adaptive_exits(
    market: str,
    entry_price: float,
    candles_1m: List,
    regime: str = "ranging",
    base_trailing_pct: float = 0.04,
    base_sl_pct: float = 0.05,
) -> Dict[str, Any]:
    """Calculate adaptive exit parameters for a trade.
    
    Returns
    -------
    dict with keys:
    - trailing_pct: adaptive trailing stop percentage
    - hard_sl_pct: adaptive hard stop loss percentage
    - tp_levels: list of take-profit levels [{pct, sell_fraction, reason}]
    - trailing_activation_pct: when to activate trailing
    - resistances: detected resistance levels
    - supports: detected support levels
    """
    result = {
        "trailing_pct": base_trailing_pct,
        "hard_sl_pct": base_sl_pct,
        "trailing_activation_pct": 0.025,
        "tp_levels": [],
        "resistances": [],
        "supports": [],
        "atr_pct": None,
        "regime": regime,
    }
    
    if not candles_1m or len(candles_1m) < 30:
        return result
    
    try:
        closes = [float(c[4]) for c in candles_1m]
        highs = [float(c[2]) for c in candles_1m]
        lows = [float(c[3]) for c in candles_1m]
    except (IndexError, TypeError, ValueError):
        return result
    
    # ATR-based volatility
    atr = _atr(highs, lows, closes)
    if atr is None or entry_price == 0:
        return result
    
    atr_pct = atr / entry_price
    result["atr_pct"] = round(atr_pct, 6)
    
    # Support/Resistance
    resistances = _find_resistance_levels(closes, highs)
    supports = _find_support_levels(closes, lows)
    result["resistances"] = [round(r, 8) for r in resistances]
    result["supports"] = [round(s, 8) for s in supports]
    
    # === Regime-Adaptive Parameters ===
    
    if regime in ("trending_up", "REGIME_TRENDING_UP"):
        # TRENDING: wide stops, let profits run
        trailing_mult = 2.5  # wider trailing
        sl_mult = 3.0  # wider SL
        activation_mult = 1.5  # activate later
        
        result["trailing_pct"] = max(0.02, min(0.08, atr_pct * trailing_mult))
        result["hard_sl_pct"] = max(0.03, min(0.10, atr_pct * sl_mult))
        result["trailing_activation_pct"] = max(0.015, min(0.05, atr_pct * activation_mult))
        
        # TP levels: scale out gradually
        result["tp_levels"] = [
            {"pct": 0.03, "sell_fraction": 0.15, "reason": "quick_profit"},
            {"pct": 0.06, "sell_fraction": 0.20, "reason": "moderate_profit"},
            {"pct": 0.10, "sell_fraction": 0.25, "reason": "strong_profit"},
            # Remaining 40% trails
        ]
        
    elif regime in ("ranging", "REGIME_RANGING"):
        # RANGING: tight stops, quick TP
        trailing_mult = 1.5
        sl_mult = 2.0
        activation_mult = 0.8
        
        result["trailing_pct"] = max(0.015, min(0.04, atr_pct * trailing_mult))
        result["hard_sl_pct"] = max(0.02, min(0.06, atr_pct * sl_mult))
        result["trailing_activation_pct"] = max(0.01, min(0.03, atr_pct * activation_mult))
        
        # TP levels: take profit fast in ranging
        result["tp_levels"] = [
            {"pct": 0.015, "sell_fraction": 0.30, "reason": "range_quick_exit"},
            {"pct": 0.03, "sell_fraction": 0.35, "reason": "range_target"},
            {"pct": 0.05, "sell_fraction": 0.25, "reason": "range_extended"},
            # Remaining 10% trails
        ]
        
    elif regime in ("high_vol", "REGIME_HIGH_VOL"):
        # HIGH VOLATILITY: very wide stops, aggressive TP
        trailing_mult = 3.0
        sl_mult = 3.5
        activation_mult = 2.0
        
        result["trailing_pct"] = max(0.03, min(0.10, atr_pct * trailing_mult))
        result["hard_sl_pct"] = max(0.04, min(0.12, atr_pct * sl_mult))
        result["trailing_activation_pct"] = max(0.02, min(0.06, atr_pct * activation_mult))
        
        result["tp_levels"] = [
            {"pct": 0.04, "sell_fraction": 0.25, "reason": "vol_quick"},
            {"pct": 0.08, "sell_fraction": 0.25, "reason": "vol_target"},
            {"pct": 0.15, "sell_fraction": 0.25, "reason": "vol_extended"},
        ]
        
    elif regime in ("bearish", "REGIME_BEARISH"):
        # BEARISH: very tight stops, tiny positions
        trailing_mult = 1.2
        sl_mult = 1.5
        activation_mult = 0.5
        
        result["trailing_pct"] = max(0.01, min(0.03, atr_pct * trailing_mult))
        result["hard_sl_pct"] = max(0.015, min(0.04, atr_pct * sl_mult))
        result["trailing_activation_pct"] = max(0.008, min(0.02, atr_pct * activation_mult))
        
        result["tp_levels"] = [
            {"pct": 0.01, "sell_fraction": 0.40, "reason": "bear_quick_exit"},
            {"pct": 0.02, "sell_fraction": 0.40, "reason": "bear_target"},
        ]
    
    # === Adjust TP levels based on detected resistance ===
    if resistances and entry_price > 0:
        for i, r in enumerate(resistances[:3]):
            r_pct = (r - entry_price) / entry_price
            if 0.005 < r_pct < 0.20:
                # Place TP just below resistance
                tp_pct = r_pct * 0.95  # 5% below resistance
                existing_pcts = [tp["pct"] for tp in result["tp_levels"]]
                if not any(abs(tp_pct - ep) < 0.005 for ep in existing_pcts):
                    result["tp_levels"].append({
                        "pct": round(tp_pct, 4),
                        "sell_fraction": 0.15,
                        "reason": f"resistance_level_{i+1}",
                    })
    
    # Sort TP levels by percentage
    result["tp_levels"].sort(key=lambda x: x["pct"])
    
    # Ensure sell fractions sum to <= 1.0
    total_fraction = sum(tp["sell_fraction"] for tp in result["tp_levels"])
    if total_fraction > 1.0:
        scale = 0.90 / total_fraction  # leave 10% for trailing
        for tp in result["tp_levels"]:
            tp["sell_fraction"] = round(tp["sell_fraction"] * scale, 2)
    
    logger.debug(
        f"[ADAPTIVE-EXIT] {market}: regime={regime}, "
        f"trail={result['trailing_pct']:.3f}, sl={result['hard_sl_pct']:.3f}, "
        f"atr_pct={atr_pct:.4f}, tp_levels={len(result['tp_levels'])}"
    )
    
    return result


def apply_exit_overrides(
    trade: Dict[str, Any],
    adaptive_exits: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply adaptive exit parameters to a trade dict.
    
    Only overrides if ADAPTIVE_EXIT_ENABLED is true in config.
    Returns modified trade dict.
    """
    if not config.get("ADAPTIVE_EXIT_ENABLED", False):
        return trade
    
    if not adaptive_exits:
        return trade
    
    # Override trailing stop
    if "trailing_pct" in adaptive_exits:
        trade["trailing_stop_pct"] = adaptive_exits["trailing_pct"]
    
    if "hard_sl_pct" in adaptive_exits:
        trade["hard_sl_pct"] = adaptive_exits["hard_sl_pct"]
    
    if "trailing_activation_pct" in adaptive_exits:
        trade["trailing_activation_pct"] = adaptive_exits["trailing_activation_pct"]
    
    # Store TP levels for the partial TP system
    if "tp_levels" in adaptive_exits and adaptive_exits["tp_levels"]:
        trade["adaptive_tp_levels"] = adaptive_exits["tp_levels"]
    
    # Store metadata
    trade["adaptive_exit_regime"] = adaptive_exits.get("regime", "unknown")
    trade["adaptive_exit_atr_pct"] = adaptive_exits.get("atr_pct")
    
    return trade
